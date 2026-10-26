"""Free public demonstration of L5's analysis engine and verified TEP studies."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from demo.logic import (  # noqa: E402
    analyze,
    example_data,
    load_uploaded_csv,
    tep_faults,
    tep_table,
)

from l5.analysis import ALGORITHMS  # noqa: E402

st.set_page_config(page_title="L5 | Industrial Process Demo", page_icon="📈", layout="wide")
st.title("L5 — Industrial Process Analysis")
st.caption("An interactive view of the L5 anomaly detection engine and published Tennessee Eastman experiments.")
st.markdown("[GitHub repository](https://github.com/dongxuelian2/L5)  ·  [TEP methodology](https://github.com/dongxuelian2/L5/blob/main/docs/tep-benchmark-expanded.md)")

tab_live, tab_tep, tab_about = st.tabs(["Explore & detect", "Tennessee Eastman", "About L5"])

with tab_live:
    st.subheader("Explore process signals")
    st.write("Run L5 detectors on an included synthetic process scenario or your own numeric CSV.")
    source = st.radio("Input", ["Built-in synthetic scenario", "Upload CSV"], horizontal=True)
    frame = None
    identity = source
    if source == "Built-in synthetic scenario":
        frame = example_data()
        st.caption("Synthetic four-channel process, with a gradual fault beginning at sample 585. This is not TEP data.")
    else:
        uploaded = st.file_uploader("Numeric CSV with a header row (up to 2 MB)", type=["csv"])
        if uploaded is not None:
            raw = uploaded.getvalue()
            identity = hashlib.sha256(raw).hexdigest()
            try:
                frame = load_uploaded_csv(raw)
            except ValueError as exc:
                st.error(str(exc))
        else:
            st.info("Upload a CSV to start the analysis. Files are used in memory for this session.")

    if frame is not None:
        available = list(frame.columns)
        left, right = st.columns([3, 2])
        with left:
            signals = st.multiselect("Signals", available, default=available[:min(4, len(available))])
        with right:
            normal_fraction = st.slider("Initial normal baseline (%)", 35, 60, 40, 5) / 100
        selected_algorithms = st.multiselect(
            "L5 detectors",
            list(ALGORITHMS),
            default=["robust-maxz", "pca-q", "pca-t2"],
            format_func=lambda key: ALGORITHMS[key],
        )
        st.caption(f"{len(frame):,} samples · {len(available)} numeric columns · "
                   f"baseline [0, {int(len(frame) * normal_fraction) - 1}] · "
                   f"analysis [{int(len(frame) * normal_fraction)}, {len(frame) - 1}]. "
                   "The horizontal axis is sample index.")
        if signals:
            st.line_chart(frame[signals], height=270)
        selection_key = hashlib.sha256(repr((identity, signals, selected_algorithms, normal_fraction)).encode()).hexdigest()
        if st.button("Run anomaly detection", type="primary", disabled=not signals or not selected_algorithms):
            with st.spinner("Running L5 algorithms"):
                try:
                    results, errors = analyze(frame, selected_algorithms, signals, normal_fraction)
                    st.session_state["l5_demo_analysis"] = {
                        "key": selection_key, "results": results, "errors": errors
                    }
                except (ValueError, TypeError) as exc:
                    st.error(str(exc))
        saved = st.session_state.get("l5_demo_analysis", {})
        if saved.get("key") == selection_key:
            for key, message in saved["errors"].items():
                st.warning(f"{ALGORITHMS[key]}: {message}")
            results = saved["results"]
            if results:
                st.subheader("Detector results")
                tabs = st.tabs([ALGORITHMS[key] for key in results])
                for tab, (key, result) in zip(tabs, results.items()):
                    with tab:
                        summary = result["summary"]
                        one, two, three = st.columns(3)
                        one.metric("Alarm samples", f"{summary['flaggedSamples']:,}")
                        two.metric("Peak score", f"{summary['peakScore']:.3g}")
                        three.metric("Alarm intervals", len(result["intervals"]))
                        trace = pd.DataFrame({
                            "Detection score": result["scores"],
                            "Threshold": [result["threshold"]] * len(result["scores"]),
                        }, index=pd.Index(result["times"], name="Sample"))
                        st.line_chart(trace, height=250)
                        if result["intervals"]:
                            st.write("Saved alarm intervals")
                            st.dataframe(pd.DataFrame([{
                                "Start sample": item["start"],
                                "End sample": item["end"],
                                "Peak score": round(item["peakScore"], 3),
                                "Related signals": ", ".join(item["signals"]),
                            } for item in result["intervals"]]).head(30), hide_index=True, use_container_width=True)
                        else:
                            st.info("No alarm intervals for the selected detector.")
                        st.write("Signal contributions at the peak")
                        st.dataframe(pd.DataFrame(result["signalContributions"]).head(10), hide_index=True, use_container_width=True)
                st.download_button(
                    "Download analysis results (JSON)",
                    json.dumps(results, ensure_ascii=False, allow_nan=False, indent=2),
                    file_name="l5-demo-analysis.json",
                    mime="application/json",
                )

with tab_tep:
    st.subheader("Tennessee Eastman Process · verified experimental results")
    st.write("Official public TEP runs evaluated with nine L5 detection methods and 20 fault types.")
    a, b, c = st.columns(3)
    a.metric("Expanded benchmark", "585 runs")
    b.metric("Training robustness", "1,755 runs")
    c.metric("Total executions", "2,340")
    st.caption("The 585-run study and the 1,755-run A/B/C study share configuration A; totals count executions, not unique combinations. "
               "All values below come from committed verified benchmark results; no new TEP simulation is run on the cloud.")
    configuration = st.selectbox("Normal training configuration", ["A", "B", "C"])
    try:
        summary = tep_table(configuration)
    except (OSError, ValueError, KeyError) as exc:
        st.error(f"Unable to load verified study: {exc}")
    else:
        st.dataframe(summary, hide_index=True, use_container_width=True)
        st.bar_chart(summary.set_index("Detector")[["Detected within 30 min", "Eventually detected"]])
        algorithm = st.selectbox("Inspect detection by fault type", summary["Detector"].tolist(),
                                 format_func=lambda value: ALGORITHMS.get(value, value))
        fault_table = tep_faults(configuration, algorithm)
        if not fault_table.empty:
            st.dataframe(fault_table, hide_index=True, use_container_width=True)
            st.bar_chart(fault_table.set_index("Fault")[["Detected in 30 min", "Eventually detected"]])
        st.caption("Event detection and normal-run alarm burden are different measurements. "
                   "Values are counts over the corresponding recorded test runs.")

with tab_about:
    st.subheader("Explore the full L5 project")
    st.markdown("""
L5 is an industrial time-series analysis and incident investigation workspace.

- Explore, transform and align multiple data sources.
- Compare nine detectors, inspect scores and investigate process incidents.
- Simulate TripLens and coupled-tank process faults.
- Generate HTML/PDF-ready reports and reproduce Tennessee Eastman studies.

This online demonstration runs the actual L5 numerical analysis functions in memory.
The full React application, persistent workspaces, incidents, model scenarios,
and investigation reports remain available in the source repository.

**[Repository and installation instructions](https://github.com/dongxuelian2/L5)**
    """)
    st.info("This public demo does not retain uploads or results across sessions. "
            "Use the full local application for persistent research and larger datasets.")
