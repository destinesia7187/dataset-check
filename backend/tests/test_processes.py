"""Exercise actual spawn, hard deadlines, ownership and parent-death cleanup."""

import json
import multiprocessing
import os
import signal
import time
from pathlib import Path

import pytest

from app.common import AppError
from app.manager import Manager
from app.processes import InstanceLock, guard_parent, process_identity, stop_orphan
from app.settings import Settings


def _guarded_child(parent_pid, marker):
    guard_parent(parent_pid)
    Path(marker).write_text(
        json.dumps({"pid": os.getpid(), "identity": process_identity(os.getpid())}),
        encoding="utf-8",
    )
    while True:
        time.sleep(0.1)


def _parent_with_worker(marker):
    worker = multiprocessing.get_context("spawn").Process(
        target=_guarded_child, args=(os.getpid(), marker)
    )
    worker.start()
    worker.join()


def test_deadline_terminates_real_worker_and_next_operation_succeeds(tmp_path):
    settings = Settings(data_dir=tmp_path)
    service = Manager(settings)
    try:
        started = time.monotonic()
        with pytest.raises(AppError) as result:
            service.execute({"kind": "import", "test_delay": 10}, timeout=1)
        assert result.value.code == "OPERATION_TIMEOUT"
        assert time.monotonic() - started < 1 + settings.limits["cleanup_grace_seconds"]
        assert service.process is None
        assert not (tmp_path / "active_worker.json").exists()
        folder = tmp_path / "staging" / "next"
        folder.mkdir()
        source = folder / "original.csv"
        source.write_bytes(b"id,name\n1,example\n")
        result = service.execute(
            {
                "kind": "import",
                "folder": str(folder),
                "input": str(source),
                "filename": "next.csv",
                "sha256": "0" * 64,
                "encoding": "utf-8",
                "delimiter": "comma",
            },
            timeout=20,
        )
        assert result["metadata"]["row_count"] == 1
    finally:
        service.close()


def test_catalogue_exclusive_instance_lock(tmp_path):
    first = InstanceLock(tmp_path / "instance.lock")
    try:
        with pytest.raises((RuntimeError, OSError)):
            InstanceLock(tmp_path / "instance.lock")
    finally:
        first.close()
    second = InstanceLock(tmp_path / "instance.lock")
    second.close()


def test_worker_stops_after_its_parent_is_terminated(tmp_path):
    marker = tmp_path / "worker.json"
    parent = multiprocessing.get_context("spawn").Process(
        target=_parent_with_worker, args=(str(marker),)
    )
    parent.start()
    identity = None
    try:
        deadline = time.monotonic() + 15
        while not marker.exists() and time.monotonic() < deadline:
            assert parent.is_alive(), "Parent failed before worker start"
            time.sleep(0.02)
        assert marker.exists(), "Spawned worker failed to initialize"
        entry = json.loads(marker.read_text("utf-8"))
        child_pid, identity = entry["pid"], entry["identity"]
        assert identity is not None
        parent.terminate()
        parent.join(timeout=5)
        deadline = time.monotonic() + 5
        while process_identity(child_pid) == identity and time.monotonic() < deadline:
            time.sleep(0.02)
        assert process_identity(child_pid) != identity, "Orphan worker is still running"
    finally:
        if parent.is_alive():
            parent.terminate()
            parent.join(timeout=5)
        if identity and process_identity(child_pid) == identity:
            os.kill(child_pid, signal.SIGTERM)
        parent.close()


def test_recovery_does_not_kill_process_with_different_identity(tmp_path):
    path = tmp_path / "active_worker.json"
    path.write_text(
        json.dumps({"pid": os.getpid(), "identity": "obsolete-other-process"}), encoding="utf-8"
    )
    stop_orphan(tmp_path)
    assert not path.exists()
    assert process_identity(os.getpid()) is not None


def test_failed_worker_identity_file_write_stops_started_process(tmp_path, monkeypatch):
    service = Manager(Settings(data_dir=tmp_path))
    original_write = Path.write_text

    def unavailable_metadata(path, *args, **kwargs):
        if path.name == "active_worker.json":
            raise OSError("Injected metadata write failure")
        return original_write(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", unavailable_metadata)
    try:
        with pytest.raises(AppError) as failure:
            service.execute({"kind": "import", "test_delay": 10}, timeout=20)
        assert failure.value.code == "TEMP_STORAGE_UNAVAILABLE"
        assert failure.value.status == 507
        assert service.process is None, "Started process leaked after worker identity write failure"
    finally:
        # If the regression is present, this test must still clean its child.
        if service.process is not None:
            process = service.process
            if process.is_alive():
                process.terminate()
            process.join(timeout=5)
            process.close()
            service.process = None
        service.close()
