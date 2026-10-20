from __future__ import annotations

import csv
import io
import json
import sqlite3
from contextlib import closing, contextmanager

from .common import AppError, dumps


@contextmanager
def results_db(store, run_id):
    path = store.root / "runs" / run_id / "results.sqlite"
    db = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        yield db
    finally:
        db.close()


def resolve_issue(row, record, columns):
    col = next((c for c in columns if c["column_id"] == row["column_id"]), None)
    return {
        "issue_id": row["issue_id"],
        "row_index": row["row_index"],
        "column_id": row["column_id"],
        "column_name": col["display_name"] if col else None,
        "rule_code": row["rule_code"],
        "raw_value": record["values"][col["position"] - 1] if col else None,
        "message": row["message"],
        "rule_parameters": json.loads(row["parameters"]),
        "duplicate_group_id": row["group_id"],
    }


def iter_issues(store, run, dataset, filters=None, offset=0, limit=None):
    clauses, params = [], []
    for key, value in (filters or {}).items():
        if key == "column_id" and value == "__row__":
            clauses.append("column_id IS NULL")
        elif value is not None and key in {"column_id", "rule_code", "row_index"}:
            clauses.append(f"{key}=?")
            params.append(value)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    sql = "SELECT * FROM issues" + where + " ORDER BY ordinal"
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params.extend((limit, offset))
    data_path = store.root / "datasets" / dataset["dataset_id"] / "records.sqlite"
    with (
        results_db(store, run["run_id"]) as db,
        closing(sqlite3.connect(f"file:{data_path.as_posix()}?mode=ro", uri=True)) as records,
    ):
        last_index, last_record = None, None
        for row in db.execute(sql, params):
            if row["row_index"] != last_index:
                values = records.execute(
                    "SELECT values_json FROM records WHERE row_index=?", (row["row_index"],)
                ).fetchone()[0]
                last_index, last_record = (
                    row["row_index"],
                    {"row_index": row["row_index"], "values": json.loads(values)},
                )
            yield resolve_issue(row, last_record, dataset["columns"])


def issues_page(store, run, dataset, filters, offset, limit):
    clauses, params = [], []
    for key, value in filters.items():
        if key == "column_id" and value == "__row__":
            clauses.append("column_id IS NULL")
        elif value is not None:
            clauses.append(f"{key}=?")
            params.append(value)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with results_db(store, run["run_id"]) as db:
        total = db.execute("SELECT count(*) FROM issues" + where, params).fetchone()[0]
    return {
        "items": list(iter_issues(store, run, dataset, filters, offset, limit)),
        "total": total,
        "offset": offset,
        "limit": limit,
    }


def safe_csv(value):
    if value is None:
        return ""
    value = str(value)
    scanned = value.lstrip("\ufeff")
    index = 0
    while index < len(value) and (value[index].isspace() or value[index] == "\ufeff"):
        index += 1
    scanned = value[index:]
    if scanned.startswith(("=", "+", "-", "@", "＝", "＋", "－", "＠")) or value.startswith(
        ("\t", "\r", "\n")
    ):
        return "'" + value
    return value


def csv_stream(store, run, dataset, kind):
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")

    def emit(row):
        buffer.seek(0)
        buffer.truncate(0)
        writer.writerow([safe_csv(v) for v in row])
        return buffer.getvalue().encode("utf-8")

    yield b"\xef\xbb\xbf"
    if kind == "violations-csv":
        fields = (
            "issue_id",
            "row_index",
            "column_id",
            "column_name",
            "rule_code",
            "raw_value",
            "message",
            "rule_parameters_json",
            "duplicate_group_id",
        )
        yield emit(fields)
        for issue in iter_issues(store, run, dataset):
            issue["rule_parameters_json"] = dumps(issue["rule_parameters"])
            yield emit([issue.get(k) for k in fields])
    else:
        yield emit(
            ["dq_record_number", "dq_violation_count", "dq_rule_codes"]
            + ["source." + c["display_name"] for c in dataset["columns"]]
        )
        path = store.root / "datasets" / dataset["dataset_id"] / "records.sqlite"
        with (
            results_db(store, run["run_id"]) as db,
            closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as records,
        ):
            for row in db.execute("SELECT * FROM problematic ORDER BY row_index"):
                values = json.loads(
                    records.execute(
                        "SELECT values_json FROM records WHERE row_index=?", (row["row_index"],)
                    ).fetchone()[0]
                )
                yield emit(
                    [
                        row["row_index"],
                        row["violation_count"],
                        "|".join(json.loads(row["rule_codes"])),
                    ]
                    + values
                )


def require_success(store, run_id):
    run = store.run(run_id)
    if run["status"] != "succeeded":
        raise AppError(
            "RUN_NOT_READY",
            "The final result is available only after a successful validation run",
            409,
        )
    return run, store.dataset(run["dataset_id"])
