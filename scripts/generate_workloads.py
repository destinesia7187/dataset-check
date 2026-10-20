"""Create deterministic local performance and budget fixtures (stdlib only)."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def column(
    index: int, kind: str, *, unique: bool = False, bounds: bool = False
) -> dict:
    return {
        "column_id": f"c{index}",
        "required": True,
        "unique": unique,
        "expected_type": kind,
        "range": {"min": "0", "max": "1000"} if bounds else None,
    }


def configuration(columns: list[dict], *, duplicates: bool = True) -> dict:
    return {
        "schema_version": "1.0",
        "decimal_separator": ".",
        "check_duplicate_rows": duplicates,
        "columns": columns,
    }


def performance(output: Path, rows: int, seed: int) -> dict:
    rng = random.Random(seed)
    previous: list[str] = []
    with output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["id"] + [f"field_{i}" for i in range(2, 21)])
        for index in range(1, rows + 1):
            row = (
                [f"R{index:06d}"]
                + [str(rng.randrange(1001)) for _ in range(5)]
                + [f"{rng.randrange(1000)}.{rng.randrange(100):02d}" for _ in range(4)]
                + [f"2024-{rng.randrange(1, 13):02d}-{rng.randrange(1, 29):02d}"]
                + [f"v{rng.randrange(10000):04d}" for _ in range(9)]
            )
            remainder = index % 10000
            if remainder == 0:
                row[11] = ""
            elif remainder == 1:
                row[1] = "abc"
            elif remainder == 2:
                row[2] = "-1"
            elif remainder == 3:
                row[10] = "2023-02-29"
            elif remainder == 4 and previous:
                row[0] = previous[0]
            elif remainder == 5 and previous:
                row = previous.copy()
            writer.writerow(row)
            previous = row
    return configuration(
        [column(1, "text", unique=True)]
        + [column(i, "integer", bounds=True) for i in range(2, 7)]
        + [column(i, "decimal") for i in range(7, 11)]
        + [column(11, "date")]
        + [column(i, "text") for i in range(12, 21)]
    )


def stress(output: Path, rows: int) -> dict:
    with output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow([f"field_{i}" for i in range(1, 21)])
        writer.writerows(["x"] * 20 for _ in range(rows))
    return configuration([column(i, "integer", unique=True) for i in range(1, 21)])


def boundary(output: Path, rows: int, extra_issue: bool) -> dict:
    with output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["key", "value"])
        for index in range(rows):
            writer.writerow(["same", "bad" if extra_issue and index == 0 else "1"])
    return configuration(
        [column(1, "text", unique=True), column(2, "integer")], duplicates=False
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "examples" / "generated")
    parser.add_argument("--rows", type=int, default=100000)
    parser.add_argument("--seed", type=int, default=20261019)
    parser.add_argument(
        "--kind", choices=["all", "performance", "stress", "boundary"], default="all"
    )
    args = parser.parse_args()
    if not 2 <= args.rows <= 100000:
        parser.error("--rows must be between 2 and 100000")
    args.output.mkdir(parents=True, exist_ok=True)
    kinds = ["performance", "stress", "boundary"] if args.kind == "all" else [args.kind]
    created = []
    for kind in kinds:
        names = ["boundary-100000", "boundary-100001"] if kind == "boundary" else [kind]
        for name in names:
            path = args.output / f"{name}.csv"
            if kind == "performance":
                rules = performance(path, args.rows, args.seed)
            elif kind == "stress":
                rules = stress(path, args.rows)
            else:
                rules = boundary(path, args.rows, name.endswith("100001"))
            write_json(path.with_suffix(".rules.json"), rules)
            created.append(
                {
                    "file": path.name,
                    "rules": path.with_suffix(".rules.json").name,
                    "rows": args.rows,
                    "file_size_bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
    manifest = {"generator_version": "1.0", "seed": args.seed, "files": created}
    write_json(args.output / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
