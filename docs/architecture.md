# L5 architecture

## Repository map

| Location | Responsibility |
| --- | --- |
| [`src/`](../src) | React interface and bundled examples. Workspace views are grouped by the Data, Monitoring, Investigation, Modeling and control, and Reliability navigation areas. Shared charts, request utilities, and types live at the workspace root. |
| [`l5/`](../l5) | Python computation, workspace storage, HTTP dispatch, and export. Individual capabilities own their request validation and numerical methods. Physical process models share the `models/` package. |
| [`server.py`](../server.py) | Local HTTP entry point. Serves the production frontend and passes workspace requests to `l5.api`. |
| [`demo/`](../demo) | Streamlit adapter over the shared analysis kernel. Uses session data for uploaded examples and a compact table of recorded Tennessee Eastman results. |
| [`simulation/`](../simulation) and [`benchmarks/`](../benchmarks) | Simulation example generation and repeatable evaluation programs. Detector implementations shared with the workstation also live in `benchmarks/`. |
| [`examples/`](../examples) | Importable measurements, the OPC UA tank example, and Tennessee Eastman data preparation and study entry points. |

## From measurements to a report

The guided tank case starts with `POST /api/guided-demo`. The handler calls `GuidedDemo` in `l5/guided_demo.py`, which runs the coupled-tank model and saves measured levels, inlet flow, and pump command as a workspace dataset. CSV imports and live recordings use the same dataset interface. Each dataset carries a time axis, stable signal identities, and acquisition or simulation context.

`POST /api/guided-demo/run` starts a saved experiment. The experiment service fits and calibrates each detector on the chosen normal window, then scores the evaluation window with `l5.analysis`. The result records scores, decisions, thresholds, alarm intervals, and signal contributions. The React views request series slices for display and read the saved result when reopening an experiment.

`POST /api/guided-demo/incident` links the dataset and detector results to an incident. The workspace stores hypotheses, timeline entries, evidence links, and conclusions with that incident. `GET /api/incidents/{id}/report.html` passes those saved records to `l5.reports` for a standalone HTML export.

## Storage and adapters

`WorkspaceStore` in `l5/workspace.py` coordinates the local services. SQLite holds workspace records and relationships. CSV and NumPy files retain measurements and numerical arrays under the same data directory. Analysis and report views use these saved records, so restarting the app with the same directory restores the workspace.

OPC UA acquisition runs through a server-side adapter that stores observations and quality events. Control, fault injection, and recovery policies consume data or run local models. The Streamlit adapter calls the numerical kernel in memory. Keep exported reports and benchmark output in the user's chosen destination or the ignored `output/` directory.
