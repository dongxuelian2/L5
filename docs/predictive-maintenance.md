# Predictive Maintenance

## Fit a Dataset and save the result

1. Start the local L5 service and open **Predictive Maintenance** in a workspace. Load the coupled-tank pump benchmark or select a Dataset with an engineering condition measurement.
2. Identify the asset and select a condition signal. Give the indicator a definition, unit, direction of degradation, and failure threshold. Set an earlier operating threshold if the asset has one. Use **Data Transformation** for a derived indicator or a unit conversion.
3. Choose the training interval on the Dataset clock and set a forecast horizon in seconds from the cutoff. Select the linear or stochastic model. If the component has been restored or replaced, record the time of the intervention. Measurements at the reset time count as post-maintenance. A confirmed failure can be entered separately from a noisy threshold crossing.
4. Inspect the measurements, fitted condition, forecast bands and threshold-crossing probabilities. Set a maintenance planning horizon and enter costs and downtime durations in consistent units. Compare continuing, preventive restoration now or at a selected time, and replacement now.
5. Save a session to keep the configuration, model version, numerical forecasts, source Dataset and Signal Catalog IDs. Reopen the session from the workspace or an Incident, and export its forecast and maintenance tables as CSV or its full snapshot as JSON. Run the held-out pump evaluation independently of the selected Dataset.

An anomaly score summarizes departure from a reference process. A degradation indicator measures a defined aspect of equipment condition, such as capacity loss at a known pump command. A RUL forecast combines that indicator with an engineering limit and a future operating assumption. The maintenance decision adds costs and durations to the failure-time distribution. The Tennessee Eastman benchmark measures process faults and detection behavior. Its fault-onset and detection timestamps cannot supply run-to-failure RUL labels.

## Models and uncertainty

The estimator reads timestamped observations with optional load values, operating periods and recorded reset events. Its `ConditionHistory` interface is independent of the acquisition source. Timestamps are in seconds in the workspace. A transformed signal can use time-aligned measurements, unit conversions and derived expressions based on observed inputs. Forward-bin mean, min or max aggregation in a selected signal's lineage is rejected because the bin's timestamp precedes the availability of its data. Missing measurements retain their timestamps. Duplicate timestamps are replicate readings. The requested cutoff is the forecast origin, including when the last finite reading precedes it. A history can end under right censoring, meaning no failure was confirmed by its follow-up time. An earlier cutoff can only use observations and events already available then.

For a decreasing indicator, L5 reverses its sign during the calculation so that both directions reduce to an upper-limit problem. With latent condition `X` and failure limit `b`, RUL is `T = inf{t ≥ 0 : X(cutoff + t) ≥ b}`. Both models assume a future regime comparable to the fitted period. Recorded loads and operating periods help assess that assumption. The forecast uses elapsed time and does not infer a load-response law.

- **Linear trend.** Ordinary least squares estimates a constant drift and an intercept with independent Gaussian measurement errors. The fit propagates joint coefficient and residual-scale uncertainty using Student-t draws. Each sampled line reaches the threshold immediately if its latent cutoff value is already across it, after a positive crossing time if the slope points toward it, or never. The future latent trend has zero process variance in this model.
- **Stochastic drift.** `dX = μ dt + √q dW` describes latent drift and process variation. A measurement is `Yᵢ = X(tᵢ) + εᵢ` with independent Gaussian noise of variance `r`. The Kalman innovation likelihood uses each actual sampling gap. On a clock scaled by the training span and condition scaled by its maximum departure from the first reading, the fit assigns `s² = q + r` an inverse-gamma prior (shape .001, rate 10⁻⁶), assigns drift a normal prior with mean zero and variance `100s²`, and uses a flat initial-level prior. It integrates drift and scale on a discrete uniform grid of log variance ratios `log(q/r)` from −12 to 12, then samples the joint posterior of parameters and cutoff state. The fitted history uses a conditional smoother at the most supported ratio. The forecast averages over the grid. Posterior mass at its outer grid points indicates sensitivity to the numerical search range.

For a positive gap `a` and process variance rate `q > 0`, the conditional first-passage time with nonzero drift is inverse Gaussian with mean `a / |μ|` and shape `a² / q`. For negative drift, the eventual hit probability is `exp(2μa/q)` and the remaining mass is at infinity. Zero drift uses the Lévy limit. The 8,192 draws use a saved seed. The first-passage sampler is continuous in time, so a simulated crossing does not require a chart-grid point. Forecast bands show pointwise 90% intervals for latent future condition. The 90% interval for first passage is separate, as is the interval for the fitted drift parameter. A RUL quantile beyond the displayed forecast horizon is recorded as null. A known threshold failure is represented at zero remaining time. The measurement likelihood uses the observed values without conditioning latent paths on past threshold survival. An uncertain cutoff state can therefore also yield probability mass at zero. Latent extrapolations are unbounded and can extend beyond the physical range of a fractional indicator, particularly on long horizons or after crossing the limit. Insufficient data, unidentified scale or design, and numerical failures have explicit statuses. The operating threshold provides a reference on the plot. RUL is defined by the failure threshold.

## Maintenance economics

The model considers the first event within the planning horizon `H`. A corrective event costs `C_f = corrective cost + downtime rate × corrective duration + failure consequence`. Planned action has its own direct cost plus downtime. For an intervention at offset `s`, failure at or before `s` wins a tie. Given failure CDF `F`, undiscounted expected cost is `C_f F(s) + C_action [1 − F(s)]`. Continuing costs `C_f F(H)`. With continuous discount over the horizon, the failure term integrates discounted cost against the CDF and the intervention term is discounted at `s`.

The comparison searches 61 evenly spaced times across the planning horizon and also evaluates the requested schedule. A cheaper recommendation follows from its expected cost under the saved parameters. Immediate and scheduled restoration and immediate replacement each end the modeled risk for the rest of the planning horizon. The model charges the full event downtime and assumes at most one intervention or failure. Recurrent failures, resource constraints and productivity revenue are outside this cost model. The workspace records decision evidence for people to review.

With zero discount and a corrective event more expensive than preventive restoration, postponing restoration increases exposure without lowering its cost. Under those assumptions, immediate restoration or continuing can dominate. A positive discount rate can make the lower present cost of later work outweigh the additional failure exposure.

## Coupled-tank benchmark

The progressive pump scenario multiplies nominal inlet flow by a time-varying capacity fraction. Command changes affect hydraulic inlet flow and can change the rate of loss. The existing tank solver integrates both levels using the reduced inlet flow and its conservative inter-tank and outlet fluxes. The benchmark keeps the instantaneous `pump_degradation` scenario available under its existing configuration.

To reuse a specific hydraulic configuration, select a saved coupled-tank scenario in **Models** and open **Simulate progressive pump degradation**. The generated Dataset records the source scenario ID and version. The progressive benchmark uses its own wear, sampling and failure settings.

The observed indicator is `1 − measured inlet flow / nominal inlet flow at the recorded command`, dimensionless. This definition assumes a known nominal flow, a linear command-to-flow relationship and no independent inlet restriction. The generator can vary initial capacity, rates, load, noise, sampling jitter, missingness and maintenance resets. It retains a noisy measured signal and pump command for fitting. The latent capacity, generator parameters and crossing time are available to the simulator and the retrospective evaluator. The workspace Dataset exposes measured signals and public scenario provenance.

## Retrospective evaluation

Reproduce the complete report from the repository root:

```bash
node scripts/python.mjs -m l5.prognostic_benchmark
```

The protocol fixes one development seed and uses three independent held-out realizations per scenario. It covers slow and rapid loss, variable load, changing rates, sparse and missing samples, censored follow-up, a restoration with model mismatch, and degradation without observed failure. At each eligible cutoff, the estimator receives only the observed prefix and past maintenance events. The evaluation measures RUL error on known failures, reports how many predictions have both interval limits resolved, and compares horizon probabilities with outcomes using the Brier score and reliability bins. Stability is the absolute revision in the forecast calendar failure time between consecutive cutoffs with an estimate. Maintenance costs compare the recommended policy with continuing, immediate restoration and fixed midpoint restoration.

An observation end or upcoming recorded restoration censors follow-up. Probability and decision comparisons require the full corresponding follow-up window. A censored endpoint never becomes a failure label.

### Results for protocol `coupled-tank-pump-wear-v1`

The evaluation used 24 trajectories and 120 eligible cutoff cases, including 78 cutoff cases with an observed failure before the end of follow-up. Repeated cutoffs on one trajectory are related observations.

| Metric | Linear | Stochastic |
|---|---:|---:|
| Mean absolute error of finite median RUL estimates | 42.0 s (46 cases) | 36.1 s (46 cases) |
| Empirical coverage of bounded 90% RUL intervals | 27/32 | 29/31 |
| Brier score at 60 / 120 / 240 s | .048 / .067 / .136 | .022 / .045 / .127 |
| Mean absolute revision of the calendar failure forecast | 21.5 s | 25.2 s |
| Insufficient-data cases | 4 | 11 |
| Numerical failures | 0 | 0 |
| Recommended policy / continue / immediate / fixed midpoint mean realized cost | 25.89 / 53.51 / 28.00 / 46.95 | 25.37 / 56.28 / 28.00 / 48.36 |

Each model's maintenance policies and baselines use the same eligible cases within that column (101 linear, 94 stochastic). The columns use different sets of cases. Changing-rate RUL error was 110.0 s for linear and 90.8 s for stochastic. In the model-mismatch family, the respective errors were 179.8 s and 131.5 s, with three finite medians and one bounded interval per model. Sparse, missing measurements yielded 4 insufficient fits out of 13 cutoffs for linear and 7 out of 13 for stochastic. In the no-failure family the linear model gave no in-horizon median in 18 cases. The stochastic model gave 16 beyond-horizon results and two insufficient fits. None of these results establishes field accuracy. The benchmark simulates accelerated wear over seconds.
