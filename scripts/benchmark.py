"""Measure a running local API: one warmup, then three measured iterations.

Only this invocation's datasets are deleted. Existing user datasets are untouched.
Server-Timing import;dur is used when the server exposes isolated import time.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from api_client import DatasetCheckClient

ROOT = Path(__file__).resolve().parents[1]


def total_ram_bytes() -> int | None:
    if os.name == "nt":
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong),
                ("load", ctypes.c_ulong),
                ("total_physical", ctypes.c_ulonglong),
                ("available_physical", ctypes.c_ulonglong),
                ("total_page", ctypes.c_ulonglong),
                ("available_page", ctypes.c_ulonglong),
                ("total_virtual", ctypes.c_ulonglong),
                ("available_virtual", ctypes.c_ulonglong),
                ("available_extended", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        return (
            status.total_physical
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            else None
        )
    try:
        return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    except (AttributeError, OSError, ValueError):
        return None


def environment() -> dict:
    packages = {}
    for name in ["fastapi", "pydantic", "uvicorn", "python-multipart", "httpx"]:
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {
        "os": platform.platform(),
        "processor": platform.processor(),
        "logical_cpu_count": os.cpu_count(),
        "total_ram_bytes": total_ram_bytes(),
        "python": platform.python_version(),
        "client_environment_dependencies": packages,
    }


def median(measurements: list[dict], key: str) -> float | None:
    values = [item[key] for item in measurements]
    if any(value is None for value in values):
        return None
    return statistics.median(values)


def fixture_label(path: Path) -> str:
    """Use a reproducible repository path instead of publishing a home directory."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--csv", type=Path, default=ROOT / "examples/generated/performance.csv"
    )
    parser.add_argument(
        "--rules", type=Path, default=ROOT / "examples/generated/performance.rules.json"
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "benchmark-results/performance.json"
    )
    parser.add_argument(
        "--disk", default="Not recorded; record SSD/HDD and model when publishing"
    )
    args = parser.parse_args()
    rules = json.loads(args.rules.read_text(encoding="utf-8"))
    measurements = []
    with DatasetCheckClient(args.url) as client:
        capabilities = client.request("GET", "capabilities").json()
        for iteration in range(4):
            dataset_id = None
            try:
                receipt, upload_import = client.upload(args.csv)
                import_only = client.last_import_seconds
                dataset_id = receipt["dataset_id"]
                started = time.perf_counter()
                run_id = client.start(dataset_id, rules)["run_id"]
                run = client.wait(run_id)
                observed_run = time.perf_counter() - started
                if run["status"] != "succeeded":
                    raise RuntimeError(f"Run failed: {run['error']}")
                started = time.perf_counter()
                issues = client.request("GET", f"runs/{run_id}/issues?limit=100").json()
                page_seconds = time.perf_counter() - started
                started = time.perf_counter()
                export = client.request("GET", f"runs/{run_id}/exports/report-json")
                export_seconds = time.perf_counter() - started
                assert len(issues["items"]) <= 100
                assert issues["total"] == run["summary"]["total_issues"]
                item = {
                    "iteration": iteration,
                    "warmup": iteration == 0,
                    "upload_and_import_seconds": upload_import,
                    "server_import_seconds": import_only,
                    "server_run_seconds": run["duration_ms"] / 1000,
                    "observed_run_seconds_including_polling": observed_run,
                    "issues_page_seconds": page_seconds,
                    "json_download_seconds": export_seconds,
                    "json_size_bytes": len(export.content),
                    "summary": run["summary"],
                }
                measurements.append(item)
                print(
                    json.dumps(
                        {key: value for key, value in item.items() if key != "summary"}
                        | {"total_issues": run["summary"]["total_issues"]},
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            finally:
                if dataset_id:
                    client.delete_dataset(dataset_id)
    samples = measurements[1:]
    medians = {
        name: median(samples, name)
        for name in [
            "upload_and_import_seconds",
            "server_import_seconds",
            "server_run_seconds",
            "issues_page_seconds",
            "json_download_seconds",
        ]
    }
    result = {
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "machine": {**environment(), "disk": args.disk},
        "fixture": {
            "file": fixture_label(args.csv),
            "bytes": args.csv.stat().st_size,
            "rules": fixture_label(args.rules),
        },
        "capabilities": capabilities,
        "methodology": "One warmup excluded; median of next three iterations; local HTTP API",
        "import_timing_note": (
            "Server-Timing excludes body reception; upload_and_import includes transfer. "
            "If server_import_seconds is null, isolated import target is not verified."
        ),
        "measurements": measurements,
        "medians": medians,
        "targets_met": {
            "import_20_seconds": (
                medians["server_import_seconds"] <= 20
                if medians["server_import_seconds"] is not None
                else None
            ),
            "analysis_30_seconds": medians["server_run_seconds"] <= 30,
            "issues_page_1_second": medians["issues_page_seconds"] <= 1,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Saved factual measurements: {args.output}")


if __name__ == "__main__":
    main()
