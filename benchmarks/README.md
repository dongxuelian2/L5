# Tennessee Eastman: reference-data ingestion (stage 1)

This is the **first incremental step**, not an evaluated TEP fault detector.
The loader is deliberately isolated from L5's existing synthetic simulation.

## Reference data

Original Russell / Chiang / Braatz reference files, mirrored at:

https://github.com/jkitchin/tennessee-eastman-profbraatz/tree/master/data

Each observation contains **41 XMEAS variables + 11 XMV variables**. The
reference interval is **180 seconds** (3 minutes). Canonical filenames:
`d00.dat` (normal training), `d01.dat` to `d21.dat` (fault training),
and `d00_te.dat` to `d21_te.dat` (test records).

> **Verified source-layout caveat:** In the above mirror, `d00.dat` is
> physically stored as **52 lines × 500 values**, while `d01.dat` is
> **480 lines × 52 values** and `d01_te.dat` is **960 lines × 52 values**.
> The importer detects both orientations, rather than trusting reported
> dimensions in every readme.

Download original files yourself; no third-party benchmark files are checked
into L5, and no downloads occur during tests.

## Usage

From the repository root:

```bash
# Download reference files from the link above to /path/to/tep-data/
python3 -m benchmarks.tep /path/to/tep-data/d00.dat
python3 -m benchmarks.tep /path/to/tep-data/d01_te.dat --csv /tmp/tep01.csv

# In-memory consumption by future evaluation code:
python3 - <<'PY'
from benchmarks.tep import read_tep_dat, VARIABLES, SAMPLE_SECONDS
d = read_tep_dat("/path/to/tep-data/d01_te.dat")
print(d.summary())
print(d.rows[0][0], VARIABLES[0], SAMPLE_SECONDS)
PY

# Run importer tests (all synthetic test fixtures)
python3 -m unittest discover -s benchmarks -p 'test_*.py' -v
```

The exported CSV header is `t,xmeas_1,...,xmeas_41,xmv_1,...,xmv_11`.
The timestamp for sample `i` is `180*i` seconds, relative to the start
of that file. No fault-onset time is inferred from the filename. `fault_id`
and train/test split appear **only in metadata**, never as model input features.

## Critical non-equivalences

- TEP's **52 channels and physical units** are not L5's existing **18
  simulated signals**. This stage makes **no guessed mapping** and does
  **not** call `simulation.platform.diagnose` on these records.
- The original 240-second L5 intervention horizon does not fit TEP's
  180-second sample spacing. This importer does **not** claim valid
  counterfactual or intervention-time results.
- Input is validated as rectangular and finite. An ambiguous 52×52 file
  requires an explicit `--layout samples-first` or `--layout variables-first`.
- No random train/test split, data leakage, synthetic accuracy, or baseline
  classification metric is introduced here.
- Other TEP dataset editions (for example the large, labeled Kaggle/Harvard
  CSV datasets) need a **separate adapter**; this loader specifically supports
  the Russell/Chiang/Braatz `.dat` convention.

## Planned follow-up PRs

1. Document a reproducible **normal-only baseline** using training data;
   evaluate anomaly alarms on held-out test files. Keep sample-level fault
   onset assumptions explicit and testable.
2. Add simple reference detectors (e.g. robust univariate baseline and
   multivariate PCA) and publish per-fault false alarm and delay metrics.
3. Add open-set reasoning and only then compare L5 investigations against
   externally validated reference evidence. Do not mix diagnostic detection
   with simulated intervention claims.

## References

- Downs, J. J. and Vogel, E. F. (1993), *A plant-wide industrial process
  control problem*, Computers & Chemical Engineering, 17, 245–255.
- Russell, E. L., Chiang, L. H. and Braatz, R. D. (2000),
  *Data-driven Techniques for Fault Detection and Diagnosis in Chemical
  Processes*, Springer.
- Source and format: https://github.com/jkitchin/tennessee-eastman-profbraatz/blob/master/data/README.md
