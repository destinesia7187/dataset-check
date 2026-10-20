# Acceptance example

`acceptance.csv` matches section 17 of the technical specification v1.1 exactly. Import settings: UTF-8, comma separator, and decimal point. `rules.json` defines the rules; `expected_summary.json` contains the complete summary defined by the API contract. `report.example.json` is an actual application report for this file, including every original field of the eight problematic records. Its UUIDs and timestamps belong to a demonstration run, not resources on the current server.

Expect **13 issues in 8 of 9 records**: three missing required values, three type errors, one out-of-range value, four uniqueness violations, and two exact duplicate records. Each column has one missing value. The two spaces in record 8's `population` field are preserved in the source file.

From the repository root, while the server is running:

```powershell
python scripts/check_example.py
```

The script compares the entire summary, downloads all three exports to `benchmark-results/acceptance`, and deletes only its own dataset. Add `--keep` to retain it in the interface. The downloaded JSON remains usable for restoration after deletion:

```powershell
python scripts/restore_problematic_records.py benchmark-results/acceptance/report-json.json --output benchmark-results/restored.json
```

The output includes every original field string from the problematic records; CSV safety transformations are not applied to it.
