# Coupled-tank reachability and recovery

Open **Safety reachability** in a local L5 workspace. The default study uses the Model Registry's coupled tanks. A versioned Scenario can initialize the hydraulic parameters. Configure the operating and recovery boxes in metres, the model's shared overflow height, pump and valve limits, command samples, grid, and horizon. The target must fit inside the operating box and contain at least one grid point.

Compute the map and select a previous pump/valve command to inspect one slice of the augmented state. Click the map, use its arrow keys, or enter the physical initial levels. The map compares nominal or robust safe recovery, controlled viability, and arrival at a viable target. Hatching marks cells intersecting a geometric boundary or adjacent to a different finite recovery or viability decision. An off-grid initial state in a flagged cell is shown as uncertain. The underlying center classification is retained in the numerical results.

Run nonlinear replay to compare the feedback policy with holding the previous command, choosing low pump with an open valve, or choosing high pump with an open valve. Fixed strategies move toward their setpoint using only admissible command changes. Select a strategy to see its path, signed margin and switch schedule. Use a constant disturbance from the replay selector to stress either a nominal or robust policy. Saving creates a SQLite snapshot with the full model configuration, versioned scenario provenance, finite objective maps, policy, nonlinear evaluations, and optional Incident reference. Export JSON, a trajectory CSV, a printable offline HTML report, or a regular L5 Dataset with signal units and a link to the study. That Dataset can be used as input to an Experiment.

## Finite model

The state is a pair of tank levels and the previous command index. The action alphabet is a Cartesian product of evenly spaced bounded pump and valve commands, with duplicate levels removed. At time kΔ, the new command is held on [kΔ, (k+1)Δ). Its difference from the previous command must be at most the respective configured slew limit times Δ. The initial previous command is selected from the alphabet and represents the setting before the first switch. This is a sampled command-rate model. Physical actuator ramps and lag are outside the model.

The planner integrates the existing hydraulic mass balance with donor-limited SSPRK2, including signed inter-tank transfer, leakage and overflow. It checks level bounds at every accepted integration substep. Safe endpoints map to their nearest grid representative, with exact half-grid ties rounded upward. A rounded endpoint outside the operating box rejects the edge. Grid points range from zero to 108% of the overflow height so the map can show unsafe states beyond the operating region. The graph budget is five million state-action-disturbance slots and 80 million physical integration substeps before expansion over previous commands.

For a set W of grid states, the controlled predecessor consists of states with at least one admissible action whose every outcome is allowed and lands in W. Robust analysis includes nominal behavior and the selected disturbance alternatives, each held for one control interval. The same action applies to every modeled outcome, and the next action may use the newly observed state. The set can switch adversarially between intervals. Compound faults, intermediate disturbance values and within-step changes are outside this disturbance model unless explicitly represented.

- **Safe recovery** starts with target representatives at rank zero and adds their controlled predecessors at each horizon step. The witness uses the minimum grid-step rank, with a secondary preference for the smallest immediate normalized actuator movement. Ties use the action index.
- **Viability** starts with the safe set and repeatedly removes states whose actions all lose a safe successor. The greatest fixed point describes indefinite operation on the finite abstraction.
- **Arrival at a viable target** applies the recovery recurrence to the intersection of the target and the viability fixed point. It requires a safe continuation after arrival.

Nonlinear replay uses the projected state only to select the next command. It evolves the original physical state continuously across switches with half the planning integration step. Replay records all checked samples and stops at the first switch boundary following a violation, reached target, missing witness, or expired horizon. Target entry is assessed at control boundaries. A point can round to a target representative while its true levels remain outside the target. Such a replay can end with no applicable witness. The computed ranks and fixed point are exact for the constructed finite graph. Integration, nearest-point projection, limited actions, and the disturbance set introduce error in the physical interpretation. The reported sets apply to representative points. Whole-cell safety, continuous optimality and plant safety are unverified.

In the numerical JSON, head indices \(i,j\) use row \(iN_2+j\), where \(N_2\) is the number of points on Tank 2's axis. The second index selects the previous command in the exported action alphabet. Rank zero denotes a target state, positive ranks give the minimum number of control steps, and rank −1 denotes no witness within the horizon. Positive ranks have an action index in the policy table. The fixed-point iteration count includes the final comparison with no removals.

## Reproducible benchmark

Run this command from the repository root with the existing requirements installed.

```shell
node scripts/python.mjs -m benchmarks.reachability --output recovery-benchmark.json
```

Add `--trajectories` to retain every independently integrated sample. The fixed held-out suite covers 15 cases, including equilibrium, high levels in each tank, low volume, actuator and hydraulic faults, short-horizon boundary states, an undeclared compound disturbance and a volume-balance impossibility. Grids, settings and cases are fixed in the benchmark script. Adaptive DOP853 trajectories evaluate both policies and the three baselines with the same physical initial state. Margins are sampled at 0.05 s or finer and remain numerical estimates. An optimistic replay failure means a finite positive whose selected policy failed that realization. A false pessimistic decision is counted on nominal cases only when an independently replayed strategy supplies a safe counterexample. The benchmark reports realization-specific witnesses separately because a single disturbance trajectory cannot settle robust reachability. An independent volume upper bound supplies a continuous impossibility reference for the zero-pump case.

| Planner | Level grid | Policy recoveries | Policy runs with a violation | Median time among recoveries | Optimistic replay failures |
| --- | --- | ---: | ---: | ---: | ---: |
| Nominal | 17 × 17 | 8/15 | 1 | 35 s | 2 |
| Robust | 17 × 17 | 8/15 | 0 | 40 s | 1 |
| Nominal | 41 × 41 | 5/15 | 0 | 20 s | 5 |
| Robust | 41 × 41 | 7/15 | 0 | 30 s | 2 |

The hold, low-pump and high-pump strategies recovered 3, 3 and 5 cases, with violations in 2, 9 and 5 cases respectively in each group. The finer grid changed robust viability in the slow-actuation case and changed several replay outcomes. The undeclared compound fault defeated all four planned policies. The zero-pump proof agreed with every grid, and no finite negative was overturned by a baseline witness in this suite. The independent integrator reported no numerical failures. JSON includes each run's movement, effort and violations, grid sensitivity, wall time, transition array bytes and the peak allocation tracked by Python's tracemalloc during graph construction. Timings and peak allocations depend on the host.
