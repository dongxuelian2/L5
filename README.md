# L5

**Industrial process analysis, simulation, and investigation in a local workstation.**

L5 turns process measurements into a connected workflow: import or record signals, inspect their quality, run anomaly detectors, investigate alarms, simulate equipment behavior, evaluate control strategies, and export the resulting evidence. Workspaces preserve datasets, configurations, analyses, experiments, and incidents across sessions.

![L5 guided investigation of a coupled-tank pump fault](docs/l5-workspace.jpg)

## What L5 does

L5 brings five areas of industrial analysis into one interface. Each area uses shared datasets and saved results, so an observation can lead directly to a detector comparison, a fault investigation, a model study, or a report.

### 1. Data acquisition and preparation

- **Persistent workspaces and datasets.** Create projects, import CSV/TSV measurements, choose time columns or sampling intervals, preview channels, and reopen saved analyses. Workspaces maintain their records in a local SQLite-backed store.
- **Signal catalog and explorer.** Assign signal identities, engineering units, descriptions, and equipment tags. View multiple sources with synchronized time windows, cursors, and detailed measurements.
- **Time-series quality and transformation.** Inspect missing samples, repeated timestamps, irregular sampling, and acquisition gaps. Align absolute and relative clocks, resample channels, convert units, and calculate derived signals. Preview changes and save the transformed measurements as reusable datasets.
- **OPC UA live acquisition.** Browse industrial variables, subscribe to read-only updates, inspect timestamps and quality flags, record a session, and convert a selected interval into a dataset for downstream analysis.

### 2. Monitoring and anomaly detection

- **Nine detection methods.** Run Robust Max-Z, PCA-Q, PCA-T², Dynamic PCA-Q, Dynamic PCA-T², EWMA, Page CUSUM, finite-window CUSUM, and experimental Adaptive Max-Z. Fit models on a selected normal period, calibrate thresholds, and score observations with the configured algorithm.
- **Interpretable detector results.** Explore score traces, thresholds, alarm intervals, first detection times, observation coverage, and channel contributions alongside the underlying sensor measurements.
- **Experiment comparisons.** Save multiple algorithms, parameter configurations, and training/evaluation windows as experiments. Compare detection behavior, labelled-event metrics, normal-data alarm burden, and individual runs.
- **Process replay.** Replay a recorded dataset on its original time axis, pause or seek through measurements, inspect emerging alarm episodes, and preserve a selected observation prefix as an incident or JSON export.
- **Operating-regime recognition.** Learn named normal operating regimes, inspect mode assignments and transitions, and compare pooled, single-mode, and regime-aware detection on shared timelines.

### 3. Fault diagnosis and incident investigation

- **Sensor health diagnostics.** Examine drift, offset, frozen readings, spikes, dropout, and noise. Compare redundant measurements, baseline relationships, and coupled-tank physical residuals to assess sensor and process explanations.
- **Alarm management.** Configure event rules and correlation criteria, group related alarms, inspect floods and recurring episodes, and review the original evidence behind each group.
- **Saved incidents.** Link datasets, analysis results, alarm intervals, simulations, and investigation notes. Build a synchronized timeline of hypotheses, observations, supporting evidence, and conclusions.
- **Reports and exports.** Generate standalone HTML incident reports with measurements, detector findings, and investigation records. Reopen a report in a browser, print it to PDF, or export structured JSON.

### 4. Simulation, modeling, and control

- **Process simulation.** Run TripLens industrial scenarios and a coupled-tank hydraulic model with configurable faults, interventions, actuator commands, and seeded measurement noise. Save simulated observations for analysis and investigation.
- **Closed-loop control.** Compare held-input operation, PI control, and receding-horizon model predictive control on matched coupled-tank scenarios. Inspect setpoint tracking, control effort, actuator limits, and physical constraint excursions.
- **Digital twin calibration.** Estimate bounded physical parameters from measured levels, flows, and input histories. Explore sensitivity, parameter identifiability, optimizer diagnostics, residuals, and validation predictions. Save calibrated revisions for reuse in simulation.
- **State estimation and sensor fusion.** Reconstruct coupled-tank states from noisy or incomplete observations, inspect innovations and uncertainty estimates, and export estimated trajectories to the data workspace.
- **Fault detectability and sensor placement.** Compare candidate sensor layouts under declared measurement noise and installation budgets. Study fault signatures, distinguishability, and the contribution of each selected measurement.
- **Optimal experiment design.** Compare constrained pump and valve excitation schedules, including stepped inputs and pseudorandom sequences. Evaluate information criteria, operating margins, and candidate experiments before running a simulation.

### 5. Reliability, maintenance, and process safety

- **Predictive maintenance.** Fit condition trends, estimate threshold-crossing horizons and remaining useful life, compare uncertainty ranges, and evaluate maintenance timing choices.
- **Process safety.** Define operational limits, warning bands, and dwell rules. Inspect measured violations and simulated time-to-constraint forecasts under candidate future inputs.
- **Resilience testing.** Compose process, sensor, and acquisition faults; run seeded fault-injection campaigns; compare detector and recovery outcomes; and inspect the worst-performing scenarios.
- **Recovery and reachability.** Compute grid-based viable regions and recovery policies for coupled-tank operating limits, then replay selected policies on the nonlinear model to examine recovery and constraint satisfaction.

## Connected workflows

The specialist tools share data and evidence. Three representative paths show how they work together:

| Starting point | Workflow | Result |
| --- | --- | --- |
| **Recorded process data** | Import measurements → inspect signal quality → calibrate anomaly detection → replay alarms → create an incident | A saved investigation with synchronized curves, evidence, and an exportable report |
| **A process model** | Configure a coupled-tank scenario → compare PI and MPC → examine tracking and constraints → save trajectories | A quantitative comparison of controller behavior under the same simulated conditions |
| **Measurements and engineering questions** | Calibrate physical coefficients → evaluate held-out predictions → estimate states → design sensors or excitation | Reusable model revisions, estimated trajectories, and saved design studies |

The **Guided investigation** example provides the shortest complete route through dataset creation, anomaly detection, incident investigation, and reporting.

## Reproducible results

L5 includes numerical experiments for Tennessee Eastman anomaly detection and coupled-tank analysis. The [benchmark guide](docs/benchmarks.md) records data sources, protocols, commands, and additional results.

### Tennessee Eastman process benchmark

The main study evaluates **nine detectors** on **20 simulated process faults**, using three independent test runs per fault and five normal test runs. Each training configuration comprises 585 detector executions. The expanded evaluation and three A/B/C training configurations together comprise **2,340 executions**.

Selected results for normal training configuration A:

| Detector | Fault runs detected within 30 minutes | Fault runs detected during the run | Alarm samples on five normal runs |
| --- | ---: | ---: | ---: |
| PCA-Q | 19 / 60 | 51 / 60 | 2 / 4,800 |
| Dynamic PCA-Q | 20 / 60 | 54 / 60 | 2 / 4,800 |

The benchmark uses separate normal fit and calibration trajectories, three consecutive threshold exceedances for an alarm, and independently recorded fault trajectories. The A/B/C comparison measures how changing normal training data affects detection and alarm burden.

### Coupled-tank studies

| Study | Representative result |
| --- | --- |
| **Digital twin calibration** | Three 2 mm-noise studies yielded held-out tank-2 RMSE values of **2.83, 2.07, and 2.01 mm**, versus approximately **377 mm** for the nominal model in that protocol. |
| **Closed-loop control** | For a 1 → 1.25 m setpoint step, measured integrated absolute error was **12.3028 m·s** for PI and **9.8953 m·s** for MPC with the same reference information. |
| **Recovery and reachability** | On a 17 × 17 grid, nominal and robust policies each recovered **8 of 15** held-out cases. The robust policy completed those 15 replays within the configured constraints. |

These figures describe the specified simulation and benchmark configurations. The benchmark guide provides the models, evaluation settings, and reproduction commands.

## Installation

Requirements: **Node.js 22.12+**, **npm**, and **Python 3.12+**.

From the repository root, install dependencies and build the frontend:

```sh
npm ci
python3 -m venv .venv
node scripts/python.mjs -m pip install -r requirements.txt
npm run build
```

On Windows, create the environment with `py -3.12 -m venv .venv`. The remaining commands use the same Node.js entry points.

### Run the workstation

```sh
npm run serve
```

Open **[http://127.0.0.1:8787](http://127.0.0.1:8787)**.

Choose **Open guided demo** for an immediate walkthrough, or create a workspace and import measurements under **Datasets**. The [motor cooling example](examples/data-foundation/README.md) demonstrates three data sources with different clocks, acquisition gaps, and transformations.

Workspace records and associated measurements are stored in `data/`. To choose a different directory and port:

```sh
npm run serve -- --data-dir ./my-l5-data --port 8790
```

## Guided investigation: from a fault to a report

1. **Load the scenario.** The seeded coupled-tank example injects inlet-pump degradation. Inspect levels, inlet flow, and pump commands around the fault.
2. **Run both detectors.** Fit Robust Max-Z and EWMA on the measured level signals. Compare their scores, thresholds, alarms, detection delays, and channel contributions.
3. **Create a linked incident.** Save the dataset and detector results as evidence. Inspect the timeline and record a hypothesis, observations, and a conclusion.
4. **Export the investigation.** Generate standalone HTML containing the saved findings and open it in a browser or print it to PDF.

The separate [Streamlit demonstration](demo/README.md) runs detectors on a built-in example or a small uploaded CSV, shows scores and alarm evidence, and includes a browser for recorded Tennessee Eastman results.

## Architecture and storage

L5 combines a **React/TypeScript** interface with a local **Python HTTP API**. NumPy, pandas, and SciPy power the numerical workflows. **SQLite** stores workspace metadata and relationships; CSV and NumPy files hold measurements and numerical results. The simulation, detection, control, and investigation workspaces exchange saved datasets and analysis records.

OPC UA acquisition uses a read-only data connection. Process-control experiments, fault injection, and recovery strategies execute on local models. Generated HTML and JSON files can be opened independently of the workstation.

## Documentation

- **[User guide](docs/user-guide.md)** — Data import, monitoring, the specialist workspaces, incident investigation, reports, and local configuration.
- **[Architecture](docs/architecture.md)** — Application structure, API workflow, storage, and adapters.
- **[Benchmarks](docs/benchmarks.md)** — Tennessee Eastman datasets, calibration studies, simulation protocols, reproduction commands, and measured results.
- **[Streamlit demo](demo/README.md)** — Lightweight detector demonstration and deployment instructions.
- **[MIT license](LICENSE)**.
