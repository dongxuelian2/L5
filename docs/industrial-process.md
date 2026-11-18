# Executable industrial plants

**Plants and runs** opens a seeded simulation, an independent monitoring fit, aligned diagnosis and a matched intervention. Each study saves the evaluation, fit, calibration, two fault references and an intervention on the plant observation clock.

## Tennessee Eastman

The closed-loop plant uses the Illinois Mode 1 revision. L5 builds it on first use in the server data directory. The reference driver defines the controller update schedule and the compatible classic signal order. [Plant and reference driver](https://github.com/jkitchin/tennessee-eastman-profbraatz/tree/9a6c8e5fcef4a2850778704e7793c87b0a187005)

### Equations and protocol

The 50 states comprise four sets of eight component inventories and energy, two cooling-water temperatures and twelve actuator positions. The reactor component balance is ṅᵢ = Fᵢ₇ − Fᵢ₈ + Rᵢ. Across all four inventories, internal flows cancel, leaving feeds 1–4, purge, product and reaction. L5 checks the sum of unit derivatives against that external balance at every derivative evaluation. Energy accumulation includes stream enthalpy, reaction heat and heat transfer. The model computes light-component partial pressures from vapor inventories and heavier-component partial pressures from saturation pressure and liquid composition. Valve position follows a first-order lag toward the limited requested opening. [Downs and Vogel](https://doi.org/10.1016/0098-1354(93)80018-I), [governing equations](../simulation/tennessee_eastman/teprob.f)

L5 retains the original one-second Euler step, controller update clocks (3, 360 and 900 s), stochastic measurements and delayed composition analyzers. Each run starts at TEINIT. L5 supplies the seed before initialization. IDV(4) warms reactor coolant by 5 °C. IDV(5) warms condenser coolant by 5 °C. Each default switches immediately after the eight-hour tick. The matched comparison changes the native gain for XMV(10) or XMV(11) at the declared intervention tick with the same state, disturbance and seed. The stripper underflow is the feedback variable for the reference XMV(11) loop. The detector uses the sensor readings and commanded openings.

Each row is stamped by its driver tick, every 180 s from 180 through 86,400 s. The recorder reads the current measurement buffer and updated commands before integration. Each of the 52 stored channels has a native unit and equipment assignment. Columns 1–41 are XMEAS and 42–52 are XMV(1..11). XMV(12), the fixed agitator setting, is outside the classic export. The Rieth reader verifies the three identity fields and original feature names. Rieth elapsed time starts at the first stored sample. Its split, simulationRun, original sample index, seed protocol and controller provenance stay separate from this driver. [Signal dictionary](../simulation/tennessee_eastman/signals.json), [Rieth dataset](https://doi.org/10.7910/DVN/6C3JR1)

### Monitoring and fault evidence

The feature vector contains XMEAS(9,21,22) and XMV(10,11). It spans reactor temperature, the two water outlet temperatures and the two controller commands. Independent 24-hour normal runs fit the mean μ and covariance Σ and calibrate the empirical 99th percentile. With LLᵀ = Σ, the residual z = L⁻¹(y − μ) gives the dimensionless score zᵀz. This removes the dependence of a Euclidean score on the chosen instrument units and includes correlations induced by feedback. Two consecutive exceedances confirm an alarm using data available at that tick. The calibration assumes comparable Mode 1 closed-loop normal variability. Serial dependence makes a per-tick percentile insufficient to predict the event false-alarm rate.

The first confirmed alarm opens a window from 30 minutes before confirmation through the next 57 minutes, inclusive at the three-minute cadence. For each cooling-water hypothesis, L5 searches candidate onset ticks in that pre-alarm history, including the alarm tick. At each observed time t it selects the reference measurement at age t − candidate onset, using the reference simulation's own injection time. The distance is the square root of the mean squared whitened residual norm across the same ticks for every candidate. Normal operation uses the frozen fit center. The minimum distance selects the hypothesis and its sampled onset. Evaluation labels enter only the detection metrics.

In the evaluation run the alarm occurred at 29,160 s. Thirty observations from 27,360 to 32,580 s gave distances of 2.76 for reactor cooling water, 9.94 for condenser cooling water and 8.57 for normal operation. The reactor fit estimated onset at 28,800 s. Temporal ordering retains the transition that a single window mean discards.

Three additional seeds per class produced nine independent trajectories. Each trajectory was evaluated with trigger delays of 3, 9 and 24 minutes, follow-up windows of 15 and 60 minutes, additive independent Gaussian noise of zero or half each channel's training standard deviation, and reference onset errors of −3, 0 and +3 minutes. All 108 comparisons per class selected the simulated class, including 108 forced triggers under normal operation. Maximum onset errors were three minutes for reactor and six minutes for condenser. The 36 settings per trajectory share observations. These counts describe sensitivity across the specified grid. They give neither a calibrated posterior nor a field false-attribution rate. The onset search assumes the disturbance began within its 30-minute history. Each fault template includes one simulated noise realization, while the normal template uses a fitted mean. This difference can favor normal operation for weaker disturbances.

For a separate known-onset comparison, the five-channel whitened signature matrix has singular values 9.75 and 4.36 (condition number 2.24). The single reactor-temperature row has rank one. This is a finite-window distinguishability check for two specified disturbances. Full-state observability and uniqueness among other faults remain open. A sensor bias or a change in heat-transfer effectiveness could also produce a compensating valve motion.

A separate one-hour finite-horizon test perturbs the initial reactor and condenser cooling-water temperatures (states 37 and 38). For each initial coordinate, stack the whitened central-difference output derivatives at 20 sample ticks into a column. A 1 °C state scale gives singular values 8.220 and 2.102 for the five-channel matrix, versus 1.852 and 0.730 for reactor temperature alone. Both matrices resolve two directions. The five-channel set increases sensitivity along the weakest direction by a factor of 2.88. Halving the perturbation from 0.02 to 0.01 °C preserves all four values to three decimals.

On the published d04_te response, reactor and condenser distances were 0.77 and 11.48. On d05_te they were 10.74 and 0.90. These comparisons use the first hour from the known test switch for external validation. The alarm-triggered study estimates onset from measured history. The gain intervention supplies local parameter excitation: centered paired differences at multiplier 1 give post-switch whitened sensitivity norms 103.62 and 104.40 at half-widths 0.02 and 0.01. Pre-switch sensitivity is zero by construction. These are trajectory sensitivities. A confidence interval for the gain would require a temporal noise model.

### Numerical evidence

The unmodified upstream executable and the L5 driver agree on all 8,320 values in the first eight hours at the upstream five-significant-digit recording precision. TEINIT gives 2705.000 kPa gauge, 120.4000 °C reactor temperature and 94.5993 °C coolant outlet temperature. Comparing the first 480 rows to published files, the median absolute channel mean difference in published standard deviations was 0.041 for normal operation, 0.030 for IDV(4) and 0.033 for IDV(5). Published recordings support distribution and signature comparisons. Their generator revisions and noise realizations limit pointwise comparisons.

| Euler step (s) | Mean post-switch valve command (%) | Temperature MAE (°C) | Maximum component balance residual (lbmol/h) |
| ---: | ---: | ---: | ---: |
| 1 | 44.907 | 0.01442 | 2.26 × 10⁻¹³ |
| 0.5 | 44.912 | 0.01373 | 2.27 × 10⁻¹³ |
| 0.25 | 44.860 | 0.01449 | 2.26 × 10⁻¹³ |

Refinement retains controller and switch times. Measurement noise draws occur per derivative evaluation, so each step size changes the stochastic path. These results measure operating-statistic sensitivity. A deterministic convergence order would require matched noise paths.

The evaluation seed gave one detected event in six minutes and zero alarm samples in 160 labelled normal ticks. After injection, reducing gain lowered sampled command travel from 186.35 to 82.79 percentage points and raised temperature MAE from 0.01442 to 0.01790 °C. Both runs stayed below 3000 kPa gauge at all recorded ticks. Sampled command travel is a lower bound on command motion. These results cover one matched intervention in simulation.

The condenser case also detected the event in six minutes with zero alarms in 160 normal ticks and selected the condenser reference. Half gain reduced condenser-valve travel from 493.91 to 247.00 percentage points. Stripper underflow MAE rose from 0.496 to 0.542 m³/h and peak pressure rose from 2785.75 to 2862.70 kPa gauge. Both stayed below 3000 kPa gauge at the observation times.

The updated driver preserves all 101,760 values across four 24-hour runs compiled with GNU Fortran 16.1 on Windows. The comparison uses the driver at Git commit `736fae8` and includes normal operation, IDV(4), paired half-gain IDV(4), and IDV(5). The current tests check arbitrary event ticks, controller switch timing, 50-state recording, conservation and pressure-mean sensitivity at a half-second Euler step. The plant definitions retain the original reactor pressure and temperature limits and the liquid-volume limits for the reactor, separator and stripper.

## Cascaded stirred-tank reactors

### Selection

| Candidate | Reproducible reference and validation cost | Investigation value |
| --- | --- | --- |
| Thermally coupled quadruple tanks | Johansson's experimental geometry, flow splits and right-half-plane zero provide a hydraulic reference. The experiments give no heat-exchange geometry or thermal transients. Adding heaters, thermal interfaces and losses would require separate parameter evidence and measurements. | Hydraulic nonminimum-phase control and thermal transport. |
| Cascaded CSTRs | Ray publishes the once-through Arrhenius cascade. Hedengren's benchmark supplies the dimensional first-vessel model and an independently reproducible equilibrium. An inventory-coordinate solution provides an additional reference for both vessels. | Feed temperature and composition propagate through reaction and transport. Two jacket boundaries allow matched control studies, and the model has a low-order stability and identifiability analysis. |

L5 uses the CSTR cascade. The parameters come from the same first-vessel benchmark for both stages, with stage two fed by stage one and no recycle. The second vessel is a simulation design choice. [Johansson's experimental four tanks](https://people.kth.se/~kallej/papers/quadtank_ieeecst00.pdf) [Ray's cascade model](https://www.eng.uwo.ca/people/aray/Ajay%20Publications%20PDF%20files/A7%20Oscillation%20CEJ%201995.pdf) [Hedengren's benchmark, Tables IV and V](https://gekko.apmonitor.com/prism/uploads/Projects/cache_nonlinear_models_2008.pdf)

### Balances and operating point

Each constant-volume vessel holds a well-mixed liquid. Equal inlet and outlet volume flows close the volume balance, and one mole of A yields one mole of B. Stage 2 receives stage 1 outlet concentrations and temperature. For each vessel and incoming stream (f),

```text
r = k0 × exp(−(E/R)/T) × C_A
V × dC_A/dt = Q × (C_A,f − C_A) − V × r
V × dC_B/dt = Q × (C_B,f − C_B) + V × r
ρ Cp V × dT/dt = ρ Cp Q × (T_f − T) + (−ΔH) × V × r + UA × (T_j − T)
```

| Parameter | Value |
| --- | --- |
| Vessel volume and flow | 0.1 m³ each, 0.1/60 m³/s through both |
| Heat capacity and reaction heat | 239,000 J/(m³·K), 50,000 J/mol released |
| Rate law | `E/R = 8750 K`, `k0 = 1.2 × 10⁹ s⁻¹` |
| Jacket conductance | 50,000/60 W/K per vessel |
| Inlet and jacket boundary | 1000 mol/m³ A, 0 mol/m³ B, 350 K feed, 300 K jackets |

The published first-stage equilibrium is 877.252946 mol/m³ A and 324.475443 K. The second stage equilibrium is 843.060603 mol/m³ A and 310.229023 K. Fixed-step RK4 advances every second. Every ten seconds the recorder adds independent seeded Gaussian noise with standard deviations 0.5 mol/m³ and 0.025 K. Jacket commands and numerical state are saved at that cadence. The control study assumes an ideal jacket boundary and bounds the Reactor 1 command to 285–305 K. The review threshold is 335 K. Concentrations remain nonnegative.

The reduced heat balance checks sign-crossing roots within the no-reaction and full-conversion bounds. The selected cold equilibrium has all continuous-time eigenvalues in the left half-plane. The discretely sampled controller acts on the measured Reactor 1 temperature and applies bounded PI with anti-windup. In the continuous linearization the two jacket inputs give controllability rank four of six. Jacket actuation cannot change total-species inventory. Temperature-only observability also has rank four. The reaction law depends on A and temperature, leaving product-only perturbations invisible to temperature. Separate A/B measurements expose the full state. Two steady temperature observations cannot independently identify both vessels' heat-transfer and kinetic parameters. Parameter identification would require known feed conditions and independent excitation with concentration and temperature responses.

### Reference checks and study results

The numerical test integrates total species, product inventory and sensible plus chemical energy using SciPy DOP853. Reaction cancels within the total-species and combined-energy balances. The warm-feed RK4 trajectory agrees within 8 × 10⁻⁶ in the plotted concentration and temperature coordinates. Reducing the RK4 step from two seconds to one reduces maximum error by more than eightfold. Across both vessels the total concentration remains 1000 mol/m³ within 5 × 10⁻¹² mol/m³. The model captures propagation of the feed step and the slower response in Reactor 2.

The default disturbances start at 600 s and the alternative PI starts at 660 s. Detection selects the four A and temperature channels, fits and calibrates on different healthy seeds, and confirms an alarm after two score exceedances. Both cases produced zero alarms in 61 labelled normal observations and confirmed the event after 20 s. The warm and lean reference signatures ranked first in their respective evaluations. Case counts describe these seeded studies.

| Scenario | Reactor 1 temperature MAE before / with PI | Final A conversion before / with PI |
| --- | ---: | ---: |
| +6 K feed step | 7.0815 / 0.2027 K | 24.22 / 15.70% |
| −8% inlet A | 1.3348 / 0.0502 K | 14.29 / 15.63% |

For the warm feed, peak Reactor 1 temperature fell from 332.30 to 328.59 K with 11.44 K of sampled jacket command travel. The conversion metric uses the final outlet concentration and disturbed inlet concentration. Improved temperature tracking and conversion are separate operating objectives.

## Reproduce

Use the repository's Python environment and GNU Fortran on PATH. The normal UI run works offline. The external comparison also needs the pinned reference checkout.

```sh
git clone https://github.com/jkitchin/tep-rust output/tep-reference
git -C output/tep-reference checkout 0735ad3b5bb7fdd367a8a31da1db8a209dac2a15
node scripts/python.mjs -m benchmarks.tep_process output/tep-reference/reference/data
node scripts/python.mjs -m unittest discover -s tests
```

From **Plants and runs**, a default study and its HTML export take two clicks, zero dataset selections and zero intermediate page changes. A fresh workspace adds one click. Switching to the cascade adds one plant selection. Each underlying measurement, detector, experiment or incident is one navigation from the study and retains its run context.

In a Windows Chrome check, the Tennessee Eastman run showed its first streamed measurements after 2.04 s at the 180 s simulated tick. The worker finished in 4.92 s from reservation to completion. A warm-feed CSTR check showed measurements after 0.62 s and the completed result after 1.73 s measured in the browser. These timings describe individual runs. The browser check exercised report download, detection navigation, refresh, cancellation and resumption.

The Fortran files derive from James Downs and Ernest Vogel's plant and the University of Illinois modified closed-loop code by Evan Russell, Leo Chiang and Richard Braatz. Source and binary redistributions retain the [University of Illinois notice](../simulation/tennessee_eastman/LICENSE-NCSA). The model hash covers both Fortran sources and the signal dictionary. The compiler version and wall-clock runtime are recorded per trajectory.
