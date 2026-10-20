# Technical specification

## Automated quality checking for open tabular data

| Parameter | Value |
| --- | --- |
| Document version | 1.1 |
| Date | October 19, 2026 |
| Purpose | Build a complete project for a portfolio and resume |
| Target product version | The MVP defined in this document |
| Working name | Dataset Check |
| Primary interface language | English |
| Application format | A locally hosted web application |

### Contents

1. [Requirement status and assumptions](#1-requirement-status-and-assumptions)
2. [Problem, goal, and purpose](#2-problem-goal-and-purpose)
3. [User and primary workflow](#3-user-and-primary-workflow)
4. [First-version scope](#4-first-version-scope)
5. [Terms and addressing](#5-terms-and-addressing-model)
6. [CSV upload](#6-csv-upload-and-parsing--fr-01)
7. [Preview and profile](#7-preview-and-profile--fr-02fr-04)
8. [Rule configuration](#8-rule-configuration)
9. [Validation semantics](#9-validation-semantics--fr-05fr-09)
10. [Statistics and report](#10-statistics-and-report--fr-10)
11. [Interface and filtering](#11-interface-and-filtering--fr-11)
12. [Exports](#12-exports--fr-12)
13. [Lifecycle](#13-dataset-and-run-lifecycle--fr-13fr-14)
14. [HTTP API](#14-http-api-contract)
15. [Architecture and storage](#15-architecture-and-storage)
16. [Non-functional requirements](#16-non-functional-requirements)
17. [Acceptance dataset](#17-acceptance-dataset-with-exact-results)
18. [Acceptance criteria](#18-verification-and-acceptance-criteria)
19. [Implementation stages](#19-implementation-stages)
20. [Deliverables](#20-deliverables-and-project-readiness)
21. [Future development](#21-future-development)
22. [References](#22-references)

## 1. Requirement status and assumptions

This document describes the application's target behavior rather than asserting that every feature has already been implemented. Performance figures are requirements for verifying the completed implementation, not results of measurements already taken.

Statements using “must,” “required,” and identified requirements are mandatory for the MVP. The “Future development” section is outside the first version's readiness criteria.

The following decisions define the project:

- The application runs in a browser, with processing on a local server.
- The primary use case is one user on their own computer.
- The first version accepts CSV only.
- Registration, user accounts, and public multi-user deployment are outside the MVP.
- Uploaded data and results are stored temporarily.
- The system detects violations and helps users investigate them but does not correct data automatically.
- The backend uses Python and FastAPI; the frontend uses React and TypeScript.
- Validation requires no external cloud services or paid APIs.

These decisions may be changed before implementation by updating this document. Adding a future-version feature does not replace fulfilling the MVP requirements.

## 2. Problem, goal, and purpose

### 2.1. Problem

Open tabular data can contain missing required fields, duplicate records, repeated identifiers, values of the wrong type, and numbers outside allowed boundaries. Large tables are difficult to check manually, and the results of separate scripts can be difficult to explain and reproduce.

### 2.2. Goal

Develop an application that automatically checks open tabular data against configurable rules and generates a report identifying specific violations.

### 2.3. Objectives

1. Upload a CSV without losing original values.
2. Show its structure, a preview, and a missing-value profile.
3. Suggest types and allow the user to configure expected types and constraints.
4. Validate every record against the confirmed configuration.
5. Show a summary and locate each violation.
6. Allow the report and problematic records to be downloaded.
7. Demonstrate correctness through reproducible tests and examples.

### 2.4. Interpretation limits

The application checks compliance with configured constraints. Valid coordinate ranges do not establish an object's actual location, and a valid date format does not establish the correct event date. The distinction between value validity and correspondence to reality is described in the [Government Data Quality Framework](https://www.gov.uk/government/publications/the-government-data-quality-framework/the-government-data-quality-framework).

The user is responsible for selecting rules and interpreting findings. If no issues are found, the interface says: “No violations of the configured rules were found.” It must not claim that “The data is completely accurate.”

## 3. User and primary workflow

### 3.1. Target user

An analyst, researcher, student, or developer who needs to check a table before analysis. Using the interface requires no code or SQL.

### 3.2. Primary workflow

1. The user opens the application and selects a CSV.
2. Reviews or changes the encoding and delimiter.
3. Uploads the file and receives a preview.
4. Reviews the record count, columns, missing values, and suggested types.
5. Configures required fields, uniqueness, expected types, and numeric boundaries.
6. Confirms the configuration using “Run validation.”
7. Sees the processing state.
8. Receives a summary, charts, and an issue table.
9. Filters issues, opens an original record, and reviews duplicate groups.
10. Downloads the required results.
11. Changes the rules and starts another run on the same dataset if needed.
12. Deletes the uploaded data or leaves it until automatic deletion.

### 3.3. Alternative workflows

| Situation | Expected behavior |
| --- | --- |
| The file cannot be read | The upload screen shows the cause and an available action |
| Automatic delimiter detection is ambiguous | The user is asked to select the delimiter manually |
| The dataset contains only a header | Columns and zero records are shown; starting a run is disabled |
| The configuration is invalid | An error appears next to the relevant setting before a run can start |
| No issues are found | Zero counters are displayed, and exports remain available |
| Rules change after a run | The old report retains its rule snapshot; new settings require a new run |
| The server connection is temporarily lost | A message is shown; the run status can be requested again |
| Data was deleted or expired | The user is prompted to upload the file again |
| The import or run response is lost | Retrying with the same key returns the previously created resource; the dataset list allows recovery |
| A result, time, or storage budget is exceeded | The specific cause is shown; no partial report is published, and the worker is released |

## 4. First-version scope

### 4.1. Mandatory MVP features

| ID | Feature |
| --- | --- |
| FR-01 | CSV upload and strict parsing |
| FR-02 | Paginated metadata and record viewing |
| FR-03 | Missing-value statistics for each column |
| FR-04 | Editable type suggestions |
| FR-05 | Required-field configuration and validation |
| FR-06 | Exact duplicate record detection |
| FR-07 | Uniqueness checks for selected columns |
| FR-08 | Expected-type checks: text, integer, decimal, date |
| FR-09 | Inclusive numeric range checks |
| FR-10 | Summary report and detailed issue list |
| FR-11 | Issue filtering and duplicate-group viewing |
| FR-12 | Report and problematic-record export |
| FR-13 | Revalidation using a new configuration snapshot |
| FR-14 | Temporary data storage and deletion |
| FR-15 | Active dataset list and recovery after a lost response |
| FR-16 | Safe retries of creation requests using an idempotency key |
| FR-17 | Bounded processing budgets and controlled termination when exceeded |

### 4.2. Outside the MVP

- Excel, JSON, archives, and URL imports.
- Automatic correction or record deletion.
- Regular-expression and allowed-value lookup checks.
- Cross-column rules such as `end_date >= start_date`.
- Composite unique keys across multiple columns.
- Fuzzy duplicate detection, geocoding, and address verification.
- Machine-learning anomaly detection.
- Time-of-day values, time zones, and custom date formats.
- Saved templates, long-term history, and version comparison.
- PDF and XLSX export formats.
- A total quality score with arbitrary weights.
- Registration, roles, collaboration, integrations, and scheduled checks.

## 5. Terms and addressing model

| Term | Definition |
| --- | --- |
| Dataset | One successfully imported CSV with fixed reading parameters |
| Record | A logical CSV record after the header; it may span several physical lines |
| Record number | The accepted data record's sequential number, starting at 1 and excluding the header |
| Physical line | A line in the source text file, used for import diagnostics |
| Column | A table field with a stable technical identifier: `c1`, `c2`, and so on |
| Original value | A string produced by CSV parsing without changing its contents |
| Validation value | The original string with surrounding whitespace removed |
| Rule | A checked constraint with a code and parameters |
| Issue / violation | One rule failure for one record and, where applicable, one column |
| Problematic record | A record with at least one issue |
| Validation / run | An analysis using an immutable configuration snapshot |
| Import error | A structural problem that prevents the whole table from being accepted |
| Execution error | A technical validation failure; it is not counted as a data quality issue |

The interface uses “Record #” rather than implying that the number matches a text-file line. Numbering is consistent across the preview, report, API, and exports. The distinction between physical lines and records follows the behavior of [Python's CSV module](https://docs.python.org/3/library/csv.html).

## 6. CSV upload and parsing — FR-01

### 6.1. Accepted input

- One file with a case-insensitive `.csv` extension.
- Encodings: UTF-8, UTF-8 with BOM, and Windows-1251.
- The default is UTF-8 with BOM support. A decoding error does not automatically trigger a Windows-1251 fallback; the user must select it explicitly.
- Delimiters: comma, semicolon, or tab.
- The first nonempty logical record is always the header; there is no headerless mode.
- Supported syntax includes LF and CRLF line endings, double quotes `"`, doubled quotes within fields, and delimiters and line breaks inside quoted fields.
- Arbitrary escape characters and CSV comments are unsupported.

The HTTP `Content-Type` header does not prove the file's type. The extension check is followed by decoding and actual syntax parsing.

### 6.2. Delimiter detection

The “Delimiter” field supports “Automatic,” “Comma,” “Semicolon,” and “Tab.”

Automatic mode works as follows:

1. Each accepted delimiter is tested against the first 100 nonempty logical records, including the header, or the entire file if it has fewer records.
2. A candidate is valid if the sampled records parse correctly and all have the same field count greater than one.
3. If exactly one candidate qualifies, it is used to parse the whole file.
4. If zero or several candidates qualify, import does not complete: `CSV_DELIMITER_AMBIGUOUS` is returned, and the user selects a delimiter manually.
5. Full parsing still validates every record. A successful sample does not allow later structural errors to be ignored.

Single-column CSV files are supported with an explicitly selected delimiter. Reading parameters are shown before rule configuration and stored in metadata.

### 6.3. Headers

- A BOM is removed only at the start of a UTF-8 file.
- Both the original name and a display name with surrounding whitespace removed are preserved.
- The display name must not be empty or contain control characters, including line breaks.
- The original name is limited to 128 Unicode characters.
- Names that match after surrounding whitespace is removed are rejected; matching is case-sensitive.
- For example, `id` and ` id ` conflict, while `ID` and `id` are different names.
- Columns receive identifiers `c1`, `c2`, … in file order. Rules and the API refer to these identifiers.
- Names must not be silently corrected or renamed.

### 6.4. Structural validity

Every record must have the same field count as the header. Missing fields are not filled automatically, and extra fields are not discarded.

Completely empty physical lines outside quotes are ignored and counted separately. A whitespace-only line is not completely empty. Records such as `,,` or `""` are retained if they match the table structure. The empty final field in `a,b,` is preserved.

Unclosed quotes, decoding errors, null bytes, incorrect field counts, or exceeded limits reject the entire import. A partially accepted dataset is unavailable for validation. Temporary data from failed imports is removed.

The error message includes a code, a clear cause, and an available position: a physical line number or the logical record number being processed. For an unclosed field, the detection position is acceptable even if it does not identify the exact start of the damage.

An empty file is rejected. A file containing only a valid header is accepted for viewing but cannot be validated.

### 6.5. Value preservation

The CSV parser removes structural quoting and restores escaped quotes. The resulting string is stored without changing its case, surrounding whitespace, leading zeros, or embedded line breaks.

Import does not convert original values to numbers, dates, or `null`. For example, `00123`, `NULL`, and `12,50` remain strings. Validation conversions happen separately and never overwrite the original value.

### 6.6. Input limits

| Limit | MVP value |
| --- | ---: |
| File size | At most 20 MiB, or 20 × 1024 × 1024 bytes |
| Data records | At most 100,000 |
| Columns | 1 to 100 |
| Data cells: records × columns | At most 2,000,000 |
| One value's length after CSV parsing | At most 65,536 Unicode characters |
| Datasets stored simultaneously | At most 3 |
| Saved runs per dataset | At most 3 |

The server enforces limits while reading. Exceeding any limit rejects the import even if all others are satisfied. Browser-only checks are insufficient.

The incoming HTTP request must be limited before `multipart/form-data` is fully parsed, rather than only when `UploadFile` is later read. The body limit is 20 MiB + 64 KiB of overhead; actual file content is still limited to 20 MiB. The limit also applies without `Content-Length`. Allowed parts are one file part named `file` and at most two text parts, `encoding` and `delimiter`, each up to 64 characters. Duplicate or additional parts are rejected. Filenames are limited to 255 characters; each part's headers are limited to 8 KiB. Exceeding the body limit returns 413; unsupported multipart structure returns 422.

Limits must be centralized in backend configuration and exposed to the frontend through the API. This document specifies their defaults.

Meeting input limits does not guarantee successful analysis: the result, time, and storage budgets in section 16.1 also apply. The interface shows these constraints before upload.

## 7. Preview and profile — FR-02–FR-04

### 7.1. Metadata

After import, display:

- The original filename without path components.
- Size in bytes and readable units.
- Encoding and actual delimiter.
- Import time.
- Data record and column counts.
- The number of ignored empty physical lines.
- The time until which data remains available without further user activity.

### 7.2. Preview

- A table with record numbers and original values.
- Fifty records per page by default, at most 100 per request.
- Horizontal scrolling for wide tables.
- Long values can be expanded in full.
- Empty strings and whitespace-only strings have visual indicators that do not replace copied values.
- Expanded cells can show line breaks, tabs, and surrounding whitespace in an escaped representation.
- The entire dataset need not be rendered in the DOM.

### 7.3. Column profile

For every column, calculate across the complete dataset:

- Its number, identifier, and name.
- The number of nonempty values.
- The missing-value count and proportion.
- The suggested type or “Undetermined.”
- The number of values used for type suggestion.
- The count and proportion of sampled values matching the suggested type.

The missing-value profile does not depend on whether the column is required.

### 7.4. Type suggestion

The algorithm is deterministic:

1. Use the first 1,000 nonempty values in each column, in file order.
2. Apply the normalization and parsing rules from sections 8 and 9.
3. If an integer representation has leading zeros, such as `00123`, suggest text to avoid misinterpreting identifiers.
4. Otherwise, independently count the sampled values matching date, integer, and decimal.
5. Among types matching at least 95% of the sample, select the one with the most matches. Break ties in this order: date, integer, decimal. `text` does not participate in this comparison.
6. If none of the three types reaches the threshold, suggest text.
7. With no nonempty values, the suggested type is undetermined; the default expected type is text.

For this algorithm, an integer representation with leading zeros matches `[+-]?0[0-9]+`. Original values always remain strings.

A suggestion includes an explanation, for example: “998 of 1,000 nonempty values match integer.” It must not be described as a probability or guarantee.

For example, 95 values of `1` and five values of `1.5` suggest `decimal`: it matches all 100 values, while integer matches 95. For 100 values of `1`, suggest `integer`, because it has equal coverage and higher tie-breaking priority. Date, precision, and leading-zero checks still apply.

The default decimal separator is a point. Changing it recalculates type suggestions without overwriting expected types already selected manually. Final validation covers the complete dataset, not the sample.

## 8. Rule configuration

### 8.1. General parameters

- Exact duplicate detection: enabled by default; it can be disabled.
- Decimal separator: point or comma; point by default.
- Trimming surrounding whitespace for validation: fixed MVP behavior with no separate switch.
- Custom missing-value markers are unsupported.

### 8.2. Column parameters

| Setting | Accepted values | Initial value |
| --- | --- | --- |
| Required | Yes / no | No |
| Unique | Yes / no | No |
| Expected type | `text`, `integer`, `decimal`, `date` | Suggested type, otherwise `text` |
| Minimum | Numeric string or absent | Absent |
| Maximum | Numeric string or absent | Absent |

Multiple columns may be marked unique, but each is checked independently. They do not form a composite key.

Ranges are available only for `integer` and `decimal`. Changing a numeric type to text or date explicitly clears its range in the interface. Changing the decimal separator revalidates entered boundaries without silently converting them.

Required and unique are independent settings. An identifier will commonly need both.

### 8.3. Configuration validation

Before starting a run, the backend must reject:

- Unknown types or column identifiers.
- An omitted column or a column described more than once.
- Unknown configuration fields.
- A range on text or date.
- A nonnumeric boundary, unsupported format, or fractional boundary for an integer type.
- A minimum greater than the maximum.
- A range object with both boundaries absent; use `null` instead.
- An unsupported schema version.

Errors identify the setting, for example `columns[2].range.min`. The interface must display them next to the corresponding form fields.

### 8.4. Configuration snapshot

Clicking “Run validation” confirms the current settings, including suggested types. Separate confirmation of every form cell is unnecessary.

A complete configuration snapshot and algorithm version are stored for each run. Editing the form does not change an existing result. A new run receives a new `run_id`. Saved runs may be deleted separately to free capacity within the limit.

### 8.5. Configuration example

```json
{
  "schema_version": "1.0",
  "decimal_separator": ".",
  "check_duplicate_rows": true,
  "columns": [
    {"column_id": "c1", "required": true, "unique": true, "expected_type": "text", "range": null},
    {"column_id": "c2", "required": true, "unique": false, "expected_type": "text", "range": null},
    {"column_id": "c3", "required": true, "unique": false, "expected_type": "integer", "range": {"min": "0", "max": "100"}},
    {"column_id": "c4", "required": false, "unique": false, "expected_type": "date", "range": null}
  ]
}
```

Boundaries are transmitted as strings to preserve precision through JSON and JavaScript.

## 9. Validation semantics — FR-05–FR-09

### 9.1. Normalization

Definitions:

- `raw_value` is the original value after CSV parsing.
- `normalized_value = raw_value.strip()` is the validation value.

Surrounding Unicode whitespace is removed using Python `str.strip()` semantics. Internal whitespace is preserved; case and Unicode representation are not normalized.

Missing-value, type, range, and uniqueness checks use `normalized_value`. Exact duplicates use `raw_value`. Normalization never changes stored data.

### 9.2. Missing values — `REQUIRED_VALUE_MISSING`

A value is missing if `normalized_value == ""`.

| Value | Missing |
| --- | --- |
| Empty string | Yes |
| Only spaces, tabs, or line breaks | Yes |
| `0` | No |
| `false` | No |
| `NULL`, `NaN`, `N/A`, `-` | No |

For a required column, each missing value creates one `REQUIRED_VALUE_MISSING` issue. Optional columns produce no missing-value issues. Type and range checks are skipped for every missing value.

### 9.3. Types — `INVALID_TYPE`

| Type | Rule |
| --- | --- |
| `text` | Any nonempty string |
| `integer` | Full match of `[+-]?[0-9]+` |
| `decimal` | An optional sign, ASCII integer digits, then an optional decimal separator followed by one or more digits |
| `date` | Strict `YYYY-MM-DD`, an existing calendar date, year 0001 to 9999 |

The point-based decimal pattern is `[+-]?[0-9]+(?:\.[0-9]+)?`; the comma-based pattern is `[+-]?[0-9]+(?:,[0-9]+)?`.

Additional conditions:

- `1.0` and `1,0` do not match integer.
- `.5`, `5.`, thousands separators, exponential notation, currency symbols, `NaN`, and infinity are unsupported.
- An integer representation such as `12` is valid for `decimal`.
- With point selected, `12,5` is invalid, and vice versa.
- `2024-02-29` is valid; `2023-02-29`, `2024-02-30`, and `2024-1-1` are invalid.
- Signs, leading zeros, and negative zero are allowed when a numeric type is selected explicitly.
- The numeric part of a nonempty value is limited to 100 digits in total. Longer representations fail numeric validation even if they fit the overall cell-length limit. This limit does not apply to text.
- Checks use Python integers and exact `Decimal` arithmetic; intermediate conversion to `float` is prohibited.

A nonempty value of the wrong type creates one `INVALID_TYPE` issue. Its range is not checked. The `text` type never produces a type issue.

### 9.4. Ranges — `OUT_OF_RANGE`

- Boundaries are inclusive: `min <= value <= max`.
- A minimum, maximum, or both may be supplied.
- An absent boundary is represented by `null`.
- Values and boundaries are parsed according to the selected numeric type and decimal separator.
- An `integer` boundary must be an integer.
- A value below the minimum or above the maximum creates one `OUT_OF_RANGE` issue.
- When `min == max`, only that value is allowed.
- Missing values and type errors do not produce range issues.

Examples include population with a minimum of `0`, WGS84 latitude from `-90` to `90`, and WGS84 longitude from `-180` to `180`. The user configures these ranges.

### 9.5. Exact duplicates — `DUPLICATE_ROW`

Two records are exact duplicates when their arrays of original values match in every column. Record numbers do not participate in the comparison.

- Case, surrounding whitespace, leading zeros, and the textual representation of numbers all matter.
- `A` and ` A ` in one field make records distinct for this rule.
- Different CSV escaping does not create a distinction if the parsed values are identical.
- Fully empty accepted records also participate.
- Hashing may improve performance, but equality must not rely solely on a hash without checking original values.

Each group of size `k >= 2` creates one issue for all `k` participants, including the first record. The issue applies to the whole record: `column_id = null`, `raw_value = null`.

For a group of three records:

- Duplicate groups: 1.
- Records in groups: 3.
- Extra repetitions beyond the first record: 2.
- `DUPLICATE_ROW` issues: 3.

### 9.6. Uniqueness — `NON_UNIQUE_VALUE`

Values are compared as case-sensitive normalized strings, regardless of the expected type.

| Pair of values | Result |
| --- | --- |
| `A` and ` A ` | The same key |
| `A` and `a` | Different keys |
| `00123` and `123` | Different keys |
| `1` and `1.0` | Different keys |
| Two missing values | Excluded from uniqueness checks |

Each nonempty value occurring `k >= 2` times produces `NON_UNIQUE_VALUE` for all `k` participants. A type error does not exclude a nonempty value from uniqueness checks.

Required-value validation is separate. Two missing values in an optional unique column create no issues. Two missing values in a required unique column create two required-value issues.

Exact duplicates and uniqueness are independent rules. One record may receive both issues.

### 9.7. Ordering and reproducibility

The logical cell-processing order is:

1. Compute the normalized value and missing-value flag.
2. Check whether it is required.
3. Check the type for a nonempty value.
4. Check the range after successful numeric parsing.
5. Independently check uniqueness of the nonempty string value.

Exact duplicate detection independently uses original fields. The implementation may combine passes for performance while preserving these semantics.

Issues are always sorted by record number, then column order; whole-record issues follow column issues. Within a column, the rule order is `REQUIRED_VALUE_MISSING`, `INVALID_TYPE`, `OUT_OF_RANGE`, `NON_UNIQUE_VALUE`.

Groups are numbered by their first participant's record number; uniqueness groups also account for column order first. Technical run IDs and timestamps may differ, but the issues, groups, and result ordering must match for identical input.

## 10. Statistics and report — FR-10

### 10.1. Main metrics

Let `N` be the data record count, `P` the number of distinct record numbers with issues, and `V` the issue count.

```text
Total records = N
Problematic records = P
Records without issues = N - P
Total issues = V
Problematic records, % = 100 × P / N
Missing values in a column, % = 100 × missing values in that column / N
```

`P` is the size of the union of problematic records, not the sum of counts from individual rules. For `N = 0`, profile proportions are zero, and validation cannot start.

The API and JSON report store exact integer counters. Interface percentages are rounded to two decimal places and are never used to reconstruct counters.

### 10.2. Statistical breakdowns

- Issues and affected-record counts for each rule code, including zero values for all five codes.
- Issues and affected-record counts for each column.
- Whole-record issues separately from column issues.
- Missing values for every column, regardless of enabled rules.
- Exact duplicates: groups, participants, and extra repetitions.
- Each unique column: repeated-key groups, participants, and extra repetitions.
- Start time, finish time, analysis duration, and algorithm version.

Column issue counts plus whole-record issues must sum to `V`. Affected-record counts summed across rules or columns may exceed `P`.

### 10.3. Visual presentation

Two simple bar charts are mandatory:

1. Issue counts by rule.
2. Missing-value proportions by column.

Numerical values are also available in a nearby table. Exact duplicates must not be assigned to an arbitrary column. No overall “quality percentage” is calculated.

### 10.4. Issue details

Minimum fields:

| Field | Contents |
| --- | --- |
| `issue_id` | Stable identifier within the run |
| `row_index` | Data record number |
| `column_id` | Column or `null` for the whole record |
| `column_name` | Display name or `null` |
| `rule_code` | One of the five rule codes |
| `message` | A clear explanation in English |
| `raw_value` | Original string or `null` for a whole-record issue |
| `rule_parameters` | Expected type, boundaries, or other parameters for this rule |
| `duplicate_group_id` | Duplicate-group reference or `null` |

Example messages:

- “Required field ‘Address’ is empty.”
- “Expected an integer; received ‘abc’.”
- “Value -5 is below the allowed minimum 0.”
- “The identifier value occurs in 3 records.”
- “This record exactly matches 2 other records.”

## 11. Interface and filtering — FR-11

### 11.1. Upload screen

File selection, supported CSV parameters, input and processing limits, and an upload button. Drag and drop is desirable but is not a separate acceptance criterion.

The home screen also lists active local datasets: filename, record count, creation time, expiry time, run count, and “Open” and “Delete” actions. The list is loaded through `GET /datasets`, is available in a new browser window, and does not depend on IDs saved in the browser. Viewing the list does not extend every dataset's retention. A busy dataset cannot be deleted; the user is shown the reason.

Before uploading or starting a run, the frontend generates and saves a UUID request key. A network failure retries the same request with the same key; a new key is not generated automatically. After receiving a short receipt, the frontend reads the resource through a separate GET request. A new intentional upload or run uses a new key. Retry and recovery rules are defined in section 14.6.

A loading/reading indicator is shown during a request. No invented exact transfer or parsing percentage is required.

### 11.2. Dataset screen

Metadata, preview, profile table, and rule form. Required and unique fields use toggles. Numeric types reveal minimum and maximum inputs.

The interface briefly explains that missing values skip type checks, uniqueness does not make a field required, and exact duplicates compare original values.

### 11.3. Processing

Display the state, stage, and elapsed time. A percentage is acceptable only with a reliable denominator. Stages are preparation, value validation, duplicate detection, and result generation.

Only one resource-intensive operation, import or validation, runs at a time. Repeated button clicks must not create duplicate runs. A new operation while the worker is busy receives a clear busy response.

The screen shows the 100,000-issue limit and processing deadline. For `RESULT_LIMIT_EXCEEDED`, suggest reducing the rules or dataset; for `OPERATION_TIMEOUT`, suggest reducing the dataset; for insufficient storage, suggest deleting unused local datasets. Failure must not appear as zero issues. A new operation can start after temporary data has been cleaned up.

### 11.4. Result screen

- Summary metrics and charts.
- Active rules and reading parameters.
- An issue table with server-side pagination.
- A full original-record view highlighting affected cells.
- Whole-record highlighting for an exact duplicate.
- Paginated viewing of every group participant.
- Export buttons.

Mandatory issue-list filters:

- One rule code or all.
- One column, “Whole record,” or all.
- One specific record number or all.

Filters combine using AND. The default page size is 50; the API accepts 1–100. Ordering is fixed by section 9.7. Display the total matching issue count and current page.

Filters do not change the overall summary. Export buttons download the complete run; exporting the current filter separately is outside the MVP.

### 11.5. States and accessibility

- Errors are available as text, not only through color.
- Fields have labels, buttons support keyboard use, and focus is visible.
- An empty filtered result says “No issues match the selected filters.”
- A zero-issue table must not resemble a loading error.
- Technical failures must not present incomplete results as successful validation.
- The interface primarily targets desktop browsers with a viewport width of at least 1,024 px; table scrolling is acceptable on narrower screens.

## 12. Exports — FR-12

### 12.1. Required files

| File | Purpose |
| --- | --- |
| `report.json` | Complete machine-readable report with summary, configuration, all issues, and full problematic records with unchanged original values |
| `violations.csv` | One exported record per issue |
| `problematic_records.csv` | Each problematic source record once |

The primary human-readable report is displayed in the application. Separate HTML, PDF, and XLSX files are not required for the MVP.

Exports are available only for successful runs and use that run's snapshot. Current unsaved form settings do not affect exports.

### 12.2. `report.json`

The report contains:

- `report_schema_version`, which is `1.1` for this revision.
- Application information and algorithm version.
- Dataset metadata, CSV parameters, and column definitions.
- The rule snapshot.
- Execution times and status.
- Main counters, rule and column breakdowns, and the missing-value profile.
- Duplicate groups and their participant record numbers.
- An array of all issues with original values.
- `problematic_records`, containing every original value of every problematic record.

Example `problematic_records` structure for a separate four-column dataset (not the acceptance CSV in section 17):

```json
[
  {
    "row_index": 7,
    "values": ["A-007", "", "-55", "=1+1"],
    "violation_count": 1,
    "rule_codes": ["REQUIRED_VALUE_MISSING"]
  }
]
```

`values` includes every field in the order of the report's `columns` array, including valid fields. Its length equals the column count; every element is an original string. Each problematic record appears once, in source order. `rule_codes` contains no duplicates and uses the order from section 14.7. With no issues, the array is empty.

CSV safety apostrophes are never applied to JSON: negative numbers, formula-like text, surrounding whitespace, and existing apostrophes retain their original strings. Normal JSON escaping does not change a value after decoding. Consequently, downloaded JSON can restore every field of problematic records after the dataset has been deleted. In the example, the empty second field violates a required-value rule; the valid coordinate `-55` and string `=1+1` are preserved whether or not those fields have issues.

JSON uses UTF-8, valid syntax, and strings for original values and numeric boundaries. `NaN` and `Infinity` are prohibited as JSON numbers. Timestamps use ISO 8601 in UTC with `Z`; the interface may display local time with a time-zone indication.

The report contains no server paths or secrets. Group references resolve within the same report. Records and issues are serialized sequentially without loading the whole document into memory. The top-level object contains `report_schema_version`, `algorithm_version`, `dataset`, `columns`, `configuration_snapshot`, `run`, `profile`, `summary`, `duplicate_groups`, `issues`, and `problematic_records`. Nested entity formats are defined in section 14.7; exported groups use a complete `row_indices` array in source order instead of an `items` page. The exported `run` contains IDs, status, and times without embedding the summary or configuration again.

The complete JSON file is generated in the run's isolated directory before success is published. Incomplete files are unavailable for download. File size counts against the storage budget. Completed JSON is streamed from the saved file.

### 12.3. `violations.csv`

Column order:

```text
issue_id,row_index,column_id,column_name,rule_code,raw_value,message,rule_parameters_json,duplicate_group_id
```

Rule parameters are serialized as a JSON string inside a CSV field. Absent columns, values, and groups use empty fields. Record order matches the unfiltered API.

### 12.4. `problematic_records.csv`

- Include only records with at least one issue.
- Include every record once, regardless of issue count.
- Preserve the dataset's original record order.
- The first columns are `dq_record_number`, `dq_violation_count`, `dq_rule_codes`.
- Follow with all source columns in their original order, using headers `source.<display name>`.
- The `source.` prefix avoids conflicts with technical columns without changing the source headers in storage.
- `dq_rule_codes` contains unique codes in the prescribed order, separated by `|`.
- Original cell values are preserved subject to the CSV safety transformation in section 12.5.

### 12.5. Common CSV export rules

- UTF-8 with BOM, comma separator, and CRLF record endings.
- A proper CSV writer escapes quotes, delimiters, and line breaks.
- Exports do not depend on the input encoding, delimiter, or decimal separator.
- With zero issues, both CSVs contain headers only, and JSON has an empty issue array.
- Headers and string fields originating from the user's file are protected against spreadsheet formula interpretation.

String safety transformation:

1. Never change the original stored value.
2. To detect a dangerous prefix, skip any leading sequence of Unicode whitespace according to `str.isspace()` and BOM characters `U+FEFF`, until the first other character. Alternating whitespace and BOM characters are also skipped; the stored string is unchanged.
3. If the first remaining character is `=`, `+`, `-`, `@`, or its full-width equivalent `＝`, `＋`, `－`, `＠`, prefix the entire original string with an apostrophe `'`.
4. Also add an apostrophe if the original string starts with a tab, CR, or LF.
5. Pass the transformed value to a normal CSV writer. Double quoting alone does not protect against formulas.

For example, `=1+1` is exported as `'=1+1`. Negative numeric strings may also receive a safety apostrophe. The download interface explains that CSV is intended for viewing and may contain a safety prefix; the exact values of every problematic record field are available in `report.json` and the application.

Verify safety behavior in an available version of Excel or LibreOffice, recording the editor and opening method. The criterion is that formulas do not execute when the exported file is first opened in the tested scenario. Universal safety across every editor or after a third-party program resaves the file is not claimed; exact values for programmatic processing are supplied in JSON. The application never executes formulas on the server. The risk of interpreting untrusted CSV as formulas is described in the [OWASP Web Security Testing Guide](https://wstg.owasp.org/latest/4-Web_Application_Security_Testing/07-Injection/21-CSV_Injection/).

## 13. Dataset and run lifecycle — FR-13–FR-14

### 13.1. Dataset

- A dataset receives a random, unpredictable `dataset_id`.
- Reading parameters and original values are immutable after successful import.
- A different encoding or delimiter requires a new import.
- Retention is 60 minutes after the last successful access to the specific dataset or one of its runs. The dataset list, `/health`, and `/capabilities` do not extend retention. Access cannot revive an expired dataset.
- `queued` and `running` states keep the dataset active and accessible through the API regardless of its previous expiry time; completion sets retention to 60 minutes from that point.
- While an export is being generated or transmitted, related data is protected from background cleanup. Manual deletion of a busy dataset or run returns 409.
- Background cleanup runs at least once every five minutes.
- Without active validation or export, the API considers a dataset expired immediately at expiry, even if physical cleanup has not finished.
- Deleting a dataset removes its file, parsed records, profile, runs, and results.
- Attempting to delete a dataset during validation returns a conflict; cancellation is outside the MVP.
- All files and the metadata catalog reside in persistent `DATA_DIR`. Temporary storage means deletion after retention expires, not loss during a normal process or container restart. Docker Compose mounts this directory as a named volume or bind mount.
- Datasets remain discoverable through the list after restart until they expire. Recovery in section 13.3 runs before requests are served.
- Deletion or expiry converts related request keys into short resource-deletion records as defined in section 14.6; those records retain no cell values.

### 13.2. Run

States:

```text
queued -> running -> succeeded
                  -> failed
```

`queued` is a brief state after a job is accepted. There is no queue of several waiting runs: only one run may be accepted by the worker at a time. Import occupies the same worker.

A successful run is immutable. A configuration error creates no run. A technical error after acceptance changes the run to `failed` with a user-safe message. Its incomplete issues are unavailable as a final report.

Unexpired successful runs, source data, configuration snapshots, summaries, and exports must survive normal backend or container restarts with preserved `DATA_DIR`. During recovery, unfinished runs become `failed` with `PROCESS_RESTARTED`; their IDs and rule snapshots are retained, and incomplete results are removed.

Exceeding dataset or run limits returns a conflict suggesting deletion of unused data. An active report must never be deleted automatically to make room for a new run.

### 13.3. Recovery and atomic publication

1. Before cleanup or acceptance of new operations, confirm that the previous parent's child worker has stopped. Check the operation identifier and process identity, not only a reusable PID. If stopping it cannot be confirmed or performed, `/health` remains `unavailable` with HTTP 503, and new operations are rejected. Then open the persistent catalog and let SQLite recover transactions through its normal mechanisms. Never delete SQLite journals manually before this step.
2. Set unfinished runs to `failed / PROCESS_RESTARTED`, populate `finished_at`, and set their dataset expiry to 60 minutes after recovery. Delete their draft data; leave previously successful runs unchanged.
3. An unfinished import never becomes a dataset. Delete its temporary files, and store a terminal `409 / IDEMPOTENCY_OPERATION_INTERRUPTED` response for its key for 24 hours. A new upload requires a new key.
   Also release saved pins from interrupted exports and set the related dataset expiry to 60 minutes after recovery. Such a record must not be removed using its old expiry before its pin is released.
4. Published, unexpired datasets and results remain available. After recovery, clean up expired data and directories unrelated to a published resource or active operation.
5. The child worker writes only to its isolated directory. After preparation succeeds, the parent moves the completed directory to its final location and publishes the resource/status and request-key result in a single metadata-catalog transaction.
6. Catalog publication happens only after files are ready. If the process crashes between file placement and the transaction, the files are unpublished and are cleaned up at startup. A public reference to a missing file must never occur.
7. On expiry or deletion, first revoke resource access in the catalog, then free its files. After a crash, physical cleanup resumes on the next startup.

SQLite must use recoverable journaling and `synchronous=FULL` for the publication catalog. Journaling must not be disabled for speed. The guarantee covers normal restarts and process crashes on a healthy local disk; user deletion of a volume or data directory is not a normal restart.

## 14. HTTP API contract

### 14.1. General rules

- The prefix is `/api/v1`.
- Data and errors use JSON, except for file uploads and downloads.
- OpenAPI documentation is available in the local build.
- Dataset and run identifiers are UUID strings.
- Record numbers start at 1; pagination `offset` starts at 0.
- User values are always transmitted as strings.
- Mutating methods send `X-Dataset-Check: 1` and pass the `Origin`/`Host` checks in section 16.4.
- Both creation POST methods require a UUID `Idempotency-Key` header; retry behavior is defined in section 14.6.
- A list's `total` is the complete filtered element count, not the page length.
- All response fields listed in section 14.7 are mandatory. An unavailable or inapplicable value uses an explicitly allowed `null`; the field is not omitted.

### 14.2. Endpoints

| Method | Path | Purpose / successful response |
| --- | --- | --- |
| GET | `/health` | Process health; 200 |
| GET | `/capabilities` | Limits, types, formats, and schema versions; 200 |
| GET | `/datasets` | Paginated active datasets for opening and deletion; 200 |
| POST | `/datasets` | `multipart/form-data` import: `file`, `encoding`, `delimiter`; short receipt; 201 |
| GET | `/datasets/{dataset_id}` | Metadata, columns, and profile; 200 |
| GET | `/datasets/{dataset_id}/rows` | Records: `offset`, `limit`; 200 |
| GET | `/datasets/{dataset_id}/type-suggestions` | Suggestions for `decimal_separator`; 200 |
| DELETE | `/datasets/{dataset_id}` | Delete the dataset and its results; 204 |
| POST | `/datasets/{dataset_id}/runs` | JSON configuration; accept validation; 202 |
| GET | `/runs/{run_id}` | Status, stage, times, rule snapshot, algorithm version, and summary after success; 200 |
| GET | `/runs/{run_id}/issues` | Issues with filters and pagination; 200 |
| GET | `/runs/{run_id}/groups/{group_id}` | Group type, column, and paginated participants; 200 |
| GET | `/runs/{run_id}/records/{row_index}` | Original record and all its issues; 200 |
| GET | `/runs/{run_id}/exports/{format}` | `report-json`, `violations-csv`, `problematic-records-csv`; 200 |
| DELETE | `/runs/{run_id}` | Delete a completed or failed run; 204 |

`encoding` values are `utf-8`, `windows-1251`; UTF-8 with BOM is accepted as `utf-8`. `delimiter` values are `auto`, `comma`, `semicolon`, `tab`.

The dataset response includes saved runs with IDs, statuses, and creation times. `GET /datasets` allows discovery without a known ID. It returns active datasets only, with `offset` and `limit`, defaulting to 50 and allowing up to 100. Sort by descending `created_at`, then ascending `dataset_id`. Listing does not extend retention. While the worker is busy, the list and other completed results remain readable.

Successful import returns a receipt and `Location: /api/v1/datasets/{dataset_id}`:

```json
{
  "dataset_id": "4f823040-1f69-4d3f-b329-cebe995fab28",
  "dataset_url": "/api/v1/datasets/4f823040-1f69-4d3f-b329-cebe995fab28"
}
```

Metadata is read with a separate GET request; the receipt contains no changing expiry time.

### 14.3. Starting a run

Successful `POST /datasets/{dataset_id}/runs` response:

```json
{
  "run_id": "78bf4217-f9ac-4b01-bb45-b11e827d0030",
  "dataset_id": "4f823040-1f69-4d3f-b329-cebe995fab28",
  "status": "queued",
  "status_url": "/api/v1/runs/78bf4217-f9ac-4b01-bb45-b11e827d0030"
}
```

The frontend polls roughly every 1–2 seconds and stops after `succeeded` or `failed`. A network failure does not mean the backend stopped validation; request the same `run_id` when connectivity returns.

The response includes `Location` equal to `status_url`. If no receipt arrives, the client retries the original POST with its original key. A saved receipt may retain the initial `queued` state even after completion; always read the current state from `status_url`.

Before success, the summary is absent or `null`. Final metrics are published atomically with `succeeded` status.

### 14.4. Issue filters

```text
GET /api/v1/runs/{run_id}/issues
    ?rule_code=INVALID_TYPE
    &column_id=c3
    &row_index=4
    &offset=0
    &limit=50
```

Each filter is optional. Whole-record issues use `column_id=__row__`; this marker is not a dataset column identifier.

An impossible combination of valid filters returns an empty list. An unknown rule code, nonexistent column, negative `offset`, invalid `limit`, or out-of-range record number returns 422.

List response:

```json
{
  "items": [],
  "total": 0,
  "offset": 0,
  "limit": 50
}
```

### 14.5. Errors

Use a single envelope, including for FastAPI validation errors:

```json
{
  "error": {
    "code": "RULE_CONFIG_INVALID",
    "message": "Minimum cannot be greater than maximum",
    "details": [{"field": "columns[2].range", "reason": "min_greater_than_max"}],
    "request_id": "f69004d1-9931-41f1-873e-c07264007856"
  }
}
```

| HTTP | Examples |
| --- | --- |
| 400 | `CSV_DECODE_ERROR`, `CSV_PARSE_ERROR`, `CSV_DELIMITER_AMBIGUOUS`, `CSV_HEADER_INVALID`, `CSV_EMPTY_FILE` |
| 403 | `ORIGIN_NOT_ALLOWED`, `REQUEST_GUARD_REQUIRED` for disallowed mutating requests |
| 404 | `DATASET_NOT_FOUND`, `RUN_NOT_FOUND`, `GROUP_NOT_FOUND`, `IDEMPOTENCY_RESOURCE_GONE`, including deleted or expired data |
| 408 | `UPLOAD_TIMEOUT` when body reception exceeds its deadline |
| 409 | `EMPTY_DATASET`, `RUN_NOT_READY`, `DATASET_BUSY`, `RUN_BUSY`, `DATASET_LIMIT_REACHED`, `RUN_LIMIT_REACHED`, `IDEMPOTENCY_KEY_REUSED`, `IDEMPOTENCY_IN_PROGRESS`, `IDEMPOTENCY_OPERATION_INTERRUPTED` |
| 413 | `FILE_TOO_LARGE`, `DATASET_LIMIT_EXCEEDED`, `CELL_TOO_LONG` |
| 415 | `UNSUPPORTED_FILE_TYPE` |
| 422 | `RULE_CONFIG_INVALID`, `QUERY_INVALID`, `REQUEST_INVALID` for missing/invalid keys or unsupported import parameters |
| 429 | `PROCESSOR_BUSY` for a new resource-intensive operation |
| 500 | `INTERNAL_ERROR` without a traceback or file contents |
| 504 | `OPERATION_TIMEOUT` when synchronous import exceeds its processing budget |
| 507 | `STORAGE_QUOTA_EXCEEDED`, `TEMP_STORAGE_UNAVAILABLE` when the quota or actual available space is exhausted |

A 404 user message may say “Data was not found or its retention period has expired.” Exporting or reading results before completion returns 409. An unexpected error must not become a successful response with an empty list.

After an asynchronous run is accepted, processing errors appear in `Run.error` with `status=failed`; status GET requests still return 200. Allowed error codes are `RESULT_LIMIT_EXCEEDED`, `OPERATION_TIMEOUT`, `STORAGE_QUOTA_EXCEEDED`, `TEMP_STORAGE_UNAVAILABLE`, `PROCESS_RESTARTED`, `WORKER_CRASHED`, and `INTERNAL_ERROR`. A failed run must not produce HTTP 500 on every subsequent GET.

### 14.6. Idempotency and lost responses

Idempotency means retrying an accepted request does not create another dataset or run.

1. The frontend generates a UUID before sending a POST and supplies it in `Idempotency-Key`. A key is scoped to the HTTP method and exact request path; run paths include `dataset_id`. New intentional actions use new keys.
2. The backend stores the key, processing state, request fingerprint, and result in the persistent SQLite catalog. These records survive restarts and contain no file bytes, cell values, or full request bodies.
3. An import fingerprint includes the SHA-256 of the exact file bytes, display filename without path components, and `encoding`/`delimiter` after defaults are applied. Multipart boundaries and text-part order do not affect it. File SHA-256 is also stored in dataset metadata.
4. A run fingerprint uses canonical JSON of the validated configuration: object keys are sorted, column-array order is preserved, and string values are not rewritten. Different object-key order does not make a different request.
5. Repeating a completed POST with the same fingerprint returns its saved HTTP status, body, and `Location`, plus `Idempotency-Replayed: true`. It creates no second resource, run, or worker occupation. Checking a repeated upload's fingerprint may use bounded streaming file reads without reimporting it.
6. A different fingerprint returns 409 `IDEMPOTENCY_KEY_REUSED` without changing the resource. An in-progress request with the same key returns 409 `IDEMPOTENCY_IN_PROGRESS` and `Retry-After: 1`. If the fingerprint is not yet available because transfer is unfinished, an in-progress response is sufficient; comparison happens on a later retry after completion.
7. Header, parameter, busy-state, and metadata-reserve checks happen before a new operation is accepted. A pre-acceptance 403, 422, 429, or 507 does not occupy the key. Once import is accepted, its terminal error is also saved under the key for 24 hours; the same key cannot reimport it. Rule-validation errors create no run.
8. Resource publication and the key's successful receipt occur in one catalog transaction. A state where the resource is accessible but its key is not recorded is prohibited. The HTTP response is sent after this transaction.
9. An accepted run's receipt is stored together with `queued` before execution. After a backend restart, retrying returns the same `run_id`, and GET shows `failed / PROCESS_RESTARTED`. A new intentional run requires a new key.
10. The key/resource relationship lasts for the resource's lifetime and 24 hours after deletion or expiry. After deletion, only a record without user data remains. A retry never revives the resource and returns 404 `IDEMPOTENCY_RESOURCE_GONE`. Unfinished imports after restart use the response from section 13.3.
11. Terminal import errors without created resources and interrupted-import records remain for 24 hours after completion/recovery. The key record may then be cleaned up. After cleanup, the server does not guarantee recognition of an old key; the frontend reuses keys only within the stated period.
12. Processing priority is: protective-header checks → scoped key lookup → retry handling → limits for new operations. A retry of an already published request is not rejected because the worker is busy or the dataset limit is full. A retry does not extend an expired resource. Deletion records must not be cascade-deleted with datasets or runs.

If the browser loses its keys, the user can find resources through the dataset list and the dataset's run list. Idempotency and discovery solve different problems; both are mandatory.

### 14.7. Required response schemas

Below, `int` means an integer JSON number, `UTC` an ISO 8601 string ending in `Z`, `UUID` a UUID string, and `RawRecord` the object `{row_index: int, values: string[]}`. Column positions and record numbers start at 1. `values` always has length `column_count` and follows `columns` order.

Pages use `Page<T> = {items: T[], total: int, offset: int, limit: int}`. An empty page preserves the complete `total` rather than resetting it to zero. Every listed field is mandatory, including allowed `null` values.

**DatasetSummary** — an item in the overall list:

```text
dataset_id: UUID
original_filename: string
file_size_bytes: int
row_count: int
column_count: int
created_at: UTC
expires_at: UTC | null
retention_pinned: boolean
run_count: int
```

`expires_at=null` only while an active operation or export pins retention; `retention_pinned=true` explains that state. Releasing the pin sets retention to 60 minutes ahead. The list has type `Page<DatasetSummary>`.

**Column**: `column_id: string`, `position: int`, `original_name: string`, `display_name: string`.

**ColumnProfile**: `column_id: string`, `non_missing_count: int`, `missing_count: int`. Proportions are calculated from exact counters; rounded API percentages are optional.

`GET /datasets/{dataset_id}/rows` returns `Page<RawRecord>` in `row_index` order; `total` equals the dataset record count. Offsets beyond the last record return an empty page while preserving that `total`.

**TypeSuggestions**:

```text
decimal_separator: "." | ","
columns: Array<{
  column_id: string,
  suggested_type: "text" | "integer" | "decimal" | "date" | null,
  sample_size: int,
  matching_count: int,
  match_counts: {date: int, integer: int, decimal: int},
  reason: "best_match" | "leading_zero" | "fallback_text" | "empty_sample"
}>
```

`matching_count` is the number of sampled values matching the suggested type. For text it equals `sample_size`; for an empty sample it is zero. `match_counts` gives independent results for all three candidates, including those not selected. `GET /type-suggestions` accepts `decimal_separator`, defaults to a point when omitted, and returns this object. An invalid separator returns 422.

**RunListItem**: `run_id: UUID`, `status`, `created_at: UTC`, `started_at: UTC | null`, `finished_at: UTC | null`. Dataset runs are sorted by descending `created_at`, then ascending `run_id`.

**Dataset** — the GET response for a specific dataset: every `DatasetSummary` field, plus `file_sha256: string` of 64 lowercase hexadecimal characters, `csv: {encoding: "utf-8" | "windows-1251", delimiter: "," | ";" | "\t"}`, `ignored_blank_line_count: int`, `columns: Column[]`, `profile: ColumnProfile[]`, `type_suggestions: TypeSuggestions`, `runs: RunListItem[]`. The base suggestions here use a point; another decimal separator uses the separate endpoint. Columns and profiles follow source order.

**DatasetInfo** — immutable JSON-export metadata: `dataset_id`, `original_filename`, `file_size_bytes`, `file_sha256`, `row_count`, `column_count`, `created_at`, `csv`, `ignored_blank_line_count`. Fields have the same types as in `Dataset`; expiry times and other runs are excluded from exports.

**Summary**:

```text
total_records: int
problematic_records: int
clean_records: int
total_issues: int
by_rule: Array<{rule_code: string, issue_count: int, record_count: int}>
by_column: Array<{column_id: string, issue_count: int, record_count: int}>
row_level: {issue_count: int, record_count: int}
duplicate_rows: {enabled: boolean, group_count: int, participant_count: int, extra_count: int}
unique_columns: Array<{column_id: string, group_count: int, participant_count: int, extra_count: int}>
```

`record_count` always counts distinct `row_index` values within the breakdown. `by_rule` includes all five codes, including zeros, in this order: required → type → range → uniqueness → exact duplicate. `by_column` contains all columns; whole-record issues appear only in `row_level`. `unique_columns` includes all configured unique columns in source order. If exact duplicate checks are disabled, `enabled=false` and all other counters in that object are zero.

**Run** — status GET response:

```text
run_id: UUID
dataset_id: UUID
status: "queued" | "running" | "succeeded" | "failed"
stage: "queued" | "preparing" | "validating" | "deduplicating" | "building_report" | "completed" | "failed"
created_at: UTC
started_at: UTC | null
finished_at: UTC | null
duration_ms: int | null
expires_at: UTC | null
retention_pinned: boolean
configuration_snapshot: object from section 8.5
algorithm_version: string
summary: Summary | null
error: {code: string, message: string, details: object} | null
```

The rule snapshot and algorithm version are available from acceptance onward, including `queued` and `failed`. `summary` is not `null` only for `succeeded`; `error` is not `null` only for `failed`. The stage is `completed` for `succeeded` and `failed` for `failed`. Before actual processing starts, `started_at` and `duration_ms` are `null`; completed runs have `finished_at`. Duration after start is measured with a monotonic clock and transmitted as integer milliseconds. Following a restart, time until recovery may include downtime; `error.details` identifies this.

**Issue** follows section 10.4. `issue_id` and `duplicate_group_id` are strings stable within the run; `row_index` is `int`; nullable fields are defined in section 10.4; `rule_parameters` is an object. The issue list is `Page<Issue>`.

Required `rule_parameters` structure by code:

| Code | Object fields |
| --- | --- |
| `REQUIRED_VALUE_MISSING` | `required: true` |
| `INVALID_TYPE` | `expected_type: string`, `decimal_separator: string or null`, `date_format: string or null`, `max_digits: int or null` |
| `OUT_OF_RANGE` | `expected_type: "integer" or "decimal"`, `min: string or null`, `max: string or null`, `decimal_separator: string or null` |
| `NON_UNIQUE_VALUE` | `comparison: "trimmed_case_sensitive_string"`, `group_size: int` |
| `DUPLICATE_ROW` | `comparison: "exact_raw_values"`, `group_size: int` |

For `decimal`, transmit the selected separator; for other types, that field is `null`. Dates use `date_format="YYYY-MM-DD"`; other types use `null`. Numeric types use `max_digits=100`; other types use `null`. In `OUT_OF_RANGE`, at least one boundary is present. `group_size` is at least two. These parameters let the frontend explain a rule without parsing `message` text.

**DuplicateGroupPage**:

```text
group_id: string
rule_code: "DUPLICATE_ROW" | "NON_UNIQUE_VALUE"
column_id: string | null
normalized_key: string | null
participant_count: int
extra_count: int
items: RawRecord[]
total: int
offset: int
limit: int
```

`total=participant_count`, `extra_count=participant_count-1`; participants follow `row_index` order. Exact duplicates use `null` for the column and key. For uniqueness, the key is the normalized string; `items` contains every original field value. Pagination parameters match other lists.

**RecordWithIssues**: `run_id: UUID`, `row_index: int`, `values: string[]`, `issues: Issue[]`, `violation_count: int`. All issues for one record are returned together; their count is bounded by the number of columns and rules. A nonexistent record number returns 422.

**Report** uses the top-level fields from section 12.2: `dataset: DatasetInfo`, `columns: Column[]`, `configuration_snapshot`, `profile: ColumnProfile[]`, `summary: Summary`, `issues: Issue[]`. `run` contains `run_id`, `dataset_id`, `status="succeeded"`, `created_at`, `started_at`, `finished_at`, `duration_ms`. `duplicate_groups` contains group objects without page fields, with full `row_indices: int[]`; groups are ordered as in section 9.7. `problematic_records` follows section 12.2. Unique exported `rule_codes` always use this order: `REQUIRED_VALUE_MISSING`, `INVALID_TYPE`, `OUT_OF_RANGE`, `NON_UNIQUE_VALUE`, `DUPLICATE_ROW`.

**Capabilities** contains `config_schema_version="1.0"`, `report_schema_version="1.1"`, `algorithm_version`, `supported_encodings`, `supported_delimiters`, `supported_types`, and `limits`. `limits` includes every input, storage, and processing parameter from sections 6.6 and 16.1, with units in the names: bytes, seconds, or counts. Exact processing-budget names appear in section 16.1; the frontend reads constraints from the response instead of duplicating numbers in code.

Required field names and defaults:

```json
{
  "config_schema_version": "1.0",
  "report_schema_version": "1.1",
  "algorithm_version": "1.0.0",
  "supported_encodings": ["utf-8", "windows-1251"],
  "supported_delimiters": ["auto", "comma", "semicolon", "tab"],
  "supported_types": ["text", "integer", "decimal", "date"],
  "defaults": {"encoding": "utf-8", "delimiter": "auto", "decimal_separator": "."},
  "limits": {
    "max_file_size_bytes": 20971520,
    "max_request_body_bytes": 21037056,
    "max_rows": 100000,
    "max_columns": 100,
    "max_cells": 2000000,
    "max_cell_length_chars": 65536,
    "max_header_length_chars": 128,
    "max_filename_length_chars": 255,
    "max_multipart_file_parts": 1,
    "max_multipart_text_parts": 2,
    "max_multipart_text_length_chars": 64,
    "max_multipart_part_header_bytes": 8192,
    "max_datasets": 3,
    "max_runs_per_dataset": 3,
    "max_numeric_digits": 100,
    "default_page_size": 50,
    "max_page_size": 100,
    "dataset_idle_ttl_seconds": 3600,
    "cleanup_interval_seconds": 300,
    "idempotency_retention_after_completion_seconds": 86400,
    "max_issues_per_run": 100000,
    "import_timeout_seconds": 120,
    "run_timeout_seconds": 120,
    "upload_timeout_seconds": 60,
    "max_storage_bytes": 1073741824,
    "storage_reserve_bytes": 8388608,
    "metadata_completion_reservation_bytes": 65536,
    "max_terminal_error_bytes": 16384,
    "cleanup_grace_seconds": 5
  }
}
```

`max_request_body_bytes` applies to multipart uploads. `supported_delimiters` contains request-side names, while `Dataset.csv` returns the actual character. `algorithm_version="1.0.0"` is the first implementation version for this revision; semantic changes increment it independently of the document version. `idempotency_retention_after_completion_seconds` means 24 hours after import failure/interruption or deletion of the related resource; while a resource exists, the relationship lasts for its complete lifetime as defined in section 14.6.

**Health**: `{status: "ok" | "recovering" | "unavailable"}`. `ok` and HTTP 200 are available after recovery. Recovery and an unavailable catalog return HTTP 503; new operations are rejected.

## 15. Architecture and storage

### 15.1. Base stack

| Component | Choice |
| --- | --- |
| Backend | Python 3.12 or later, FastAPI, Pydantic, Uvicorn |
| CSV reading | Standard `csv` module, strict mode, and additional structural checks |
| Numbers and dates | `int`, `decimal.Decimal`, `datetime.date` |
| Time-limited storage | Local SQLite and files in persistent `DATA_DIR` |
| Frontend | React, TypeScript, Vite |
| Backend tests | pytest and an HTTP client for API integration checks |
| End-to-end scenario | Playwright or an equivalent using a real browser |
| Delivery | Docker Compose and instructions for running without Docker |

Exact dependency versions are pinned in lockfiles during implementation. The frontend uses a supported Node.js LTS version pinned in project settings. This document does not call specific versions “the latest.”

pandas is not required. If added, automatic type inference and default missing-value markers must not change the established semantics. Relevant options are described in the [`pandas.read_csv` documentation](https://pandas.pydata.org/docs/reference/api/pandas.read_csv.html).

### 15.2. Separation of responsibilities

```text
Browser
  -> HTTP API
      -> import service -> CSV parser -> original-record store
      -> profiling -> profile and type suggestions
      -> run service -> rule engine -> issues and aggregates
      -> report service -> JSON / CSV
```

The rule engine does not depend on FastAPI, React, HTTP requests, or a specific storage mechanism. It can be tested with a small table without starting the web application.

Exports use saved issues and summaries rather than rerunning rules. The result interface and exports share one rule source.

### 15.3. Long-running operations

- One parent HTTP API process coordinates at most one heavy-processing child process. Each new operation creates a new child, for example using `multiprocessing` with the `spawn` context.
- Celery, Redis, and distributed queues are unnecessary. Uvicorn has one HTTP worker; one child processor is allowed concurrently. These counts do not mean two HTTP workers.
- The parent monitors a monotonic deadline, the storage budget, and child state. If a budget expires, it terminates the child, waits for it to stop, and performs cleanup. Publishing `failed` while the heavy task continues in the background is prohibited.
- Tie the worker lifecycle to the parent coordinator through the OS or an equivalent supervisor: a crash of the HTTP process must stop its worker rather than leave it writing to staging. `spawn` alone is insufficient. Recovery also checks that the previous worker is no longer alive as required by section 13.3. Supported platforms must pass this acceptance scenario.
- `ThreadPoolExecutor` is not the sole mechanism for bounding long operations: stopping the wait does not stop an already running function. This limitation is described in the [concurrent.futures documentation](https://docs.python.org/3/library/concurrent.futures.html).
- The child writes only to its operation directory and its own SQLite files. It does not modify the shared metadata catalog, completed datasets, or results. Analysis opens source datasets read-only.
- Shared SQLite connections, publication locks, and reusable queues are not passed between the parent and a forcibly terminated worker. A fresh progress channel is created for each operation and closed afterward. Forced-termination limitations are described in the [multiprocessing documentation](https://docs.python.org/3/library/multiprocessing.html).
- Child failure or termination removes its draft files. The operation slot is released within the cleanup period in section 16.1; the next job receives a new process and channel.
- Short GET requests, the dataset list, and completed reports remain available during analysis. SQLite lock waits cannot be unbounded; `busy_timeout` is limited to one second, with controlled conflict handling.
- Issues are written in bounded batches. Stored `Issue` records refer to source records/columns; full values are not copied repeatedly into issue SQL rows. The API and exports resolve these references to original strings.
- `message` is limited to 1,024 characters, including a value excerpt of at most 128 characters with a truncation marker. The separate `raw_value` field remains complete and untruncated.
- Duplicate detection uses indexes or grouping rather than quadratic pairwise comparison. Large selections, pages, and exports are read in batches.
- A completed run stores separate result files and finished JSON. CSV streams without saving another complete copy; access pins the dataset during transfer.

### 15.4. Storage entities

| Entity | Main data |
| --- | --- |
| Dataset | ID, filename, size, CSV parameters, record/column counts, creation and expiry times |
| Column | Dataset ID, column ID, position, original and display names |
| Record | Dataset ID, record number, array of original strings |
| ColumnProfile | Missing values, populated counts, and type suggestions |
| Run | ID, Dataset ID, status, stage, rule snapshot, algorithm version, timestamps, error |
| Issue | Run ID and the fields from section 10.4 |
| DuplicateGroup | Run ID, rule kind, column or `null`, participants and their count |
| Summary | Final counters and aggregates for a successful run |
| IdempotencyRequest | Scope and key, fingerprint, state, resource ID, saved receipt/error, and retention time |

The physical schema may use JSON fields for original arrays and parameters but must support issue pagination without loading the complete report into memory. Indexes are required on run, record number, rule code, and column.

The shared SQLite catalog stores metadata, publications, and keys. Large dataset and run data are stored separately, so worker termination cannot affect completed results and deleting a resource frees its files without a full `VACUUM` of the shared database. The catalog, sources, results, staging, and SQLite auxiliary files share one budget.

### 15.5. Repository layout

```text
backend/
  app/
    api/
    schemas/
    services/
    domain/
    storage/
  tests/
frontend/
  src/
    api/
    components/
    features/
  tests/
examples/
  synthetic/
  open-data/
docs/
scripts/
README.md
TECHNICAL_SPECIFICATION.md
compose.yaml
.env.example
```

This layout guides responsibility boundaries. Empty layers without a purpose are unnecessary. User data, SQLite files, reports, temporary files, and secrets are excluded from Git.

## 16. Non-functional requirements

### 16.1. Performance

#### Processing budgets

| Parameter in `Capabilities.limits` | Default | Behavior when exceeded |
| --- | ---: | --- |
| `max_issues_per_run` | 100,000 | Finding issue 100,001 produces `failed / RESULT_LIMIT_EXCEEDED` |
| `import_timeout_seconds` | 120 | Import is not published; HTTP 504 `OPERATION_TIMEOUT` |
| `run_timeout_seconds` | 120 | Run becomes `failed / OPERATION_TIMEOUT` |
| `upload_timeout_seconds` | 60 | HTTP 408 `UPLOAD_TIMEOUT`; incomplete body is removed |
| `max_storage_bytes` | 1,073,741,824, or 1 GiB | A new operation is rejected or stopped with `STORAGE_QUOTA_EXCEEDED` |
| `storage_reserve_bytes` | 8,388,608, or 8 MiB within the total quota | Reserve for the status catalog, recording failures, and cleanup; user artifacts do not consume it |
| `cleanup_grace_seconds` | 5 | Maximum time to stop the child and release its slot after a budget overrun is detected |

Body reception time runs from the start of upload handling until the complete bounded HTTP body is received. The import budget starts after body reception and before child startup, ending when the complete dataset and profile are published. The validation budget starts after run acceptance and before child startup, covering analysis, complete JSON construction, and publication of `succeeded`. Report download time is excluded. The parent controls deadlines independently of child progress.

Exactly 100,000 issues are allowed. Exceeding the limit stops the run without a final summary, results list, or export. Issues observed before termination must not be presented as a complete result; `error.details` may include `limit` and `observed_at_least`. Rechecking after rule changes requires a new run and key.

The quota counts the complete actual size of all files in `DATA_DIR`: uploads, catalog and resource databases, WAL/journal/SHM, saved JSON, temporary upload files, staging, and key records. Counting only the main `.sqlite` file or live database rows is insufficient. HTTP body reception and library temporary files also use the controlled directory. SQLite settings must not allow journals or temporary sorting to bypass the budget unnoticed.

Check the available budget before writing/allocating each bounded batch; use a SQLite file-growth limit or equivalent controlled mechanism. Reaching the quota or exhausting actual disk space must stop uncontrolled writing. Keep a reserve for completion and recovery metadata. The coordinator serializes quota checks; opening multiple exports does not save multiple copies.

Before accepting an operation, reserve enough capacity to persist its final state and key: at least 64 KiB of available metadata growth. If reservation is impossible, return 507 before acceptance, without a resource or new key record. Release the reservation after recording the final state; actual metadata remains counted until retention cleanup. The 8 MiB reserve is not unlimited space for keys and errors. Terminal error messages and `details` are limited to 16 KiB when serialized as UTF-8; original cells are excluded.

After failure, delete only the new operation's draft data. Preserve existing unexpired datasets, successful runs, and their keys. Cleanup of deleted datasets/runs frees the quota occupied by their files. If the OS temporarily prevents cleanup, release the slot after stopping the process, mark leftovers for retry, continue counting them against the quota, and never expose them to users.

An accepted input file can exceed these budgets. For example, 100,000 × 20 values of `x`, with `integer` and `unique=true` for every column and exact duplicates enabled, would produce 4,100,000 issues. The MVP must stop predictably at issue 100,001 instead of trying to store millions of rows. Show this limit before a run and include it in the README.

#### Benchmark performance

Benchmark environment: at least four logical CPUs, 8 GiB RAM, an SSD, and a local run without heavy background work. Record the specific CPU, RAM, OS, and dependency versions with measurements.

Benchmark dataset: 100,000 records × 20 columns, a file no larger than 20 MiB, all fields shorter than 100 characters, required-value and type checks on every column, uniqueness on one column, ranges on five numeric columns, exact duplicates enabled, and at most 10,000 final issues.

| Metric | Acceptance target |
| --- | --- |
| Import of the benchmark file, including profiling | At most 20 seconds, excluding network transfer |
| Analysis of the already imported benchmark dataset | At most 30 seconds |
| API page of up to 100 issues from a completed run | At most one second for a normal local request |
| Interface availability during analysis | Status and interface remain accessible |
| Completeness of successful results | All issues within the budget are saved; no truncated successful report |

For import and analysis, take three measurements after one warm-up and evaluate the median. Measure export and file transfer separately. Publish actual results in the README, including any missed targets.

A dataset with many issues may take longer than the benchmark target, but never longer than its processing budget. Exceeding any budget requires the failure behavior defined above. Streaming downloads and server-side pagination are mandatory; the browser must not retain all issues. To restore the rules screen, the frontend reads `configuration_snapshot` from the run GET rather than downloading the complete JSON report.

### 16.2. Reliability

- Never modify the user's original file.
- A failed import leaves no accessible partial dataset.
- A failed run does not damage previously completed results.
- Counters, details, and exports refer to the same run snapshot.
- Insufficient storage returns a clear error and cleans up failed-operation resources.
- The result page can be restored using `dataset_id`/`run_id` after a browser reload while the data remains available.
- After IDs or local browser state are lost, discover datasets through the overall list and runs through the dataset's run list.
- Unexpired successful results and rules remain available after a process/container restart with a preserved data directory; this is a mandatory acceptance scenario.
- Artificially truncated details must not be presented as a complete report.

### 16.3. Untrusted data handling

- Never use an uploaded filename as a server path; generate server-side names in the application.
- Store files outside the static-resource directory and never execute them.
- Never pass cell contents to `eval`, OS commands, SQL concatenation, or executable templates.
- Render all interface values as properly escaped text.
- Rules use structured parameters; arbitrary code and expressions are rejected.
- Enforce size limits while reading, including requests without a trustworthy `Content-Length`.
- Downloads use correct `Content-Type`, `Content-Disposition: attachment`, and no caching of user results.
- Normal logs contain no cell contents, source files, or issue values.
- Logs contain request/run IDs, operation codes, duration, and technical error codes.
- User responses contain no tracebacks, SQL, or internal paths.

File validation and limit principles follow the [OWASP File Upload Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html). Application-specific requirements are stated above and in sections 6 and 12.

### 16.4. Local deployment

- By default, publish the application port only on `127.0.0.1`.
- The shipped frontend and API share one origin.
- Development allows only an explicitly configured frontend origin; CORS `*` is prohibited. Explicitly allow `X-Dataset-Check`, `Idempotency-Key`, and required methods for that origin; expose response headers `Location`, `Idempotency-Replayed`, and `Retry-After` for reading receipts.
- State-changing requests require `X-Dataset-Check: 1`. This guards against simple cross-origin browser requests; it is not user authentication. The frontend and API examples send it explicitly.
- If supplied, validate `Origin` against the allowlist and reject disallowed origins before changing state. Requests without `Origin`, such as CLI requests, are allowed only with the protective header. CORS preflight must not authorize that header for a third-party origin.
- Validate `Host` against an explicit list of local names and configured addresses. CORS configuration alone is insufficient because a simple third-party multipart request can be sent without permission to read its response.
- The API is not intended for unauthenticated deployment on the public internet.
- The interface states that the local server processes the file and deletes it automatically after retention expires.
- After dependency installation, the application can run without external network calls.

A public demonstration accepting different users' files requires a separate specification extension covering isolation, authentication or sessions, quotas, and access policies. It is not a readiness condition for the local MVP.

### 16.5. Maintainability

- Backend, frontend, and report schemas have pinned versions.
- Formatting checks, static analysis, and TypeScript type checks are available.
- Environment configuration is documented in `.env.example`; secrets are excluded from the repository.
- Public rule-engine functions have types and clear contracts.
- Core checks run through one documented command without a browser or external service.
- CI runs the required backend checks, frontend build, and primary end-to-end scenario.
- An arbitrary coverage percentage is not a standalone criterion; tests of the specified semantics and failures matter.

## 17. Acceptance dataset with exact results

### 17.1. Data

The implemented `examples/synthetic/acceptance.csv` must contain:

```csv
id,name,population,opened_at
A,Object A,10,2024-02-29
B,,5,2024-02-30
B,Object B,-1,2024-03-01
C,Object C,abc,
A,Object A,10,2024-02-29
,Object D,100,2024-03-02
D,Object E,1.5,2024-03-03
E,Object F,"  ",2024-03-04
F,Object G,0,2024-03-05
```

Parameters: UTF-8, comma delimiter, point decimal separator. Rules match the JSON in section 8.5: `id`, `name`, and `population` are required; `id` is unique; `population` is an integer in `[0; 100]`; `opened_at` is an optional date; exact duplicate detection is enabled.

### 17.2. Expected summary

| Metric | Value |
| --- | ---: |
| Data records | 9 |
| Columns | 4 |
| Problematic records | 8 |
| Records without issues | 1 |
| Total issues | 13 |
| `REQUIRED_VALUE_MISSING` | 3 |
| `INVALID_TYPE` | 3 |
| `OUT_OF_RANGE` | 1 |
| `NON_UNIQUE_VALUE` | 4 |
| `DUPLICATE_ROW` | 2 |
| Problematic-record proportion | 88.89% |
| Exact duplicate groups | 1 |
| Exact duplicate participants / extra repetitions | 2 / 1 |
| Non-unique `id` key groups | 2 |
| Non-unique key participants / extra repetitions | 4 / 2 |

### 17.3. Expected issues by record

| Record | Issues | Count |
| --- | --- | ---: |
| 1 | Non-unique `id=A`; exact duplicate of record 5 | 2 |
| 2 | Missing `name`; invalid date; non-unique `id=B` | 3 |
| 3 | `population=-1` is out of range; non-unique `id=B` | 2 |
| 4 | `population=abc` is not an integer | 1 |
| 5 | Non-unique `id=A`; exact duplicate of record 1 | 2 |
| 6 | Missing required `id` | 1 |
| 7 | `population=1.5` is not an integer | 1 |
| 8 | Missing required `population` | 1 |
| 9 | No issues | 0 |

Each of the four columns has exactly one missing value, or 11.11%. The optional missing date in record 4 increases the missing-value count but not the issue count.

Column issue counts are `id`: 5, `name`: 1, `population`: 4, `opened_at`: 1. Two more issues apply to whole records. Total: `5 + 1 + 4 + 1 + 2 = 13`.

## 18. Verification and acceptance criteria

### 18.1. Verification levels

1. Core unit checks: normalization, types, ranges, uniqueness, exact duplicates, and aggregates.
2. Integration checks for import, storage, API, exports, and deletion.
3. One primary real-browser scenario: upload → configure → run → review → export.
4. Manual interface readability and CSV safety checks in a spreadsheet editor.
5. A separate reproducible performance benchmark.

### 18.2. Mandatory scenario matrix

| ID | Condition | Expected result |
| --- | --- | --- |
| AC-01 | Acceptance file and rules from section 17 | Every counter and issue matches exactly |
| AC-02 | A valid dataset | Zero issues and zero problematic records; exports work |
| AC-03 | An empty required number with a range | Only one required-value issue |
| AC-04 | `abc` in a numeric field with a range | A type issue and no range issue |
| AC-05 | A number equal to the minimum or maximum | No range issue |
| AC-06 | Minimum exceeds maximum | 422; no run is created |
| AC-07 | Three identical records | One group, three participants, two extra repetitions, three exact duplicate issues |
| AC-08 | Two missing values in an optional unique field | No uniqueness issue |
| AC-09 | `A`, ` A `, `a` in a unique field | The first pair forms a group; `a` is separate |
| AC-10 | `00123` and `123` | Distinct keys; original values are preserved |
| AC-11 | Duplicates containing an invalid number | Type and duplication issues are counted independently |
| AC-12 | UTF-8 with BOM and Cyrillic text | The BOM is excluded from the first header; text is correct |
| AC-13 | Explicitly selected Windows-1251 | Cyrillic text is read correctly |
| AC-14 | A delimiter, quote, and line break inside a field | Correct values and logical record numbering |
| AC-15 | An empty final field | The field is preserved |
| AC-16 | An empty file | Import error |
| AC-17 | Header only | Preview of zero records; run unavailable |
| AC-18 | An unclosed quote or incorrect field count | The entire import is rejected, with an available position |
| AC-19 | An empty or duplicate header | Error identifying positions |
| AC-20 | File, records, columns, cells, or value exceeds a limit | Predictable error; no partial dataset |
| AC-21 | `NULL`, `NaN`, `0`, `false` | Not automatically treated as missing |
| AC-22 | `2024-02-29`, `2023-02-29`, `2024-1-1` | Only the first date is valid |
| AC-23 | Change the decimal separator | Rules and suggestions are recalculated using the selected separator |
| AC-24 | Change rules after success | The old run is immutable; a new result has a different ID |
| AC-25 | Filtering and page navigation | Complete match count, with no gaps or duplicates across pages |
| AC-26 | Multiple issues in one record | The record appears once in the problematic-record CSV |
| AC-27 | Export any successful run | Counters and details match that run's API |
| AC-28 | `=1+1`, `+1+1`, `@SUM(1)`, full-width variants, a dangerous prefix after whitespace, TAB/CR/LF, and BOM → space → BOM sequences | CSV includes a safety apostrophe; JSON preserves the original string; the tested opening scenario executes no formula |
| AC-29 | `<script>alert(1)</script>` in a cell | Rendered as text; no code executes |
| AC-30 | Repeat a run with identical data and rules | Identical issues, groups, and ordering, excluding technical IDs and times |
| AC-31 | A second run or import while the worker is busy | The new heavy operation is rejected without double processing |
| AC-32 | Restart the backend during analysis, including a container restart with preserved volume | The unfinished run becomes `failed / PROCESS_RESTARTED`; unexpired completed results, rules, summary, issue pages, and all exports remain unchanged and accessible |
| AC-33 | Manual deletion / expiry / previous expiry time passes during an active run | Unpinned expired data is unavailable and cleaned up; the active dataset stays available through completion and then receives another 60 minutes |
| AC-34 | Benchmark workload from section 16.1 | Time targets are met, or this criterion remains incomplete |
| AC-35 | A single-column CSV with an explicit delimiter | Import succeeds; automatic mode asks for clarification |
| AC-36 | Ambiguous automatic delimiter detection | Manual selection is required without silent interpretation |
| AC-37 | Multipart exceeds the limit without `Content-Length`, includes an extra file part, or repeats a parameter | Rejected before saving the complete body; no partial dataset |
| AC-38 | A mutating request with a third-party `Origin`, invalid `Host`, or no protective header | Application state is unchanged; allowed frontend and CLI requests work |
| AC-39 | 95 values of `1` and five values of `1.5` | Suggest `decimal`; `match_counts.integer=95`, `match_counts.decimal=100` |
| AC-40 | A sample of integers only, without leading zeros | Equal `integer` and `decimal` coverage suggests `integer` |
| AC-41 | A problematic record with an empty required field and valid fields containing `-55`, `=1+1`, whitespace, and an original apostrophe | JSON includes all original fields without safety transformations; the record can be restored from `problematic_records` after dataset deletion |
| AC-42 | Acceptance dataset from section 17 | JSON contains exactly eight full problematic records numbered 1–8; `violation_count` sums to 13 |
| AC-43 | Import is committed but its 201 response is lost; repeat the request with the same key | Original ID, status, and receipt are returned; `Idempotency-Replayed=true`; only one dataset exists |
| AC-44 | A run is accepted but its 202 response is lost; repeat the POST after completion | The same `run_id` returns; no second job or extra run-limit usage |
| AC-45 | The same key with another file/parameters or configuration | 409 `IDEMPOTENCY_KEY_REUSED`; the original resource is unchanged |
| AC-46 | Concurrent requests with one still-processing key | No second operation; 409 `IDEMPOTENCY_IN_PROGRESS` with `Retry-After`; a later retry returns the original resource |
| AC-47 | A new browser without saved IDs/keys when three local datasets already exist | Datasets appear in the overall list; one can be deleted to upload another; reading the list does not extend all TTLs |
| AC-48 | Change the form rules, then open/reload an older run | Restore original rules and algorithm version from run GET without downloading the complete issue JSON |
| AC-49 | Exactly 100,000 issues with sufficient time and storage | Success and a complete, untruncated report |
| AC-50 | The 100,001st issue is found | `failed / RESULT_LIMIT_EXCEEDED`; `summary=null`; final issue lists and exports are unavailable |
| AC-51 | 100,000 × 20 values of `x`, integer types and uniqueness on every column, exact duplicates enabled | Controlled limit failure, cleanup, and worker release; the next valid job runs |
| AC-52 | An artificially delayed worker with a reduced test deadline | Child process stops; import is unpublished or run becomes `failed / OPERATION_TIMEOUT`; slot released within `cleanup_grace_seconds` |
| AC-53 | Exceed a reduced test disk quota, including SQLite auxiliary files | `STORAGE_QUOTA_EXCEEDED`; new drafts are cleaned up, previous successful reports and exports remain available |
| AC-54 | Delete a large completed dataset or run after a quota failure | Its files free quota; the next operation is accepted without manual database cleanup |
| AC-55 | Delete or expire a resource, then retry its POST with the original key within 24 hours | 404 `IDEMPOTENCY_RESOURCE_GONE`; no dataset/run recreation |
| AC-56 | Backend crashes after committing the resource and key but before sending the receipt | After restart, retry returns the original resource without a second dataset/run |
| AC-57 | Restart during an unfinished import | No partial dataset; drafts are cleaned up; the original key returns `IDEMPOTENCY_OPERATION_INTERRUPTED`; a new key permits a new upload |
| AC-58 | Execute all main GETs and JSON export | Responses satisfy section 14.7 schemas, including nullable fields, array order, and complete original strings |
| AC-59 | HTTP body reception exceeds a reduced test limit | HTTP 408 `UPLOAD_TIMEOUT`; temporary body removed; operation slot is not left occupied |
| AC-60 | JSON and CSV from one successful run with the result limit active | Complete counters, safely transformed CSV, all original problematic records in JSON; reading exports creates no extra full copies |
| AC-61 | Crash the parent HTTP process while its child worker is running, then restart | The old worker stops writing; its absence is confirmed before cleanup; two heavy workers never run concurrently |
| AC-62 | Restart during an active export transfer after the dataset's previous expiry | Recovery releases the pin and grants another 60 minutes; dataset remains available; completed JSON and results are intact |
| AC-63 | Completion-metadata reserve is exhausted while previous error keys are retained | A new operation receives 507 before acceptance; no new key/resource; existing results and keys remain available |

For fast CI, time, quota, and issue-count budgets may be reduced through test configuration while preserving boundary logic. Default-value checks are also mandatory, including 100,000/100,001 issues and stress case AC-51; they may run through a separate documented command. Boundary example: 100,000 identical nonempty keys with only a uniqueness rule create exactly 100,000 issues; adding a type issue in another column produces 100,001.

### 18.3. Open-data demonstration

The repository must include at least one reproducible example using a real open dataset. Record:

- Its name, publisher, and direct source link.
- Retrieval date and license or terms of use.
- Included fields and the selected rules.
- A reproduction command or instructions.
- Findings and interpretation limits.
- A file checksum or version information where needed.

If the source changes, the example must not promise an unchanged issue count without a fixed version. Distinguish artificially introduced errors from source-data issues explicitly. If redistribution of the source file is not permitted, retain retrieval instructions and permissible demonstration material in the repository.

## 19. Implementation stages

| Stage | Scope | Verifiable result |
| --- | --- | --- |
| 1. Core | Original-value model, normalization, rules, aggregates | The acceptance example and edge cases pass without a web server |
| 2. Import and storage | CSV, limits, profile, SQLite, dataset list, request keys, cleanup, recovery | A dataset is fully imported or rejected; lost receipts and restarts neither duplicate nor lose published data |
| 3. Runs and reports | Rule snapshots, states, child-process budgets, filters, groups, complete exports | The API provides a consistent result or controlled failure without truncated success |
| 4. Interface | Upload, preview, form, state, result | The primary workflow works in a browser |
| 5. Verification and delivery | Integration, E2E, load, Docker, documentation | The project starts from a clean installation following the README |
| 6. Portfolio | Real example, screenshots, explanation of decisions | The problem, implementation, and measurable results can be demonstrated |

Estimate duration after selecting specific frontend libraries and checking the environment. This document sets no calendar deadlines.

## 20. Deliverables and project readiness

The MVP is ready when mandatory requirements and acceptance scenarios are satisfied and the repository contains:

- Backend and frontend source code.
- This document.
- A README with purpose, limits, screenshots, and startup instructions.
- Pinned dependencies and `.env.example`.
- Docker Compose supporting `docker compose up --build`.
- Local startup instructions without Docker.
- Automated checks and commands for running them.
- The acceptance CSV, its configuration, and expected summary.
- A fixed-seed benchmark dataset generator.
- A mass-issue stress dataset and separate budget-check command.
- Actual measurements with machine details.
- A real open-data demonstration.
- API schemas and export format documentation.
- Explicit retention and local-mode constraints.
- Documentation for `DATA_DIR`, persistent volumes, request retries, and restart recovery.
- A JSON report example that restores every original field of problematic records.

During delivery verification on a clean environment, the user must be able to open the application, upload the acceptance file, obtain 13 issues in eight records, and download all three results using the documented instructions. After a normal restart with the same directory, the dataset is found in the list and yields the same result; after deletion, full problematic records can be restored from downloaded JSON.

Resume claims must describe work actually completed. Unverified performance, user counts, and future-version features must not be included.

## 21. Future development

Possible independent extensions after the MVP is complete:

1. XLSX with worksheet selection and formula-handling rules.
2. Rule templates and their import/export.
3. Allowed-value lookups and regular expressions.
4. Composite keys and cross-field consistency rules.
5. Additional date formats, boolean, and datetime.
6. Long-term history and dataset version comparison.
7. Suspicious values and anomalies as separate warnings.
8. Batch processing and scheduled runs.
9. Public deployment with user isolation and quotas.
10. HTML/PDF reports and XLSX export.

Each extension requires its own acceptance criteria and must not change existing rule semantics without incrementing the algorithm version.

## 22. References

These references inform data quality concepts and format limitations. Product decisions, limits, and criteria in this specification are defined for this project.

- [Government Data Quality Framework](https://www.gov.uk/government/publications/the-government-data-quality-framework/the-government-data-quality-framework) — distinctions between data quality dimensions.
- [Python: csv](https://docs.python.org/3/library/csv.html) — parsing, string values, dialects, and logical records.
- [FastAPI: Request Files](https://fastapi.tiangolo.com/tutorial/request-files/) — `multipart/form-data` uploads.
- [pandas.read_csv](https://pandas.pydata.org/docs/reference/api/pandas.read_csv.html) — type and missing-marker behavior if pandas is introduced.
- [OWASP: File Upload Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html) — handling untrusted uploaded files.
- [OWASP: Testing for CSV Injection](https://wstg.owasp.org/latest/4-Web_Application_Security_Testing/07-Injection/21-CSV_Injection/) — formula risks in CSV exports.
- [Python: concurrent.futures](https://docs.python.org/3/library/concurrent.futures.html) — limits of cancelling an already running function.
- [Python: multiprocessing](https://docs.python.org/3/library/multiprocessing.html) — separate processes and forced-termination limitations.
- [SQLite: Atomic Commit](https://www.sqlite.org/atomiccommit.html) — transactional commits and crash recovery.
