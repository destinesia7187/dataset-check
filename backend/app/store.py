from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import time
from contextlib import closing, contextmanager
from pathlib import Path

from .common import AppError, dumps, iso


class Store:
    """Only the coordinator writes this catalogue; workers write isolated artifacts."""

    def __init__(self, settings):
        self.settings = settings
        self.root = settings.data_dir
        self.root.mkdir(parents=True, exist_ok=True)
        for name in ("datasets", "runs", "staging"):
            (self.root / name).mkdir(exist_ok=True)
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS datasets (
                    id TEXT PRIMARY KEY, metadata TEXT NOT NULL,
                    created REAL NOT NULL, expires REAL NOT NULL, pins INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, configuration TEXT NOT NULL,
                    status TEXT NOT NULL, stage TEXT NOT NULL, created REAL NOT NULL,
                    started REAL, finished REAL, duration INTEGER, summary TEXT, error TEXT,
                    algorithm_version TEXT NOT NULL DEFAULT '1.0.0', export_pins INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS runs_dataset ON runs(dataset_id,created);
                CREATE TABLE IF NOT EXISTS requests (
                    scope TEXT NOT NULL, key TEXT NOT NULL, fingerprint TEXT,
                    state TEXT NOT NULL, resource_type TEXT, resource_id TEXT,
                    http_status INTEGER, response TEXT, location TEXT, expires REAL,
                    PRIMARY KEY(scope,key)
                );
                CREATE TABLE IF NOT EXISTS pending_deletes(path TEXT PRIMARY KEY);
            """)
            names = {r[1] for r in db.execute("PRAGMA table_info(runs)")}
            if "algorithm_version" not in names:
                db.execute(
                    "ALTER TABLE runs ADD COLUMN algorithm_version TEXT NOT NULL DEFAULT '1.0.0'"
                )
            if "export_pins" not in names:
                db.execute("ALTER TABLE runs ADD COLUMN export_pins INTEGER NOT NULL DEFAULT 0")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.root / "catalog.sqlite", timeout=1)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA busy_timeout=1000")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def used_bytes(self):
        total = 0
        for path in self.root.rglob("*"):
            try:
                if path.is_file():
                    total += path.stat().st_size
            except FileNotFoundError:
                continue
        return total

    def check_space(self, additional=0, metadata=False):
        limit = self.settings.limits["max_storage_bytes"]
        if not metadata:
            limit -= self.settings.limits["storage_reserve_bytes"]
        if self.used_bytes() + additional > limit:
            raise AppError(
                "STORAGE_QUOTA_EXCEEDED",
                "The storage quota has been exhausted. Delete unused datasets or runs.",
                507,
            )
        if shutil.disk_usage(self.root).free < additional + 65536:
            raise AppError("TEMP_STORAGE_UNAVAILABLE", "Not enough free disk space", 507)

    def reserve_completion(self):
        self.check_space(
            self.settings.limits["metadata_completion_reservation_bytes"], metadata=True
        )

    def request(self, scope, key):
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM requests WHERE scope=? AND key=?", (scope, key)
            ).fetchone()
        if row and row["expires"] is not None and row["expires"] <= time.time():
            with self.connect() as db:
                db.execute("DELETE FROM requests WHERE scope=? AND key=?", (scope, key))
            return None
        return dict(row) if row else None

    def begin_request(self, scope, key):
        self.reserve_completion()
        with self.connect() as db:
            db.execute(
                "INSERT INTO requests(scope,key,state) VALUES(?,?,'processing')", (scope, key)
            )

    def fingerprint_request(self, scope, key, fingerprint):
        with self.connect() as db:
            db.execute(
                "UPDATE requests SET fingerprint=? WHERE scope=? AND key=?",
                (fingerprint, scope, key),
            )

    def fail_request(self, scope, key, status, response):
        expiry = (
            time.time() + self.settings.limits["idempotency_retention_after_completion_seconds"]
        )
        with self.connect() as db:
            db.execute(
                "UPDATE requests SET state='failed',http_status=?,response=?,expires=? WHERE scope=? AND key=?",
                (status, dumps(response), expiry, scope, key),
            )

    def drop_processing_request(self, scope, key):
        with self.connect() as db:
            db.execute(
                "DELETE FROM requests WHERE scope=? AND key=? AND state='processing'", (scope, key)
            )

    def publish_dataset(self, resource_id, metadata, scope, key, receipt):
        now = time.time()
        with self.lock, self.connect() as db:
            db.execute(
                "INSERT INTO datasets VALUES(?,?,?,?,0)",
                (
                    resource_id,
                    dumps(metadata),
                    now,
                    now + self.settings.limits["dataset_idle_ttl_seconds"],
                ),
            )
            db.execute(
                "UPDATE requests SET state='done',resource_type='dataset',resource_id=?,http_status=201,response=?,location=?,expires=NULL WHERE scope=? AND key=?",
                (resource_id, dumps(receipt), receipt["dataset_url"], scope, key),
            )

    def dataset(self, resource_id, touch=True):
        with self.lock, self.connect() as db:
            row = db.execute("SELECT * FROM datasets WHERE id=?", (resource_id,)).fetchone()
            if not row or (not row["pins"] and row["expires"] <= time.time()):
                raise AppError("DATASET_NOT_FOUND", "Dataset not found or expired", 404)
            if touch:
                expiry = time.time() + self.settings.limits["dataset_idle_ttl_seconds"]
                db.execute("UPDATE datasets SET expires=? WHERE id=?", (expiry, resource_id))
            else:
                expiry = row["expires"]
            value = json.loads(row["metadata"])
            runs = db.execute(
                "SELECT id,status,created,started,finished FROM runs WHERE dataset_id=? ORDER BY created DESC,id",
                (resource_id,),
            ).fetchall()
        value |= {
            "dataset_id": resource_id,
            "created_at": iso(row["created"]),
            "expires_at": None if row["pins"] else iso(expiry),
            "retention_pinned": bool(row["pins"]),
            "run_count": len(runs),
        }
        value["runs"] = [
            {
                "run_id": r["id"],
                "status": r["status"],
                "created_at": iso(r["created"]),
                "started_at": iso(r["started"]) if r["started"] else None,
                "finished_at": iso(r["finished"]) if r["finished"] else None,
            }
            for r in runs
        ]
        return value

    def list_datasets(self, offset, limit):
        with self.connect() as db:
            rows = db.execute(
                "SELECT id FROM datasets WHERE pins>0 OR expires>? ORDER BY created DESC,id",
                (time.time(),),
            ).fetchall()
        keys = (
            "dataset_id",
            "original_filename",
            "file_size_bytes",
            "row_count",
            "column_count",
            "created_at",
            "expires_at",
            "retention_pinned",
            "run_count",
        )
        items = []
        for row in rows[offset : offset + limit]:
            try:
                data = self.dataset(row["id"], touch=False)
                items.append({k: data[k] for k in keys})
            except AppError:
                continue
        return {"items": items, "total": len(rows), "offset": offset, "limit": limit}

    def pin(self, dataset_id, change):
        with self.lock, self.connect() as db:
            db.execute(
                "UPDATE datasets SET pins=max(0,pins+?),expires=? WHERE id=?",
                (
                    change,
                    time.time() + self.settings.limits["dataset_idle_ttl_seconds"],
                    dataset_id,
                ),
            )

    def publish_run(self, run_id, dataset_id, config, scope, key, receipt):
        from .settings import ALGORITHM_VERSION

        with self.lock, self.connect() as db:
            dataset = db.execute(
                "SELECT expires,pins FROM datasets WHERE id=?", (dataset_id,)
            ).fetchone()
            if not dataset or (not dataset["pins"] and dataset["expires"] <= time.time()):
                raise AppError("DATASET_NOT_FOUND", "The dataset was deleted or expired", 404)
            count = db.execute(
                "SELECT count(*) FROM runs WHERE dataset_id=?", (dataset_id,)
            ).fetchone()[0]
            if count >= self.settings.limits["max_runs_per_dataset"]:
                raise AppError("RUN_LIMIT_REACHED", "The run limit has been reached", 409)
            db.execute(
                "INSERT INTO runs(id,dataset_id,configuration,status,stage,created,algorithm_version) VALUES(?,?,?,'queued','queued',?,?)",
                (run_id, dataset_id, dumps(config), time.time(), ALGORITHM_VERSION),
            )
            db.execute("UPDATE datasets SET pins=pins+1 WHERE id=?", (dataset_id,))
            db.execute(
                "UPDATE requests SET state='done',resource_type='run',resource_id=?,http_status=202,response=?,location=?,expires=NULL WHERE scope=? AND key=?",
                (run_id, dumps(receipt), receipt["status_url"], scope, key),
            )

    def update_run(self, run_id, **fields):
        allowed = {"status", "stage", "started", "finished", "duration", "summary", "error"}
        if not fields.keys() <= allowed:
            raise ValueError("Invalid run fields")
        fields = {
            k: dumps(v) if k in {"summary", "error"} and v is not None else v
            for k, v in fields.items()
        }
        with self.connect() as db:
            db.execute(
                "UPDATE runs SET " + ",".join(f"{k}=?" for k in fields) + " WHERE id=?",
                (*fields.values(), run_id),
            )

    def run(self, run_id, touch=True):
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            raise AppError("RUN_NOT_FOUND", "Validation run not found or expired", 404)
        try:
            dataset = self.dataset(row["dataset_id"], touch=touch)
        except AppError:
            raise AppError("RUN_NOT_FOUND", "Validation run not found or expired", 404) from None
        return {
            "run_id": row["id"],
            "dataset_id": row["dataset_id"],
            "status": row["status"],
            "stage": row["stage"],
            "created_at": iso(row["created"]),
            "started_at": iso(row["started"]) if row["started"] else None,
            "finished_at": iso(row["finished"]) if row["finished"] else None,
            "duration_ms": row["duration"],
            "expires_at": dataset["expires_at"],
            "retention_pinned": dataset["retention_pinned"],
            "configuration_snapshot": json.loads(row["configuration"]),
            "algorithm_version": row["algorithm_version"],
            "summary": json.loads(row["summary"]) if row["summary"] else None,
            "error": json.loads(row["error"]) if row["error"] else None,
        }

    def _tombstone(self, db, resource_type, resource_id):
        db.execute(
            "UPDATE requests SET state='gone',expires=? WHERE resource_type=? AND resource_id=?",
            (
                time.time()
                + self.settings.limits["idempotency_retention_after_completion_seconds"],
                resource_type,
                resource_id,
            ),
        )

    def remove_tree(self, path):
        path = Path(path).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise ValueError("Unsafe deletion target")
        if path.exists():
            shutil.rmtree(path)

    def delete_run(self, run_id):
        with self.lock, self.connect() as db:
            run = self.run(run_id, touch=False)
            pins = db.execute("SELECT export_pins FROM runs WHERE id=?", (run_id,)).fetchone()[0]
            if run["status"] in {"queued", "running"} or pins:
                raise AppError(
                    "RUN_BUSY", "The validation run is in use by the worker or an export", 409
                )
            db.execute("DELETE FROM runs WHERE id=?", (run_id,))
            self._tombstone(db, "run", run_id)
            db.execute(
                "INSERT OR IGNORE INTO pending_deletes VALUES(?)",
                (str(self.root / "runs" / run_id),),
            )
        self.flush_deletes()

    def pin_export(self, run_id, change):
        with self.lock, self.connect() as db:
            run = db.execute("SELECT dataset_id FROM runs WHERE id=?", (run_id,)).fetchone()
            if run:
                db.execute(
                    "UPDATE runs SET export_pins=max(0,export_pins+?) WHERE id=?", (change, run_id)
                )
                db.execute(
                    "UPDATE datasets SET pins=max(0,pins+?),expires=? WHERE id=?",
                    (
                        change,
                        time.time() + self.settings.limits["dataset_idle_ttl_seconds"],
                        run["dataset_id"],
                    ),
                )

    def delete_dataset(self, dataset_id, expired=False):
        with self.lock, self.connect() as db:
            row = db.execute("SELECT * FROM datasets WHERE id=?", (dataset_id,)).fetchone()
            if not row:
                raise AppError("DATASET_NOT_FOUND", "Dataset not found", 404)
            if expired and (row["pins"] or row["expires"] > time.time()):
                # A GET may have extended retention since cleanup selected IDs.
                return
            if row["pins"]:
                raise AppError(
                    "DATASET_BUSY", "The dataset is in use by a validation run or an export", 409
                )
            runs = [
                r["id"] for r in db.execute("SELECT id FROM runs WHERE dataset_id=?", (dataset_id,))
            ]
            for run_id in runs:
                self._tombstone(db, "run", run_id)
            self._tombstone(db, "dataset", dataset_id)
            db.execute("DELETE FROM runs WHERE dataset_id=?", (dataset_id,))
            db.execute("DELETE FROM datasets WHERE id=?", (dataset_id,))
            for run_id in runs:
                db.execute(
                    "INSERT OR IGNORE INTO pending_deletes VALUES(?)",
                    (str(self.root / "runs" / run_id),),
                )
            db.execute(
                "INSERT OR IGNORE INTO pending_deletes VALUES(?)",
                (str(self.root / "datasets" / dataset_id),),
            )
        self.flush_deletes()

    def flush_deletes(self):
        with self.connect() as db:
            paths = [row[0] for row in db.execute("SELECT path FROM pending_deletes")]
        for path in paths:
            try:
                self.remove_tree(path)
            except OSError:
                continue
            with self.connect() as db:
                db.execute("DELETE FROM pending_deletes WHERE path=?", (path,))

    def recover(self):
        now = time.time()
        with self.lock, self.connect() as db:
            active = db.execute(
                "SELECT id,dataset_id,started FROM runs WHERE status IN ('queued','running')"
            ).fetchall()
            for row in active:
                error = {
                    "code": "PROCESS_RESTARTED",
                    "message": "The server was restarted. Create a new validation run.",
                    "details": {"includes_downtime": True},
                }
                duration = int((now - row["started"]) * 1000) if row["started"] else None
                db.execute(
                    "UPDATE runs SET status='failed',stage='failed',finished=?,duration=?,summary=NULL,error=? WHERE id=?",
                    (now, duration, dumps(error), row["id"]),
                )
                self.remove_tree(self.root / "runs" / row["id"])
            db.execute(
                "UPDATE datasets SET expires=?,pins=0 WHERE pins>0",
                (now + self.settings.limits["dataset_idle_ttl_seconds"],),
            )
            db.execute("UPDATE runs SET export_pins=0 WHERE export_pins>0")
            error = {
                "error": {
                    "code": "IDEMPOTENCY_OPERATION_INTERRUPTED",
                    "message": "The import was interrupted by a restart. Use a new key for a new upload.",
                    "details": [],
                    "request_id": "recovery",
                }
            }
            db.execute(
                "UPDATE requests SET state='failed',http_status=409,response=?,expires=? WHERE state='processing'",
                (
                    dumps(error),
                    now + self.settings.limits["idempotency_retention_after_completion_seconds"],
                ),
            )
        for path in (self.root / "staging").iterdir():
            if path.is_dir():
                self.remove_tree(path)
            else:
                path.unlink(missing_ok=True)
        self.cleanup()
        with self.connect() as db:
            dataset_ids = {row[0] for row in db.execute("SELECT id FROM datasets")}
            run_ids = {row[0] for row in db.execute("SELECT id FROM runs WHERE status='succeeded'")}
        for folder, valid in (("datasets", dataset_ids), ("runs", run_ids)):
            for path in (self.root / folder).iterdir():
                if path.is_dir() and path.name not in valid:
                    self.remove_tree(path)

    def cleanup(self):
        self.flush_deletes()
        with self.connect() as db:
            expired = [
                r[0]
                for r in db.execute(
                    "SELECT id FROM datasets WHERE pins=0 AND expires<=?", (time.time(),)
                )
            ]
            db.execute(
                "DELETE FROM requests WHERE expires IS NOT NULL AND expires<=?", (time.time(),)
            )
        for dataset_id in expired:
            try:
                self.delete_dataset(dataset_id, expired=True)
            except (OSError, AppError):
                continue

    def record(self, dataset_id, row_index):
        path = self.root / "datasets" / dataset_id / "records.sqlite"
        with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as db:
            row = db.execute(
                "SELECT values_json FROM records WHERE row_index=?", (row_index,)
            ).fetchone()
        if not row:
            raise AppError("QUERY_INVALID", "The record number is outside the dataset", 422)
        return {"row_index": row_index, "values": json.loads(row[0])}

    def records(self, dataset_id, offset, limit):
        path = self.root / "datasets" / dataset_id / "records.sqlite"
        with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as db:
            rows = db.execute(
                "SELECT row_index,values_json FROM records WHERE row_index>? ORDER BY row_index LIMIT ?",
                (offset, limit),
            ).fetchall()
        return [{"row_index": row[0], "values": json.loads(row[1])} for row in rows]
