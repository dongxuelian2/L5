# L5 / Signal & Time-Series Workspace

**Turn your industrial time series into a lasting analysis project.**

[中文](README.md) · [Architecture](docs/architecture.md) · [TripLens video](video/README.md)

L5 opens a local Workspace where you can import your own CSV, run anomaly detection, and organize intervals, analyses and model experiments into a persistent **Incident**. The incident workstation saves editable notes, evidence, hypotheses and conclusions so investigation can continue after restarting. **Process simulator** provides runtime process creation, investigation and intervention. **TripLens examples** uses the same runtime interface.

## Capabilities

- Create, open, rename and delete projects, each containing multiple datasets and analyses.
- Preview and save CSV/TSV data with arbitrary numeric signal names. Choose a timestamp or numeric time column and its unit, or generate time from a sampling interval. Comma, semicolon, tab and pipe delimiters are supported.
- Maintain a persistent signal catalog with stable IDs, display names, units, descriptions, categories, devices, tags and explicit logical measurement keys across datasets.
- Inspect actual missing measurements, invalid/duplicate timestamps, irregular sampling, long interruptions, statistics and available sample spans. Open a problem's original curve from its quality view.
- Browse multiple sources in Signal Explorer with shared windows and full-resolution cursor readings. Absolute sources share UTC; relative sources require saved references or explicit UTC origins. Save and restore selections, windows, cursors and layouts.
- Run Robust Max-Z, PCA-Q/T², EWMA, Page CUSUM, finite-window CUSUM, Dynamic PCA-Q/T² and experimental Adaptive Max-Z against an explicitly chosen normal baseline. Max-Z also supports one signal.
- Inspect raw measurements, scores, fixed thresholds, above-threshold intervals, first detection time and related signals.
- Automatically retain successful analyses with their models and parameters. Reopen a result, adjust parameters for another run, or export JSON.
- Create, edit, find and archive incidents. Associate multiple datasets, analyses and detection intervals; inspect source-window curves, peaks and contributions; maintain hypotheses with supporting or opposing evidence.
- Store metadata in SQLite and keep original CSV, numeric arrays and result files on disk.

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
