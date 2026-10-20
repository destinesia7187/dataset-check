# Checking a real open dataset: Iris

This example uses a fixed snapshot of **Iris** by R. A. Fisher, published by the UCI Machine Learning Repository. Source: [dataset page](https://archive.ics.uci.edu/dataset/53/iris), [original file](https://archive.ics.uci.edu/ml/machine-learning-databases/iris/iris.data). Retrieved on **October 19, 2026**. UCI specifies the [CC BY 4.0 license](https://creativecommons.org/licenses/by/4.0/), which permits redistribution and adaptation with attribution.

Attribution: Fisher, R. (1936). Iris [Dataset]. UCI Machine Learning Repository. [DOI: 10.24432/C56C76](https://doi.org/10.24432/C56C76).

`iris.data` contains the exact downloaded bytes. `iris.csv` adds a header, removes the final blank line, and normalizes line endings to LF. All 150 records retain their original values. No artificial errors were added. SHA-256 hashes and adaptation details are recorded in `source.json`; future source versions may differ.

Fields are sepal length and width, petal length and width (cm), and plant species. `rules.json` checks that all fields are required, the four measurements are decimals within the inclusive range `[0; 20]` cm, and records are not exact duplicates. The 20 cm boundary demonstrates a plausible range rather than providing biological proof of correctness. Individual measurements and species are not required to be unique.

From the repository root, while the application is running:

```powershell
python scripts/check_example.py --csv examples/open-data/iris.csv --rules examples/open-data/rules.json --expected examples/open-data/expected_summary.json --output benchmark-results/iris
```

The fixed file produces **five exact duplicate issues in five records**, in two groups `[10, 35, 38]` and `[102, 143]`, representing three extra repetitions. There are no missing values, type errors, or violations of the selected range. This is the expected result for this file and configuration, not a claim that five observations are wrong: different plants can share the same rounded measurements.

The UCI page separately documents historical differences between records 35 and 38 and Fisher's publication. These checks do not establish those differences themselves; they only find matching original values. Source data is never corrected automatically.
