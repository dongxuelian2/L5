# L5

L5 is a local workstation for industrial process analysis. Import measurements or run a simulation, compare detectors, investigate alarms, and export the evidence in a standalone report.

![L5 guided investigation of a coupled-tank pump fault](docs/l5-workspace.jpg)

## Core capabilities

| Workflow | Tools |
| --- | --- |
| Measure and monitor | Import CSV or TSV, record read-only OPC UA subscriptions, inspect signal quality, align time series, replay measurements, and compare anomaly detectors across operating regimes. |
| Diagnose and investigate | Examine alarm episodes, correlate related events, compare sensor and process fault explanations, and link supporting evidence to an incident. |
| Simulate and design | Run TripLens and coupled-tank scenarios, compare PI and model predictive control, calibrate digital twins, estimate states, and design sensor layouts and experiments. |
| Evaluate risk and maintenance | Compare fault-injection responses, forecast limit crossings and remaining useful life, and study simulated safety recovery and reachability. |

## Installation

Use Node.js 22.12 or later, npm, and Python 3.12 or later. From the repository root, run the installation commands below.

```sh
npm ci
python3 -m venv .venv
node scripts/python.mjs -m pip install -r requirements.txt
npm run build
```

On Windows, use `py -3.12 -m venv .venv`. The remaining commands are the same in both environments.

## Quick start

```sh
npm run serve
```

Open [L5](http://127.0.0.1:8787), then choose **Open guided demo** to try a built-in case. To work with your own measurements, create a workspace and import a CSV in **Datasets**. Try the motor cooling example to explore clocks, gaps, and transformations across three sources. [Example data](examples/data-foundation/README.md)

Workspaces are stored locally in `data/`. Reopen the application with the same data directory to resume your work.

## Guided demonstration

1. Choose **Load the scenario** to open the coupled-tank case. Compare measured levels with inlet flow and the pump command around the injected fault.
2. Select **Run both detectors** and compare Robust Max-Z with EWMA. Inspect scores, thresholds, alarm delay, and signal contributions.
3. Choose **Create linked incident**. Open the incident timeline and record your hypothesis, evidence, and conclusion.
4. Generate the report and download the HTML. Open it in a browser to review the saved evidence or print to PDF.

The [Streamlit demo](demo/README.md) runs the same detectors on an example or a small CSV and includes a Tennessee Eastman results browser.

## Technical components

The React and TypeScript interface uses a local Python HTTP API. NumPy, pandas, and SciPy support numerical analysis. SQLite stores workspace records alongside CSV and array files. Models, detectors, and specialist workspaces share the same dataset and incident model. OPC UA acquisition uses subscriptions with read-only access. Control, fault injection, and recovery policies run on local simulations.

## Reproducible results

A fixed Tennessee Eastman mode 1 benchmark evaluated nine detection methods on three test runs for each of 20 simulated faults, plus five independent normal runs. These results use normal training configuration A.

| Detector | Faults detected within 30 min | Faults detected during the run | Alarm samples on normal data |
| --- | ---: | ---: | ---: |
| PCA-Q | 19 / 60 | 51 / 60 | 2 / 4,800 |
| Dynamic PCA-Q | 20 / 60 | 54 / 60 | 2 / 4,800 |

## Documentation

- [User guide](docs/user-guide.md) for importing measurements, specialist workspaces, and report export.
- [Architecture](docs/architecture.md) for repository responsibilities, the data pipeline, and persistence.
- [Benchmarks](docs/benchmarks.md) for data sources, experimental protocols, and reproduction commands.
- [MIT license](LICENSE).
