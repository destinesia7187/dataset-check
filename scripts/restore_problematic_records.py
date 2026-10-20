"""Restore original raw fields from the lossless JSON report, without a server.

The output is raw JSON, not CSV: no spreadsheet formula escaping is applied.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path, default=Path("restored-records.json"))
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    columns = report["columns"]
    records = [
        {"row_index": record["row_index"], "values": record["values"]}
        for record in report["problematic_records"]
    ]
    assert all(len(record["values"]) == len(columns) for record in records)
    args.output.write_text(
        json.dumps(
            {"columns": columns, "records": records}, ensure_ascii=False, indent=2
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Restored {len(records)} records to {args.output}")


if __name__ == "__main__":
    main()
