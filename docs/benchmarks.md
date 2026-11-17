# L5 benchmarks

## Tennessee Eastman detection

The main case study uses mode 1 simulated trajectories from the [Rieth et al. dataset](https://doi.org/10.7910/DVN/6C3JR1). Each test run contains 960 observations at three-minute intervals over 52 process variables. Fault injection begins at zero-based index 160 (eight hours). The protocol fits each detector on a designated normal training run and calibrates its threshold on a separate normal training run. An alarm requires three consecutive threshold exceedances. Fault and normal test runs stay separate from fit and calibration.

The expanded study uses nine methods on 65 test trajectories (three runs per fault for 20 faults and five normal runs). That gives 585 executions per training configuration. The A/B/C study repeats the same workload for three fit/calibration pairs. The timely detection metric checks for an alarm sample during the first 30 minutes of the fault window. Eventual detection counts an alarm interval overlapping any part of that window. Healthy alarm samples come from the five independent normal runs.

On the same normal runs, Page CUSUM produced 0, 739, and 1,833 alarm samples under configurations A, B, and C. Thresholds and alarm burden depend on the normal training data. The configured reporting windows also include one hour, four hours, and the full run. [Configuration A results](../README.md#reproducible-results)

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
