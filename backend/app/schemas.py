"""Strict, JSON-preserving public API contracts from specification 1.1 §14.7.

These models describe small HTTP resources and the downloadable report. They do
not read files, access storage, or replace the engine's dataset-dependent rule
validation. Nullable response fields intentionally have no defaults: callers
must publish them explicitly. Numeric bounds and raw values remain strings.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Generic, Literal, Self, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .domain.engine import RULE_CODES, parse_value

NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveInt = Annotated[int, Field(ge=1)]
PageLimit = Annotated[int, Field(ge=1, le=100)]
Identifier = Annotated[
    str,
    Field(
        pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
        json_schema_extra={"format": "uuid"},
    ),
]
UTC = Annotated[
    str,
    Field(
        pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z$",
        json_schema_extra={"format": "date-time"},
    ),
]
ColumnId = Annotated[str, Field(pattern=r"^c[1-9][0-9]*$")]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
DataType = Literal["text", "integer", "decimal", "date"]
DecimalSeparator = Literal[".", ","]
Encoding = Literal["utf-8", "windows-1251"]
ImportDelimiter = Literal["auto", "comma", "semicolon", "tab"]
RuleCode = Literal[
    "REQUIRED_VALUE_MISSING", "INVALID_TYPE", "OUT_OF_RANGE", "NON_UNIQUE_VALUE", "DUPLICATE_ROW"
]
RunStatus = Literal["queued", "running", "succeeded", "failed"]
RunStage = Literal[
    "queued", "preparing", "validating", "deduplicating", "building_report", "completed", "failed"
]
T = TypeVar("T")


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator("*", mode="after", check_fields=False)
    @classmethod
    def valid_utc_strings(cls, value: Any, info: Any) -> Any:
        # Avoid datetime coercion, which would alter string serialization.
        if info.field_name.endswith("_at") and value is not None:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value


class Page(Schema, Generic[T]):
    items: list[T]
    total: NonNegativeInt
    offset: NonNegativeInt
    limit: PageLimit

    @model_validator(mode="after")
    def page_size(self) -> Self:
        if len(self.items) > self.limit or len(self.items) > max(0, self.total - self.offset):
            raise ValueError("The item count does not match the page boundaries")
        return self


class Column(Schema):
    column_id: ColumnId
    position: PositiveInt
    original_name: str
    display_name: str


class ColumnProfile(Schema):
    column_id: ColumnId
    non_missing_count: NonNegativeInt
    missing_count: NonNegativeInt


class RawRecord(Schema):
    row_index: PositiveInt
    values: list[str]


class NumericRange(Schema):
    min: str | None = Field(
        default=None, description="An exact numeric string; floating-point conversion is not used"
    )
    max: str | None = Field(
        default=None, description="An exact numeric string; floating-point conversion is not used"
    )

    @model_validator(mode="after")
    def at_least_one_bound(self) -> Self:
        if self.min is None and self.max is None:
            raise ValueError("A range requires at least one bound; otherwise use null")
        return self


class ColumnRule(Schema):
    column_id: ColumnId
    required: bool
    unique: bool
    expected_type: DataType
    range: NumericRange | None

    @model_validator(mode="after")
    def range_requires_number(self) -> Self:
        if self.range is not None and self.expected_type not in ("integer", "decimal"):
            raise ValueError("Ranges apply only to integer and decimal values")
        return self


class Configuration(Schema):
    schema_version: Literal["1.0"]
    decimal_separator: DecimalSeparator
    check_duplicate_rows: bool
    columns: list[ColumnRule]

    @model_validator(mode="after")
    def valid_bounds_and_unique_columns(self) -> Self:
        seen = set()
        for column in self.columns:
            if column.column_id in seen:
                raise ValueError(f"Column {column.column_id} is specified more than once")
            seen.add(column.column_id)
            if column.range is None:
                continue
            parsed = {}
            for name in ("min", "max"):
                value = getattr(column.range, name)
                if value is not None:
                    number = parse_value(value, column.expected_type, self.decimal_separator)
                    if number is None:
                        raise ValueError(f"Invalid bound for {column.column_id}.range.{name}")
                    parsed[name] = number
            if "min" in parsed and "max" in parsed and parsed["min"] > parsed["max"]:
                raise ValueError(f"The minimum for {column.column_id} cannot exceed the maximum")
        return self


class MatchCounts(Schema):
    date: NonNegativeInt
    integer: NonNegativeInt
    decimal: NonNegativeInt


class TypeSuggestion(Schema):
    column_id: ColumnId
    suggested_type: DataType | None
    sample_size: Annotated[int, Field(ge=0, le=1000)]
    matching_count: NonNegativeInt
    match_counts: MatchCounts
    reason: Literal["best_match", "leading_zero", "fallback_text", "empty_sample"]

    @model_validator(mode="after")
    def counts_fit_sample(self) -> Self:
        if any(
            value > self.sample_size
            for value in (
                self.matching_count,
                self.match_counts.date,
                self.match_counts.integer,
                self.match_counts.decimal,
            )
        ):
            raise ValueError("The match count exceeds the sample size")
        return self


class TypeSuggestions(Schema):
    decimal_separator: DecimalSeparator
    columns: list[TypeSuggestion]


class DatasetSummary(Schema):
    dataset_id: Identifier
    original_filename: str
    file_size_bytes: NonNegativeInt
    row_count: NonNegativeInt
    column_count: PositiveInt
    created_at: UTC
    expires_at: UTC | None
    retention_pinned: bool
    run_count: NonNegativeInt

    @model_validator(mode="after")
    def retention_matches_pin(self) -> Self:
        if (self.expires_at is None) != self.retention_pinned:
            raise ValueError("expires_at=null is allowed only while the dataset is pinned")
        return self


class CSVParameters(Schema):
    encoding: Encoding
    delimiter: Literal[",", ";", "\t"]


class RunListItem(Schema):
    run_id: Identifier
    status: RunStatus
    created_at: UTC
    started_at: UTC | None
    finished_at: UTC | None


class Dataset(DatasetSummary):
    file_sha256: Sha256
    csv: CSVParameters
    ignored_blank_line_count: NonNegativeInt
    columns: list[Column]
    profile: list[ColumnProfile]
    type_suggestions: TypeSuggestions
    runs: list[RunListItem]

    @model_validator(mode="after")
    def structure_matches_counts(self) -> Self:
        ids = [column.column_id for column in self.columns]
        if len(ids) != self.column_count or len(ids) != len(set(ids)):
            raise ValueError("The column structure does not match column_count")
        if [item.column_id for item in self.profile] != ids:
            raise ValueError("The profile order must match the column order")
        if [item.column_id for item in self.type_suggestions.columns] != ids:
            raise ValueError("Type suggestions must cover all columns")
        if any(p.missing_count + p.non_missing_count != self.row_count for p in self.profile):
            raise ValueError("The profile counts do not match the record count")
        if len(self.runs) != self.run_count:
            raise ValueError("The number of runs does not match run_count")
        return self


class RuleSummary(Schema):
    rule_code: RuleCode
    issue_count: NonNegativeInt
    record_count: NonNegativeInt


class ColumnSummary(Schema):
    column_id: ColumnId
    issue_count: NonNegativeInt
    record_count: NonNegativeInt


class RowLevelSummary(Schema):
    issue_count: NonNegativeInt
    record_count: NonNegativeInt


class DuplicateCounts(Schema):
    group_count: NonNegativeInt
    participant_count: NonNegativeInt
    extra_count: NonNegativeInt

    @model_validator(mode="after")
    def repeats_equal_participants_less_groups(self) -> Self:
        if self.extra_count != self.participant_count - self.group_count:
            raise ValueError(
                "The extra duplicate count must equal the participant count minus the group count"
            )
        return self


class DuplicateRowsSummary(DuplicateCounts):
    enabled: bool

    @model_validator(mode="after")
    def disabled_has_zero_counts(self) -> Self:
        if not self.enabled and (self.group_count or self.participant_count or self.extra_count):
            raise ValueError("A disabled duplicate check must have zero counts")
        return self


class UniqueColumnSummary(DuplicateCounts):
    column_id: ColumnId


class Summary(Schema):
    total_records: NonNegativeInt
    problematic_records: NonNegativeInt
    clean_records: NonNegativeInt
    total_issues: NonNegativeInt
    by_rule: Annotated[list[RuleSummary], Field(min_length=5, max_length=5)]
    by_column: list[ColumnSummary]
    row_level: RowLevelSummary
    duplicate_rows: DuplicateRowsSummary
    unique_columns: list[UniqueColumnSummary]

    @model_validator(mode="after")
    def consistent_totals(self) -> Self:
        if self.problematic_records + self.clean_records != self.total_records:
            raise ValueError("The problematic and clean record counts do not add up to the total")
        if tuple(item.rule_code for item in self.by_rule) != RULE_CODES:
            raise ValueError("All five rules must appear in the prescribed order")
        if sum(item.issue_count for item in self.by_rule) != self.total_issues:
            raise ValueError("The issue counts by rule do not add up to the total")
        if (
            sum(item.issue_count for item in self.by_column) + self.row_level.issue_count
            != self.total_issues
        ):
            raise ValueError(
                "The column-level and record-level issue counts do not add up to the total"
            )
        if self.problematic_records > self.total_issues:
            raise ValueError("The problematic record count cannot exceed the issue count")
        return self


class RunError(Schema):
    code: str
    message: str
    details: dict[str, Any]


class Run(Schema):
    run_id: Identifier
    dataset_id: Identifier
    status: RunStatus
    stage: RunStage
    created_at: UTC
    started_at: UTC | None
    finished_at: UTC | None
    duration_ms: NonNegativeInt | None
    expires_at: UTC | None
    retention_pinned: bool
    configuration_snapshot: Configuration
    algorithm_version: str
    summary: Summary | None
    error: RunError | None

    @model_validator(mode="after")
    def terminal_result_matches_status(self) -> Self:
        if (self.status == "succeeded") != (self.summary is not None):
            raise ValueError("A summary is published only for a successful run")
        if (self.status == "failed") != (self.error is not None):
            raise ValueError("An error is published only for a failed run")
        if self.status in ("succeeded", "failed"):
            if self.finished_at is None:
                raise ValueError("A finished run requires finished_at")
            if self.stage != ("completed" if self.status == "succeeded" else "failed"):
                raise ValueError("The final stage does not match the status")
        return self


class RequiredParameters(Schema):
    required: Literal[True]


class InvalidTypeParameters(Schema):
    expected_type: DataType
    decimal_separator: DecimalSeparator | None
    date_format: Literal["YYYY-MM-DD"] | None
    max_digits: PositiveInt | None


class OutOfRangeParameters(Schema):
    expected_type: Literal["integer", "decimal"]
    min: str | None
    max: str | None
    decimal_separator: DecimalSeparator | None


class UniqueParameters(Schema):
    comparison: Literal["trimmed_case_sensitive_string"]
    group_size: Annotated[int, Field(ge=2)]


class DuplicateParameters(Schema):
    comparison: Literal["exact_raw_values"]
    group_size: Annotated[int, Field(ge=2)]


RuleParameters = (
    RequiredParameters
    | InvalidTypeParameters
    | OutOfRangeParameters
    | UniqueParameters
    | DuplicateParameters
)


class Issue(Schema):
    issue_id: str
    row_index: PositiveInt
    column_id: ColumnId | None
    column_name: str | None
    rule_code: RuleCode
    message: str
    raw_value: str | None
    rule_parameters: RuleParameters
    duplicate_group_id: str | None

    @model_validator(mode="after")
    def parameters_match_rule(self) -> Self:
        parameter_type = {
            "REQUIRED_VALUE_MISSING": RequiredParameters,
            "INVALID_TYPE": InvalidTypeParameters,
            "OUT_OF_RANGE": OutOfRangeParameters,
            "NON_UNIQUE_VALUE": UniqueParameters,
            "DUPLICATE_ROW": DuplicateParameters,
        }[self.rule_code]
        if not isinstance(self.rule_parameters, parameter_type):
            raise ValueError("The parameters do not match the rule code")
        if self.rule_code == "DUPLICATE_ROW":
            if (
                self.column_id is not None
                or self.column_name is not None
                or self.raw_value is not None
            ):
                raise ValueError("An exact duplicate applies to the entire record")
        elif self.column_id is None or self.column_name is None or self.raw_value is None:
            raise ValueError("A column-level issue requires a column and its raw value")
        if (self.rule_code in ("DUPLICATE_ROW", "NON_UNIQUE_VALUE")) != (
            self.duplicate_group_id is not None
        ):
            raise ValueError(
                "A group reference is required only for exact duplicates and uniqueness issues"
            )
        return self


class DuplicateGroup(Schema):
    group_id: str
    rule_code: Literal["DUPLICATE_ROW", "NON_UNIQUE_VALUE"]
    column_id: ColumnId | None
    normalized_key: str | None
    participant_count: Annotated[int, Field(ge=2)]
    extra_count: PositiveInt

    @model_validator(mode="after")
    def group_matches_rule(self) -> Self:
        if self.extra_count != self.participant_count - 1:
            raise ValueError(
                "The extra duplicate count in a group must equal the participant count minus one"
            )
        if self.rule_code == "DUPLICATE_ROW":
            if self.column_id is not None or self.normalized_key is not None:
                raise ValueError("An exact duplicate has no column or normalized key")
        elif self.column_id is None or self.normalized_key is None:
            raise ValueError("A uniqueness group requires a column and a normalized key")
        return self


class DuplicateGroupPage(DuplicateGroup, Page[RawRecord]):
    @model_validator(mode="after")
    def total_equals_participants(self) -> Self:
        if self.total != self.participant_count:
            raise ValueError("total must equal the group participant count")
        return self


class RecordWithIssues(RawRecord):
    run_id: Identifier
    issues: list[Issue]
    violation_count: NonNegativeInt

    @model_validator(mode="after")
    def all_issues_belong_to_record(self) -> Self:
        if self.violation_count != len(self.issues) or any(
            issue.row_index != self.row_index for issue in self.issues
        ):
            raise ValueError("Issues must refer to this record and match its issue count")
        return self


class CapabilityDefaults(Schema):
    encoding: Encoding
    delimiter: ImportDelimiter
    decimal_separator: DecimalSeparator


class Limits(Schema):
    max_file_size_bytes: PositiveInt
    max_request_body_bytes: PositiveInt
    max_rows: PositiveInt
    max_columns: PositiveInt
    max_cells: PositiveInt
    max_cell_length_chars: PositiveInt
    max_header_length_chars: PositiveInt
    max_filename_length_chars: PositiveInt
    max_multipart_file_parts: PositiveInt
    max_multipart_text_parts: PositiveInt
    max_multipart_text_length_chars: PositiveInt
    max_multipart_part_header_bytes: PositiveInt
    max_datasets: PositiveInt
    max_runs_per_dataset: PositiveInt
    max_numeric_digits: PositiveInt
    default_page_size: PageLimit
    max_page_size: PageLimit
    dataset_idle_ttl_seconds: PositiveInt
    cleanup_interval_seconds: PositiveInt
    idempotency_retention_after_completion_seconds: PositiveInt
    max_issues_per_run: PositiveInt
    import_timeout_seconds: PositiveInt
    run_timeout_seconds: PositiveInt
    upload_timeout_seconds: PositiveInt
    max_storage_bytes: PositiveInt
    storage_reserve_bytes: PositiveInt
    metadata_completion_reservation_bytes: PositiveInt
    max_terminal_error_bytes: PositiveInt
    cleanup_grace_seconds: PositiveInt


class Capabilities(Schema):
    config_schema_version: Literal["1.0"]
    report_schema_version: Literal["1.1"]
    algorithm_version: str
    supported_encodings: list[Encoding]
    supported_delimiters: list[ImportDelimiter]
    supported_types: list[DataType]
    defaults: CapabilityDefaults
    limits: Limits


class Health(Schema):
    status: Literal["ok", "recovering", "unavailable"]


class ErrorPayload(Schema):
    code: str
    message: str
    details: dict[str, Any] | list[Any]
    request_id: Identifier


class ErrorEnvelope(Schema):
    error: ErrorPayload


class PostDatasetReceipt(Schema):
    dataset_id: Identifier
    dataset_url: str


class PostRunReceipt(Schema):
    run_id: Identifier
    dataset_id: Identifier
    status: Literal["queued"]
    status_url: str


class DatasetInfo(Schema):
    dataset_id: Identifier
    original_filename: str
    file_size_bytes: NonNegativeInt
    file_sha256: Sha256
    row_count: NonNegativeInt
    column_count: PositiveInt
    created_at: UTC
    csv: CSVParameters
    ignored_blank_line_count: NonNegativeInt


class ReportRun(Schema):
    run_id: Identifier
    dataset_id: Identifier
    status: Literal["succeeded"]
    created_at: UTC
    started_at: UTC
    finished_at: UTC
    duration_ms: NonNegativeInt


class ExportDuplicateGroup(DuplicateGroup):
    row_indices: list[PositiveInt]


class ProblematicRecord(RawRecord):
    violation_count: PositiveInt
    rule_codes: list[RuleCode]


class Report(Schema):
    report_schema_version: Literal["1.1"]
    algorithm_version: str
    dataset: DatasetInfo
    columns: list[Column]
    configuration_snapshot: Configuration
    run: ReportRun
    profile: list[ColumnProfile]
    summary: Summary
    duplicate_groups: list[ExportDuplicateGroup]
    issues: list[Issue]
    problematic_records: list[ProblematicRecord]


# These constants document the bounded streaming multipart parser without
# replacing it with FastAPI's eager form-body dependency processing.
WRITE_HEADERS_OPENAPI = [
    {
        "name": "X-Dataset-Check",
        "in": "header",
        "required": True,
        "schema": {"type": "string", "enum": ["1"]},
    },
]
IDEMPOTENCY_HEADERS_OPENAPI = WRITE_HEADERS_OPENAPI + [
    {
        "name": "Idempotency-Key",
        "in": "header",
        "required": True,
        "schema": {"type": "string", "format": "uuid"},
        "description": "Use a new UUID for a new action; reuse the same UUID and body when retrying a request.",
    },
]
UPLOAD_OPENAPI = {
    "parameters": IDEMPOTENCY_HEADERS_OPENAPI,
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "additionalProperties": False,
                    "properties": {
                        "file": {
                            "type": "string",
                            "format": "binary",
                            "description": "A single CSV file",
                        },
                        "encoding": {
                            "type": "string",
                            "enum": ["utf-8", "windows-1251"],
                            "default": "utf-8",
                        },
                        "delimiter": {
                            "type": "string",
                            "enum": ["auto", "comma", "semicolon", "tab"],
                            "default": "auto",
                        },
                    },
                },
            },
        },
    },
}

# Short aliases for callers that use the terms from the technical specification.
Profile = ColumnProfile
GroupPage = DuplicateGroupPage
UploadOpenAPISchema = UPLOAD_OPENAPI
