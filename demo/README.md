# L5 Online Demo

An interactive, zero-cost Streamlit Community Cloud demonstration backed by the L5 detection engine and the verified Tennessee Eastman benchmark outputs.

## Online deployment

1. Open https://share.streamlit.io and connect your GitHub account.
2. Create an app from repository `dongxuelian2/L5`.
3. Choose branch `main` (after this PR is merged), file path `demo/streamlit_app.py`, and Python 3.12.
4. Deploy. Community Cloud installs `demo/requirements.txt` and assigns a public `streamlit.app` address. GitHub updates to the selected branch update the deployed demo.

No Node.js build, cloud database, paid API, persistent volume, or custom domain is needed for this entrypoint.

## Local start

From the repository root, using Python 3.12+:

```bash
python -m pip install -r demo/requirements.txt
python -m streamlit run demo/streamlit_app.py
python -m unittest tests.test_streamlit_demo -v
```

## User flow

- **Explore & detect**: start with a reproducible 4-channel synthetic scenario, or upload a UTF-8 CSV. Use 300–3,000 samples and up to 12 numeric columns, with a 2 MB upload limit. The display uses row index as a common sample clock. Choose signals, a disjoint normal baseline, and one or more of L5's nine detectors. Inspect time-series scores, fixed empirical thresholds, alarm intervals, and ranked signal contributions. Download a JSON record.
- **Tennessee Eastman**: browse committed official TEP results, compare nine algorithms over three normal-training configurations, and inspect detection counts for each of 20 faults. The 585-run expanded benchmark and 1,755-run robustness study are the same verified results described in the main README.
- **About L5**: jump to the full application's source and documentation.

Computation uses `l5.analysis.run_analysis` directly. Original uploaded CSV data and analysis output remain in the Streamlit session rather than a shared L5 workspace or database. The demo deliberately restricts dataset size, does not launch offline TEP replays, and provides no persistent projects, incident editing, or production monitoring. Individual visitors can independently explore the demonstration.

The full React/TypeScript workbench continues to run with `npm run serve`; it is unchanged.

## Verification

```bash
python -m unittest tests.test_streamlit_demo -v
npm run check
```

A deployed instance should additionally be checked in a browser: open synthetic example; run Robust Max-Z and PCA-Q; inspect nonempty scores/intervals; download JSON; switch to the TEP tab; inspect configuration A/B/C and fault tables; upload a bounded numeric CSV; ensure rejected files produce a useful message.
