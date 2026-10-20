"""Validate a CSV through the running API, export results and compare a fixture."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from api_client import DatasetCheckClient

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--csv", type=Path, default=ROOT / "examples/synthetic/acceptance.csv"
    )
    parser.add_argument(
        "--rules", type=Path, default=ROOT / "examples/synthetic/rules.json"
    )
    parser.add_argument(
        "--expected",
        type=Path,
        default=ROOT / "examples/synthetic/expected_summary.json",
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "benchmark-results/acceptance"
    )
    parser.add_argument(
        "--keep", action="store_true", help="Keep own dataset for browser inspection"
    )
    args = parser.parse_args()
    rules = json.loads(args.rules.read_text(encoding="utf-8"))
    expected = json.loads(args.expected.read_text(encoding="utf-8"))
    args.output.mkdir(parents=True, exist_ok=True)
    dataset_id = None
    with DatasetCheckClient(args.url) as client:
        try:
            receipt, elapsed = client.upload(args.csv)
            dataset_id = receipt["dataset_id"]
            run_id = client.start(dataset_id, rules)["run_id"]
            run = client.wait(run_id)
            if run["status"] != "succeeded":
                raise AssertionError(f"Run failed: {run['error']}")
            if run["summary"] != expected:
                raise AssertionError(
                    "Summary mismatch:\n"
                    + json.dumps(run["summary"], ensure_ascii=False, indent=2)
                )
            for name, extension in [
                ("report-json", "json"),
                ("violations-csv", "csv"),
                ("problematic-records-csv", "csv"),
            ]:
                response = client.request("GET", f"runs/{run_id}/exports/{name}")
                (args.output / f"{name}.{extension}").write_bytes(response.content)
            report = json.loads(
                (args.output / "report-json.json").read_text(encoding="utf-8")
            )
            records = report["problematic_records"]
            assert len(records) == expected["problematic_records"]
            assert (
                sum(record["violation_count"] for record in records)
                == expected["total_issues"]
            )
            print(
                json.dumps(
                    {
                        "dataset_id": dataset_id,
                        "run_id": run_id,
                        "summary_matches": True,
                        "upload_and_import_seconds": round(elapsed, 3),
                        "output": str(args.output),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        finally:
            if dataset_id and not args.keep:
                client.delete_dataset(dataset_id)


if __name__ == "__main__":
    main()
