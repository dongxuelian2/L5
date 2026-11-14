# Fault detectability and sensor placement

Open a workspace and choose **Sensor placement**. Select the coupled-tank model, the operating conditions and the reference condition. Set the horizon, sample interval, fault timing, hypothesis intensities, and sensor constraints. **Run, optimize and save** creates an immutable study. Select a layout in the chart or table to update the distance matrix, sensitivity results and trajectories. Switch the trajectory view between clean measurements, deviations from healthy operation and representative noisy holdouts. Publishing a trajectory creates a Dataset with engineering units, Signal Catalog IDs and study provenance, then opens it in Signal Explorer. Saved runs can be reopened or exported as full JSON or standalone English or Chinese HTML.

## Model and measurements

The study uses the same conservative SSPRK2 stepper and square-root flow law as Models & Scenarios. It examines five candidate measurements: Tank 1 and Tank 2 levels (m), inlet, inter-tank and outlet flows (m³/s). Pump and valve commands are known inputs. Actual pump delivery and actual transfer flow are measurable only when the corresponding sensors are installed. Each measurement has positive noise and an installation cost. The default standard deviations are 0.004 m per level and 0.0015 m³/s per flow. The default costs in sensor order are 1, 1, 3, 2 and 2.

A hypothesis specifies dimensionless mechanism intensities in [0, 1]. Pump efficiency falls by 0.7 times the pump fault intensity. Effective inter-tank valve opening falls by 0.85 times the valve fault intensity. Leakage adds a square-root discharge from Tank 1. Bias adds an offset to the Tank 2 measurement. The combined cases apply both changes to the same integration, with one shared onset and optional duration. Nominal time settings are a 30 s window, 0.5 s samples and an onset at 4 s. The saved run includes the validated hydraulic parameters, initial levels, commands, integration step, noise covariance, timings and intensities for each condition.

For hypothesis h and condition c, simulate the nonlinear measurement mean μ(c,h,t). Form a signature by subtracting the corresponding healthy trajectory. For layout S, let Σ(S) be the principal submatrix of the physical sensor covariance. The full covariance is D R D, with standard deviations in D and the user-declared positive-definite correlation matrix R. Noise is independent across times. The distance between two templates is:

    d(h,g; c,S)^2 = Σ_t (μ_h(t) − μ_g(t))ᵀ Σ(S)^−1 (μ_h(t) − μ_g(t))

The minimum distance from healthy measures detectability. The minimum over distinct nonhealthy pairs measures isolability. State observability describes reconstruction of internal states from outputs and inputs. The workspace evaluates fault signatures and local fault parameter sensitivity. It does not calculate a state observability matrix.

Distances below 2 are flagged as weak. In an ideal equal-prior two-template Gaussian test, d = 2 gives 15.9% classification error and d = 0 gives 50%. Practical detector performance can differ because of multiple comparisons, unknown intensities, mismatch, or model and noise error. Denser samples add information in this model because temporal independence is assumed. Compare layouts using a shared sampling protocol.

The local Jacobian has time-and-sensor rows and mechanism columns. Each derivative is taken at healthy operation with the second-order one-sided stencil [−3μ(0) + 4μ(h) − μ(2h)]/(2h). The engine compares h = 0.001 with h/2 and stores absolute and relative L2 differences by channel. It reports singular values, numerical rank and full-column-rank condition number for both the whitened local Jacobian and the nonlinear signature matrix. The cutoff is σ_max × max(rows, columns) × machine epsilon. Small step differences check numerical stability near the evaluation point. Nonlinear trajectories supply the finite-intensity comparisons.

## Exact layout search

All nonempty feasible subsets are enumerated after required/excluded sensors, count and budget constraints. Complete trajectories are generated once per operating condition and reused across layouts. The objective can maximize minimum overall separation, minimum detectability, minimum isolability, or local linear-Gaussian information with an independent intensity prior of standard deviation 0.2. The information objective is ½ Σ log(1 + 0.2² σᵢ²) for the whitened Jacobian. Each objective has a reference, arithmetic mean and minimax winner. Score ties within relative tolerance 10⁻¹² prefer lower cost, fewer sensors and stable signal order. Pareto membership compares cost, reference score and worst-case score for the selected objective.

The default options cover equilibrium, reduced pump capacity, changed initial levels, changed valve opening, increased measurement noise and hydraulic parameter shift. At budget 4 with up to three sensors, the default minimum-distance objective has 15 feasible candidates.

| Layout | Cost | Reference d | Mean d | Worst-case d |
|---|---:|---:|---:|---:|
| Tank 1 + Tank 2, reference and minimax winner | 2 | 21.840 | 19.056 | 12.134 |
| Both levels + transfer flow, mean winner | 4 | 21.840 | 19.067 | 12.134 |

A second simulated case uses the pump, valve, leak, pump-plus-valve and pump-plus-leak hypotheses with the nominal, changed-level, changed-valve and parameter-shift conditions. Budget 4 and a two-sensor cap produce a clearer nominal/robust trade-off. The mean winner uses both levels (cost 2, mean 26.315, worst 15.949). The minimax winner uses Tank 1 and inlet flow (cost 4, mean 25.790, worst 23.510). This scenario omits the Tank 2 sensor bias hypothesis. Including that hypothesis can make a layout without Tank 2 exactly blind to bias.

## Cancellation experiment

The independent 12 s cancellation experiment starts at nominal equilibrium and applies a 0.35 pump fault at 2 s. A bounded coarse scan and local refinement minimize Tank 1 RMS over the 2–12 s samples, yielding a valve intensity of approximately 0.3094. Tank 1 RMS is 39.09 mm for pump degradation, 40.16 mm for valve restriction and 0.737 mm when they occur together.

| Measurement layout | Combined vs. healthy d | Combined vs. nearest single-fault d | Ideal detection power at 5% false alarm |
|---|---:|---:|---:|
| Tank 1 | 0.844 | 44.782 | 21.2% |
| Tank 2 | 46.420 | 3.156 | ≈100% |
| Both levels | 46.428 | 46.122 | ≈100% |
| Both levels and all three flows | 56.121 | 51.341 | ≈100% |

The nearest single fault for Tank 2 is valve restriction. Doubling sensor noise halves the distances and reduces their separation to 1.578 while combined-vs-healthy distance remains 23.210. A two-second event and milder intensities also produce weak isolation on Tank 2. Both levels separate the combined fault from healthy and its closest single fault in every default cancellation stress. A small operating shift increases the Tank 1 detection distance to 2.93 and shows how sensitive the cancellation is to the reference condition. The power column is an ideal matched-template reference Φ(d − Φ⁻¹(0.95)), with a known alternative and calibrated Gaussian noise. It does not use the independent evaluation detector.

## Held-out simulated detector

A generalized likelihood-ratio detector takes only observed channels and frozen healthy/fault templates from the chosen reference condition. It thresholds the maximum log-likelihood ratio to healthy. Calibrate the 95th percentile on 2,048 healthy noise windows (seed 1729). Assign a fault only if its lead exceeds log(3) and its residual passes the 99th percentile goodness-of-fit gate from the same healthy calibration noise. The held-out seed is 42139, with 96 trials per truth per cohort. The cohorts are fresh noise, shifted onset plus shorter duration and milder intensity, and hydraulic parameter plus noise mismatch. They enter neither subset scoring nor threshold calibration. The same synthetic observations are sliced into each layout. Pairwise accuracy conditions on the two named templates and counts ambiguous trials in the denominator. Multiway accuracy divides total correctly classified fault windows by all fault windows, including misses and abstentions.

| Layout | Fresh noise detection | Fresh noise classification | Shifted timing classification | Parameter mismatch classification |
|---|---:|---:|---:|---:|
| Tank 1 | 79.8% | 78.3% | 13.3% | 0.2% |
| All five | 100% | 98.8% | 0% | 0% |
| Cost-limited baseline, both levels + transfer | 100% | 98.5% | 0% | 0% |
| Minimax, both levels | 100% | 98.1% | 0% | 0% |

Tank 1 never sees the Tank 2 bias mechanism. Under model mismatch, Tank 1 alone also flags 100% of healthy windows, so its 100% detection in that cohort is uninformative. The two-level and five-sensor layouts detect 80% in that cohort with zero observed false alarms. They abstain on every detection there. Timing changes also make both layouts detect every faulty trial while abstaining on assignment. Clean separation and multiway performance under mismatch answer different questions. No layout here establishes causal identification or an optimal real-plant installation.

## Reproduction and API

Run from the repository root after installing the usual dependencies.

```bash
node scripts/python.mjs -c "import json; from l5.sensor_placement import analyze; print(json.dumps(analyze({}), indent=2))" > sensor-study.json
node scripts/python.mjs -m unittest tests.test_sensor_placement -v
npm run check
```

The reusable numerical functions live in `l5.sensor_placement` and `l5.sensor_placement_evaluation`. The local API prefix is `/api/workspaces/{workspaceId}/sensor-placement`. GET lists run identities and input options. POST with `{name, config}` computes and saves a run. GET `/{runId}` reopens it. GET `/{runId}/analysis.json` or `/{runId}/report.html?lang=en&download=1` exports evidence. POST `/{runId}/dataset` with `{condition, hypothesis, sensors}` publishes clean measurements. Add a saved holdout `cohort` ID for its representative noisy window and use the reference condition. JSON retains trajectories, sensitivity matrices, pair distances, seeds, representative noisy observations and aggregate evaluation metrics. Seeds and model settings regenerate the remaining trial observations. Wall-clock timing varies by host.
