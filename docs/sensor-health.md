# Sensor Health & Fault Isolation

The **Sensor health** workspace investigates measurement integrity and compares
explicit physical explanations. It complements the existing anomaly detectors:
an unusual value alone is not classified as a failed sensor.

## Try the workflow

1. Start the existing local application with `npm run build` and `npm run serve`.
2. In a Workspace, open **Models**, choose **Coupled-Tank Process**, and run a
   sensor-bias scenario: onset 60 s, duration 160 s, noise 0.002 m, seed 17.
3. Open **Sensor health** in the sidebar. Select the simulation under **Use
   existing simulation**, or select an imported Dataset. Simulations are saved
   through the existing Dataset service.
4. Select the seven tank signals. Set normal reference `[0, 30]` and analysis
   `[30.2, 160]`, and declare that the reference is normal. Choose **Coupled-tank
   constraints**. The saved simulation schema supplies an editable signal mapping
   and only the allowed nominal physical parameters. CSV datasets require an
   explicit mapping; column names never establish physical relationships.
5. Run and save. Inspect competing explanations, the estimated offset, measured
   versus flow-derived levels, physical residuals, individual fault indicators
   and their thresholds. Graphs share a cursor and time domain. Choose an interval
   to see its numerical evidence. Switch EN/中文 without changing saved evidence.
6. Use **Link this interval to Incident** to select an existing Incident. Its
   timeline, source preview and offline HTML report retain the diagnostic source.
   Saved diagnostics reopen from this workspace's history or the Incident link.

Repeat with pump degradation or a tank leak, keeping the same fault-free
reference. A pump capacity change should be supported by inlet-flow versus pump
command evidence; a leak by sustained unexplained tank-1 outflow. An isolated
level offset instead violates the flow-derived level relationship.

For ordinary datasets, declare redundant agreement or a baseline linear
relationship between selected channels. These checks expose disagreement but do
not decide which channel failed or invent process topology.

## Numerical methods

All computations use full-resolution selected measurements, NumPy and the existing
`MaxZMonitor` robust scale and `data_quality` cadence, segmentation and interval
utilities. No new dependency or detector framework is introduced.

The normal reference precedes the analysis interval and needs at least
`max(90, 3 × window)` timestamps. Its first 70% fit centers/scales or regression
coefficients; the last 30% calibrate limits. Each selected signal needs 30 finite
fit values and 20 finite calibration values. Model residual fitting excludes
windows that extend before the reference starts, and requires 30/20 valid paired
fit/calibration windows. This can require a longer reference when data are missing.
The saved evidence records the effective counts.

Default settings are a 21-sample window, 3 consecutive exceedances and multiplier
6. Robust scales use `max(1.4826 × MAD, 0.05 × standard deviation, numerical floor)`.
Most limits are the larger of a fixed minimum and `1.25 × normal-calibration
99th percentile`. These empirical limits are not false-alarm probability guarantees.

| Indicator | Computation and interpretation |
| --- | --- |
| Level shift / possible offset | Absolute trailing mean minus fitted normal median, divided by normal scale. Detects persistent bias or an abrupt step; real process changes can also trigger it. |
| Drift | Absolute trailing OLS slope times actual window duration, divided by normal scale. Slow drifts below this local limit can first appear as level shifts or model residuals. |
| Frozen value | A full consecutive window has effectively zero range, while the reference has measurable variation. The tolerance and reference range are retained. No frozen-value claim is made from a constant reference alone. |
| Isolated spike | The middle sample differs strongly from its two neighbours while the neighbours agree. Uses one subsequent measured sample; `detectedAt` records that confirmation time. A terminal sample cannot borrow future evidence. |
| Dropout | An unavailable measured value, including a processed value whose provenance mask is unobserved. No imputation is used. |
| Abnormal noise | Trailing RMS after local linear detrending, compared with reference-derived noise limits. Process oscillations and steps can also raise it. |
| Declared relationship | A redundant-channel difference with fitted normal offset, or fitted single-predictor linear residual. Uses paired normal fit/calibration samples. |

Severity is the statistic divided by its limit; values above 1 indicate an
exceedance. It is a descriptive scale within an indicator, not a common physical
damage scale. Frozen/dropout scores are binary evidence, so their duration and
sample counts are more meaningful than the peak ratio. Intervals use measured
start/end timestamps and do not extrapolate duration beyond the last sample.

Missing observations and time gaps greater than five normal median sample
intervals reset trailing windows and persistence. Timestamps must be strictly
increasing; duplicates need explicit resolution in the existing transformation
workspace. The current synchronous run budget is 50,000 source rows, 24 selected
signals, eight relationships and a window of 5–101 samples.

## Coupled-tank isolation

Levels must be in metres, flows in m³/s, pump command in percent, and opening in
fraction. Known incompatible unit metadata are rejected; use the existing
Transformations workspace for explicit conversion. Untagged CSV values require
the user to verify these units. Redundant agreement also requires matching units.

Seven explicitly mapped measured signals are required: two levels, inlet flow,
signed transfer flow, outlet flow, pump command and actual connection opening.
Known parameters are tank areas, connection/outlet coefficients, outlet opening,
nominal pump rate and overflow height. Simulator fault type, onset, intensity,
injected bias, hidden physical states and truth intervals are **not inputs**.

The independent flow-derived hydraulic estimates are

```text
expected_h2 = (outlet_flow / (outlet_coefficient × outlet_opening))²
expected_h1 = expected_h2
              + sign(transfer_flow) × (transfer_flow / (connection × opening))²
```

Two further constraints integrate measured flows over the trailing window:

```text
balance1 = [integral(inlet − transfer) − area1 × change(level1)] / duration
balance2 = [integral(transfer − outlet) − area2 × change(level2)] / duration
pump_capacity = nominal_pump_rate × pump_command / 100 − inlet_flow
valve_opening = fitted_normal_opening − measured_opening
```

Together with the two hydraulic level errors, these yield six separately
standardized constraint residuals. Positive balance1 suggests an unmeasured
withdrawal under the stated assumptions. An abrupt sensor offset creates a
transient balance residual and a persistent hydraulic error; a real leak can
preserve the hydraulic law while producing sustained missing mass.

For each contiguous union of indicator intervals, the workflow compares healthy
constraints, either level sensor's constant offset or linear drift, pump capacity
loss, valve opening loss, and a nonnegative tank-1 withdrawal. If a substantial
part of the interval also has frozen/noise/spike evidence, it additionally tests
a flow-derived sensor correction. Drift corrections affect both hydraulic and
mass-balance residuals; a sensor correction cannot simply erase an unrelated
pump/valve violation.

Candidates report fitted parameters, mean squared standardized residual loss
(each squared component capped at 900), improvement over the healthy candidate,
and a complexity penalty: 0 healthy, 1 constant/process correction, 2 drift,
3 general integrity correction. All available constraints contribute to the
score. A category is favored only with at least 10 complete observations, 60%
interval coverage, 40% improvement, corrected loss below 9, and a penalized-loss
margin greater than 0.25. Otherwise the assessment is **insufficient or ambiguous
evidence**. These are fixed engineering rules, not posterior probabilities.

Per-timestamp physical evidence states and missing residual values preserve
abstentions inside an interval whose remaining measured portions can still be
diagnosed. Graphs retain gaps. Short or entirely unavailable intervals can show
integrity faults while remaining physically unisolated.

The physical method assumes one dominant fault, calibrated nominal coefficients,
independent trustworthy flow measurements, and nonempty tanks below overflow.
Shared instrumentation failures, level-derived flow channels, coefficient errors,
unmeasured control changes and simultaneous faults can invalidate isolation.
Measured opening loss does not distinguish restriction from deliberate closure;
unexplained outflow does not prove a literal tank leak. Bias already in a declared
normal reference can be absorbed into its calibration.

## Persistence and API

An additive SQLite `sensor_diagnostics` table references existing Workspaces and
Datasets. Atomic JSON results under `<data-dir>/<workspace>/sensor-health/` retain
configuration, stable signal identities and units, the actual normal reference
values/times, fit/calibration evidence, source SHA-256 digest, observed/expected
traces, indicators, intervals and candidate comparisons. The digest covers selected
measured values and times through the analysis end; it is a provenance check,
not an external signature. Reopening reads saved computations without rerunning.
Existing Dataset and analysis-history formats are unchanged.

| Endpoint | Purpose |
| --- | --- |
| `GET/POST /api/workspaces/{id}/sensor-health` | List saved diagnostics / compute and persist one |
| `GET /api/sensor-health/{id}` | Reopen the complete saved result |
| `GET /api/datasets/{id}/sensor-model` | Allowed nominal model defaults for known coupled-tank datasets; `null` for an ordinary dataset |
| `POST /api/incidents/{id}/links` | Existing link service with `{kind: "sensor-health", diagnosticId, episodeIndex?}` |

Cross-workspace references and nonexistent interval indices are rejected. Linking
is idempotent and uses the source Dataset's established clock. Existing Incident
entries can cite the linked diagnosis as evidence. HTML reports read the saved
observations and numerical evidence, including the reference snapshot.

## Reproducible evaluation

Run on Windows or Linux after installing the existing requirements:

```sh
node scripts/python.mjs scripts/evaluate-sensor-health.py
```

The fixed protocol and all 120 case-level outcomes are in
[`sensor-health-evaluation.json`](sensor-health-evaluation.json). Development smoke
tests use seeds 1/17; evaluation seeds are 401/409. No threshold search or parameter
tuning on these evaluation cases is performed. Fits to the declared normal
reference and candidate parameter estimation on an observed fault interval are
part of the method, not hyperparameter tuning. Regression corrections to reference
boundary isolation and the detection-delay accounting were verified before the
final recorded run.

The grid uses level-noise standard deviations 0.001/0.003/0.008 m, fault intensities
0.25/0.7, 0.2-second sampling, 180 seconds total, reference `[0,30]`, and analysis
`[30.2,180]`. Seeded onsets fall between 70 and 89.8 seconds. Six measurement faults
are injected deterministically into the observed second-level channel; three
process faults use the existing conservative simulator. No hidden state is passed
to diagnosis. Fault truth is used only for scoring.

Offset magnitude is `0.3 × intensity` m; drift rate `0.004 × intensity` m/s;
spikes `0.5 × intensity` m every 25 s; added noise SD `0.05 × intensity` m.
Dropouts last 2 s every 20 s. The frozen sensor is exercised by an observed pump
command change to 145% eight seconds before freezing. Frozen/dropout definitions
do not vary with the intensity factor, so those grid cells are repeated conditions,
not independent evidence of intensity sensitivity.

| Metric | Result |
| --- | --- |
| Fault runs with a new confirmed indicator at/after onset | 107 / 108 |
| Median detection delay among detected fault runs | 0.6 s |
| Correct sensor-fault indicator type **and** channel | 62 / 72 (86.1%) |
| Pre-fault alarm-sample burden | 1.674% |
| Healthy-run alarm-sample burden | 0 / 9,000 samples across 12 runs |

Detection is any new confirmed indicator interval, not necessarily a correct causal
isolation. Ongoing episodes can acquire new indicators; these confirmations count
without restarting the union episode. Pre-fault burden includes the deliberate
pump excitation preceding frozen measurements, which legitimately triggers process
change indicators. Healthy controls have neither excitation nor injected faults.
The conditional median excludes the missed case and is not a worst-case delay.

Dominant post-onset interval assessment (all abstentions retained):

| Injected condition | Sensor favored | Process favored | Insufficient / ambiguous | No indicator |
| --- | ---: | ---: | ---: | ---: |
| Sensor fault (72) | 53 | 0 | 18 | 1 |
| Process fault (36) | 0 | 34 | 2 | 0 |
| Healthy (12) | 0 | 0 | 0 | 12 |

| Level-noise SD | Fault runs detected | Sensor type + channel accuracy |
| --- | ---: | ---: |
| 0.001 m | 36 / 36 | 95.8% |
| 0.003 m | 36 / 36 | 87.5% |
| 0.008 m | 35 / 36 | 75.0% |
| Intensity 0.25 (all noises) | 53 / 54 | 80.6% |
| Intensity 0.7 (all noises) | 54 / 54 | 91.7% |

Failures matter: only 4/12 slow-drift runs trigger the **local drift indicator**,
although other indicators detect all 12 and physical evidence favors a sensor fault
in 11. All 12 dropout cases are detected but physically abstain. Two high-noise,
weak-leak cases remain ambiguous, and one weak added-noise case is missed.
The zero sensor/process swaps apply only to this favorable known-model grid:
flows are exact independent simulator outputs, nominal coefficients match, and
only level sensors receive noise. This is reproducible simulation evidence, not
real-plant validation, proof of causality, or a calibrated accuracy guarantee.
