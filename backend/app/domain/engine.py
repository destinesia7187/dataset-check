"""Pure validation engine implementing specification 1.1, algorithm 1.0.0.

No input value is modified. All public results contain only JSON-compatible
values, so callers can persist them or transfer them between worker processes.
"""

import copy
import re
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from typing import Callable

from .errors import DomainError

ALGORITHM_VERSION = "1.0.0"
RULE_CODES = (
    "REQUIRED_VALUE_MISSING",
    "INVALID_TYPE",
    "OUT_OF_RANGE",
    "NON_UNIQUE_VALUE",
    "DUPLICATE_ROW",
)
TYPES = ("text", "integer", "decimal", "date")
INTEGER = re.compile(r"[+-]?[0-9]+\Z")
DECIMALS = {
    separator: re.compile(r"[+-]?[0-9]+(?:" + re.escape(separator) + r"[0-9]+)?\Z")
    for separator in (".", ",")
}
DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
LEADING_ZERO = re.compile(r"[+-]?0[0-9]+\Z")
TYPE_NAMES = {
    "integer": "an integer",
    "decimal": "a decimal number",
    "date": "a date in YYYY-MM-DD format",
    "text": "text",
}


def parse_value(
    value: str, expected_type: str, decimal_separator: str = "."
) -> str | int | Decimal | date | None:
    """Return an exact parsed value, or None for an unsupported representation.

    The caller handles missing values separately. This function intentionally
    accepts ASCII digits only and never performs a float conversion.
    """
    normalized = value.strip()
    if expected_type == "text":
        return normalized if normalized else None
    if expected_type in ("integer", "decimal"):
        expression = INTEGER if expected_type == "integer" else DECIMALS[decimal_separator]
        if (
            not expression.fullmatch(normalized)
            or sum("0" <= char <= "9" for char in normalized) > 100
        ):
            return None
        return (
            int(normalized) if expected_type == "integer" else Decimal(normalized.replace(",", "."))
        )
    if expected_type == "date" and DATE.fullmatch(normalized):
        try:
            return date.fromisoformat(normalized)
        except ValueError:
            return None
    return None


def suggest_types(rows: list[list[str]], columns: list[dict], decimal_separator: str = ".") -> dict:
    """Suggest each type from the first 1,000 non-missing values, deterministically."""
    if not isinstance(decimal_separator, str) or decimal_separator not in DECIMALS:
        raise DomainError(
            "QUERY_INVALID",
            "The decimal separator must be a period or a comma",
            {"field": "decimal_separator"},
        )
    suggestions = []
    for index, column in enumerate(columns):
        sample = []
        for row in rows:
            value = row[index].strip()
            if value:
                sample.append(value)
                if len(sample) == 1000:
                    break
        counts = {
            candidate: sum(
                parse_value(value, candidate, decimal_separator) is not None for value in sample
            )
            for candidate in ("date", "integer", "decimal")
        }
        if not sample:
            selected, reason = None, "empty_sample"
        elif any(LEADING_ZERO.fullmatch(value) for value in sample):
            selected, reason = "text", "leading_zero"
        else:
            eligible = [
                candidate for candidate in counts if counts[candidate] * 100 >= len(sample) * 95
            ]
            if eligible:
                selected, reason = (
                    max(eligible, key=lambda candidate: counts[candidate]),
                    "best_match",
                )
            else:
                selected, reason = "text", "fallback_text"
        matching = (
            0 if selected is None else len(sample) if selected == "text" else counts[selected]
        )
        suggestions.append(
            {
                "column_id": column["column_id"],
                "suggested_type": selected,
                "sample_size": len(sample),
                "matching_count": matching,
                "match_counts": counts,
                "reason": reason,
            }
        )
    return {"decimal_separator": decimal_separator, "columns": suggestions}


def validate_configuration(config: dict, columns: list[dict]) -> dict:
    """Validate the complete rule snapshot, returning a defensive normalized copy.

    Range strings and array order are retained for immutable snapshots and
    canonical request fingerprints. Execution maps rules to file column order.
    """
    problems = []

    def error(field: str, reason: str) -> None:
        problems.append({"field": field, "reason": reason})

    def keys(value: dict, allowed: set[str], field: str) -> None:
        for name in value.keys() - allowed:
            error(f"{field}.{name}" if field else name, "unknown_field")
        for name in allowed - value.keys():
            error(f"{field}.{name}" if field else name, "required_field")

    if not isinstance(config, dict):
        raise DomainError(
            "RULE_CONFIG_INVALID",
            "The configuration must be an object",
            [{"field": "configuration", "reason": "object_required"}],
        )
    keys(config, {"schema_version", "decimal_separator", "check_duplicate_rows", "columns"}, "")
    if config.get("schema_version") != "1.0":
        error("schema_version", "unsupported_schema_version")
    separator = config.get("decimal_separator")
    valid_separator = isinstance(separator, str) and separator in DECIMALS
    if not valid_separator:
        error("decimal_separator", "unsupported_decimal_separator")
    if type(config.get("check_duplicate_rows")) is not bool:
        error("check_duplicate_rows", "boolean_required")
    rules = config.get("columns")
    if not isinstance(rules, list):
        error("columns", "array_required")
        rules = []
    column_ids = {column["column_id"] for column in columns}
    seen = set()
    for index, rule in enumerate(rules):
        field = f"columns[{index}]"
        if not isinstance(rule, dict):
            error(field, "object_required")
            continue
        keys(rule, {"column_id", "required", "unique", "expected_type", "range"}, field)
        column_id = rule.get("column_id")
        if not isinstance(column_id, str) or column_id not in column_ids:
            error(f"{field}.column_id", "unknown_column")
        elif column_id in seen:
            error(f"{field}.column_id", "duplicate_column")
        else:
            seen.add(column_id)
        for name in ("required", "unique"):
            if type(rule.get(name)) is not bool:
                error(f"{field}.{name}", "boolean_required")
        expected = rule.get("expected_type")
        if expected not in TYPES:
            error(f"{field}.expected_type", "unsupported_type")
        bounds = rule.get("range")
        if bounds is not None:
            if expected not in ("integer", "decimal"):
                error(f"{field}.range", "range_requires_numeric_type")
            if not isinstance(bounds, dict):
                error(f"{field}.range", "object_or_null_required")
                continue
            # A single bound is allowed; absent bounds become explicit null.
            for name in bounds.keys() - {"min", "max"}:
                error(f"{field}.range.{name}", "unknown_field")
            parsed = {}
            for name in ("min", "max"):
                bound = bounds.get(name)
                if bound is not None:
                    if (
                        not isinstance(bound, str)
                        or expected not in ("integer", "decimal")
                        or not valid_separator
                    ):
                        error(f"{field}.range.{name}", "invalid_numeric_bound")
                    else:
                        parsed[name] = parse_value(bound, expected, separator)
                        if parsed[name] is None:
                            error(f"{field}.range.{name}", "invalid_numeric_bound")
            if bounds.get("min") is None and bounds.get("max") is None:
                error(f"{field}.range", "empty_range")
            if (
                parsed.get("min") is not None
                and parsed.get("max") is not None
                and parsed["min"] > parsed["max"]
            ):
                error(f"{field}.range", "min_greater_than_max")
    for column in columns:
        if column["column_id"] not in seen:
            error("columns", f"missing_column:{column['column_id']}")
    if problems:
        raise DomainError(
            "RULE_CONFIG_INVALID", "Correct the validation rule configuration", problems
        )
    validated = copy.deepcopy(config)
    for rule in validated["columns"]:
        if rule["range"] is not None:
            rule["range"].setdefault("min", None)
            rule["range"].setdefault("max", None)
    return validated


def analyze(
    rows: list[list[str]],
    columns: list[dict],
    config: dict,
    max_issues: int = 100_000,
    progress: Callable[[str], None] | None = None,
) -> dict:
    """Return complete checks, or fail on the first issue beyond the budget.

    Progress receives real stage transitions. Resource deadlines and persistent
    storage quotas are enforced by the supervising process, not this pure core.
    """
    config = validate_configuration(config, columns)
    rule_by_id = {rule["column_id"]: rule for rule in config["columns"]}
    config["columns"] = [rule_by_id[column["column_id"]] for column in columns]
    if not rows:
        raise DomainError("EMPTY_DATASET", "The dataset contains no records to validate", {})
    separator = config["decimal_separator"]
    issues: list[dict] = []
    groups: list[dict] = []
    missing = [0] * len(columns)
    unique_values: dict[int, dict[str, list[int]]] = {
        index: defaultdict(list) for index, rule in enumerate(config["columns"]) if rule["unique"]
    }
    duplicate_values: dict[tuple[str, ...], list[int]] = defaultdict(list)
    column_positions = {column["column_id"]: index for index, column in enumerate(columns)}

    def stage(name: str) -> None:
        if progress:
            progress(name)

    def issue(
        row_index: int,
        column_index: int | None,
        code: str,
        message: str,
        parameters: dict,
        group_id: str | None = None,
    ) -> None:
        if len(issues) >= max_issues:
            raise DomainError(
                "RESULT_LIMIT_EXCEEDED",
                "The issue limit has been exceeded. Reduce the dataset size or the number of rules",
                {"max_issues_per_run": max_issues, "detected_at_least": max_issues + 1},
            )
        column = columns[column_index] if column_index is not None else None
        issues.append(
            {
                "issue_id": "",
                "row_index": row_index,
                "column_id": column["column_id"] if column else None,
                "column_name": column["display_name"] if column else None,
                "rule_code": code,
                "message": message[:1024],
                "raw_value": rows[row_index - 1][column_index]
                if column_index is not None
                else None,
                "rule_parameters": parameters,
                "duplicate_group_id": group_id,
            }
        )

    stage("validating")
    bounds = [
        {
            name: parse_value(rule["range"][name], rule["expected_type"], separator)
            if rule["range"] and rule["range"][name] is not None
            else None
            for name in ("min", "max")
        }
        for rule in config["columns"]
    ]
    for row_index, row in enumerate(rows, start=1):
        if len(row) != len(columns):
            raise DomainError(
                "CSV_PARSE_ERROR",
                "The record field count does not match the header",
                {"row_index": row_index},
            )
        if config["check_duplicate_rows"]:
            duplicate_values[tuple(row)].append(row_index)
        for index, rule in enumerate(config["columns"]):
            value = row[index].strip()
            if not value:
                missing[index] += 1
                if rule["required"]:
                    issue(
                        row_index,
                        index,
                        "REQUIRED_VALUE_MISSING",
                        f"Required field “{columns[index]['display_name']}” is empty",
                        {"required": True},
                    )
                continue
            if rule["unique"]:
                unique_values[index][value].append(row_index)
            expected = rule["expected_type"]
            if expected == "text":
                continue
            parsed = parse_value(value, expected, separator)
            if parsed is None:
                excerpt = value if len(value) <= 128 else value[:127] + "…"
                issue(
                    row_index,
                    index,
                    "INVALID_TYPE",
                    f"Expected {TYPE_NAMES[expected]}; received “{excerpt}”",
                    {
                        "expected_type": expected,
                        "decimal_separator": separator if expected == "decimal" else None,
                        "date_format": "YYYY-MM-DD" if expected == "date" else None,
                        "max_digits": 100 if expected in ("integer", "decimal") else None,
                    },
                )
            elif rule["range"] is not None:
                below = bounds[index]["min"] is not None and parsed < bounds[index]["min"]
                above = bounds[index]["max"] is not None and parsed > bounds[index]["max"]
                if below or above:
                    boundary = "min" if below else "max"
                    message = f"Value {value} {'is below the minimum' if below else 'is above the maximum'} {rule['range'][boundary]}"
                    issue(
                        row_index,
                        index,
                        "OUT_OF_RANGE",
                        message,
                        {
                            "expected_type": expected,
                            "min": rule["range"]["min"],
                            "max": rule["range"]["max"],
                            "decimal_separator": separator if expected == "decimal" else None,
                        },
                    )

    stage("deduplicating")
    # Column-first ordering, then first participant, is independent of dict keys.
    unique_summaries = []
    for index, values in unique_values.items():
        repeated = sorted(
            (indices for indices in values.values() if len(indices) >= 2),
            key=lambda indices: indices[0],
        )
        unique_summaries.append(
            {
                "column_id": columns[index]["column_id"],
                "group_count": len(repeated),
                "participant_count": sum(map(len, repeated)),
                "extra_count": sum(len(indices) - 1 for indices in repeated),
            }
        )
        for number, indices in enumerate(repeated, start=1):
            group_id = f"unique-{columns[index]['column_id']}-{number}"
            groups.append(
                {
                    "group_id": group_id,
                    "rule_code": "NON_UNIQUE_VALUE",
                    "column_id": columns[index]["column_id"],
                    "normalized_key": rows[indices[0] - 1][index].strip(),
                    "participant_count": len(indices),
                    "extra_count": len(indices) - 1,
                    "row_indices": indices,
                }
            )
            for row_index in indices:
                issue(
                    row_index,
                    index,
                    "NON_UNIQUE_VALUE",
                    f"The value in field “{columns[index]['display_name']}” occurs in {len(indices)} records",
                    {"comparison": "trimmed_case_sensitive_string", "group_size": len(indices)},
                    group_id,
                )
    repeated_rows = sorted(
        (indices for indices in duplicate_values.values() if len(indices) >= 2),
        key=lambda indices: indices[0],
    )
    for number, indices in enumerate(repeated_rows, start=1):
        group_id = f"row-{number}"
        groups.append(
            {
                "group_id": group_id,
                "rule_code": "DUPLICATE_ROW",
                "column_id": None,
                "normalized_key": None,
                "participant_count": len(indices),
                "extra_count": len(indices) - 1,
                "row_indices": indices,
            }
        )
        for row_index in indices:
            issue(
                row_index,
                None,
                "DUPLICATE_ROW",
                f"This record exactly matches {len(indices) - 1} other "
                f"{'record' if len(indices) == 2 else 'records'}",
                {"comparison": "exact_raw_values", "group_size": len(indices)},
                group_id,
            )

    stage("building_report")
    issues.sort(
        key=lambda item: (
            item["row_index"],
            column_positions.get(item["column_id"], len(columns)),
            RULE_CODES.index(item["rule_code"]),
        )
    )
    by_rule_counts = Counter()
    by_rule_records: dict[str, set[int]] = defaultdict(set)
    by_column_counts = Counter()
    by_column_records: dict[str | None, set[int]] = defaultdict(set)
    per_record: dict[int, list[str]] = defaultdict(list)
    for number, item in enumerate(issues, start=1):
        item["issue_id"] = f"issue-{number}"
        by_rule_counts[item["rule_code"]] += 1
        by_rule_records[item["rule_code"]].add(item["row_index"])
        by_column_counts[item["column_id"]] += 1
        by_column_records[item["column_id"]].add(item["row_index"])
        per_record[item["row_index"]].append(item["rule_code"])
    summary = {
        "total_records": len(rows),
        "problematic_records": len(per_record),
        "clean_records": len(rows) - len(per_record),
        "total_issues": len(issues),
        "by_rule": [
            {
                "rule_code": code,
                "issue_count": by_rule_counts[code],
                "record_count": len(by_rule_records[code]),
            }
            for code in RULE_CODES
        ],
        "by_column": [
            {
                "column_id": column["column_id"],
                "issue_count": by_column_counts[column["column_id"]],
                "record_count": len(by_column_records[column["column_id"]]),
            }
            for column in columns
        ],
        "row_level": {
            "issue_count": by_column_counts[None],
            "record_count": len(by_column_records[None]),
        },
        "duplicate_rows": {
            "enabled": config["check_duplicate_rows"],
            "group_count": len(repeated_rows),
            "participant_count": sum(map(len, repeated_rows)),
            "extra_count": sum(len(indices) - 1 for indices in repeated_rows),
        },
        "unique_columns": unique_summaries,
    }
    return {
        "issues": issues,
        "summary": summary,
        "duplicate_groups": groups,
        "problematic_records": [
            {
                "row_index": row_index,
                "values": list(rows[row_index - 1]),
                "violation_count": len(codes),
                "rule_codes": [code for code in RULE_CODES if code in codes],
            }
            for row_index, codes in sorted(per_record.items())
        ],
        "profile": [
            {
                "column_id": column["column_id"],
                "missing_count": missing[index],
                "non_missing_count": len(rows) - missing[index],
            }
            for index, column in enumerate(columns)
        ],
    }
