# L5 user guide

## Run a plant investigation

Open **Plants and runs** and select a plant and scenario. Tennessee Eastman requires GNU Fortran on the server path. Expand **Run settings and plant equipment** to change duration, disturbance time, intervention time or the evaluation seed.

Choose **Run investigation**. The measurements panel updates during simulation. The completed study presents the alarm delay, the closest reference trajectory and the intervention metrics. **Export investigation report** downloads HTML. The linked measurements, detection analysis, experiment and incident open with the original run context. Expand **Diagnostic residuals and exports** to download evidence JSON or inspect the intervention trace.

**Saved runs** reopens investigations after navigation or refresh. **Cancel run** preserves the available measurements. **Resume investigation** repeats an interrupted trajectory from initialization and reuses complete sources with the same configuration. For a staged study, choose **Run measurements only** under the run settings, then **Complete investigation** when ready. See the [industrial process guide](industrial-process.md) for model provenance and numerical assumptions.

## Import and prepare measurements

1. Create a workspace and open **Datasets**. Select a CSV or TSV with a unique, nonempty name for each column and inspect the preview. Enter the recorded plant name when known. Choose the time column and its unit, or supply a sample interval. Set the interpretation timezone for local dates.
2. Inspect missing measurements, duplicate times, and acquisition gaps in **Data quality**. Use **Signal catalog** to update engineering units, display names, and device tags. Use transformations to convert values between units.
3. Open **Signal explorer** to browse multiple sources. Absolute clocks share a UTC time base. For a relative clock, select a reference source and set an offset before aligning with other measurements.
4. Use **Transformations** to resample signals, choose missing-value and duplicate policies, or derive values from expressions. Preview the output grid and quality, then save the transformed output as a new dataset. Derived columns retain sample lineage and indicate which values were observed or processed.

The [motor cooling example](../examples/data-foundation/README.md) provides three source clocks and a known temperature rise for a first import and analysis.

## Analyze and monitor

- **Analysis** fits a detector on an earlier, representative normal window and scores a separate window. With the default 70/30 split, the normal window needs at least 30 fit observations and 30 calibration observations. Robust Max-Z accepts a single channel. PCA-based detectors require at least two channels. Choose the alarm persistence and compare scores to the calibrated threshold. Low coverage produces abstention and resets temporal alarm state.
- **Experiments** compares methods and parameter settings across the same window or separate fit, calibration, and test datasets. Add event labels to evaluate detection delay, healthy alarm burden, and coverage. Reopen individual results from the saved experiment.
- **Replay and monitoring** replays measurements in timestamp order with a frozen detector. Start, pause, seek, and inspect alarm peaks. Save an observed alarm to an incident or download the replay prefix as JSON. Missing observations interrupt active alarms and reset temporal state.
- **Operating regimes** trains on labelled normal operating modes. Compare global, single-mode, and regime-aware scores and inspect mode assignments, transitions, and abstentions.

Try replay on a coupled-tank simulation with a tank 1 leak at 60 s, duration 85 s, sample interval 0.2 s, and seed 17. Save the simulation as a dataset. Select the two measured levels, set the normal range to 0–55 s and replay range to 55.2–85 s, then choose Robust Max-Z with alpha 0.05.

## Record live signals

With L5 running, launch the simulated OPC UA server in a second terminal from the repository root:

```sh
node scripts/python.mjs -m examples.opcua_tanks --interval 0.2 --fault sensor_bias --fault-at 30 --bad-quality-at 45 --interrupt-at 55
```

Under **Data**, open **Live data**. Connect anonymously to `opc.tcp://127.0.0.1:4840/l5/tanks/` and choose variables under **Objects → Coupled Tanks**. Start the recording before the simulated fault, observe quality and connection events, then stop and create a dataset. The server continues recording while you visit another workspace view. The dataset uses good numeric measurements at their acquisition times. Resample asynchronous channels explicitly before multichannel analysis.

For equipment, use **Sign & Encrypt**, a trusted server certificate, a client certificate with matching application URI and private key, and a read-only account. Username and password authentication requires **Sign & Encrypt**. L5 keeps credentials in memory and exposes live routes through the loopback interface.

## Investigate and report

- **Sensor health** checks measurement integrity and compares physical hypotheses. Declare redundant or baseline signal relationships for ordinary datasets. For coupled tanks, map the measured levels, flows, and commands to the model and select a normal reference. Inspect residuals, thresholds, and possible sensor or process explanations.
- **Alarm management** applies alarm rules and groups related episodes. Inspect duration, rates, correlation, and contextual signals to choose episodes for investigation.
- **Incidents** organize source data, detector intervals, and investigation notes on a shared timeline. Add a hypothesis, link timestamped evidence, and record a conclusion. Generate standalone HTML from the saved evidence, print the report to PDF in the browser, or export the incident record as JSON.

## Model, control, and estimate

| View | Workflow |
| --- | --- |
| **Process simulation** | Choose TripLens or Coupled-Tank, configure a fault and seed, and simulate the scenario. Compare interventions and save observations as CSV or as a workspace dataset. |
| **Closed-loop control** | Compare open-loop, PI, and model predictive control on a coupled-tank scenario. Inspect tracking error, command saturation, and limit violations on a shared time axis. |
| **Digital twins** | Map calibration measurements and inputs to coupled-tank variables in physical units. Fit selected coefficients within bounds, check rank and residual diagnostics, and score a separate validation interval or dataset. Save a converged twin and export its revision as a model scenario. |
| **State estimation** | Map measured channels and commands to the coupled-tank model. Compare state and sensor-fusion estimates, innovations, and uncertainty under the chosen noise assumptions. |
| **Sensor placement** | Compare sensor subsets using simulated operating points, fault signatures, and noise. Inspect which faults each layout detects or distinguishes. |
| **Experiment design** | Compare bounded pump and valve excitation sequences. Inspect worst-case margins and predicted information before saving a plan for simulation. |

Digital twin predictions use known inputs and estimated parameters. State estimation updates predictions as measurements arrive. Use separate calibration and validation data to evaluate parameter fit on a fresh trajectory.

## Evaluate maintenance and safety

| View | Workflow |
| --- | --- |
| **Predictive maintenance** | Select a condition indicator, its observation window, and a failure limit. Compare forecasts and remaining useful life under the selected trend assumptions. |
| **Process safety** | Choose operating and trip limits. Inspect projected limit crossings and the effects of simulated candidate responses. |
| **Resilience testing** | Compare strategies across a seeded matrix of simulated faults. Inspect recovery times, constraint violations, and worst runs. |
| **Recovery and reachability** | Choose state bounds, a target, and actuator limits. Compute finite-grid recovery and viability maps, then compare policies and fixed emergency actions in nonlinear replay. Grid classifications are numerical approximations within the configured states, inputs, and scenarios. |

Control, recovery, and fault-injection actions execute in simulation. Saved numerical results can be reopened for comparison. Where a view offers dataset export, use it to continue in Signals, Analysis, Experiments, or Incidents.

## Local storage and configuration

L5 binds to `127.0.0.1:8787` by default. Pass options to use a different storage directory or port.

```sh
npm run serve -- --data-dir ./my-l5-data --port 8790
```

Use one L5 server per data directory. Stop the service before backing up or moving the directory so the SQLite database and associated signal and result files stay together. Extracted Tennessee Eastman runs can be shared with the local service through `L5_TEP_CACHE`. See the [benchmark guide](benchmarks.md) for preparing and using those runs.
