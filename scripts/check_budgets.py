"""Exercise the real 100000/100001 issue boundary and 4.1M-potential stress case."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from api_client import DatasetCheckClient

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--fixtures", type=Path, default=ROOT / "examples/generated")
    args = parser.parse_args()
    with DatasetCheckClient(args.url) as client:
        limit = client.request("GET", "capabilities").json()["limits"][
            "max_issues_per_run"
        ]
        if limit != 100000:
            raise RuntimeError(
                "This acceptance check requires the real default max_issues=100000"
            )
        for name, succeeds in [
            ("boundary-100000", True),
            ("boundary-100001", False),
            ("stress", False),
            ("boundary-100000", True),  # proves processor is available after stress
        ]:
            dataset_id = None
            try:
                rules = json.loads(
                    (args.fixtures / f"{name}.rules.json").read_text(encoding="utf-8")
                )
                receipt, _ = client.upload(args.fixtures / f"{name}.csv")
                dataset_id = receipt["dataset_id"]
                run_id = client.start(dataset_id, rules)["run_id"]
                run = client.wait(run_id)
                if succeeds:
                    assert run["status"] == "succeeded", run
                    assert run["summary"]["total_issues"] == 100000, run["summary"]
                else:
                    assert run["status"] == "failed", run
                    assert run["error"]["code"] == "RESULT_LIMIT_EXCEEDED", run
                    assert run["summary"] is None
                    for endpoint in ["issues", "exports/report-json"]:
                        response = client.http.get(f"runs/{run_id}/{endpoint}")
                        assert response.status_code == 409, response.text
                print(f"PASS {name}: {run['status']}", flush=True)
            finally:
                if dataset_id:
                    client.delete_dataset(dataset_id)


if __name__ == "__main__":
    main()
