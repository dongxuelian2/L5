# Optimal experiment design

Open a workspace and choose **Experiment design**. Set the initial levels and actuator commands, select the coefficients and observations, enter the sensor standard deviations, and choose **Generate and save experiment**. Use the comparison table to select a schedule, then select a parameter configuration to inspect its trajectory, information matrix, sensitivity curves and constraint margins. Reopen a saved experiment from the selector. Editing a saved definition creates a new snapshot when you run it.

Export the complete snapshot as JSON, or download the selected schedule and observations as CSV. Schedule rows contain an inclusive start, an exclusive end, pump command in percent and connection valve opening as a fraction. The last command remains in effect at the final observation. Publishing uses the identical observation rows and puts the Dataset and its tagged signals in the current workspace. Published observations include seeded synthetic measurement noise and carry the source experiment, strategy, scenario and simulated feasibility in Dataset metadata.

## Model, information and constraints

The coupled-tank model uses its existing conservative SSPRK2 integration. A schedule carries one physical state and one flow balance across the full horizon. The integrator splits steps at command changes. Both stages before a switch use the outgoing command, and measurements at the switch use the incoming command. Tank areas and the outlet valve use the model defaults. Initial water levels are assumed known, and the model runs in healthy operation. The workspace is for offline simulation.

Scheduled changes occur at multiples of the update interval. The first segment uses the initial command, and the last segment can be fixed to a terminal command. The simulation stops exactly at the requested duration. The magnitude, per-update slew (absolute change divided by the control interval) and per-actuator sum of absolute changes are hard constraints. Tank limits and overflow height are checked at every accepted integration substep, including the initial state, with half the configured integration step. Integrated delivered volume has a hard minimum. An optional terminal band constrains both ending levels around their initial levels. The substep checks are numerical estimates of the continuous trajectory. Feasibility permits residuals down to −1e-6 in metres, cubic metres or normalized actuator units. There are no soft movement penalties.

Constant, single-step, multistep and seeded maximal-length PRBS references share the same duration, initial condition, observation cadence and actuator constraints. For unequal fixed endpoints, the constant reference is a linear progression of segment commands between the endpoints. Other references constrain their proposed jumps and blend toward that reference as needed to meet movement budgets. State feasibility is evaluated independently for every reference and parameter configuration. The observation grid includes time zero and the exact endpoint.

The physical coefficients are pump flow (m³/s at 100% command) and the two discharge coefficients (m^(5/2)/s). For coefficient θ the dimensionless coordinate is θ divided by its nominal value, including when evaluating a mismatched configuration. The whitened sensitivity divides each measurement derivative by its configured standard deviation. The assumed covariance is diagonal and constant across independent samples. The information matrix is the whitened sensitivity transposed times itself. Physical-coordinate information divides each matrix entry by the product of the corresponding nominal parameter scales.

- **D-optimality** maximizes the sum of the logs of the scaled information eigenvalues plus a dimensionless 1e-6 diagonal ridge.
- **E-optimality** maximizes the smallest scaled information eigenvalue without a ridge.
- **Worst-case design** maximizes a lower bound on the criterion across nominal and additional design configurations while enforcing state constraints in all of them. Nominal design uses the nominal configuration for optimization. Both schedules are subsequently evaluated on every design configuration.

Scaled central differences use a relative-to-nominal perturbation of 2e-4 for optimization and 1e-4 for reporting. Second-order one-sided differences keep perturbations inside the coefficient ranges at the boundaries. The report compares both perturbations on the finer integration grid. Effective rank uses the unregularized whitened singular values, with a relative cutoff of the larger of 1e-7 and twice the noise-weighted derivative disagreement. Information eigenvalues are the squared singular values. Weak or null parameter directions use the corresponding right singular vectors. Unregularized log determinant, condition and local correlation are reported when full rank is resolved. With inlet flow alone, the connection and outlet coefficients are structurally absent because the inlet equation depends only on the pump coefficient and input. Other observed numerical rank deficiencies describe the selected experiment and local model assumptions.

The constrained local solver starts from the best feasible conventional reference on its design configurations, or the least-violating reference if necessary. It retains its return status, evaluation count, elapsed time, objective, candidate schedule and constraint diagnostics. Final selection compares the solver candidate to the conventional references again using the finer information calculation. If all evaluated candidates fail, the least-violating result remains available as evidence with a failed feasibility status. The evaluation budget limits large designs. [SciPy SLSQP documentation](https://docs.scipy.org/doc/scipy-1.16.2/reference/optimize.minimize-slsqp.html)

## Reproduce the independent evaluation

From the repository root, with the standard Python requirements installed:

```sh
node scripts/python.mjs -m benchmarks.experiment_design --trials 8
```

The command emits JSON with the frozen schedules, three development configurations, solver diagnostics, three held-out truths, independent trajectory metrics, recovery results and a small exhaustive reference. The schedules are frozen before the held-out computations. An adaptive DOP853 solve with dense level checks at intervals of at most 0.025 s supplies the held-out trajectories and independent finite-difference information. Bounded least squares fits all three coefficients from the same nominal starting estimate using L5’s conservative integrator. Each scenario uses eight seeded Gaussian noise realizations paired across strategies. Relative RMSE averages squared fractional errors across trials and all three coefficients.

### Results for the default D-optimal design

The three development configurations used nominal coefficients (0.030, 0.040, 0.030) and scenarios (0.027, 0.046, 0.033) and (0.034, 0.035, 0.027) in pump, connection, outlet order. The robust design raised the worst-case D score from **34.466** for the strongest feasible conventional strategy (PRBS) to **36.571**. The nominal design’s worst-case score was **35.964**, and it exceeded the Tank 1 level limit in the third development configuration. The nominal and robust solves used 103 and 299 distinct model evaluations, respectively, and took about 1 and 9 seconds on the Windows development machine. In the separate 11×11 two-actuator E-optimal reference, the continuous result matched the best grid point at an independently evaluated minimum information eigenvalue of 3,526.09.

All held-out rows had information rank 3. The table gives the smallest whitened sensitivity singular value σmin, natural log determinant and mean relative recovery error in percent. The JSON also contains the smallest information eigenvalue (σmin²), condition numbers, per-actuator variation, constraint margins, individual trials and fit cost.

| Held-out coefficients (pump, connection, outlet) | Strategy | σmin | log det | Recovery RMSE | Simulated violations |
|---|---|---:|---:|---:|---|
| Near (0.0315, 0.038, 0.0285) | Constant | 2.86 | 29.22 | 12.43% | None |
| | Single step | 85.67 | 36.41 | 0.52% | None |
| | Multistep | 41.34 | 34.74 | 1.58% | None |
| | PRBS | 58.05 | 35.31 | 0.84% | None |
| | Nominal design | 98.58 | 36.53 | 0.40% | None |
| | Robust design | 121.16 | 37.26 | 0.51% | None |
| High head (0.035, 0.0338, 0.027) | Constant | 11.27 | 32.32 | 4.51% | None |
| | Single step | 85.83 | 36.63 | 0.72% | Level and overflow |
| | Multistep | 45.33 | 35.18 | 1.68% | None |
| | PRBS | 64.19 | 35.79 | 0.87% | None |
| | Nominal design | 100.05 | 36.79 | 0.59% | Level and overflow |
| | Robust design | 131.57 | 37.63 | 0.31% | Level |
| Low head (0.0255, 0.049, 0.0345) | Constant | 10.45 | 30.93 | 3.55% | None |
| | Single step | 80.10 | 35.64 | 0.49% | None |
| | Multistep | 35.71 | 33.79 | 1.49% | None |
| | PRBS | 47.02 | 34.16 | 1.14% | None |
| | Nominal design | 91.16 | 35.75 | 0.45% | None |
| | Robust design | 98.48 | 36.30 | 0.46% | None |

The robust schedule yielded higher log determinant in all three held-out configurations. Its recovery error exceeded the nominal design on the near and low-head cases. It matched or lost to single step in 4, 1 and 3 of 8 paired trials across the three cases, respectively. On high head, the robust schedule reduced the Tank 1 limit exceedance from 0.138 m to 0.055 m. PRBS had the lowest recovery RMSE among feasible schedules on that held-out case. These results apply to these coefficients, horizons and noise realizations.
