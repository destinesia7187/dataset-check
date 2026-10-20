"""Semantic tests run with the standard library: unittest discover -s tests."""

import copy
import csv
import io
import random
import tempfile
import unittest
from pathlib import Path

from app.domain.csvio import parse_csv
from app.domain.engine import (
    RULE_CODES,
    analyze,
    parse_value,
    suggest_types,
    validate_configuration,
)
from app.domain.errors import DomainError


def columns(*names):
    return [
        {"column_id": f"c{index}", "position": index, "original_name": name, "display_name": name}
        for index, name in enumerate(names, start=1)
    ]


def configuration(cols, **changes):
    result = {
        "schema_version": "1.0",
        "decimal_separator": ".",
        "check_duplicate_rows": False,
        "columns": [
            {
                "column_id": col["column_id"],
                "required": False,
                "unique": False,
                "expected_type": "text",
                "range": None,
            }
            for col in cols
        ],
    }
    result.update(changes)
    return result


class CsvImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def parse(self, content, **options):
        path = Path(self.temp.name) / "input.csv"
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
        return parse_csv(path, **options)

    def assert_code(self, code, content, **options):
        with self.assertRaises(DomainError) as result:
            self.parse(content, **options)
        self.assertEqual(result.exception.code, code)
        return result.exception

    def test_bom_crlf_quoting_multiline_and_blank_lines_are_lossless(self):
        data = self.parse(
            '\ufeff\r\nid,name,note,tail\r\n\r\n001," A; B ","line 1\r\n\r\nline ""2""",\r\n002,NULL,"=1+1",\r\n'
        )
        self.assertEqual(
            data["rows"],
            [["001", " A; B ", 'line 1\r\n\r\nline "2"', ""], ["002", "NULL", "=1+1", ""]],
        )
        self.assertEqual(data["ignored_blank_line_count"], 2)
        self.assertEqual(data["delimiter"], ",")
        self.assertEqual(data["profile"][3]["missing_count"], 2)

    def test_windows_1251_is_explicit(self):
        # Cyrillic text exercises the encoding without localizing the test source.
        city = "\u041c\u043e\u0441\u043a\u0432\u0430"
        raw = f"\u0438\u043c\u044f;\u0447\u0438\u0441\u043b\u043e\n{city};12,50\n".encode("cp1251")
        self.assert_code("CSV_DECODE_ERROR", raw)
        data = self.parse(raw, encoding="windows-1251")
        self.assertEqual(data["rows"], [[city, "12,50"]])
        self.assertEqual(data["delimiter"], ";")

    def test_all_three_delimiters_and_header_original_name(self):
        for delimiter, selector in ((",", "comma"), (";", "semicolon"), ("\t", "tab")):
            with self.subTest(delimiter=selector):
                result = self.parse(f" id {delimiter}ID\n001{delimiter}002\n", delimiter=selector)
                self.assertEqual(result["columns"][0]["original_name"], " id ")
                self.assertEqual(result["columns"][0]["display_name"], "id")
                self.assertEqual(result["rows"][0][0], "001")

    def test_single_column_requires_explicit_delimiter(self):
        self.assert_code("CSV_DELIMITER_AMBIGUOUS", 'value\n""\n \n')
        data = self.parse('value\n""\n \n', delimiter="comma")
        self.assertEqual(data["rows"], [[""], [" "]])
        self.assertEqual(data["ignored_blank_line_count"], 0)

    def test_ambiguous_delimiters_never_choose_silently(self):
        self.assert_code("CSV_DELIMITER_AMBIGUOUS", "a,b;c\nx,y;z\n")

    def test_empty_and_header_only(self):
        for content in ("", "\n\r\n", b"\xef\xbb\xbf"):
            self.assert_code("CSV_EMPTY_FILE", content, delimiter="comma")
        data = self.parse("a,b\n")
        self.assertEqual(data["rows"], [])
        self.assertEqual(data["type_suggestions"]["columns"][0]["reason"], "empty_sample")

    def test_invalid_headers(self):
        for content in (
            "a, a \n",
            "a,\n",
            'a,"  "\n',
            'a,"bad\nname"\n',
            "a,b\tname\n",
            "a," + "x" * 129 + "\n",
        ):
            with self.subTest(content=content[:50]):
                self.assert_code("CSV_HEADER_INVALID", content, delimiter="comma")

    def test_invalid_structure_and_quotes_reject_whole_import(self):
        for content in (
            "a,b\nx\n",
            "a,b\nx,y,z\n",
            'a,b\n"x,y\n',
            'a,b\nabc"def,z\n',
            'a,b\n"x"oops,y\n',
            "a,b\nx,\0\n",
        ):
            with self.subTest(content=content):
                error = self.assert_code("CSV_PARSE_ERROR", content, delimiter="comma")
                self.assertIn("physical_line", error.details)

    def test_auto_detection_does_not_ignore_errors_after_sample(self):
        content = "a,b\n" + "x,y\n" * 100 + "x,y,z\n"
        self.assert_code("CSV_PARSE_ERROR", content)

    def test_import_limits(self):
        cases = [
            ("FILE_TOO_LARGE", "a,b\nx,y\n", {"max_file_size_bytes": 5}),
            ("DATASET_LIMIT_EXCEEDED", "a,b\nx,y\n", {"max_columns": 1}),
            ("DATASET_LIMIT_EXCEEDED", "a,b\nx,y\nx,z\n", {"max_rows": 1}),
            ("DATASET_LIMIT_EXCEEDED", "a,b\nx,y\nx,z\n", {"max_cells": 3}),
            ("CELL_TOO_LONG", "a,b\n12345,y\n", {"max_cell_length_chars": 4}),
        ]
        for code, content, limits in cases:
            with self.subTest(code=code, limits=limits):
                self.assert_code(code, content, delimiter="comma", limits=limits)
        data = self.parse("a,b\n1234,y\n", delimiter="comma", limits={"max_cell_length_chars": 4})
        self.assertEqual(data["rows"][0][0], "1234")

    def test_seeded_csv_round_trip_preserves_quoted_unicode_values(self):
        generator = random.Random(20261019)
        alphabet = ' \u0430\u0431\u0432ABC0123,;\t\n\r"=+-'
        for delimiter in (",", ";", "\t"):
            rows = [
                [
                    "".join(generator.choice(alphabet) for _ in range(generator.randrange(30)))
                    for _ in range(3)
                ]
                for _ in range(150)
            ]
            stream = io.StringIO(newline="")
            writer = csv.writer(stream, delimiter=delimiter, lineterminator="\r\n")
            writer.writerow(["a", "b", "c"])
            writer.writerows(rows)
            with self.subTest(delimiter=delimiter):
                parsed = self.parse(stream.getvalue())
                self.assertEqual(parsed["rows"], rows)


class TypeAndConfigurationTests(unittest.TestCase):
    def test_exact_numeric_grammar_and_precision(self):
        accepted = ("0", "+1", "-0", "001", "9" * 100)
        for value in accepted:
            self.assertIsNotNone(parse_value(value, "integer"))
        for value in ("1.0", "1,0", "1e3", ".5", "5.", "NaN", "inf", "１２", "١", "9" * 101):
            self.assertIsNone(parse_value(value, "integer"))
        for value in ("+001.50", "-0.0", "12", "0." + "0" * 98 + "1"):
            self.assertIsNotNone(parse_value(value, "decimal"))
        for value in ("1,5", ".5", "5.", "1e2", "NaN", "Infinity", "0." + "0" * 99 + "1"):
            self.assertIsNone(parse_value(value, "decimal"))
        self.assertEqual(str(parse_value("12,50", "decimal", ",")), "12.50")

    def test_strict_calendar_dates(self):
        for value in ("0001-01-01", "2024-02-29", "9999-12-31"):
            self.assertIsNotNone(parse_value(value, "date"))
        for value in (
            "0000-01-01",
            "2023-02-29",
            "2024-02-30",
            "2024-1-1",
            "20240101",
            "2024-01-01T00:00:00",
            "２０２４-01-01",
        ):
            self.assertIsNone(parse_value(value, "date"))

    def test_inference_best_coverage_and_priority(self):
        cols = columns("number")
        result = suggest_types([["1"]] * 95 + [["1.5"]] * 5, cols)["columns"][0]
        self.assertEqual(result["suggested_type"], "decimal")
        self.assertEqual(result["match_counts"], {"date": 0, "integer": 95, "decimal": 100})
        self.assertEqual(
            suggest_types([["1"]] * 100, cols)["columns"][0]["suggested_type"], "integer"
        )

    def test_inference_leading_zero_empty_and_sample_order(self):
        cols = columns("value")
        self.assertEqual(
            suggest_types([["00123"], ["123"]], cols)["columns"][0]["reason"], "leading_zero"
        )
        empty = suggest_types([[" "], ["\t"]], cols)["columns"][0]
        self.assertEqual(
            (empty["suggested_type"], empty["sample_size"], empty["matching_count"]), (None, 0, 0)
        )
        result = suggest_types([[""]] * 15 + [["1"]] * 1000 + [["bad"]] * 1000, cols)["columns"][0]
        self.assertEqual((result["sample_size"], result["suggested_type"]), (1000, "integer"))
        self.assertEqual(
            suggest_types([["1,5"]], cols, ",")["columns"][0]["suggested_type"], "decimal"
        )

    def test_configuration_rejects_invalid_values_with_field_paths(self):
        cols = columns("id", "value")
        base = configuration(cols)
        cases = []
        for key, value in (
            ("schema_version", "9"),
            ("decimal_separator", []),
            ("check_duplicate_rows", 1),
            ("extra", True),
            ("columns", []),
        ):
            item = copy.deepcopy(base)
            item[key] = value
            cases.append(item)
        for change in (
            {"column_id": "unknown"},
            {"column_id": "c2"},
            {"expected_type": "float"},
            {"required": "yes"},
            {"extra": True},
            {"range": {"min": "0"}},
        ):
            item = copy.deepcopy(base)
            item["columns"][0].update(change)
            cases.append(item)
        for bounds in (
            {"min": None, "max": None},
            {"min": "1.5", "max": "2"},
            {"min": "3", "max": "2"},
            {"min": 1},
            {"min": "0", "extra": True},
            {"min": "9" * 101},
        ):
            item = copy.deepcopy(base)
            item["columns"][0].update(expected_type="integer", range=bounds)
            cases.append(item)
        for item in cases:
            with self.subTest(config=item):
                with self.assertRaises(DomainError) as result:
                    validate_configuration(item, cols)
                self.assertEqual(result.exception.code, "RULE_CONFIG_INVALID")
                self.assertTrue(
                    all(
                        "field" in detail and "reason" in detail
                        for detail in result.exception.details
                    )
                )

    def test_validation_defensive_copy_and_array_order(self):
        cols = columns("a", "b")
        config = configuration(cols)
        config["columns"].reverse()
        config["columns"][0].update(expected_type="integer", range={"min": "+00"})
        validated = validate_configuration(config, cols)
        self.assertEqual(validated["columns"][0]["column_id"], "c2")
        self.assertEqual(validated["columns"][0]["range"], {"min": "+00", "max": None})
        self.assertNotIn("max", config["columns"][0]["range"])


class AnalysisTests(unittest.TestCase):
    def test_acceptance_thirteen_issues_eight_problematic_records(self):
        cols = columns("id", "name", "population", "opened_at")
        rows = [
            ["A", "Object A", "10", "2024-02-29"],
            ["B", "", "5", "2024-02-30"],
            ["B", "Object B", "-1", "2024-03-01"],
            ["C", "Object C", "abc", ""],
            ["A", "Object A", "10", "2024-02-29"],
            ["", "Object D", "100", "2024-03-02"],
            ["D", "Object E", "1.5", "2024-03-03"],
            ["E", "Object F", "  ", "2024-03-04"],
            ["F", "Object G", "0", "2024-03-05"],
        ]
        config = configuration(cols, check_duplicate_rows=True)
        config["columns"][0].update(required=True, unique=True)
        config["columns"][1]["required"] = True
        config["columns"][2].update(
            required=True, expected_type="integer", range={"min": "0", "max": "100"}
        )
        config["columns"][3]["expected_type"] = "date"
        stages = []
        result = analyze(rows, cols, config, progress=stages.append)
        summary = result["summary"]
        self.assertEqual(
            (
                summary["total_records"],
                summary["total_issues"],
                summary["problematic_records"],
                summary["clean_records"],
            ),
            (9, 13, 8, 1),
        )
        self.assertEqual([item["issue_count"] for item in summary["by_rule"]], [3, 3, 1, 4, 2])
        self.assertEqual([item["issue_count"] for item in summary["by_column"]], [5, 1, 4, 1])
        self.assertEqual(summary["row_level"], {"issue_count": 2, "record_count": 2})
        self.assertEqual(
            summary["duplicate_rows"],
            {"enabled": True, "group_count": 1, "participant_count": 2, "extra_count": 1},
        )
        self.assertEqual(
            summary["unique_columns"],
            [{"column_id": "c1", "group_count": 2, "participant_count": 4, "extra_count": 2}],
        )
        self.assertEqual(
            [item["violation_count"] for item in result["problematic_records"]],
            [2, 3, 2, 1, 2, 1, 1, 1],
        )
        self.assertEqual([item["missing_count"] for item in result["profile"]], [1, 1, 1, 1])
        self.assertEqual(stages, ["validating", "deduplicating", "building_report"])
        self.assertEqual(result, analyze(rows, cols, config))

    def test_missing_skips_type_range_and_uniqueness(self):
        cols = columns("n")
        config = configuration(cols)
        config["columns"][0].update(
            required=True, unique=True, expected_type="integer", range={"min": "0", "max": "10"}
        )
        result = analyze([[""], [" \t\n"], ["NULL"], ["NaN"], ["0"]], cols, config)
        self.assertEqual(
            [item["issue_count"] for item in result["summary"]["by_rule"]], [2, 2, 0, 0, 0]
        )

    def test_duplicate_rules_use_different_comparison_and_include_first(self):
        cols = columns("id")
        config = configuration(cols, check_duplicate_rows=True)
        config["columns"][0].update(unique=True, expected_type="integer")
        result = analyze([["A"], [" A "], ["A"], ["a"], [""], [" "]], cols, config)
        unique = [
            item for item in result["duplicate_groups"] if item["rule_code"] == "NON_UNIQUE_VALUE"
        ]
        full = [item for item in result["duplicate_groups"] if item["rule_code"] == "DUPLICATE_ROW"]
        self.assertEqual(unique[0]["row_indices"], [1, 2, 3])
        self.assertEqual(full[0]["row_indices"], [1, 3])
        self.assertEqual(len(unique), 1)
        self.assertEqual(result["summary"]["by_rule"][1]["issue_count"], 4)
        self.assertEqual(result["summary"]["by_rule"][3]["issue_count"], 3)

    def test_numeric_looking_unique_keys_remain_strings(self):
        cols = columns("id")
        config = configuration(cols)
        config["columns"][0].update(unique=True, expected_type="decimal")
        result = analyze([["00123"], ["123"], ["1"], ["1.0"]], cols, config)
        self.assertEqual(result["summary"]["total_issues"], 0)

    def test_exact_decimal_range_boundary(self):
        cols = columns("number")
        config = configuration(cols, decimal_separator=",")
        config["columns"][0].update(
            expected_type="decimal",
            range={
                "min": "0,100000000000000000000000000000000001",
                "max": "0,100000000000000000000000000000000002",
            },
        )
        rows = [
            ["0,100000000000000000000000000000000000"],
            ["0,100000000000000000000000000000000001"],
            ["0,100000000000000000000000000000000002"],
            ["0,100000000000000000000000000000000003"],
            ["abc"],
        ]
        result = analyze(rows, cols, config)
        self.assertEqual(
            [(item["row_index"], item["rule_code"]) for item in result["issues"]],
            [(1, "OUT_OF_RANGE"), (4, "OUT_OF_RANGE"), (5, "INVALID_TYPE")],
        )

    def test_problematic_records_preserve_all_values_and_rule_order(self):
        cols = columns("missing", "negative", "formula", "spaces", "apostrophe")
        config = configuration(cols)
        config["columns"][0]["required"] = True
        row = ["", "-55", "=1+1", " \t ", "'original"]
        result = analyze([row], cols, config)
        self.assertEqual(
            result["problematic_records"],
            [
                {
                    "row_index": 1,
                    "values": row,
                    "violation_count": 1,
                    "rule_codes": ["REQUIRED_VALUE_MISSING"],
                }
            ],
        )
        self.assertIsNot(result["problematic_records"][0]["values"], row)

    def test_issue_message_has_bounded_excerpt_but_raw_value_is_complete(self):
        cols = columns("number")
        config = configuration(cols)
        config["columns"][0]["expected_type"] = "integer"
        raw = " " + "x" * 65_534 + " "
        result = analyze([[raw]], cols, config)
        self.assertEqual(result["issues"][0]["raw_value"], raw)
        message = result["issues"][0]["message"]
        self.assertLessEqual(len(message), 1024)
        self.assertIn("x" * 127 + "…", message)
        self.assertNotIn("x" * 128, message)

    def test_full_empty_records_and_zero_rule_counts(self):
        cols = columns("a", "b")
        result = analyze([["", ""], ["", ""]], cols, configuration(cols, check_duplicate_rows=True))
        self.assertEqual(result["summary"]["total_issues"], 2)
        self.assertEqual(
            [item["rule_code"] for item in result["summary"]["by_rule"]], list(RULE_CODES)
        )
        self.assertEqual([item["issue_count"] for item in result["summary"]["by_column"]], [0, 0])
        self.assertEqual(result["issues"][0]["column_id"], None)
        self.assertEqual(result["issues"][0]["raw_value"], None)

    def test_rules_follow_column_ids_even_with_reordered_config(self):
        cols = columns("a", "b")
        config = configuration(cols)
        config["columns"][1].update(required=True, expected_type="integer")
        config["columns"].reverse()
        result = analyze([["abc", "bad"]], cols, config)
        self.assertEqual(result["issues"][0]["column_id"], "c2")

    def test_empty_dataset_and_budget_fail_without_partial_result(self):
        cols = columns("a")
        config = configuration(cols)
        config["columns"][0]["required"] = True
        with self.assertRaises(DomainError) as result:
            analyze([], cols, config)
        self.assertEqual(result.exception.code, "EMPTY_DATASET")
        self.assertEqual(
            analyze([[""]] * 3, cols, config, max_issues=3)["summary"]["total_issues"], 3
        )
        with self.assertRaises(DomainError) as result:
            analyze([[""]] * 4, cols, config, max_issues=3)
        self.assertEqual(result.exception.code, "RESULT_LIMIT_EXCEEDED")
        self.assertEqual(result.exception.details["detected_at_least"], 4)


class DefaultBudgetTests(unittest.TestCase):
    def test_exact_default_boundary_100000_and_100001(self):
        cols = columns("id", "number")
        config = configuration(cols)
        config["columns"][0]["unique"] = True
        config["columns"][1]["expected_type"] = "integer"
        rows = [["same", "1"] for _ in range(100_000)]
        self.assertEqual(analyze(rows, cols, config)["summary"]["total_issues"], 100_000)
        rows[0][1] = "bad"
        with self.assertRaises(DomainError) as result:
            analyze(rows, cols, config)
        self.assertEqual(result.exception.code, "RESULT_LIMIT_EXCEEDED")

    def test_mass_violations_100000_by_20_fails_and_next_run_works(self):
        cols = columns(*(f"field{index}" for index in range(20)))
        config = configuration(cols, check_duplicate_rows=True)
        for rule in config["columns"]:
            rule.update(expected_type="integer", unique=True)
        rows = [["x"] * 20 for _ in range(100_000)]
        with self.assertRaises(DomainError) as result:
            analyze(rows, cols, config)
        self.assertEqual(result.exception.code, "RESULT_LIMIT_EXCEEDED")
        self.assertEqual(analyze([["1"] * 20], cols, config)["summary"]["total_issues"], 0)


if __name__ == "__main__":
    unittest.main()
