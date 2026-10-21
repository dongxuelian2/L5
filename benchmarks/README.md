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


## Frozen-model sensor-stress audit (stage 3)

The independent benchmark now measures **robustness without retraining**.
It evaluates all 21 original fault tests and the healthy test under six
conditions: **clean** (unchanged), **loss-xmeas7**, **loss-xmeas9**
(entire sensor unavailable), **random-missing-05** (seeded 5% missing cells),
**noise-20pct** (Gaussian noise at 20% of healthy-fit channel standard
deviation), and **offset-half-sigma** (uniform half-standard-deviation
offset on every channel).

These are artificial stress settings, **not validated physical plant
disturbance distributions**. Perturbation sizes are fixed and were not
selected by optimizing against fault-test performance.

To reproduce locally, install the benchmark dependencies and run:

    python3 -m benchmarks.fetch_reference --dest /tmp/tep-reference
    python3 -m benchmarks.robustness /tmp/tep-reference --output-dir /tmp/tep-stress
    python3 -m benchmarks.robustness /tmp/tep-reference --faults 1 --methods robust-maxz

The evaluator writes JSON (all cases, original SHA-256 data hashes, frozen
thresholds and scenario seeds) and a Markdown scoreboard (early-detection
changes versus clean and nuisance alarm episode counts) named
tep_robustness_report.json and tep_robustness_scoreboard.md. The same reports
are collected as artifacts by the reference-evaluation GitHub workflow.

**Leakage control:** normal fit data determine imputation medians, noise
scales and model parameters; the normal calibration partition determines
the fixed alarm thresholds. Stressors are applied exclusively to *held-out
normal and fault tests*. No test-time retraining or threshold tuning occurs.
Unmodified clean metrics are checked against the canonical reference report.

**Incomplete signals:** missing channels are imputed with frozen *training*
medians, not test-series means. This can hide evidence and cause PCA
artifacts. A completely unobserved row causes an explicit error rather than
a reassuring normal score. An independent follow-up should introduce
coverage-aware abstention.

**Alarm quality:** a continuous false alarm is one *episode* (a rising
edge within the healthy interval), no matter how many samples it lasts.
Alarm-active sample fractions and episodes per 24 hours are reported
separately; neither is an independent per-observation false-alarm guarantee.

These results audit the current unsupervised monitors rather than claiming
state-of-the-art industrial fault diagnostics.

## Coverage-aware abstention / three-state monitoring (stage 4)

The robustness benchmark previously reported anomaly scores even when sensor
values had been filled from the normal-training median. That masked a crucial
distinction: a *computable number* is not necessarily a *credible observation*.

Run a separate three-state audit (the original baseline and ungated stress
report remain available for comparison):

    python3 -m benchmarks.coverage /tmp/tep-reference --output-dir /tmp/tep-coverage
    python3 -m benchmarks.coverage /tmp/tep-reference --faults 1 --methods robust-maxz

The new output states are **normal**, **alarm** and **abstain**. A sample
abstains if fewer than 90% of original channels were observed or either of
the illustrative required channels **XMEAS(7)** or **XMEAS(9)** is missing.
The policy is configurable with --min-observed-fraction and
--required-channels. Choosing these required channels does **not** establish
them as a verified safety-critical sensor set for any real plant.

The original 52-channel observation mask is preserved next to imputed data.
Imputed values are allowed to maintain the feature shape for mathematical
scoring, but **do not override abstention**. Fully unavailable rows are
counted as abstentions; they are never silently labeled normal. Each
abstention breaks the consecutive-alarm streak, which must be rebuilt from
fresh observed samples before raising a new alert.

The audit adds a deliberately severe 15-sample (45-minute) all-channel
blackout from test indexes 155 through 169, spanning the nominal
fault-onset sample 160. Every scenario is applied to healthy and faulty test
series using the same non-label-based rule. Other previous stress scenarios
are also evaluated.

Reports include healthy coverage, missing/abstained sample counts, early
post-onset observation coverage, confirmed alarm episodes, conditional
alarm-active fraction over *observed* samples, early 60-minute fault
detection and its change from the clean reference. An unobserved fault
still counts in the **full fault denominator**; silently removing it from
the evaluation would falsely inflate the detection rate. Conditional
false-alarm fractions are explicitly null if no normal samples are
observable, rather than falsely reporting a zero rate.

Normal data alone still fit monitors, estimate imputation values and set
thresholds. Test faults and perturbations have no access to that process.
The clean coverage-policy run is regression-checked against the original
reference benchmark. Data hashes, policy parameters, seed, all cases and
explicit limitations are included in the JSON/Markdown workflow artifacts.

This gate provides only auditable data-availability behavior: it does not
prove safe fault response, causality, or robustness to real-world plant
telemetry failure.

## Predetermined threshold / perturbation-seed sensitivity (stage 5)

The next evaluation layer keeps the **same fixed public TEP reference
files** and repeats synthetic dropout/noise trials under several declared
random seeds. It does not create independent plant runs or infer a confidence
interval for actual deployment performance.

    python3 -m benchmarks.sensitivity /tmp/tep-reference --output-dir /tmp/tep-sweep
    # Small smoke test for local development:
    python3 -m benchmarks.sensitivity /tmp/tep-reference --faults 1 --methods robust-maxz --seeds 19 23 --alphas .01 .05

The default grid is specified in source **before testing**:

- Alpha (nominal upper empirical threshold tail): 0.005, 0.01, 0.05.
  These are distinct sensitivity settings fitted from the unchanged normal
  training/calibration split, not competing candidates ranked on fault tests.
  Alpha is **not** a guarantee of a realized test false-alarm probability.
- Five deterministic perturbation seeds: 20261021 through 20261025.
- Three test conditions: **clean**, **5% seeded cell deletion**, and
  **20% training-standard-deviation added Gaussian noise**.
- Three frozen monitors: robust Max-Z, PCA-Q and PCA-T2. Each alpha setting
  is calibrated on the held-out *normal training partition only*; no
  abnormal test values or labels affect the models or thresholds.

Results include individual seed/alpha/scenario records and
min/median/max across artificial stress seeds for early (60-minute)
fault detection, healthy coverage and nuisance false-alarm episodes. For
each seed there are **paired differences versus clean at the same alpha**;
per-fault early hit frequencies are also retained. The baseline clean
condition must remain exactly the same across seeds, and thresholds must
remain fixed across test perturbations at a given alpha.

The report intentionally never outputs a "winning" alpha; choosing it
after looking at test faults would contaminate the external benchmark.
No uncertainty interval or generalization guarantee is attached to these
seed ranges: the *original process trajectory is the same* every time.

Artifacts: tep_sensitivity_report.json and
tep_sensitivity_scoreboard.md, both archived by the independent reference
workflow, alongside the base, robustness and coverage reports.

## Causal temporal detectors and static-baseline comparison (stage 6)

This stage adds **two predeclared, causal temporal monitors** as actual
algorithmic baselines, rather than another synthetic stress mode.

- **cusum-maxz**: classical two-sided Page CUSUM applied independently
  to 52 robust-standardized channels; at each instant take the maximum
  positive or negative accumulated score. Reference drift k=0.5.
- **ewma-maxz**: causal exponential moving average of robust-standardized
  signed deviations in each channel, smoothed with lambda=0.25; alarm on
  the largest absolute averaged deviation.

Neither learns fault identity or accesses future samples. Channel centers
and scales derive **only from the healthy fitting partition**. Each record
starts with zero temporal state; the healthy calibration segment is scored
from a zero state independently of the testing records. The empirical
threshold for each detector is calibrated on the *same held-out normal
training portion*, using alpha=0.01 and three consecutive exceedances;
the original Max-Z / PCA-Q / PCA-T2 baselines use those identical rules.

    python3 -m benchmarks.temporal_evaluate /tmp/tep-reference --output-dir /tmp/tep-temporal
    python3 -m benchmarks.temporal_evaluate /tmp/tep-reference --faults 1 --alpha .01

The full 21-fault reference CI generates tep_temporal_comparison.json and
tep_temporal_comparison.md in the same artifact as all previous reports.
These show early (60-minute) fault detections, eventual detections,
**healthy alarm episodes**, alarm-active samples and delay conditional
on detected faults, plus the complete per-fault canonical evaluation.

**A causal explanation is not a root cause:** feature summaries at an
alarm come from the full *past* time series, not the single current
measurement, and are strictly labelled statistical contributions.

**Limitations:** Standard Page CUSUM does not automatically reset on alarm,
so an ongoing drift or operating-point shift can lead to an extremely
persistent nuisance alarm over long records. The calibration segment
(approximately 150 points) is much shorter than the 960-point held-out
test, so the nominal empirical alpha does not control deployed false
alarms. Temporal monitor parameters are fixed before examining test faults:
any performance improvement, if found, must be considered together with
nuisance-alarm episode counts and coverage. Temporal models have not
been integrated into online L5 decisions or physical process actuation.

**Next increments:** alarm-state-aware temporal resets around unobserved
windows; controlled operating-point drift, repeated healthy trajectories
and matched nuisance-alarm-budget comparisons. These must be evaluated
without optimizing on held-out TEP fault labels.

## Bounded-memory temporal evidence & normal-calibration alarm budgets (stage 7)

Previous public TEP evaluation exposed a major limitation: conventional
unbounded Page CUSUM kept its alarm active for 433/960 healthy test samples.
The next increment evaluates finite-lookback, two-sided Page-style suffix
accumulation, with fixed windows of **12 samples (36 min)** and **24 samples
(72 min)**. Positive and negative standardized evidence are evaluated
only over suffixes of the last W observations. They cannot accumulate
historical drift from earlier in the record.

    python3 -m benchmarks.bounded_evaluate /tmp/tep-reference --output-dir /tmp/tep-bounded
    python3 -m benchmarks.bounded_evaluate /tmp/tep-reference --faults 1

Seven detectors are compared: Max-Z, PCA-Q, PCA-T2, classic unbounded
CUSUM, EWMA and the two bounded CUSUM windows. The reference drift k=0.5
and both window lengths were declared **before** evaluating test faults.

To avoid "better detection only because of a more permissive alarm
threshold", each algorithm is evaluated under **two frozen calibration
policies**:

1. The prior per-method empirical healthy-calibration 99th percentile
   (nominal alpha=0.01).
2. That same threshold raised when needed so the **healthy calibration
   sequence** contains zero episodes of three consecutive threshold
   exceedances. The required threshold is the greatest rolling minimum
   of three adjacent healthy calibration scores. No held-out fault or
   healthy *test* data may contribute to this calculation.

These policies are equal in **calibration episode budget**, not necessarily
in *realized test* false alarm rate. The calibration interval is short,
and a policy that produces zero calibration alarms may still suffer many
alarms on a much longer or shifted healthy test. The results deliberately
report both the number of false alarm *episodes* and the total number of
alarm-active samples, including prolonged false alarms.

    python3 -m benchmarks.coverage /tmp/tep-reference \
      --methods window-cusum-12 window-cusum-24 \
      --scenarios clean random-missing-05 blackout-15samples \
      --output-dir /tmp/tep-bounded-coverage

The coverage audit has a second important change: **temporal state resets
at every abstention**. It segments the observations into contiguous valid
runs before scoring a history-dependent monitor. Imputed sensor readings
cannot silently carry CUSUM history through an all-channel blackout.
Alarm persistence independently resets on those same abstentions. The
clean-data control is checked against the original reference pipeline.

Outputs: tep_bounded_cusum_report.json, tep_bounded_cusum_scoreboard.md
and the separate coverage audit's standard JSON/Markdown reports, retained
by the pinned 21-fault GitHub workflow.

These bounded detectors are **candidate baselines, not production-ready
alarms**. Even matched normal-calibration workload does not imply matched
field nuisance alarm rates. Early detection must be interpreted together
with missed faults, 960-sample healthy-test workload, coverage and actual
detection delays. No test-based method tuning or fault-type classification
is performed.

## Causal drift adaptation and evidence-based alarm recovery (stage 8)

This increment adds an exploratory **guarded adaptive Max-Z** monitor
and a separate, hysteretic alarm recovery policy to investigate slow
baseline drift without hiding genuinely persistent high-score faults.

New fixed-before-evaluation model **adaptive-maxz**:
- Robust normal-fit median and scale are the original baseline reference.
- An adaptive per-channel reference is updated by rate 0.02 **only after
  scoring each sample**, and only where that channel's pre-update absolute
  robust residual is at most 2.5. This guards against absorbing abrupt,
  high-amplitude faults, but does **not** protect against a subtle or
  slowly developing fault being tracked away.
- Drift adjustment is capped at 1.5 original training scales per channel;
  all adaptive state starts fresh at each file/valid observation segment.
- Fit statistics and thresholds use normal training/calibration only.
  No test faults or perturbations affect reference parameters.

The **recovery-hysteresis** alarm policy confirms an incident after three
high-threshold exceedances and releases it *only after three consecutive
observed scores at or below 75% of the same trigger threshold*. It does not
silence a still-high anomaly after a fixed clock duration. A missing
observation triggers an explicit abstention and resets both the alarm latch
and any temporal monitor state. The unchanged legacy persistence policy is
also run as a control.

    python3 -m benchmarks.drift_recovery /tmp/tep-reference --output-dir /tmp/tep-drift
    python3 -m benchmarks.drift_recovery /tmp/tep-reference --faults 1

Evaluation is paired across three detectors (static Max-Z, EWMA and new
adaptive Max-Z), two alarm policies, and four predeclared test conditions:
unaltered records, a linear ramp that accumulates **+1 normal-fit standard
deviation across each 960-sample file**, a **+2 standard-deviation artificial
offset at samples 240..259**, and a complete 15-sample sensor blackout at
155..169. The perturbations are applied to both healthy and fault test
records with no test-dependent tuning. The ramps/steps are *arbitrary
instrumentation challenges*, **not** physically validated Tennessee
Eastman operating-point transitions.

The evaluation records early (60-minute) detections, eventual fault hits,
false-alarm episodes, total alarm-active samples and coverage. It also counts
fault-test records that were **already in alarm before the declared onset**;
a pre-existing alarm carried through onset must not be credited as a new
fault detection merely because the latch remained active. In the
temporary-step healthy test, it also records whether an alarm is still
active at the end of the temporary offset, whether it later clears, and
time-to-clear or right-censoring; no clearance time is invented when no
alarm was raised. Clean legacy scores are checked against the existing
canonical reference benchmark for every method.

**Do not promote an adaptive monitor based only on fewer false alarms.**
The ability to absorb normal slow drift is also a mechanism for suppressing
subtle fault signatures. The entire held-out fault denominator is retained,
and any early-hit loss is reported plainly. The evaluation does not learn
a production safety rule or propose unattended plant actuation.

Output artifacts: tep_drift_recovery_report.json and
tep_drift_recovery_scoreboard.md, archived by the pinned full 21-fault CI.

## Causal dynamic PCA: multivariate time-lag structure (stage 9)

This stage studies a different hypothesis from the preceding CUSUM,
EWMA and online-adaptive detector experiments: a fault might change the
**relationships across sensors and across successive time instants**
rather than only the instantaneous magnitude of a measurement.

Two predeclared new baselines, **dpca-q-lag2** and **dpca-t2-lag2**,
fit PCA to 156-dimensional observations composed of **52 current
channels + 52 channels one sample ago + 52 channels two samples ago**
(a nine-minute window sampled every 180 seconds). At time t, no x[t+1]
or future observations are consumed. Each file starts with unavailable
past observations filled from the normal-fit **per-channel mean**, not
a peek at the first or later test record. No state crosses file
boundaries or a coverage-gated abstention interval.

The PCA normal-fit segment alone supplies augmented-feature means
and scales, components, eigenvalues, and lag-padding values. Its
chronologically later normal-calibration segment sets each method's
empirical alpha=0.01 threshold; never inspect held-out faults while
setting the number of lags, target 90% variance, 20-component cap,
threshold or three-sample alert persistence.

Models use the established squared prediction error (Q) and Hotelling
T-squared statistics of the lag-augmented standardized matrix. At
alert time the explanation lists channels with large descriptive
lag-aggregated PCA contributions, **not physical fault root causes**.

    python3 -m benchmarks.dynamic_pca_evaluate /tmp/tep-reference --output-dir /tmp/tep-dpca
    python3 -m benchmarks.dynamic_pca_evaluate /tmp/tep-reference --faults 1
    python3 -m benchmarks.coverage /tmp/tep-reference \
      --methods dpca-q-lag2 dpca-t2-lag2 \
      --scenarios clean random-missing-05 blackout-15samples \
      --output-dir /tmp/tep-dpca-coverage

The same pinned public TEP workflow compares **Max-Z, ordinary PCA-Q/T2,
and DPCA-Q/T2** over the original 21 held-out fault-test trajectories and
independent normal test. Reports include early detection **within 60
minutes**, eventual detection, mean delay conditional on detection,
healthy false-alarm episode counts and alarm-active sample totals.
The separate sensor-loss audit confirms the lag history resets after
missing observation intervals; unavailable evidence must not count
as a healthy observation.

Expected limitations: a lag-augmented model has more dimensions, and
the short original 350-sample normal-fit segment may estimate them
poorly. Fixed calibration alpha does **not** equalize observed nuisance
alarm rates among five methods; more early detections alone cannot
establish superior monitoring. No result-based lag tuning is permitted.
This is anomaly evaluation, not causal diagnosis or plant actuation.

Artifacts: tep_dynamic_pca_report.json,
tep_dynamic_pca_scoreboard.md, and separate coverage audit reports,
with original dataset SHA-256 hashes included.

## Forward normal-only validation and equal calibration alarm caps (stage 10)

Stage 9's DPCA-Q reported 12/21 timely faults against Max-Z 11/21
on the original TEP held-out fault suite, with 3 vs 4 nuisance episodes.
This was a small difference on one public reference collection, not
evidence of statistically independent industrial superiority.

This independent increment **freezes the five algorithms and their fixed
DPCA lag structure** (Max-Z, PCA-Q/T², two-lag DPCA-Q/T²). It introduces
two forward-chronological normal-data partitions and a declared workload
cap **without changing the algorithms**:

- **Forward A:** normal d00.dat [0,250) fit, [250,350) calibration,
  [350,425) untouched normal validation.
- **Forward B:** d00.dat [0,300) fit, [300,400) calibration, [400,500)
  normal validation; if d00.dat contains 480 observations instead of 500,
  the final interval ends at 480.
- These are **overlapping temporal folds of the SAME normal trajectory**,
  not statistically independent training runs, operating regimes or
  independent bootstrap replicates. The second normal file d00_te.dat
  is a distinct *held-out file*, not a demonstrated independent plant
  realization. The 21 fault files are reused in both folds.

Two precommitted calibration thresholds are tested per detector and fold:

1. Legacy empirical normal-calibration higher-quantile threshold at
   alpha=0.01; strict greater-than comparison and three consecutive
   exceedances.
2. A more direct **matched healthy-calibration workload cap**:
   choose the **smallest observed calibration score threshold** for
   which there are **at most 1 confirmed normal calibration alarm
   episode** and **at most 2% alarm-active calibration samples**.
   The 2% limit is an exact floor of the number of calibration samples,
   not a Monte Carlo estimate. All scores used for threshold selection
   are calculated exclusively on normal calibration observations.

    python3 -m benchmarks.normal_budget_validation \
      /tmp/tep-reference --output-dir /tmp/tep-normal-validation
    python3 -m benchmarks.normal_budget_validation \
      /tmp/tep-reference --faults 1 --methods robust-maxz dpca-q-lag2

The **normal validation partition** is never used to choose any
threshold: it measures out-of-sample workload after the threshold has
been frozen. The external normal d00_te.dat is assessed separately for
healthy nuisance episodes and total alarm-active sample counts; no
thresholds are adjusted from that file. All 21 original test fault
records are then evaluated with unchanged nominal onset sample 160
and 60-minute early-detection window.

A matching calibration cap is **NOT a guarantee of equal false-alarm
burden** on either the later normal holdout or the external 960-point
normal test; these realized differences are fully reported. Similarly
the overlapping folds do not establish independent statistical
uncertainty estimates. The report includes all method-specific
thresholds, fitted metadata, calibration/validation/test alarm
episodes and active samples, per-fault hit sets, explicit gained
and lost early-fault IDs relative to Max-Z, reference source hashes,
and all prespecified methodological limitations.

The report deliberately avoids selecting or deploying a "winning"
algorithm based on these reused held-out fault outcomes.

Artifacts: tep_normal_budget_validation.json and
tep_normal_budget_scoreboard.md, attached to the pinned public
21-fault GitHub CI run.

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
