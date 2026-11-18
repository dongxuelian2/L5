# Tennessee Eastman cooling-water study

The pilot follows a 5 °C rise in reactor cooling-water inlet temperature through a closed-loop plant. The temperature controller compensates by opening the cooling valve. Its command carries evidence that temperature tracking alone suppresses.

## Model selection

The study requires executable dynamics, independent reference observations, controllable inputs, reproducible disturbance timing and permission to distribute the runtime. Compatibility with L5 depends on signal identity and sampling as well as file format.

| Candidate | Physical and experimental basis | Integration decision |
| --- | --- | --- |
| Tennessee Eastman | Eight chemical components, four reactions, coupled reactor, condenser, separator, recycle compressor and stripper. Published multi-rate feedback, twenty disturbances and external 52-channel recordings support paired interventions. | Both the executable and L5's independent-run dataset reader implement the classic signal order. Select the Illinois closed-loop Fortran revision. [Plant and reference driver](https://github.com/jkitchin/tennessee-eastman-profbraatz/tree/9a6c8e5fcef4a2850778704e7793c87b0a187005) |
| IWA BSM1 | Activated sludge kinetics, hydraulic transport, settling, influent variation and aeration control support effluent-quality and energy studies. IWA supplies MATLAB implementations. The BSD-3-Clause Python implementation includes steady-state and dynamic checks with Simulink references. | Feasible for wastewater control. A pilot would need a new influent, sensor and fault protocol in L5. BSM1 offers an effluent objective while TEP provides direct compatibility with L5's calibrated monitoring experiments. [IWA models and scientific report](https://github.com/wwtmodels/Benchmark-Simulation-Models), [Python implementation](https://github.com/fau-evt/bsm2-python) |
| SWaT | Instrumented physical water-treatment testbed and recorded actuator/sensor histories. Observations provide empirical process variation. | Recordings alone cannot execute a matched policy intervention. The provider requires separate access requests and prohibits sharing the files. [Testbed](https://www.sutd.edu.sg/itrust/swat/), [access terms](https://www.sutd.edu.sg/itrust/itrust-labs/datasets/terms-of-usage/) |

TEP-Rust provides an independent port and differentials against the original Fortran. Its Python binding adds a Rust build and records a twelfth actuator. TEP Studio implements a modified plant with RK4 and Ricker feedback. Both support valuable comparisons within their own initialization, controller and disturbance conventions. The Fortran pair directly executes the reference equations with one system compiler and no additional Python packages. L5 builds it on first use in the server data directory. [Rust validation and delta register](https://github.com/jkitchin/tep-rust/tree/0735ad3b5bb7fdd367a8a31da1db8a209dac2a15), [Studio validation and control](https://github.com/khalidlabs/tep-studio)

## Equations and protocol

The 50 states comprise four sets of eight component inventories and energy, two cooling-water temperatures and twelve actuator positions. The reactor component balance is ṅᵢ = Fᵢ₇ − Fᵢ₈ + Rᵢ. Across all four inventories, internal flows cancel, leaving feeds 1–4, purge, product and reaction. L5 checks the sum of unit derivatives against that external balance at every derivative evaluation. Energy accumulation includes stream enthalpy, reaction heat and heat transfer. The model computes light-component partial pressures from vapor inventories and heavier-component partial pressures from saturation pressure and liquid composition. Valve position follows a first-order lag toward the limited requested opening. [Downs and Vogel](https://doi.org/10.1016/0098-1354(93)80018-I), [governing equations](../simulation/tennessee_eastman/teprob.f)

L5 retains the original one-second Euler step, controller update clocks (3, 360 and 900 s), stochastic measurements and delayed composition analyzers. Each run starts at TEINIT. L5 supplies the seed before initialization and selects the disturbance explicitly. The evaluation run switches IDV(4) immediately after the 8-hour tick. The intervention applies half of GAIN10 at that switch with the same state, seed and disturbance. The inlet step is scenario truth. Only sensor readings and commanded openings enter the detector. The simulation uses the original measured-variable controller.

Each row is stamped by its driver tick, every 180 s from 180 through 86,400 s. The recorder reads the current measurement buffer and updated commands before integration. Each of the 52 stored channels has a native unit and equipment assignment. Columns 1–41 are XMEAS and 42–52 are XMV(1..11). XMV(12), the fixed agitator setting, is outside the classic export. The Rieth reader verifies the three identity fields and original feature names. Rieth elapsed time starts at the first stored sample. Its split, simulationRun, original sample index, seed protocol and controller provenance stay separate from this driver. [Signal dictionary](../simulation/tennessee_eastman/signals.json), [Rieth dataset](https://doi.org/10.7910/DVN/6C3JR1)

## Monitoring and fault evidence

The feature vector contains XMEAS(9,21,22) and XMV(10,11). It spans reactor temperature, the two water outlet temperatures and the two controller commands. Independent 24-hour normal runs fit the mean μ and covariance Σ and calibrate the empirical 99th percentile. With LLᵀ = Σ, the residual z = L⁻¹(y − μ) gives the dimensionless score zᵀz. This removes the dependence of a Euclidean score on the chosen instrument units and includes correlations induced by feedback. Two consecutive exceedances confirm an alarm using data available at that tick. The calibration assumes comparable Mode 1 closed-loop normal variability. Serial dependence makes a per-tick percentile insufficient to predict the event false-alarm rate.

For diagnosis, L5 compares the mean of the first hour from the first confirmed alarm with two independently simulated one-hour signatures. For each candidate, the distance is the norm of the whitened difference in means. The five-channel whitened signature matrix has singular values 9.75 and 4.36 (condition number 2.24). The single reactor-temperature row has rank one. This is a finite-window distinguishability check for two specified disturbances. Full-state observability and uniqueness among other faults remain open. A sensor bias or a change in heat-transfer effectiveness could also produce a compensating valve motion.

A separate one-hour finite-horizon test perturbs the initial reactor and condenser cooling-water temperatures (states 37 and 38). For each initial coordinate, stack the whitened central-difference output derivatives at 20 sample ticks into a column. A 1 °C state scale gives singular values 8.220 and 2.102 for the five-channel matrix, versus 1.852 and 0.730 for reactor temperature alone. Both matrices resolve two directions. The five-channel set increases sensitivity along the weakest direction by a factor of 2.88. Halving the perturbation from 0.02 to 0.01 °C preserves all four values to three decimals.

On the published d04_te response, reactor and condenser distances were 0.77 and 11.48. On d05_te they were 10.74 and 0.90. These comparisons use the first hour from the known test switch for external validation. In the live study the diagnostic window starts at the alarm. The gain intervention supplies local parameter excitation: centered paired differences at multiplier 1 give post-switch whitened sensitivity norms 103.62 and 104.40 at half-widths 0.02 and 0.01. Pre-switch sensitivity is zero by construction. These are trajectory sensitivities. A confidence interval for the gain would require a temporal noise model.

## Numerical evidence

The unmodified upstream executable and the L5 driver agree on all 8,320 values in the first eight hours at the upstream five-significant-digit recording precision. TEINIT gives 2705.000 kPa gauge, 120.4000 °C reactor temperature and 94.5993 °C coolant outlet temperature. Comparing the first 480 rows to published files, the median absolute channel mean difference in published standard deviations was 0.041 for normal operation, 0.030 for IDV(4) and 0.033 for IDV(5). Published recordings support distribution and signature comparisons. Their generator revisions and noise realizations limit pointwise comparisons.

| Euler step (s) | Mean post-switch valve command (%) | Temperature MAE (°C) | Maximum component balance residual (lbmol/h) |
| ---: | ---: | ---: | ---: |
| 1 | 44.907 | 0.01442 | 2.26 × 10⁻¹³ |
| 0.5 | 44.912 | 0.01373 | 2.27 × 10⁻¹³ |
| 0.25 | 44.860 | 0.01449 | 2.26 × 10⁻¹³ |

Refinement retains controller and switch times. Measurement noise draws occur per derivative evaluation, so each step size changes the stochastic path. These results measure operating-statistic sensitivity. A deterministic convergence order would require matched noise paths.

The evaluation seed gave one detected event in six minutes and zero alarm samples in 160 labelled normal ticks. After injection, reducing gain lowered sampled command travel from 186.35 to 82.79 percentage points and raised temperature MAE from 0.01442 to 0.01790 °C. Both runs stayed below 3000 kPa gauge at all recorded ticks. Sampled command travel is a lower bound on command motion. These results cover one matched intervention in simulation.

## Reproduce

Use the repository's Python environment and GNU Fortran on PATH. The normal UI run works offline. The external comparison also needs the pinned reference checkout.

```sh
git clone https://github.com/jkitchin/tep-rust output/tep-reference
git -C output/tep-reference checkout 0735ad3b5bb7fdd367a8a31da1db8a209dac2a15
node scripts/python.mjs -m benchmarks.tep_process output/tep-reference/reference/data
node scripts/python.mjs -m unittest discover -s tests
```

The browser journey at 1280 × 800 in desktop Chrome used one run click after opening the plant page, zero repeated selections and zero page changes before export. In one Windows run with an empty build and dataset cache, measurements appeared at 3.06 s and the report at 4.89 s. Export required one further click. The check opened the evaluation dataset, returned to the study, reloaded it and read the downloaded JSON.

The Fortran files derive from James Downs and Ernest Vogel's plant and the University of Illinois modified closed-loop code by Evan Russell, Leo Chiang and Richard Braatz. Source and binary redistributions retain the [University of Illinois notice](../simulation/tennessee_eastman/LICENSE-NCSA). The model hash in each report covers both Fortran sources. Compilers and measured runtimes are recorded per trajectory.
