# L5 / Industrial Analysis Workspace

**Turn your industrial time series into a lasting analysis project.**

[中文](README.md) · [Architecture](docs/architecture.md) · [TripLens video](video/README.md)

L5 opens a local Workspace where you can import your own CSV, run anomaly detection, and organize intervals, analyses and model experiments into a persistent **Incident**. The incident workstation saves editable notes, evidence, hypotheses and conclusions so investigation can continue after restarting. **Models** selects TripLens or a coupled-tank process from the backend catalog, saves versioned scenarios and opens each model’s supported investigation and intervention tools. **TripLens examples** retains the original professional interface.

**TEP case study** imports verified original Harvard Dataverse process simulation runs with 52 feature identities and separate published labels. Experiments fit on one normal dataset, calibrate on another and score independent test datasets with fresh sequence state. The fixed case runs all nine existing detectors on eight held-out trajectories, retaining missed faults, per-run distributions, Incident evidence and offline measurement reports. [Prepare and reproduce](examples/tep/README.md) · [Actual results and limitations](docs/tep-case-study.md).

## Capabilities

- Create, open, rename and delete projects, each containing multiple datasets and analyses.
- Preview and save CSV/TSV data with arbitrary numeric signal names. Choose a timestamp or numeric time column and its unit, or generate time from a sampling interval. Comma, semicolon, tab and pipe delimiters are supported.
- Maintain a persistent signal catalog with stable IDs, display names, units, descriptions, categories, devices, tags and explicit logical measurement keys across datasets.
- Inspect actual missing measurements, invalid/duplicate timestamps, irregular sampling, long interruptions, statistics and available sample spans. Open a problem's original curve from its quality view.
- Browse multiple sources in Signal Explorer with shared windows and full-resolution cursor readings. Absolute sources share UTC; relative sources require saved references or explicit UTC origins. Save and restore selections, windows, cursors and layouts.
- Run Robust Max-Z, PCA-Q/T², EWMA, Page CUSUM, finite-window CUSUM, Dynamic PCA-Q/T² and experimental Adaptive Max-Z against an explicitly chosen normal baseline. Max-Z also supports one signal.
- Inspect raw measurements, scores, fixed thresholds, above-threshold intervals, first detection time and related signals.
- Automatically retain successful analyses with their models and parameters. Reopen a result, adjust parameters for another run, or export JSON.
- Save, edit and duplicate formal experiments; batch the nine existing detectors and finite parameter studies with task progress, individual errors and independently saved AnalysisResults.
- Configure independent fit/calibration/test datasets, native time ranges, verified original-name signal mappings and observation policies. Reuse each fitted detector across test runs; preserve all dataset hashes, source identities and label versions. Inspect the TEP fault-by-method matrix, delays in seconds, coverage, missed events and per-run median/ranges.
- Evaluate reviewed normal/anomaly intervals or saved model simulation truth, compare alarm timing and independent score scales, retain research records with run references, and export offline experiment reports.
- Create, edit, find and archive incidents. Associate multiple datasets, analyses and detection intervals; inspect source-window curves, peaks and contributions; maintain hypotheses with supporting or opposing evidence.
- Store metadata in SQLite and keep original CSV, numeric arrays and result files on disk.

## Models and scenarios

Open **Models** in a Workspace. The backend registry supplies model versions, signal definitions and units, parameter ranges, faults, tools, actions and capability declarations. Scenario forms use those descriptors. Save, copy, inspect historical versions and rerun a scenario; every session fixes its model descriptor, scenario version, configuration, seed, measurements and fault truth.

| Model | Signals and faults | Investigation and intervention |
|---|---|---|
| TripLens `triplens-synthetic-18-v2` v2.0.0 | The original 18 channels and 12 faults | Existing diagnosis, alarms, 11 tools, seven actions, observed-data fitting, known-model forecasts and recovery-window search |
| Coupled-Tank Process `coupled-tanks` v1.0.0 | Seven level, flow and control signals; pump degradation, restricted connection, leakage and sensor bias | Level trends, measured flow balance and sensor checks; computed pump/valve changes, backup pump and controlled supply stop |

The tank model uses volume balances and square-root head-dependent flow. Conservative SSPRK2 stages preserve nonnegative physical levels, with separate sampling and integration settings. Default levels of 1.5625 m and 1 m balance a 0.03 m³/s flow. Parameters are illustrative rather than plant-calibrated. Measured levels include noise and possible sensor bias; forecasts show physical levels. An observed balance residual is evidence, not a fault classification.

Inspect an observation window, overlay another run of the same model/version, save tool results and compare real simulated interventions. Save either model's output as a normal Dataset for the Signal Catalog, quality tools, transformations, all nine detectors, Experiments and Incidents. Derived provenance retains model/scenario/session snapshots. Evaluation uses saved model fault intervals; recovery after a finite fault remains unlabelled.

**Research across models** indexes persisted experiment tasks and evaluations with their own datasets, model/scenario identities and label versions. It does not normalize physical variables or rank incompatible score scales. Real CSV data without a supported process model retain generic analysis and incident workflows without physical intervention forecasts. Existing TripLens URLs, APIs, sessions and saved results remain supported.

[Model interface, equations and storage](docs/model-workspace.md) · [Validation, migration and limitations](docs/model-workspace-validation.md)

## Run locally

Requires Node.js 20.19+ / 22.12+, npm and Python 3.12+.

```bash
npm ci
python -m venv .venv
node scripts/python.mjs -m pip install -r requirements.txt
npm run build
npm run serve
```

Open **http://127.0.0.1:8787**. No API key or cloud service is needed. The Python runner prefers `.venv`; `PYTHON` can select another interpreter.

For development, run `npm run serve` and `npm run dev` in separate terminals. Vite proxies `/api` to port 8787. The examples can still run as a static app; workspaces use the Python service.

## Analysis workflow

1. Create a Workspace on the home page.
2. Open **Datasets**, choose your CSV, check the time axis and preview, then import it.
3. Select signals and choose **Configure analysis**.
4. Set an assumed-normal baseline and a later, disjoint analysis window. Inputs use seconds; timestamp datasets also show their UTC origin.
5. Select an algorithm and parameters, then choose **Run analysis and save**.
6. Inspect results. Use **History** to reopen a run and rerun its parameters.
7. Choose **创建事件** (create incident) on an interval card or in the complete anomaly record. Edit the title, time range and description before saving.
8. Add other intervals or algorithm results with **添加到已有事件** (add to existing incident). Save notes, hypotheses, evidence relationships and the current conclusion in the incident workstation.
9. Restart the service, open **事件** (incidents) in the Workspace sidebar and continue the same investigation.

The configured chronological split needs at least 30 fit and 30 calibration observations (default 70%/30%). The first partition fits preprocessing and the model; the second calibrates a fixed empirical threshold. Target data never select that threshold. Raw missing measurements remain missing in plots and are filled with fit-partition medians for computation. The original observation mask gates decisions: insufficient coverage or missing required channels produces abstain and resets temporal history. Configure persistence, sensor loss, noise and offset experiments, then compare saved runs in History. Review the baseline and choose data you believe are healthy.

## Experiment workflow

Open **Experiments**, or start from a saved Dataset. Choose signals, a normal baseline, a later analysis window, alpha, coverage policy and one or more methods. Method-specific controls reuse the existing analysis controls. **Parameter study** accepts comma-separated candidates: at most eight per parameter and 64 Cartesian-product tasks per batch. Preview the concrete plan, then **Save & run all tasks**.

A local sequential worker saves progress, timing and individual AnalysisResults. Successful tasks survive other failures. Restarting marks unfinished work as interrupted; **Retry unfinished tasks** starts a new run using the original input snapshot. Editing or rerunning never replaces previous results. Snapshots include dataset/CSV hashes, source lineage, signal metadata, clock, effective configuration, engine source hashes and the full immutable label version.

Labels explicitly declare native dataset seconds and their time source. Create closed normal/anomaly intervals in the editor, import JSON with `timeBasis: "dataset-seconds"`, `timeSource` and `intervals`, or use saved TripLens truth. Intervals must not overlap or share endpoints. Unlabelled and abstained samples are excluded from TP/FP/TN/FN. Precision, recall and F1 describe only reviewed intervals; positive-only labels cannot establish false-alarm behavior outside them. A zero denominator produces an undefined metric. Event recall, unobserved truth events, normal-only false alarm events and onset delay are reported separately from sample metrics.

Filter tasks by method, parameter text, run or status. Select up to 12 successful tasks to compare common/unique alarm spans, exact-timestamp agreement, separate score scales and variable contributions. A shared cursor reads full-resolution dataset measurements. Different clocks remain separate; different windows, coverage, inputs/baselines or truth versions are identified. Duration is last minus first timestamp within each contiguous alarm span, excluding acquisition gaps.

Save notes and conclusions with explicit run references; revisions remain available. Associate one run’s selected analyses or specific intervals with a new or existing Incident, and return from its sources to the experiment. **Experiment report** previews persisted evidence, provenance, real measurement and detection plots, parameters, evaluation, notes and result IDs. Download independent HTML or print with A4 browser styles. The same data directory restores the research after restarting. See [validation and boundaries](docs/experiment-validation.md).

## Multi-source signal workflow

Import each file in **Datasets**, reviewing the displayed time interpretation. Choose **Unix epoch time** explicitly for Unix seconds or milliseconds. ISO timestamps normalize to UTC; naive dates use the entered timezone (UTC by default). Numeric and generated time remain relative.

Use **Signal catalog** to edit semantics and filter by dataset, device, category or tag. Equal logical measurement keys explicitly associate physical points; each source keeps its own unit. **Data quality** shows measured statistics, coverage and timestamp issues; problem buttons open the corresponding signal window.

Select signals and open **Signal Explorer**. Relative sources start on independent clocks. In **Time relationships**, choose another dataset or a timezone-aware source-zero timestamp and save the relationship. Source seconds plus offset equal reference-source seconds. References stay within a workspace and cannot form cycles.

Different physical quantities use separate curves sharing time. Overlay mode groups only signals with equal, nonempty units and categories. Set a window, zoom, and move or type the cursor offset to inspect the original value and actual measurement time. Missing values, sampling gaps and stopped-source coverage are distinct. Save the named view to restore signals, per-clock windows, cursor and layout after restarting. Continue with an existing analysis, configure a new one, create an incident, or return to a saved process simulation.

Quality counts include source rows with invalid time. Those rows remain in the original CSV; timed arrays and analyses omit them. Finite-value statistics include those measurements, while usable counts require valid timestamps. Duplicate timestamps retain every row; the cursor shows the first row at the nearest timestamp. Gaps exceed five times the median positive interval; remaining deviations above 5% are irregular. Sample spans do not claim continuous observation. Display reduction preserves extrema and hole boundaries; cursor readings use full arrays. Use Transformation Workspace to generate a common grid or calculated variables.

## Transformation Workspace

Select signals in the catalog or Explorer and choose **Transform selected signals**, or open **Transformations** in the sidebar. UTC sources align directly; relative sources need an explicit saved reference. Choose intersection, union or custom coverage, a sampling interval, and per-signal units, resampling, maximum gap, duplicate and missing-value policies. Available resampling methods are nearest, linear, previous, and left-closed window mean/min/max. Missing values can remain missing or use bounded linear/previous, a fixed value, or a valid-source statistic. No method fills outside source coverage.

Bind expressions to stable selected signal IDs through editable keys. Arithmetic, abs, sqrt, log, exp, sin, cos, minimum, maximum, clip, diff and rate use a bounded AST interpreter. Compatible arithmetic converts units; absolute-temperature subtraction yields a temperature difference. Scalar bounds in clip/minimum/maximum use the first input's unit. Ambiguous absolute-temperature arithmetic is rejected; complex products need an explicit output unit and use the displayed numeric input units. rate uses elapsed seconds and leaves its first point missing.

Engineering conversions cover °C/K/°F, Pa/kPa/MPa/bar, m³/s/m³/h/L/min, W/kW/MW, V/kV, A/mA, s/ms/min/h, and explicitly identified rotational rpm/Hz. Unknown custom units can only be preserved. Simple rate units and temperature differences support proportional conversion.

The computed preview shows curves, before/after fill counts, missing fractions, ranges and point provenance. Save the editable definition, then generate an ordinary Dataset for monitoring, Explorer and Incidents. Each execution keeps its own arrays, resolved clock, definition revision, source hashes and provenance masks; rerunning never replaces past data or analysis references. Saved definitions retain source clocks and unit semantics until **Use current source clocks and units** explicitly refreshes them. The grid budget is 1,000,000 rows and 10,000,000 values.

Monitoring defaults to original observation coverage. **Include processed values** explicitly permits interpolation and fills to count; remaining missing data still cause abstention under the selected coverage rule. Max-Z/PCA need 30 eligible fit and 30 eligible calibration rows; temporal models require a covered baseline. Statistical fills use original valid data across the output window, which can contain information from the entire window. Provenance links open original signals, datasets and TripLens sessions; incident reports embed the source and processing appendix. See [validation](docs/transformation-validation.md).

See the [three synthetic industrial CSV examples](examples/data-foundation/README.md) and [validation record](docs/signal-workspace-validation.md).

## Continuing an incident investigation

Users create and maintain incidents. Several adjacent, overlapping or independently detected intervals can belong to one incident. Each source retains its own time axis; the incident's overall range is maintained by the user. The list supports status, title and intersecting time-range filters. Archived incidents remain available and can be reopened by changing their status.

The workstation links to original analyses at the selected interval and shows the corresponding raw signals and score curve. Editable evidence can point to a source and support or oppose a candidate explanation. Notes, observation times, conclusions and all associations are stored in Workspace SQLite, using stable incident IDs. Forms have explicit save controls with service confirmation.

RuntimeWorkbench can associate its current hypothesis, latest completed result or any saved experiment with an incident. The event displays existing tool outputs and intervention plots; returning to the simulation restores the recorded observation window, hypothesis and experiment parameters. Ordinary CSV investigations work independently of process models.

## Runtime process workflow

1. Open **Process simulator** in a Workspace. Start from any of twelve fault templates or healthy operation. Configure onset, severity, initial temperature offset, noise, response, actuator delay, seed, duration and integration step. **Run new simulation** computes new observations in Python.
2. Set any observation cutoff, such as `93` or `156.6` seconds, and an optional window start. Diagnosis, alarms and propagation use only that prefix. Process diagnosis needs an assumed-stable first 20 seconds; early windows report insufficient data.
3. Inspect all hypotheses and select any one. Invoke signal/window inspection, change points, controllers, alarms, downstream paths, hypothesis comparison, sensor consistency, measurement suggestions, SOP checks or a fitted fault trial.
4. In **Interventions**, choose observation-only fitting or an explicit known-model trial, action times, horizon, feed reduction, setpoint reduction, bypass flow and pump strength. Compare multiple actions and successive parameter runs. Optionally search safe start times at a chosen resolution.
5. **Save dataset & model** links the observations and reusable model to Datasets. Run generic monitoring or reopen model investigation. Tools, assistant outputs and interventions persist in **Saved experiments**, including editable parameters.

The stable integration step is 0.05–1 second, with 100,000 steps per simulation and a 3,000,000-step recovery-search budget. Physical pressure determines simulated limit crossings. Generic CSV does not acquire topology or counterfactual control from its column names.

The assistant executes selected deterministic tools or routes keywords. Optional `TRIPLENS_MODEL_ENDPOINT`, `TRIPLENS_MODEL` and `TRIPLENS_MODEL_API_KEY` settings enable a model to summarize current observed context and actual Python outputs. Numerical computation stays in Python.

## Persistent data

The default directory is the Git-ignored `data/` folder. Incident information, source references, records, evidence relationships and conclusions live in `workspace.sqlite3`, without browser storage. Startup adds the incident tables while retaining existing database records and data files. Use `L5_DATA_DIR` or:

```bash
node scripts/python.mjs server.py --data-dir /path/to/l5-data
```

Reuse the directory after restarting. Copy the entire directory to back up projects. Deleting a Workspace removes its incidents, investigation records, datasets and generic analysis history. Simulation sessions and their experiments remain in the local simulator library with that Workspace association removed.

## Examples and research

**TripLens examples** retains the original Live / Replay / Lab teaching experience. Runtime investigation and comparison share the same engine and components as Workspaces.

`benchmarks/` retains the Tennessee Eastman, temporal, PCA/DPCA, independent-seed and six-mode studies. Workspace temporal, DPCA, adaptation and coverage reuse existing research implementations. Generic Max-Z/PCA computation lives in `l5/monitoring.py` and is shared with research. No physical interpretation is inferred across 52-, 53- and 18-channel datasets.

Statistical signal contributions describe deviations. Process evidence scores are not probabilities, and conditional simulator forecasts are not plant control guarantees.

## Verification

```bash
npm run test:workspace   # CSV, algorithms, incident/model workflows and HTTP restart
npm run check            # product/example tests, TypeScript and production build
npm run test:research     # existing research tests separately
npm run verify:artifacts # optional numerical artifact verification
```

Full research and artifact regeneration are separate from the daily Workspace checks. [Research documentation](benchmarks/README.md) · [PR #13 integration record](docs/integration-2026-10-23.md)
