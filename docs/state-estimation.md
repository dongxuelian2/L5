# State Estimation & Sensor Fusion Workspace

Open **State estimation** in a saved L5 workspace. Generate a seeded coupled-tank
experiment, select a saved tank scenario, or map columns from a Dataset. Choose
which level sensors and commanded pump/valve inputs are known. Configure the
initial estimate, P0, Q, R and assumed physical parameters, then **Run estimation
and save**. Runs reopen by their own URL and retain their original inputs.
The editor restores saved settings and pins the saved scenario version for
reruns. Acquisition noise overrides a scenario's built-in sensor noise: physical
trajectories are sampled noiselessly, then the two configured independent sensor
noises and dropout/sampling rules are applied reproducibly.

The shared window and cursor synchronize two level charts, innovations,
posterior residuals, covariance and NIS. Observations are points, including
isolated asynchronous samples. Purple bands show conditional 95% intervals.
The cursor identifies states measured at that instant and states inferred by
the model. Missing observations remain null. Export creates an ordinary Dataset
with estimates, prior predictions, open-loop predictions, observations,
intervals, innovations, residuals, P11/P12/P22, NIS and update dimensionality.
Signal Explorer shows generated values as processed. Select the existing
**Include processed values** policy for downstream detection and experiments.

## Physical and statistical model

The state is x = [h1, h2]ᵀ in meters. The implementation reuses the existing
`l5/models/tanks.py` flow law and conservative, positivity-preserving SSPRK2
step; it does not replace the plant with a linear tank approximation:

```text
q12 = connection · valve · sign(h1-h2) · sqrt(abs(h1-h2))
qin = pumpRate · pumpControl / 100
qout = outlet · outletValve · sqrt(max(0,h2))
si = 0.1 · max(0,hi-tankHeight)^1.5
dh1/dt = (qin - q12 - s1) / area1
dh2/dt = (q12 - qout - s2) / area2
```

Withdrawal limits use available donor volume and preserve transfer mass. The
estimator assumes a healthy plant with explicitly supplied physical parameters.
Fault schedules, simulator initial levels, hidden effective pump efficiency and
hidden valve restriction are never inference parameters. A fault is therefore
model mismatch unless the user explicitly supplies changed physical assumptions.
The nominal controls are used until known timestamped commands become available.

Inputs are right-continuous zero-order holds. A command at time t changes
prediction after t, never the interval ending at t. Integration splits at every
command and observation event, with configurable maximum step (default 0.1 s).
No measurement interpolation, backward filling or smoothing is performed. Rows
without usable measurements execute prediction only. Simultaneous sensors share
one row; duplicate or unordered Dataset timestamps must be resolved beforehand.

For the actual discrete hydraulic step φΔt, the EKF applies:

```text
x− = φΔt(x+, u)
F = ∂φΔt/∂x
P− = F P+ Fᵀ + Q Δt
H = selected rows of I₂, Rm = matching submatrix of R
innovation ν = z - Hx−
S = H P− Hᵀ + Rm
K = P− Hᵀ S⁻¹                      (computed with linear solves)
x+ = x− + Kν
P+ = (I-KH) P− (I-KH)ᵀ + K Rm Kᵀ  (Joseph form)
posterior residual = z - Hx+
```

P0 and R are in m²; **Q is a continuous spectral density in m²/s**, not a
per-observation covariance. Independent additive QΔt increments are applied at
each integration substep; this is a small-step noise discretization. Reduce
`maxStep` when checking sensitivity to that approximation. Full symmetric
2×2 matrices, including cross-covariances, are supported. R must be positive
definite; P0 and Q may be semidefinite. Covariances are symmetrized and only
roundoff-scale negative eigenvalues are repaired. Material indefiniteness or
overflow raises an error rather than silently producing a saved result.

The discrete Jacobian uses centered differences with h = ε max(1,abs(xj)),
default ε = 1e-5 m, and a forward difference at a dry boundary. Tests compare
this with an independently derived SSPRK2 chain-rule Jacobian at two resolutions
and in both flow directions. This differentiates donor limiting and overflow as
well as the square-root law. **At equal heads or a dry outlet the physical law
has no classical derivative.** The finite-resolution secant there is an explicit
approximation, and the run flags reduced confidence. Negative posterior heights
are projected to zero, with a warning that the covariance remains an untruncated
Gaussian approximation. Intervals are not clipped at zero or claimed to describe
boundary probability exactly.

## What can one sensor observe?

At a smooth selected point, define
k = connection·valve/(2√|h1-h2|), d = outlet·outletValve/(2√h2),
and bi = 0.15√max(0,hi-tankHeight). The continuous Jacobian is

```text
A = [ -(k+b1)/area1        k/area1       ]
    [       k/area2      -(k+d+b2)/area2]
H = I₂, [1 0], [0 1], or an empty matrix
O = [H; HA]
```

With Tank 1 alone, det(O) = k/area1. With Tank 2 alone,
det(O) = -k/area2. Either is rank 2 for nonzero coupling at a smooth point.
At the default equilibrium [1.5625, 1], k = 0.0266667 s⁻¹ for unit areas.
Closing the connection valve gives k = 0: a single sensor gives rank 1;
both sensors still directly observe both states. Near-closed valves can retain
rank 2 yet convey very weak practical information over a finite noisy record.

The UI compares all four sensor selections and reports O, A, H, operating-point
drift, singular values, SVD rank tolerance and condition number. The rank tolerance
is max(O.shape)·machine-epsilon·largest-singular-value. A rank deficit, smallest
singular value below 1e-3, or condition number above 1000 flags poor observability.
These last two thresholds are **SI-scale heuristics**, not invariant statistical
tests. Rows of H and HA have different time scales. They are not a finite-horizon
noise-weighted observability Gramian. At non-equilibrium points this is a frozen
local linearization; equal-level or dry-outlet points return no rank, rather than
claiming a derivative exists. None of these calculations proves global nonlinear
observability, identifies unknown parameters or guarantees EKF convergence.

## Reproducible evaluation and honest failure cases

```bash
node scripts/python.mjs -m benchmarks.estimation_evaluate
node scripts/python.mjs -m unittest discover -s tests -p test_estimation.py -v
npm run check
```

[The committed numerical report](../examples/state-estimation/evaluation.json)
contains 33 runs: 11 fixed cases × seeds 11, 29 and 47, each 180 seconds.
The protocol declares P0, Q, R, sensor masks and case overrides before execution;
there is no covariance fitting, search or tuning on these final runs.

| Fixed case | Mean EKF RMSE h1 / h2 (m) | Empirical 95% coverage h1 / h2 |
|---|---:|---:|
| Both sensors, healthy | 0.0019 / 0.0029 | 100.0% / 99.3% |
| Tank 1 only | 0.0030 / 0.0381 | 100.0% / 100.0% |
| Tank 2 only | 0.0488 / 0.0052 | 95.4% / 95.4% |
| Tank 2, dropouts, asynchronous rates, irregular times | 0.0702 / 0.0300 | 99.0% / 100.0% |
| Unmodeled pump degradation, Tank 2 only | 0.2853 / 0.0821 | 18.2% / 21.0% |
| Unmodeled valve restriction, Tank 2 only | 0.7930 / 0.0740 | 18.4% / 17.9% |
| Wrong pump/connection parameters, both sensors | 0.2273 / 0.1176 | 1.3% / 1.2% |
| Small P0, wrong initial estimate, Tank 2 only | 0.1270 / 0.0750 | 29.1% / 40.5% |
| Large P0, same initial estimate and observations | 0.0483 / 0.0045 | 98.4% / 97.8% |
| Biased sensor and overconfident R | 0.0107 / 0.1551 | 10.5% / 2.6% |

Valve restriction makes the inferred Tank 1 estimate **worse than open loop in
all three seeds**. With exactly known initial equilibrium and a correct model,
the open-loop baseline is exact; noisy EKF estimates are worse on both states in
all three seeds. No numerical overflow occurs in this protocol, but mismatch
cases fail to converge and produce severely overconfident intervals. The
report retains those failures, maximum absolute errors and per-seed metrics.

RMSE and MAE use matching hidden physical states only **after inference**.
Direct measurement baselines are scored only where current real measurements
exist, with their own denominators; missing states remain unavailable. Open loop
uses the same initial estimate, assumed model and causal controls as EKF, without
updates. Convergence is the first timestamp after which both errors remain within
0.05 m through run end; null means this never happens over the record.

NIS = νᵀS⁻¹ν has the available measurement dimension, separately grouped as
1 or 2; pointwise 95% chi-square reference bounds are 3.841459 and 5.991465.
NEES = eᵀP⁻¹e has 2 states; singular covariances (minimum eigenvalue ≤ 1e-14)
are excluded and the denominator is reported. Chi-square expectations require
correct Gaussian unbiased model/noise assumptions. Here Q models uncertainty
and robustness while the simulator has deterministic physics: these simulation
statistics are **diagnostics, not evidence of calibrated chi-square behavior**.
Time samples are correlated. Coverage is empirical marginal coverage, not
simultaneous trajectory coverage. An independent 1,200-trial Gaussian prior and
measurement ensemble tests the update's NIS, NEES and 95% calibration under
assumptions that actually justify them. Three example seeds are not population
guarantees.

## Persistence and API

No new dependencies or cloud services are required. SQLite stores immutable
estimation payloads with frozen observation/control rows, SHA-256 fingerprint,
source/scenario version, model version, numerical engine version, explicit
assumptions, filter settings, timestamps, trajectories, scores and comparisons.
Source edits do not alter saved runs. Export uses the existing Dataset writer
and signal registration. Dataset metadata links back to the complete run;
generated values carry an observed=false mask to prevent their reuse as
independent sensor evidence. Workspace deletion cascades to its estimation runs.

| Endpoint | Operation |
|---|---|
| `GET /api/workspaces/:id/estimations` | Saved run index |
| `POST /api/workspaces/:id/estimations` | Estimate and save |
| `GET /api/estimations/:id` | Reopen frozen inputs, result and provenance |
| `POST /api/estimations/:id/dataset` | Save ordinary Dataset; optional name |
| `POST /api/workspaces/:id/estimations/observability` | Independent point/model/sensor analysis |

Minimal run request:

```json
{
  "name": "Tank 2 only",
  "source": {
    "kind": "simulation",
    "simulation": {"duration": 180, "step": 0.5, "seed": 31},
    "noise": [0.02, 0.02], "every": [1, 3],
    "dropout": 0.1, "irregular": true
  },
  "sensors": ["level2"],
  "knownControls": ["pumpControl", "valve"],
  "compareSensors": true
}
```

`source.kind="scenario"` takes `scenarioId` and optional version plus acquisition
settings. `source.kind="dataset"` takes `datasetId` and a mapping from `level1`,
`level2`, `pumpControl`, `valve` to column names (null means unavailable). Dataset
measurements must be meters; commands percent/fraction; time uses Dataset seconds.
Only original measured samples are assimilated. Use `config.initialTime` for an
initial state specified after t=0. The core `estimate(observations, controls,
model=..., config=..., sensors=...)` function has no simulator or truth interface
and can be reused by future MPC/fault diagnosis work without these PRs.

Requests are bounded to 6,000 observation rows, 6,000 control events and 120,000
prediction substeps per filter. Sensor comparison runs four filters on identical
frozen inputs. This workspace intentionally estimates two liquid levels; it does
not classify faults, identify parameters or optimize controls.
