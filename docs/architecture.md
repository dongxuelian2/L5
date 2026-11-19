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

The [plant catalog](../l5/plants.py) defines the version, equipment, signal keys and units, observation clock, run settings, and reference trajectories. Each scenario declares its operating plot channels. `POST /api/workspaces/{id}/plants/runs` reserves a run using its workspace, scenario, configuration, and model version. The worker integrates one trajectory per role. Fortran streams native measurements through standard output, and the CSTR solver supplies samples directly to the worker. The observations endpoint serves a growing numerical checkpoint, then the saved evaluation dataset. `?view=operating` selects the scenario's plot channels. The default response uses the detector channels.

The worker saves time, measurements, observation flags and model-specific states as NumPy arrays. SQLite records the plant, configuration, seed, event definition and each dataset's role. Independent normal fit and calibration use separate random streams. The experiment service checks measurement identity, units and model version before scoring. A separate deterministic identity links the experiment result and counterfactual to the incident.

`GET /api/incidents/{id}/report.html` renders the linked records, diagnosis, and comparison metrics. Plant evidence links carry the plant ID, model version, run ID, selected dataset and signals, diagnosed interval, and saved record IDs. A server restart marks active runs interrupted. A retry reuses complete sources and repeats an incomplete trajectory from seeded initialization. Historical incident and experiment records retain their original snapshots.

## Storage and adapters

`WorkspaceStore` in `l5/workspace.py` coordinates SQLite records and NPZ measurement and state arrays. File imports retain their supplied source CSV or TSV. Numerical runs record an NPZ digest in each experiment snapshot. CSV export builds a table from the observed channels on request. NPZ download includes the state and observation arrays when present.

OPC UA acquisition stores observed timestamps and quality events. Recorded sources participate in data and monitoring workflows. A native simulation carries its plant and model version. An operator-entered plant name or published dataset provenance identifies recorded equipment for investigation. Predictive and control tools require their own compatible model and input mapping.

## Specialist applicability

| Capability | Inputs and scope | Evidence |
| --- | --- | --- |
| Signal exploration and quality | Any saved dataset with a time basis. Align distinct clocks explicitly. | Trends, gaps, coverage and observed samples. |
| Anomaly detection, replay and regimes | Either plant or measured history. Use comparable normal periods and compatible variables, units and model version for independent training. Regime models require labelled normal windows. | Detector scores, thresholds, alarm episodes and regime assignments. |
| Alarm correlation and incidents | Measured intervals, compatible chronology and linked results. | Grouped episodes, hypotheses and reports. |
| Sensor diagnostics | Statistical tests use numeric channels with a declared normal reference. Physical residuals use a coupled-tank model and compatible level, flow, and command measurements. | Sensor-health indicators and competing process explanations. |
| Fault investigation | Tennessee Eastman and CSTR plant studies use independent, clock-aligned trajectories for their configured fault hypotheses. | Estimated onset and whitened residuals through the displayed cutoff. |
| Calibration and estimation | Coupled-tank simulations or recorded hydraulic measurements with explicit signal mappings and physical units. | Calibration revisions, validation residuals and estimated trajectories. |
| PI and MPC | Tennessee Eastman perturbs the selected native PI loop. CSTR uses bounded PI on the Reactor 1 jacket. The coupled-tank control workspace compares open loop, PI, and MPC. | Tracking, command travel and sampled limits. |
| Sensor placement and experiment design | Coupled-tank dynamics, candidate measurements, and feasible actuation. | Rank, distinguishability, information metrics and recommended excitation. |
| Predictive maintenance | Recorded or simulated condition history with a meaningful degradation indicator and a failure threshold. | Remaining useful life and uncertainty. |
| Safety | Operating-limit assessment uses numeric histories with declared units and bounds. Physics-based forecasts use the coupled-tank simulation. | Observed excursions and forecast margins. |
| Resilience and recovery | Coupled-tank simulations with configured faults, state bounds, and actuator limits. | Campaign results, reachability maps, and recovery outcomes. |
