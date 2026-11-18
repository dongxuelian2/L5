# L5 benchmarks

## Tennessee Eastman detection

The main case study uses mode 1 simulated trajectories from the [Rieth et al. dataset](https://doi.org/10.7910/DVN/6C3JR1). Each test run contains 960 observations at three-minute intervals over 52 process variables. Fault injection begins at zero-based index 160 (eight hours). The protocol fits each detector on a designated normal training run and calibrates its threshold on a separate normal training run. An alarm requires three consecutive threshold exceedances. Fault and normal test runs stay separate from fit and calibration.

The expanded study uses nine methods on 65 test trajectories (three runs per fault for 20 faults and five normal runs). That gives 585 executions per training configuration. The A/B/C study repeats the same workload for three fit/calibration pairs. The timely detection metric checks for an alarm sample during the first 30 minutes of the fault window. Eventual detection counts an alarm interval overlapping any part of that window. Healthy alarm samples come from the five independent normal runs.

On the same normal runs, Page CUSUM produced 0, 739, and 1,833 alarm samples under configurations A, B, and C. Thresholds and alarm burden depend on the normal training data. The configured reporting windows also include one hour, four hours, and the full run. [Configuration A results](../README.md#reproducible-results)

### Reading detection results

Rieth labels identify simulated operating periods. A post-injection alarm counts as a hit even if the same detector also alarms on the matched normal trajectory. Sample recall measures alarm occupancy during the labelled fault period. The 30-minute window includes the sample exactly 1,800 seconds after injection (indices 160 through 170). Each detector confirms on the third exceedance, without backdating to the first.

| Quantity | Counting rule |
| --- | --- |
| Sample precision, recall, F1 | Pool TP, FP, TN and FN over explicitly labelled, evaluable samples. Precision = TP/(TP+FP), recall = TP/(TP+FN), F1 = 2TP/(2TP+FP+FN). An empty denominator gives an undefined value. |
| Event recall | Count hits divided by in-scope fault intervals with at least one evaluable sample. A miss has observed samples and zero alarms. |
| Detection by a horizon | Divide hits by all in-scope declared events in completed evaluations, including wholly abstained events. Each hit requires a confirmed alarm sample inside the interval and a delay within the horizon. Eventual detection uses the entire available interval. |
| First detection delay | Subtract original onset from the first in-interval alarm time, in seconds. Report distributions over hits. Early alarms count separately in labelled normal periods. |
| Coverage and incomplete work | Coverage is evaluable samples / submitted samples. Unobserved counts indicate no evaluable sample in the window. Truncated counts indicate that the available time range ends before the window endpoint. These counts can overlap. Failed, interrupted and pending tasks contribute to workload counts only. Version 1 records retain their original whole-event observation counts. |
| False alarms | Sample FPR = FP/(FP+TN). Normal alarm frequency = 3,600 × normal episodes / observed normal seconds. Split spans at annotation boundaries, abstentions and acquisition gaps above five median positive sample intervals. Exposure and alarm duration sum last minus first time per span. Singletons contribute zero time. Pool episode counts and exposure before dividing. Historical records without exposure have an undefined frequency. |

The A/B/C replay reproduced every count in the 567 published configuration–detector–fault rows. Configuration A DPCA-Q detected 20/60 fault runs within 30 minutes and 54/60 eventually. The corresponding B results were 21/60 and 57/60, and C yielded 20/60 and 55/60. Its independent normal alarm samples were 2, 5 and 2 out of 4,800 respectively. The expanded A study repeats the A condition. The 2,340 recorded executions represent 1,755 distinct configuration–detector–trajectory combinations.

### Prepare the source data

Install L5 using the [README](../README.md#installation). Run the following commands at the repository root. The three source files total about 909 MB. The preparation command extracts the selected runs after verifying the original files. Use `--source-dir` to point to local originals and omit `--download` to prepare data offline.

```sh
node scripts/python.mjs -m examples.tep.prepare --source-dir output/rieth --cache-dir output/tep-cache --source fault-free-training --faults 0 --runs 1 2 3 4 5 6 --download
node scripts/python.mjs -m examples.tep.prepare --source-dir output/rieth --cache-dir output/tep-cache --source fault-free-testing --faults 0 --runs 1 2 3 4 5 --download
node scripts/python.mjs -m examples.tep.prepare --source-dir output/rieth --cache-dir output/tep-cache --source faulty-testing --faults 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 --runs 1 2 3 --download
```

### Run the fixed studies

Run the studies with a dedicated data directory. Set `L5_TEP_CACHE` to `output/tep-cache` in the server environment to browse the extracted trajectories and saved studies in **Tennessee Eastman benchmark**. Start the server with `npm run serve -- --data-dir output/tep-workspace` after the CLI jobs finish.

```sh
node scripts/python.mjs -m examples.tep.expanded_run --data-dir output/tep-workspace --cache-dir output/tep-cache --output-dir output/tep-expanded
node scripts/python.mjs -m examples.tep.robustness --data-dir output/tep-workspace --cache-dir output/tep-cache --output-dir output/tep-robustness
```

Each output directory contains `study.json` with the saved workspace and study IDs, `results.json` with per-run model and detection results, and `per-run.csv` for tabular comparison. Pass `--workspace-id` to reuse a workspace. Pass `--workspace-id` and `--study-id` together to continue or export a saved study. The [Streamlit result table](../demo/tep-results.csv) aggregates the recorded A/B/C per-run counts by configuration, detector, and fault. Normal alarm counts use the rows for fault 0.

For a shorter case, the original protocol uses two independent normal runs and two runs each for faults 1, 3, and 5. The command below evaluates 72 tasks and exports an experiment report and a linked example incident report.

```sh
node scripts/python.mjs -m examples.tep.run --data-dir output/tep-small-workspace --cache-dir output/tep-cache --output-dir output/tep-small --investigate
```

Open the resulting workspace and select **Tennessee Eastman benchmark** to compare the detection matrix, training configurations, and individual trajectories. Drill into an experiment to inspect its synchronized scores and raw signals, or link an alarm interval to an incident for export.

### Independent reference evaluation

The earlier [Braatz laboratory reference data](https://github.com/camaramm/tennessee-eastman-profBraatz) is a separate protocol. It chronologically splits the normal training run for fit and calibration, scores 21 fault runs and a held-out normal run, and reports fault detection, pre-fault alarm burden, and normal-run alarm burden.

```sh
node scripts/python.mjs -m benchmarks.fetch_reference --dest output/tep-reference
node scripts/python.mjs -m benchmarks.run_suite output/tep-reference --output-dir output/tep-reference-results
```

The independent Rieth normal-operation study uses the original training and testing RData files in `output/rieth`. Prepare them with the first two source commands above. The study compares calibration and healthy alarm burden across distinct simulation runs.

```sh
node scripts/python.mjs -m pip install pyreadr==0.5.7
node scripts/python.mjs -m benchmarks.rieth_independent output/rieth --local-only --output-dir output/rieth-normal
```

The six-mode normal transfer study evaluates threshold behavior across operating modes using the [THUFDD normal-operation files](https://github.com/Lichen0102/Multi-mode-Fault-Diagnosis-Datasets-with-TE-process).

```sh
node scripts/python.mjs -m benchmarks.multimode_normal output/thufdd --output-dir output/thufdd-normal
```

## TripLens simulation

Run the embedded TripLens validation to print its JSON summary.

```sh
node scripts/python.mjs -m simulation.platform
```

## Coupled-tank simulation studies

The model uses square-root flow laws with signed inter-tank transfer and conservative volume updates. State and fault truth are available in seeded simulations for evaluation. Identification fits measurements with bounded, noise-weighted least squares. Use an independent run or disjoint interval to evaluate predictions with frozen coefficients. Fit rank and residual structure help identify weak parameter combinations. Additional input excitation or flow measurements can help separate their effects.

For constant areas, storage satisfies A₁ dh₁/dt = inlet − transfer − leak₁ − spill₁ and A₂ dh₂/dt = transfer − outlet − spill₂ in the base plant. Orifice coefficients absorb discharge coefficient, opening area and √(2g), with units m⁵ᐟ²/s. The overflow law uses positive head above the crest to the power 3/2. A rectangular free weir has coefficient (2/3) Cd b √(2g), in m³ᐟ²/s. L5 assumes a lumped value of 0.1. Equipment geometry, measured head–discharge curves and fitted Cd are required to validate it. [US Bureau of Reclamation, thin-plate weir relationships](https://www.usbr.gov/tsc/techreferences/mands/wmm/chap02_09.html)

Pump and valve fault intensities interpolate linearly to 30% of nominal pump delivery and 15% of nominal valve opening at full severity. Those endpoints, the nominal geometry and the default 2 mm sensor noise are illustrative assumptions. Flow-meter tests across commands and heads, valve characterization and sensor residual measurements would establish equipment-specific values. SSPRK2 uses shared donor-volume-limited stage fluxes. Smooth positive-head cases permit second-order convergence. Drying, flow reversal and switching require case-specific step refinement.

With the application requirements installed, run these fixed studies at the repository root.

```sh
node scripts/python.mjs -m benchmarks.calibration_benchmark --datasets output/calibration-examples
node scripts/python.mjs -m benchmarks.estimation_evaluate
node scripts/python.mjs -m benchmarks.alarm_correlation
node scripts/python.mjs -m benchmarks.safety_tanks
node scripts/python.mjs -m benchmarks.resilience --output-dir output/resilience
node scripts/python.mjs -m benchmarks.regime_evaluate --output output/regime-synthetic.json
node scripts/python.mjs -m benchmarks.experiment_design --trials 8
node scripts/python.mjs -m benchmarks.reachability --output output/recovery-benchmark.json
node scripts/python.mjs scripts/benchmark-control.py
node scripts/python.mjs scripts/evaluate-sensor-health.py
```

In the calibration study, three noisy training seeds (19, 32, and 71) and a separate validation seed (201) used 2 mm level noise. Held-out tank 2 RMSE was 2.83, 2.07, and 2.01 mm after fitting, with an original nominal RMSE of about 377 mm. Static level-only data yielded rank two for three coefficients. Time-varying pump and valve commands yielded rank three in the same benchmark model.

The reachability benchmark replays fixed policies on 15 held-out initial conditions and disturbances with an independent adaptive integrator. On the 17 × 17 grid, nominal and robust policies each recovered 8 of 15 runs. The nominal policy violated a constraint on one run and the robust policy completed all 15 runs within the configured constraints. These counts describe that simulation protocol and grid.

The six-mode regime study also accepts [THUFDD normal-operation files](https://github.com/Lichen0102/Multi-mode-Fault-Diagnosis-Datasets-with-TE-process). It holds out chronological tails from six independent normal-mode files and assesses recognition and healthy alarm burden. The synthetic regime study scores fault detection under independent seeded trajectories. For the THUFDD study, run:

```sh
node scripts/python.mjs -m benchmarks.regime_evaluate --thufdd-dir output/thufdd --download --output output/regime-full.json
```
