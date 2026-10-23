# L5 / Workspace First

**Turn your industrial time series into a lasting analysis project.**

[中文](README.md) · [Architecture](docs/architecture.md) · [TripLens video](video/README.md)

L5 opens a local Workspace where you can import your own CSV, select signals and time windows, run anomaly detection, and reopen datasets and analysis history after restarting. The original TripLens workstation remains under **TripLens examples**.

## Capabilities

- Create, open, rename and delete projects, each containing multiple datasets and analyses.
- Preview and save CSV/TSV data with arbitrary numeric signal names. Choose a timestamp or numeric time column and its unit, or generate time from a sampling interval. Comma, semicolon, tab and pipe delimiters are supported.
- Run Robust Max-Z, PCA-Q or PCA-T² against an explicitly chosen normal baseline. Max-Z also supports one signal.
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

A baseline needs at least 100 samples. Its first 70% fits the model and imputation medians; the last 30% calibrates a fixed empirical threshold. Target data never select that threshold. Raw missing measurements remain missing in plots and are filled with fit-partition medians for computation. Review the default baseline and choose data you believe are healthy.

## Persistent data

The default directory is the Git-ignored `data/` folder. Use `L5_DATA_DIR` or:

```bash
node scripts/python.mjs server.py --data-dir /path/to/l5-data
```

Reuse the directory after restarting. Copy the entire directory to back up projects. Deleting a Workspace removes its datasets and analysis history.

## Examples and research

**TripLens examples** retains twelve simulated incidents, evidence investigation, alarm compression, intervention search, case comparison and the original Live / Replay / Lab experience. Their process-specific diagnosis remains separate from generic Workspace analysis.

`benchmarks/` retains the Tennessee Eastman, temporal, PCA/DPCA, independent-seed and six-mode studies. Generic Max-Z/PCA computation now lives in `l5/monitoring.py` and is shared with research. No physical interpretation is inferred across 52-, 53- and 18-channel datasets.

The Workspace currently provides statistical anomaly monitoring. Related signals describe deviation contributions. External root-cause analysis, investigation notes, live ingestion and large-dataset background execution are future work.

## Verification

```bash
npm run test:workspace   # CSV, algorithms, persistence and HTTP service restart
npm run check            # product/example tests, TypeScript and production build
npm run test:research     # existing research tests separately
npm run verify:artifacts # optional numerical artifact verification
```

Full research and artifact regeneration are separate from the daily Workspace checks. [Research documentation](benchmarks/README.md) · [PR #13 integration record](docs/integration-2026-10-23.md)
