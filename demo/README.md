# L5 Streamlit demo

Run L5's anomaly detectors on a built-in four-channel simulation or an uploaded CSV. The Tennessee Eastman tab shows recorded results for nine detectors, 20 faults, and three normal training configurations.

## Run locally

Use Python 3.12 and run these commands from the repository root.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r demo/requirements.txt
.venv/bin/python -m streamlit run demo/streamlit_app.py
```

On Windows, create the environment with `py -3.12 -m venv .venv` and use `.venv\Scripts\python.exe` in the next two commands.

Open [the demo](http://localhost:8501) and select **Run anomaly detection**. Choose signals and detectors, set the normal baseline, and inspect score traces, thresholds, alarm intervals, and signal contributions. Choose **Download analysis results (JSON)** to keep the result. CSV uploads accept 300–3,000 rows, up to 12 numeric signals, and files up to 2 MB. The demo uses row index as its time axis and stores results in the current session.

## Deploy to Streamlit Community Cloud

Create an app in [Streamlit Community Cloud](https://share.streamlit.io). Select `dongxuelian2/L5`, branch `main`, entry point `demo/streamlit_app.py`, and Python 3.12. Community Cloud installs `demo/requirements.txt` and assigns the deployed app a URL.

See the [workstation README](../README.md) for persistent workspaces, models, incident investigation, and standalone reports. See the [benchmark guide](../docs/benchmarks.md) for the Tennessee Eastman protocols.
