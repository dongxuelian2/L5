# Operating regime monitoring

Use **Regime monitoring** in an L5 workspace to compare three ways of monitoring a process that has multiple healthy operating conditions. The global detector pools the normal partitions, the single-mode detector uses one declared reference regime, and the regime-aware system uses each mode’s frozen detector and threshold.

1. Import normal fit and calibration data and any separate evaluation Datasets. Define at least two modes with distinct identities and display labels. Select one or more Dataset ranges for each mode’s fit and calibration partitions. A versioned Experiment label set can constrain a partition to a declared normal interval.
2. Select detector signals in consistent engineering units across datasets. Choose which of those signals provide mode evidence. Operating commands and setpoints can make recognition less sensitive to faults on monitored outputs when those inputs reliably identify the operating condition.
3. Choose Robust Max-Z, PCA-Q or PCA-T², set the normal-calibration tail level and sample persistence, and optionally override the detector settings by mode. Fit and save the model. Inspect the mode means, covariance structure, pairwise location differences and thresholds.
4. Select a held-out Dataset and time range and run the chronological replay. On a reused Dataset, its evaluation range must follow all fit and calibration ranges. The workspace rejects a different Dataset identity that shares training provenance, such as a re-imported file or a Dataset with shared transformation ancestry. Each fitted mode needs at least 30 complete observations in each normal partition.
5. Use the synchronized measurements, mode history and detector scores to inspect a sample or transition. An evaluation label version adds detector metrics after scoring. Models and runs are saved in the local workspace with partition references, fitted parameters, decisions and alarm evidence. Reopen a saved run to export an offline report or link an alarm interval to an existing Incident.

## Recognition and alarm semantics

For recognition, each mode has a fit mean and covariance on the selected recognition signals. A pooled within-mode standard deviation scales the differences, with a small numerical floor for constant signals. In that common scale the mode covariance is regularized as $(1-\lambda)\Sigma_m+\lambda I$. Cholesky solves give the squared Mahalanobis distance $d_m^2$. Each mode’s calibration data determines its distance limit using the higher empirical $(1-\alpha)$ order statistic.

A mode supports a sample when its distance is within that limit. With multiple supported modes, the minimum $d_m^2 + \log\det(\Sigma_{m,\mathrm{regularized}})$ wins only when the runner-up is separated by the configured margin. This is equal-prior Gaussian discriminant evidence on the supported set. The displayed margin measures separation in discriminant units. No supported mode yields **unknown**. An unresolved comparison yields **ambiguous**. Missing recognition inputs yield **insufficient** evidence.

The current candidate must persist for the configured dwell before a new mode is confirmed. The timeline keeps the last confirmed identity distinct from the current sample’s assigned identity. Transition events preserve the first departure evidence, candidate start and confirmation time. A transient candidate failed to persist and a pending candidate remained unresolved at the evaluation boundary. A departure timestamp estimates when the observations first left the previous mode; measured ramp onset may occur earlier.

Detector scores use the current candidate when available and the last confirmed detector when the candidate is uncertain. When neither exists or required detector inputs are missing, the regime-aware detector abstains. Strict exceedances must persist under the same detector. A data gap resets pending evidence and alarm persistence. The workspace freezes the gap threshold at fit time as five times the median positive time step pooled across fit ranges. The fit API accepts an optional `gapThreshold` in seconds. A sample can raise an alarm during a candidate transition or while its mode is unknown. The run preserves the alarm’s context and transition evidence. Mode choice uses recognition inputs and discriminants exclusively. A fault that closely resembles a different regime in those inputs can still cause misclassification.

## Evaluation

The fixed benchmark fits all three detectors separately and compares each detector with global, single-mode and regime-aware fit/calibration using the same observations. The one-mode baseline uses the first available mode in the predefined order. The detector and recognition tail levels are both 1%, covariance shrinkage is 0.15, the discriminant margin is 2, recognition dwell is four samples and alarm persistence is three samples. PCA targets 90% retained variance. Empirical thresholds on correlated normal samples can produce different alarm rates on later healthy data.

### Six-mode Tennessee Eastman normal data

The benchmark uses the pinned THUFDD MMFDD-TEP original MATLAB files and verifies their Git blob hashes before parsing. Each of the six `m{mode}d00.mat` files contains one normal trajectory with 7,201 rows. Fit uses rows `[0, 720)`, calibration `[720, 1080)` and evaluation `[1080, 7201)` in every mode. These are chronological holdouts within six source trajectories. The schema is `thufdd-tep-native-53-v1`, which retains `source_col_00` through `source_col_52` in native order and discards 28 disturbance columns. The Rieth/Braatz 52-variable schema is a separate representation. The report stores file hashes, the schema and the exact column indices. [THUFDD source repository](https://github.com/Lichen0102/Multi-mode-Fault-Diagnosis-Datasets-with-TE-process)

On the isolated tails, the recognizer confirmed **29,639 of 36,726 samples correctly (80.70%)**, left 7,087 unconfirmed and made zero wrong confirmed assignments. Mode 4 had the most abstentions at 2,635 of 6,121 samples. Across six leave-one-mode-out fits, all 36,726 withheld-mode samples were rejected. Those isolated out-of-catalog runs had zero regime-aware score coverage because no mode had been confirmed. This distinguishes a rejection from healthy detector operation.

Stitching the six untouched tails end to end produced five artificial joins. All five were confirmed after three samples and one transient candidate was recorded. On 60 healthy samples near these joins, every one-mode detector was active on 58 samples, and all three global and regime-aware detectors were inactive. Join delays use sample indices and characterize artificial joins between recorded steady regimes.

| Detector | Global alarm samples / starts | Single-mode alarm samples / starts | Regime-aware alarm samples / starts |
|---|---:|---:|---:|
| Robust Max-Z | 0 / 0 | 31,152 / 39 | 7,405 / 211 |
| PCA-Q | 129 / 36 | 30,648 / 22 | 5,486 / 323 |
| PCA-T² | 1 / 1 | 30,617 / 14 | 5,100 / 270 |

The denominator is 36,726 isolated healthy samples per method. The regime-aware monitors had a lower active-sample burden than the single-mode baselines and a higher burden than the global baselines. The six-mode public-data experiment measures recognition and healthy alarm burden. Fault results below come from the separate seeded simulation.

### Independent synthetic runs

Independent fixed seeds generate 600 normal fit and 300 normal calibration observations per mode, and six evaluation seeds generate four trajectories each. Each has autocorrelated measurement noise. The trajectories exercise healthy ramps, brief excursions, close regimes, an out-of-catalog regime, faults in stable operation and a fault spanning an actual simulated ramp. The load and setpoint channels drive recognition, and all five signals enter detection. Synthetic ramp, mode and fault labels are used only to score the finished replay.

The recognizer assigned **4,238 of 4,992 healthy steady-state samples correctly (84.90%)**, left 746 unconfirmed and misclassified eight. It rejected all 450 novel-mode samples and left 280 of 480 intentionally ambiguous samples unconfirmed (58.33%). The 200 accepted samples in that ambiguous phase reflect imperfect rejection. All 24 declared transitions were confirmed, with a median delay of 12 samples from ramp onset. There were 28 additional confirmed switches, chiefly around overlapping modes and ambiguous conditions, plus 221 transient candidates.

| Detector | Approach | Healthy alarm samples / 6,066 | Near-transition alarm samples / 360 | Within-mode faults / 18 | Ramp-spanning faults / 6 | Median hit delay |
|---|---|---:|---:|---:|---:|---:|
| Robust Max-Z | Global | 439 | 0 | 6 | 6 | 2 |
| Robust Max-Z | Single mode | 3,904 | 316 | 6 | 6 | 2 |
| Robust Max-Z | Regime-aware | 470 | 31 | 14 | 6 | 2 |
| PCA-Q | Global | 438 | 0 | 14 | 6 | 2 |
| PCA-Q | Single mode | 1,274 | 61 | 11 | 6 | 3 |
| PCA-Q | Regime-aware | 438 | 0 | 12 | 5 | 2 |
| PCA-T² | Global | 0 | 0 | 6 | 5 | 2 |
| PCA-T² | Single mode | 3,910 | 322 | 6 | 6 | 2 |
| PCA-T² | Regime-aware | 475 | 37 | 9 | 6 | 2 |

Healthy burden includes novel and ambiguous operation. For regime-aware Robust Max-Z, 438 of the 470 active healthy samples were from the novel-mode phase after a known mode was established. The last confirmed detector was still scoring there. The near-transition subset starts at a declared ramp or join onset and ends 12 samples after settling, excluding fault-active samples. Fault hits require a **new confirmed alarm** inside the injection window. Reported delay is in samples and is conditional on a hit. The JSON retains alarm starts, per-window coverage, confusion matrices, extra switches and every fault miss. In this protocol the regime-aware Max-Z found more faults than its baselines, while the pooled PCA-Q found more than its regime-aware counterpart.

### Reproduce

From the repository root with the normal Python environment set up, run the synthetic experiment locally.

```bash
node scripts/python.mjs -m benchmarks.regime_evaluate --output output/regime-synthetic.json
```

For THUFDD, install the optional MATLAB reader and allow the pinned downloads on the first run. With all six verified files cached, omit `--download` to reproduce the results offline.

```bash
node scripts/python.mjs -m pip install scipy==1.16.2
node scripts/python.mjs -m benchmarks.regime_evaluate --thufdd-dir output/thufdd --download --output output/regime-full.json
```

[Recorded benchmark JSON](../examples/regime-monitoring/evaluation.json)
