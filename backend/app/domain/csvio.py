"""Lossless, bounded CSV import with explicit encodings and strict structure."""

import csv
import io
import unicodedata
from pathlib import Path
from typing import Any

from .engine import suggest_types
from .errors import DomainError

DEFAULT_LIMITS = {
    "max_file_size_bytes": 20 * 1024 * 1024,
    "max_rows": 100_000,
    "max_columns": 100,
    "max_cells": 2_000_000,
    "max_cell_length_chars": 65_536,
    "max_header_length_chars": 128,
}
DELIMITERS = {"comma": ",", "semicolon": ";", "tab": "\t", ",": ",", ";": ";", "\t": "\t"}


def _syntax_check(text: str, delimiter: str, sample_size: int | None = None) -> None:
    """csv.reader accepts quotes inside bare fields; this rejects those too."""
    state = "start"
    line = 1
    records = 0
    record_nonempty = False
    i = 0
    while i < len(text):
        char = text[i]
        newline = char in "\r\n"
        if state == "quoted":
            if char == '"':
                state = "closed"
        elif state == "closed":
            if char == '"':
                state = "quoted"
            elif char == delimiter:
                state = "start"
            elif newline:
                state = "start"
            else:
                raise DomainError(
                    "CSV_PARSE_ERROR",
                    "Expected a delimiter or the end of a record after a closing quote",
                    {"physical_line": line},
                )
        elif char == '"':
            if state != "start":
                raise DomainError(
                    "CSV_PARSE_ERROR",
                    "A quote was found inside an unquoted field",
                    {"physical_line": line},
                )
            state = "quoted"
        elif char == delimiter:
            state = "start"
        elif newline:
            state = "start"
        else:
            state = "bare"

        if newline:
            # A CRLF is one physical line, both within and outside quoted fields.
            if char == "\r" and i + 1 < len(text) and text[i + 1] == "\n":
                i += 1
            line += 1
            if state != "quoted":
                if record_nonempty:
                    records += 1
                record_nonempty = False
                if sample_size is not None and records >= sample_size:
                    return
        else:
            record_nonempty = True
        i += 1
    if state == "quoted":
        raise DomainError("CSV_PARSE_ERROR", "Unclosed quoted field", {"physical_line": line})


def _reader(text: str, delimiter: str) -> Any:
    return csv.reader(
        io.StringIO(text, newline=""),
        delimiter=delimiter,
        quotechar='"',
        doublequote=True,
        strict=True,
    )


def _detect_delimiter(text: str) -> str:
    candidates = []
    for delimiter in (",", ";", "\t"):
        try:
            _syntax_check(text, delimiter, 100)
            width = None
            count = 0
            valid = True
            for fields in _reader(text, delimiter):
                if not fields:
                    continue
                if width is None:
                    width = len(fields)
                if width <= 1 or len(fields) != width:
                    valid = False
                    break
                count += 1
                if count == 100:
                    break
            if valid and count:
                candidates.append(delimiter)
        except (csv.Error, DomainError):
            continue
    if len(candidates) != 1:
        raise DomainError(
            "CSV_DELIMITER_AMBIGUOUS",
            "The delimiter could not be determined unambiguously. Select it manually",
            {"candidates": candidates},
        )
    return candidates[0]


def parse_csv(
    path: str | Path, encoding: str = "utf-8", delimiter: str = "auto", limits: dict | None = None
) -> dict:
    """Import all rows atomically. Values remain exact strings after CSV decoding.

    The caller validates the public filename and manages temporary-file lifetime.
    Any failure raises DomainError; no partial dataset is returned.
    """
    budget = {**DEFAULT_LIMITS, **(limits or {})}
    if encoding not in ("utf-8", "windows-1251") or (
        delimiter != "auto" and delimiter not in DELIMITERS
    ):
        raise DomainError("REQUEST_INVALID", "Unsupported encoding or delimiter", {})
    with Path(path).open("rb") as source:
        data = source.read(budget["max_file_size_bytes"] + 1)
    if len(data) > budget["max_file_size_bytes"]:
        raise DomainError(
            "FILE_TOO_LARGE",
            "The CSV file exceeds the size limit",
            {"max_file_size_bytes": budget["max_file_size_bytes"]},
        )
    try:
        text = data.decode("utf-8-sig" if encoding == "utf-8" else "cp1251", errors="strict")
    except UnicodeDecodeError as error:
        raise DomainError(
            "CSV_DECODE_ERROR",
            "Could not read the file using the selected encoding",
            {"byte_offset": error.start},
        ) from error
    if "\0" in text:
        raise DomainError(
            "CSV_PARSE_ERROR",
            "The CSV file contains a null byte",
            {"physical_line": text.count("\n", 0, text.index("\0")) + 1},
        )
    if not text or not text.strip("\r\n"):
        raise DomainError("CSV_EMPTY_FILE", "The CSV file has no header", {})
    # The csv module has a process-wide field limit. This parser runs in the
    # application's single isolated heavy-operation worker.
    # Parse candidate dialects independently of semantic length limits. Our
    # checks below can then distinguish a bad header from an oversized cell
    # and retain a useful row/column position in the diagnostic.
    csv.field_size_limit(
        max(
            budget["max_file_size_bytes"],
            budget["max_cell_length_chars"],
            budget["max_header_length_chars"],
        )
    )
    actual_delimiter = _detect_delimiter(text) if delimiter == "auto" else DELIMITERS[delimiter]
    _syntax_check(text, actual_delimiter)
    reader = _reader(text, actual_delimiter)
    columns: list[dict] = []
    rows: list[list[str]] = []
    missing: list[int] = []
    ignored = 0
    try:
        for fields in reader:
            if not fields:
                ignored += 1
                continue
            if not columns:
                if len(fields) > budget["max_columns"]:
                    raise DomainError(
                        "DATASET_LIMIT_EXCEEDED",
                        "The column count limit has been exceeded",
                        {"physical_line": reader.line_num, "max_columns": budget["max_columns"]},
                    )
                names: set[str] = set()
                for index, name in enumerate(fields, start=1):
                    display = name.strip()
                    if (
                        not display
                        or len(name) > budget["max_header_length_chars"]
                        or display in names
                        or any(unicodedata.category(char) in ("Cc", "Cf") for char in display)
                    ):
                        raise DomainError(
                            "CSV_HEADER_INVALID",
                            "Column names must be nonempty and unique, and must not contain control characters",
                            {"column_position": index, "physical_line": reader.line_num},
                        )
                    names.add(display)
                    columns.append(
                        {
                            "column_id": f"c{index}",
                            "position": index,
                            "original_name": name,
                            "display_name": display,
                        }
                    )
                missing = [0] * len(columns)
                continue
            record_index = len(rows) + 1
            if len(fields) != len(columns):
                raise DomainError(
                    "CSV_PARSE_ERROR",
                    "The record field count does not match the header",
                    {
                        "row_index": record_index,
                        "physical_line": reader.line_num,
                        "expected_fields": len(columns),
                        "actual_fields": len(fields),
                    },
                )
            if (
                record_index > budget["max_rows"]
                or record_index * len(columns) > budget["max_cells"]
            ):
                raise DomainError(
                    "DATASET_LIMIT_EXCEEDED",
                    "The record or cell count limit has been exceeded",
                    {"row_index": record_index, "physical_line": reader.line_num},
                )
            for index, value in enumerate(fields):
                if len(value) > budget["max_cell_length_chars"]:
                    raise DomainError(
                        "CELL_TOO_LONG",
                        "A value exceeds the length limit",
                        {
                            "row_index": record_index,
                            "column_id": columns[index]["column_id"],
                            "max_cell_length_chars": budget["max_cell_length_chars"],
                        },
                    )
                missing[index] += not value.strip()
            rows.append(fields)
    except csv.Error as error:
        code = (
            "CELL_TOO_LONG" if "field larger than field limit" in str(error) else "CSV_PARSE_ERROR"
        )
        raise DomainError(
            code,
            "A value exceeds the length limit"
            if code == "CELL_TOO_LONG"
            else "Invalid CSV structure",
            {"physical_line": reader.line_num},
        ) from error
    if not columns:
        raise DomainError("CSV_EMPTY_FILE", "The CSV file has no header", {})
    profile = [
        {
            "column_id": column["column_id"],
            "missing_count": missing[index],
            "non_missing_count": len(rows) - missing[index],
        }
        for index, column in enumerate(columns)
    ]
    return {
        "columns": columns,
        "rows": rows,
        "profile": profile,
        "type_suggestions": suggest_types(rows, columns),
        "encoding": encoding,
        "delimiter": actual_delimiter,
        "row_count": len(rows),
        "column_count": len(columns),
        "ignored_blank_line_count": ignored,
    }
