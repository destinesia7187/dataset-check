from __future__ import annotations

import multiprocessing
import os
import threading
import time
import uuid

from .common import AppError, dumps, iso
from .processes import InstanceLock, process_identity, stop_orphan
from .store import Store
from .worker import worker_entry


class Manager:
    def __init__(self, settings):
        self.settings = settings
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.lease = InstanceLock(settings.data_dir / "coordinator.lock")
        try:
            stop_orphan(settings.data_dir)
            self.store = Store(settings)
            self.store.recover()
        except BaseException:
            self.lease.close()
            raise
        self.gate = threading.Lock()
        self.stop_event = threading.Event()
        self.process = None
        self.thread = None
        self.cleaner = threading.Thread(target=self._clean, daemon=True, name="dataset-cleanup")
        self.cleaner.start()

    def _clean(self):
        while not self.stop_event.wait(self.settings.limits["cleanup_interval_seconds"]):
            try:
                self.store.cleanup()
            except (OSError, Exception):
                # No cell contents or exception representation are logged.
                continue

    def acquire(self):
        if self.stop_event.is_set() or not self.gate.acquire(blocking=False):
            raise AppError(
                "PROCESSOR_BUSY",
                "The worker is busy. Wait for the current operation to finish.",
                429,
            )

    def release(self):
        self.gate.release()

    def execute(self, payload, timeout, run_id=None):
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        payload |= {"root": str(self.settings.data_dir), "limits": self.settings.limits}
        process = context.Process(
            target=worker_entry, args=(payload, sender, os.getpid()), name="dataset-check-worker"
        )
        started = time.monotonic()
        active_path = self.settings.data_dir / "active_worker.json"
        has_started = False
        result = None
        try:
            process.start()
            has_started = True
            sender.close()
            self.process = process
            identity = process_identity(process.pid)
            active_path.write_text(
                dumps(
                    {"pid": process.pid, "identity": identity, "operation_id": str(uuid.uuid4())}
                ),
                encoding="utf-8",
            )
            while time.monotonic() - started < timeout:
                if receiver.poll(0.04):
                    try:
                        message = receiver.recv()
                    except EOFError:
                        break
                    if "stage" in message:
                        if run_id:
                            self.store.update_run(run_id, stage=message["stage"])
                    else:
                        result = message
                        break
                self.store.check_space()
                if not process.is_alive():
                    if receiver.poll(0.1):
                        continue
                    break
            if result is None:
                if self.stop_event.is_set():
                    raise AppError(
                        "PROCESS_RESTARTED",
                        "Processing was interrupted when the server stopped",
                        500,
                    )
                if time.monotonic() - started >= timeout:
                    raise AppError(
                        "OPERATION_TIMEOUT",
                        "The processing time limit was exceeded. Use a smaller dataset.",
                        504,
                    )
                raise AppError(
                    "WORKER_CRASHED",
                    "The worker stopped unexpectedly. Start a new validation run.",
                    500,
                )
            if not result["ok"]:
                status = {
                    "FILE_TOO_LARGE": 413,
                    "CELL_TOO_LONG": 413,
                    "DATASET_LIMIT_EXCEEDED": 413,
                    "REQUEST_INVALID": 422,
                    "STORAGE_QUOTA_EXCEEDED": 507,
                    "TEMP_STORAGE_UNAVAILABLE": 507,
                    "EMPTY_DATASET": 409,
                }.get(result["code"], 500 if result["code"] == "INTERNAL_ERROR" else 400)
                raise AppError(result["code"], result["message"], status, result.get("details", {}))
            return result["result"]
        except OSError as exc:
            raise AppError(
                "TEMP_STORAGE_UNAVAILABLE", "Could not prepare the working storage", 507
            ) from exc
        finally:
            receiver.close()
            sender.close()
            if has_started:
                if process.is_alive():
                    process.terminate()
                process.join(timeout=self.settings.limits["cleanup_grace_seconds"])
                if process.is_alive():
                    process.kill()
                    process.join(timeout=1)
            self.process = None
            process.close()
            active_path.unlink(missing_ok=True)

    def start_run(self, run_id, dataset, configuration):
        root = self.settings.data_dir
        folder = root / "staging" / run_id
        folder.mkdir()
        run = self.store.run(run_id)

        def task():
            started = time.time()
            monotonic = time.monotonic()
            try:
                self.store.update_run(run_id, status="running", stage="preparing", started=started)
                result = self.execute(
                    {
                        "kind": "run",
                        "folder": str(folder),
                        "dataset_folder": str(root / "datasets" / dataset["dataset_id"]),
                        "dataset": dataset,
                        "configuration": configuration,
                        "started_monotonic": monotonic,
                        "run_info": {
                            "run_id": run_id,
                            "dataset_id": dataset["dataset_id"],
                            "created_at": run["created_at"],
                            "started_at": iso(started),
                        },
                    },
                    self.settings.limits["run_timeout_seconds"],
                    run_id=run_id,
                )
                self.store.check_space()
                folder.rename(root / "runs" / run_id)
                self.store.update_run(
                    run_id,
                    status="succeeded",
                    stage="completed",
                    finished=result["finished"],
                    duration=result["duration"],
                    summary=result["summary"],
                )
            except AppError as exc:
                details = (
                    exc.details if isinstance(exc.details, dict) else {"validation": exc.details}
                )
                self.store.update_run(
                    run_id,
                    status="failed",
                    stage="failed",
                    finished=time.time(),
                    duration=int((time.monotonic() - monotonic) * 1000),
                    error={"code": exc.code, "message": exc.message, "details": details},
                )
            except Exception:
                self.store.update_run(
                    run_id,
                    status="failed",
                    stage="failed",
                    finished=time.time(),
                    duration=int((time.monotonic() - monotonic) * 1000),
                    error={
                        "code": "INTERNAL_ERROR",
                        "message": "Could not save the validation result",
                        "details": {},
                    },
                )
            finally:
                try:
                    self.store.remove_tree(folder)
                finally:
                    try:
                        self.store.pin(dataset["dataset_id"], -1)
                    finally:
                        self.release()

        self.thread = threading.Thread(target=task, daemon=True, name="run-coordinator")
        self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.process and self.process.is_alive():
            self.process.terminate()
        if self.thread:
            self.thread.join(timeout=self.settings.limits["cleanup_grace_seconds"] + 2)
        self.cleaner.join(timeout=1)
        self.lease.close()
