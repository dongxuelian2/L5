# L5 / Capability Restoration

**Turn your industrial time series into a lasting analysis project.**

[中文](README.md) · [Architecture](docs/architecture.md) · [TripLens video](video/README.md)

L5 opens a local Workspace where you can import your own CSV, select signals and time windows, run anomaly detection, and reopen datasets and analysis history after restarting. **Process simulator** provides runtime process creation, investigation and intervention within each Workspace. **TripLens examples** retains the teaching demos and uses the same runtime investigation interface.

## Capabilities

- Create, open, rename and delete projects, each containing multiple datasets and analyses.
- Preview and save CSV/TSV data with arbitrary numeric signal names. Choose a timestamp or numeric time column and its unit, or generate time from a sampling interval. Comma, semicolon, tab and pipe delimiters are supported.
- Run Robust Max-Z, PCA-Q/T², EWMA, Page CUSUM, finite-window CUSUM, Dynamic PCA-Q/T² and experimental Adaptive Max-Z against an explicitly chosen normal baseline. Max-Z also supports one signal.
- Inspect raw measurements, scores, fixed thresholds, above-threshold intervals, first detection time and related signals.
- Automatically retain successful analyses with their models and parameters. Reopen a result, adjust parameters for another run, or export JSON.
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
7. Restart the service and reopen the same project to continue.

The configured chronological split needs at least 30 fit and 30 calibration observations (default 70%/30%). The first partition fits preprocessing and the model; the second calibrates a fixed empirical threshold. Target data never select that threshold. Raw missing measurements remain missing in plots and are filled with fit-partition medians for computation. The original observation mask gates decisions: insufficient coverage or missing required channels produces abstain and resets temporal history. Configure persistence, sensor loss, noise and offset experiments, then compare saved runs in History. Review the baseline and choose data you believe are healthy.

## Runtime process workflow

1. Open **Process simulator** in a Workspace. Start from any of twelve fault templates or healthy operation. Configure onset, severity, initial temperature offset, noise, response, actuator delay, seed, duration and integration step. **Run new simulation** computes new observations in Python.
2. Set any observation cutoff, such as `93` or `156.6` seconds, and an optional window start. Diagnosis, alarms and propagation use only that prefix. Process diagnosis needs an assumed-stable first 20 seconds; early windows report insufficient data.
3. Inspect all hypotheses and select any one. Invoke signal/window inspection, change points, controllers, alarms, downstream paths, hypothesis comparison, sensor consistency, measurement suggestions, SOP checks or a fitted fault trial.
4. In **Interventions**, choose observation-only fitting or an explicit known-model trial, action times, horizon, feed reduction, setpoint reduction, bypass flow and pump strength. Compare multiple actions and successive parameter runs. Optionally search safe start times at a chosen resolution.
5. **Save dataset & model** links the observations and reusable model to Datasets. Run generic monitoring or reopen model investigation. Tools, assistant outputs and interventions persist in **Saved experiments**, including editable parameters.

The stable integration step is 0.05–1 second, with 100,000 steps per simulation and a 3,000,000-step recovery-search budget. Physical pressure determines simulated limit crossings. Generic CSV does not acquire topology or counterfactual control from its column names.

The assistant executes selected deterministic tools or routes keywords. Optional `TRIPLENS_MODEL_ENDPOINT`, `TRIPLENS_MODEL` and `TRIPLENS_MODEL_API_KEY` settings enable a model to summarize current observed context and actual Python outputs. Numerical computation stays in Python.

## Persistent data

The default directory is the Git-ignored `data/` folder. Use `L5_DATA_DIR` or:

```bash
node scripts/python.mjs server.py --data-dir /path/to/l5-data
```

Reuse the directory after restarting. Copy the entire directory to back up projects. Deleting a Workspace removes its datasets and generic analysis history. Simulation sessions and their experiments remain in the local simulator library with that Workspace association removed.

## Examples and research

**TripLens examples** retains the original Live / Replay / Lab teaching experience. Runtime investigation and comparison share the same engine and components as Workspaces.

`benchmarks/` retains the Tennessee Eastman, temporal, PCA/DPCA, independent-seed and six-mode studies. Workspace temporal, DPCA, adaptation and coverage reuse existing research implementations. Generic Max-Z/PCA computation lives in `l5/monitoring.py` and is shared with research. No physical interpretation is inferred across 52-, 53- and 18-channel datasets.

Statistical signal contributions describe deviations. Process evidence scores are not probabilities, and conditional simulator forecasts are not plant control guarantees.

## Verification

```bash
npm run test:workspace   # CSV, algorithms, persistence and HTTP service restart
npm run check            # product/example tests, TypeScript and production build
npm run test:research     # existing research tests separately
npm run verify:artifacts # optional numerical artifact verification
```

Full research and artifact regeneration are separate from the daily Workspace checks. [Research documentation](benchmarks/README.md) · [PR #13 integration record](docs/integration-2026-10-23.md)
