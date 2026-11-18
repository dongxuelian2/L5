# L5 architecture

## Repository map

| Location | Responsibility |
| --- | --- |
| [`src/`](../src) | React plant workstation and specialist views. Shared charts, request utilities and types live at the workspace root. |
| [`l5/`](../l5) | Python computation, workspace storage, HTTP dispatch, and export. Individual capabilities own their request validation and numerical methods. Physical process models share the `models/` package. |
| [`server.py`](../server.py) | Local HTTP entry point. Serves the production frontend and passes workspace requests to `l5.api`. |
| [`simulation/`](../simulation) and [`benchmarks/`](../benchmarks) | Executable Tennessee Eastman and CSTR plants, reproducible evaluation and shared detector methods. |
| [`examples/`](../examples) | Importable measurements, the OPC UA tank example, and Tennessee Eastman data preparation and study entry points. |

## From measurements to a report

The [plant catalog](../l5/plants.py) defines the version, equipment, original signal keys and units, observation clock, supported settings and scenario-specific references for each plant. `POST /api/workspaces/{id}/plants/runs` reserves a run using its workspace, scenario, configuration and model version. The worker integrates one trajectory per role. Fortran flushes native measurements through its standard output as it advances, and the CSTR solver supplies samples directly to the worker. The observations endpoint serves a growing numerical checkpoint, then the saved evaluation dataset.

The worker saves time, measurements, observation flags and model-specific states as NumPy arrays. SQLite records the plant, configuration, seed, event definition and each dataset's role. Independent normal fit and calibration use separate random streams. The experiment service checks measurement identity, units and model version before scoring. A separate deterministic identity links the experiment result and counterfactual to the incident.

`GET /api/incidents/{id}/report.html` renders the existing records and the run's diagnosis and comparison metrics. The browser carries dataset, signals, observation window, experiment, analysis and incident IDs on links between those views. A server restart marks active runs interrupted. A retry reuses complete sources and repeats an incomplete trajectory from seeded initialization. Historical incident and experiment records retain their original snapshots.

## Storage and adapters

`WorkspaceStore` in `l5/workspace.py` coordinates SQLite records and NPZ measurement and state arrays. File imports retain their supplied source CSV or TSV. Numerical runs record an NPZ digest in each experiment snapshot. CSV export builds a table from the observed channels on request. NPZ download includes the state and observation arrays when present.

OPC UA acquisition stores observed timestamps and quality events. Recorded sources participate in data and monitoring workflows. A native simulation carries its plant and model version. An operator-entered plant name or published dataset provenance identifies recorded equipment for investigation. Predictive and control tools require their own compatible model and input mapping.

## Specialist applicability

| Capability | Inputs and scope | Evidence |
| --- | --- | --- |
| Signal exploration and quality | Any saved dataset with a time basis. Align distinct clocks explicitly. | Trends, gaps, coverage and observed samples. |
| Anomaly detection, replay and regimes | Either plant or measured history. Use comparable normal periods and compatible variables, units and model version for independent training. Regime models require labelled normal windows. | Detector scores, thresholds, alarm episodes and regime assignments. |
| Alarm correlation and incidents | Measured intervals, compatible chronology and linked results. | Grouped episodes, hypotheses and reports. |
| Sensor diagnostics | Statistical tests use numeric measurements. Physical residuals use the hydraulic sensor and equation contract. | Sensor-health indicators and competing process explanations. |
| Fault investigation | Plant studies use independent, clock-aligned trajectories for the two hypotheses implemented by each plant. | Estimated onset and whitened residuals through the displayed cutoff. |
| Calibration and estimation | Hydraulic specialist tools require a supported model, physical measurements or explicit mappings, and parameter or state bounds. | Calibration revisions, validation residuals and estimated trajectories. |
| PI and MPC | Plant studies execute the declared native-loop or bounded-jacket intervention. The hydraulic control workspace compares its own model's PI and MPC under matched settings. | Tracking, command travel and sampled limits. |
| Sensor placement and experiment design | Hydraulic specialist model, candidate measurements and feasible actuation. | Rank, distinguishability, information metrics and recommended excitation. |
| Predictive maintenance | A meaningful degradation indicator, history and explicit threshold. | RUL estimate and uncertainty. |
| Safety, resilience and recovery | Measured limit assessment uses declared units and bounds. Forecasting and recovery simulations require the supported hydraulic dynamics and state/actuator limits. | Excursions, forecast margins and paired recovery outcomes. |
