# Tennessee Eastman: independent detection benchmark

This is a growing **external validation track** for L5, independent of the
TripLens synthetic incident engine. Stage 1 imported the data; stage 2 adds
three baseline detectors, chronological training, explicit evaluation
protocols, auditable metrics and reproducible CI on the original reference
files.

## Reproduce a full 21-fault reference evaluation

From repository root (Python 3.10+ recommended):

```bash
python3 -m pip install -r benchmarks/requirements.txt
python3 -m benchmarks.fetch_reference --dest /tmp/tep-reference
python3 -m benchmarks.evaluate /tmp/tep-reference --output-dir /tmp/tep-report

# Faster single-fault exploratory run (still evaluates held-out normal):
python3 -m benchmarks.evaluate /tmp/tep-reference --faults 1 --output-dir /tmp/tep-small

# Fixed, isolated tests using generated data; network never needed:
python3 -m unittest discover -s benchmarks -p 'test_*.py' -v
```

All 21 `dXX_te.dat` files plus `d00_te.dat` are **required by default**:
missing files cause an error, not silently missing fault scores. Reports
`tep_detection_report.json`, `tep_detection_cases.csv` and
`tep_detection_scoreboard.md` contain per-case results,
evaluation configuration, original channel names and per-file SHA-256s.
Continuous integration additionally runs the pinned external dataset
workflow `.github/workflows/tep-reference.yml` and retains these reports as
workflow artifacts for 30 days.

The reference mirror is pinned to commit
`9a6c8e5fcef4a2850778704e7793c87b0a187005` to prevent unnoticed data drift.
Downloads are opt-in through the command above or the dedicated external CI
workflow. **No third-party DAT files are checked in**, and the L5 web app
requires neither NumPy nor an external model/API key.

## What is actually measured?

Only the **normal training file** `d00.dat` is split chronologically:
first 70% for model fit, last 30% for calibration. No training fault files or
test files are used for fitting, threshold selection or PCA component choice.

- `robust-maxz`: maximal absolute per-channel robust standardized deviation.
- `pca-q`: PCA squared prediction-error (residual) statistic.
- `pca-t2`: PCA retained-component Hotelling T² statistic.

PCA standardizes channels using *normal-fit* statistics and retains components
explaining at least 90% training variance, subject to a 20-component cap.
Each method calibrates an empirical 99th-percentile threshold on normal
**calibration** data. A default of three consecutive exceedances raises a
confirmed alarm. None of these default choices was tuned using the fault
test labels.

TEP test records are 960 samples at a 180-second (3-minute) interval.
The conventional first **fault-affected** test sample is indexed **160**
(zero-based), so rows `0..159` are treated as pre-fault; this is an
**explicit protocol assumption** and can be overridden via
`--onset-sample`. The normal test `d00_te.dat` is fully healthy.

Metrics are intentionally separated:
- **Held-out healthy test false alarm fraction:** fraction of normal
  `d00_te.dat` samples whose persisted alarm is active.
- **Pre-fault alarm fraction:** pooled across the normal prefixes of all
  evaluated fault test records.
- **Per-fault event detection:** at least one persisted alarm **after**
  the declared onset. This is anomaly detection, *not fault-ID classification*.
- **Timely detection:** fraction of faults that trigger a new persisted
  alarm within 20 samples (60 minutes) after the declared onset. The
  window is explicit and configurable via `--early-window-samples`; a
  previously active pre-fault alarm is not counted as a new detection.
- **Detection delay:** number of test samples from onset to the first
  newly raised post-onset alarm and corresponding minutes. Average delay is **conditional
  on successfully detected faults**; undetected fault IDs are listed.
- **Post-onset detected sample fraction**, plus descriptive leading signal
  deviations at the first alarm. These are **not verified causal attributions**.

The 40-hour post-fault test horizon can make eventual detection rates look
misleadingly strong; the early-window metric is therefore shown separately.
We publish both errors and successes, including undetected faults.
Empirical calibration does not guarantee a target false-alarm rate on
serially correlated or shifted test data. No use of fault classification
accuracy, test-tuned model selection, online plant intervention, process
simulation verification or industrial safety certification is implied.

## Reference dataset and known caveats

The Russell / Chiang / Braatz TEP reference file convention contains
**41 XMEAS variables + 11 XMV variables**, each observed every 180 seconds.

Primary mirror and source notes:
https://github.com/jkitchin/tennessee-eastman-profbraatz/tree/master/data

The pinned mirror physically stores `d00.dat` as **52 lines × 500
columns** (transposed), whereas `d01.dat` is **480 × 52**, and
`d01_te.dat` is **960 × 52**. This differs from some earlier data
description documents; the importer handles both layouts explicitly.
It does not silently infer fault labels from measurements or assume all
data editions have identical sample counts.

The relative export format is:
`t,xmeas_1,...,xmeas_41,xmv_1,...,xmv_11`.
Use the stand-alone read/export utility:

```bash
python3 -m benchmarks.tep /tmp/tep-reference/d00.dat
python3 -m benchmarks.tep /tmp/tep-reference/d01_te.dat --csv /tmp/tep01.csv
```

There is **no mapping** between TEP's physical units and the existing
18 synthetic process channels. A three-minute observation interval also
cannot support L5's existing 1-second intervention horizon. The baseline
framework therefore uses TEP only for anomaly detection and explicitly
**does not call** `simulation.platform.diagnose` or its
counterfactual simulator.

## Framework boundaries and next increments

The dataset ingestion boundary lives in `benchmarks/tep.py`. The
dataset-neutral monitor and metric code lives in
`benchmarks/monitoring.py`; TEP-specific benchmark orchestration and
report export live in `benchmarks/evaluate.py`. It will be
straightforward to add another dataset adapter with a declared sample clock
and onset convention without reusing incorrect TEP physical assumptions.

Next independent increments can add:
1. Multiple healthy-training runs / time-series cross-validation and
   statistical uncertainty for false alarms.
2. A consolidated public results table comparing independent baselines and
   error modes; avoid hidden tuning on test faults.
3. Robustness to missing sensors, heterogeneous sample rates, unknown
   fault categories and operating-point shifts.
4. Independent diagnostic explanations and actual model-vs-model comparisons,
   without treating anomaly detection as root-cause identification.

## Source references

- Downs, J. J. and Vogel, E. F. (1993), *A plant-wide industrial process
  control problem*, Computers & Chemical Engineering 17, 245–255.
- Russell, E. L., Chiang, L. H., Braatz, R. D. (2000), *Data-driven Techniques
  for Fault Detection and Diagnosis in Chemical Processes*.
- Pinned public mirror: https://github.com/jkitchin/tennessee-eastman-profbraatz
