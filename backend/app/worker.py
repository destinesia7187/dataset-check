from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing, contextmanager
from pathlib import Path

from .common import dumps, iso
from .domain.csvio import parse_csv
from .domain.engine import analyze
from .domain.errors import DomainError
from .processes import guard_parent
from .settings import ALGORITHM_VERSION


class Quota:
    def __init__(self, root, limits):
        self.root, self.limits = Path(root), limits

    def check(self, extra=0):
        used = 0
        for path in self.root.rglob("*"):
            try:
                if path.is_file():
                    used += path.stat().st_size
            except FileNotFoundError:
                continue
        if used + extra > self.limits["max_storage_bytes"] - self.limits["storage_reserve_bytes"]:
            raise DomainError(
                "STORAGE_QUOTA_EXCEEDED",
                "The storage quota has been exceeded. Delete unused datasets.",
                {},
            )

    def sqlite_limit(self, db):
        used = sum(path.stat().st_size for path in self.root.rglob("*") if path.is_file())
        free = self.limits["max_storage_bytes"] - self.limits["storage_reserve_bytes"] - used
        pages = db.execute("PRAGMA page_count").fetchone()[0]
        page_size = db.execute("PRAGMA page_size").fetchone()[0]
        db.execute(f"PRAGMA max_page_count={max(pages, pages + max(0, free // (page_size * 2)))}")


def write_json(path, value, quota):
    encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    write_fragments(path, encoder.iterencode(value), quota)


def write_fragments(path, fragments, quota):
    with Path(path).open("wb") as output:
        buffer = bytearray()
        for chunk in fragments:
            buffer.extend(chunk.encode("utf-8"))
            if len(buffer) >= 65536:
                quota.check(len(buffer))
                output.write(buffer)
                buffer.clear()
        if buffer:
            quota.check(len(buffer))
            output.write(buffer)


@contextmanager
def data_connection(path, quota):
    db = sqlite3.connect(path)
    try:
        db.execute("PRAGMA journal_mode=DELETE")
        db.execute("PRAGMA synchronous=FULL")
        quota.sqlite_limit(db)
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def import_data(payload, quota, send):
    send({"stage": "preparing"})
    result = parse_csv(
        payload["input"],
        encoding=payload["encoding"],
        delimiter=payload["delimiter"],
        limits=payload["limits"],
    )
    rows = result.pop("rows")
    folder = Path(payload["folder"])
    with data_connection(folder / "records.sqlite", quota) as db:
        db.execute("CREATE TABLE records(row_index INTEGER PRIMARY KEY, values_json TEXT NOT NULL)")
        for offset in range(0, len(rows), 500):
            quota.check(65536)
            db.executemany(
                "INSERT INTO records VALUES(?,?)",
                [(i + 1, dumps(row)) for i, row in enumerate(rows[offset : offset + 500], offset)],
            )
            db.commit()
    result |= {
        "file_sha256": payload["sha256"],
        "file_size_bytes": Path(payload["input"]).stat().st_size,
        "original_filename": payload["filename"],
        "row_count": len(rows),
        "column_count": len(result["columns"]),
        "csv": {"encoding": result.pop("encoding"), "delimiter": result.pop("delimiter")},
    }
    write_json(folder / "metadata.json", result, quota)
    return {"metadata": result}


def analyze_data(payload, quota, send):
    dataset = payload["dataset"]
    path = Path(payload["dataset_folder"]) / "records.sqlite"
    with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as db:
        rows = [
            json.loads(row[0])
            for row in db.execute("SELECT values_json FROM records ORDER BY row_index")
        ]
    result = analyze(
        rows,
        dataset["columns"],
        payload["configuration"],
        max_issues=payload["limits"]["max_issues_per_run"],
        progress=lambda stage: send({"stage": stage}),
    )
    quota.check()
    folder = Path(payload["folder"])
    with data_connection(folder / "results.sqlite", quota) as db:
        db.executescript("""
            CREATE TABLE issues(ordinal INTEGER PRIMARY KEY,issue_id TEXT,row_index INTEGER,column_id TEXT,rule_code TEXT,group_id TEXT,message TEXT,parameters TEXT);
            CREATE TABLE groups(group_id TEXT PRIMARY KEY,metadata TEXT);
            CREATE TABLE members(group_id TEXT,row_index INTEGER);
            CREATE TABLE problematic(row_index INTEGER PRIMARY KEY,violation_count INTEGER,rule_codes TEXT);
        """)
        values = []
        for number, issue in enumerate(result["issues"], 1):
            # Raw values remain in Record; response serialization resolves the reference.
            values.append(
                (
                    number,
                    issue["issue_id"],
                    issue["row_index"],
                    issue["column_id"],
                    issue["rule_code"],
                    issue["duplicate_group_id"],
                    issue["message"][:1024],
                    dumps(issue["rule_parameters"]),
                )
            )
            if len(values) == 500:
                quota.check(65536)
                db.executemany("INSERT INTO issues VALUES(?,?,?,?,?,?,?,?)", values)
                db.commit()
                values.clear()
        db.executemany("INSERT INTO issues VALUES(?,?,?,?,?,?,?,?)", values)
        for group in result["duplicate_groups"]:
            db.execute(
                "INSERT INTO groups VALUES(?,?)",
                (group["group_id"], dumps({k: v for k, v in group.items() if k != "row_indices"})),
            )
            db.executemany(
                "INSERT INTO members VALUES(?,?)",
                [(group["group_id"], i) for i in group["row_indices"]],
            )
        for record in result["problematic_records"]:
            db.execute(
                "INSERT INTO problematic VALUES(?,?,?)",
                (record["row_index"], record["violation_count"], dumps(record["rule_codes"])),
            )
        db.executescript("""
            CREATE INDEX issue_row ON issues(row_index);
            CREATE INDEX issue_rule ON issues(rule_code,ordinal);
            CREATE INDEX issue_column ON issues(column_id,ordinal);
            CREATE INDEX member_group ON members(group_id,row_index);
        """)
    send({"stage": "building_report"})
    dataset_info_fields = (
        "dataset_id",
        "original_filename",
        "file_size_bytes",
        "file_sha256",
        "row_count",
        "column_count",
        "created_at",
        "csv",
        "ignored_blank_line_count",
    )
    report = {
        "report_schema_version": "1.1",
        "algorithm_version": ALGORITHM_VERSION,
        "dataset": {k: dataset[k] for k in dataset_info_fields},
        "columns": dataset["columns"],
        "configuration_snapshot": payload["configuration"],
        "profile": dataset["profile"],
        "summary": result["summary"],
        "duplicate_groups": result["duplicate_groups"],
        "issues": result["issues"],
        "problematic_records": result["problematic_records"],
    }
    timing = {}

    def report_fragments():
        encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        yield "{"
        for index, (key, value) in enumerate(report.items()):
            if index:
                yield ","
            yield dumps(key) + ":"
            yield from encoder.iterencode(value)
        # All potentially large sections have been serialized before stopping
        # the clock. Only the small run metadata object remains to be written.
        timing["finished"] = time.time()
        timing["duration"] = int((time.monotonic() - payload["started_monotonic"]) * 1000)
        run = payload["run_info"] | {
            "finished_at": iso(timing["finished"]),
            "duration_ms": timing["duration"],
            "status": "succeeded",
        }
        yield ',"run":'
        yield from encoder.iterencode(run)
        yield "}"

    write_fragments(folder / "report.json", report_fragments(), quota)
    return {
        "summary": result["summary"],
        "finished": timing["finished"],
        "duration": timing["duration"],
    }


def worker_entry(payload, connection, parent_pid):
    guard_parent(parent_pid)
    quota = Quota(payload["root"], payload["limits"])
    try:
        # Test-only delay is passed by tests, never by HTTP input.
        if payload.get("test_delay"):
            time.sleep(payload["test_delay"])
        result = (import_data if payload["kind"] == "import" else analyze_data)(
            payload, quota, connection.send
        )
        connection.send({"ok": True, "result": result})
    except DomainError as exc:
        connection.send(
            {"ok": False, "code": exc.code, "message": exc.message, "details": exc.details}
        )
    except (OSError, sqlite3.Error) as exc:
        code = (
            "STORAGE_QUOTA_EXCEEDED" if "full" in str(exc).lower() else "TEMP_STORAGE_UNAVAILABLE"
        )
        connection.send(
            {
                "ok": False,
                "code": code,
                "message": "Not enough space or storage is unavailable",
                "details": {},
            }
        )
    except Exception:
        connection.send(
            {
                "ok": False,
                "code": "INTERNAL_ERROR",
                "message": "Processing failed. Retry with a new key.",
                "details": {},
            }
        )
    finally:
        connection.close()
