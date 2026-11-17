"""Run with python -m benchmarks.experiment_design [--trials N].

Freeze both optimized and baseline schedules before solving held-out trajectories
with an adaptive DOP853 integrator. Use a common noise realization across
strategies for each trial, and fit with L5's conservative model.
"""
from __future__ import annotations

import argparse
from itertools import product
import json
from time import perf_counter

import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import least_squares

from l5.experiment_design import (DEFAULT, PARAMETERS, actuator_box, design, input_margins,
                                  observations, schedule_times, simulate, validate_config)
from l5.models.tanks import DEFAULTS, flows

HELD_OUT = {
    'held-out-near': dict(pumpRate=.0315, connection=.038, outlet=.0285),
    'held-out-high-head': dict(pumpRate=.035, connection=.0338, outlet=.027),
    'held-out-low-head': dict(pumpRate=.0255, connection=.049, outlet=.0345),
}
NOISE_SEED = 73021


def reference_path(c, u, parameters):
    """Integrate state and delivery using an independent adaptive ODE solve."""
    config = DEFAULTS | parameters | dict(tankHeight=c['tankHeight'])
    starts = schedule_times(c)
    ends = [*starts[1:], c['duration']]
    sample_times = np.r_[np.arange(0, c['duration'], c['sampleInterval']), c['duration']]
    sample_times = np.unique(sample_times.round(9))
    sensor_values = []
    state = np.array([*c['initialLevels'], 0., 0.])
    low, high = state[:2].copy(), state[:2].copy()
    for i, (start, end) in enumerate(zip(starts, ends)):
        inputs = u[i]

        def rates(t, h):
            f, *_ = flows(config, h[:2], t, None, 0., {}, inputs=inputs)
            inlet, transfer, outlet, leak, spill1, spill2 = f
            return [(inlet-transfer-leak-spill1)/config['area1'],
                    (transfer-outlet-spill2)/config['area2'], outlet, spill1+spill2]

        run = solve_ivp(rates, (start, end), state, method='DOP853', dense_output=True,
                        rtol=2e-10, atol=2e-12, max_step=.25)
        if not run.success:
            raise RuntimeError(run.message)
        state = run.y[:, -1]
        dense_levels = run.sol(np.linspace(start, end, int(np.ceil((end-start)/.025))+1))[:2]
        low, high = np.minimum(low, dense_levels.min(axis=1)), np.maximum(high, dense_levels.max(axis=1))
        audit_times = sample_times[(sample_times >= start) & ((sample_times < end) if i < len(u)-1 else True)]
        if not audit_times.size:
            continue
        for t, heads in zip(audit_times, run.sol(audit_times).T):
            f, *_ = flows(config, heads[:2], t, None, 0., {}, inputs=inputs)
            values = dict(level1=heads[0], level2=heads[1], inlet=f[0], transfer=f[1], outlet=f[2])
            sensor_values.append([values[k] for k in c['noise']])
    return np.array(sensor_values), low, high, state


def reference_metrics(c, u, p):
    y, low, high, state = reference_path(c, u, p)
    scales = np.array([c['nominal'][key] for key in c['parameters']])
    noise = np.array(list(c['noise'].values()))
    # Independently form the whitened Jacobian on the adaptive trajectory.
    h = 3e-5
    jac = np.column_stack([
        ((reference_path(c, u, p | {key: p[key]+h*s})[0] -
          reference_path(c, u, p | {key: p[key]-h*s})[0])/(2*h*noise)).ravel()
        for key, s in zip(c['parameters'], scales)])
    sv = np.linalg.svd(jac, compute_uv=False)
    rank = int(np.count_nonzero(sv > 1e-7*sv[0]))
    full_rank = rank == len(scales)
    margins = dict(levelLower=low-np.array(c['levelMin']), levelUpper=np.array(c['levelMax'])-high,
                   overflow=c['tankHeight']-high, delivery=np.array([state[2]-c['minDelivery']]))
    if c['terminalLevelTolerance'] is not None:
        margins['terminalLevel'] = c['terminalLevelTolerance']-np.abs(state[:2]-c['initialLevels'])
    inp, movement, _ = input_margins(c, u)
    failed = [k for k, values in (margins | inp).items() if min(values) < -1e-6]
    return y, dict(rank=rank, minWhitenedSingularValue=float(sv[-1]), minInformationSingularValue=float(sv[-1]**2),
                   logDet=float(2*np.log(sv).sum()) if full_rank else None,
                   condition=float((sv[0]/sv[-1])**2) if full_rank else None,
                   violations=failed, margins={k: v.tolist() for k, v in margins.items()},
                   actuatorVariation=movement, delivered=float(state[2]), spilled=float(state[3]))


def recovery(c, u, truth, y, draws):
    keys = c['parameters']
    nominal = np.array([c['nominal'][k] for k in keys])
    known = {k: c['nominal'][k] for k in c['nominal'] if k not in keys}
    lower = np.array([max(PARAMETERS[k]['min'], 1e-4) for k in keys])/nominal
    upper = np.array([PARAMETERS[k]['max'] for k in keys])/nominal
    true = np.array([truth[k] for k in keys])/nominal
    sigma = np.array(list(c['noise'].values()))
    errors, failed, calls = [], 0, 0
    for draw in draws:
        noisy = y + sigma*draw

        def residual(x):
            p = known | dict(zip(keys, (x*nominal).tolist()))
            predicted = observations(simulate(c, u, p, refine=True)[0], c['noise'])
            return ((predicted-noisy)/sigma).ravel()

        fit = least_squares(residual, np.ones(len(keys)), bounds=(lower, upper), diff_step=1e-4, max_nfev=45)
        failed += not fit.success
        calls += fit.nfev
        errors.append(((fit.x-true)/true).tolist())
    relative = np.asarray(errors)
    return dict(relativeRmse=float(np.sqrt(np.mean(relative**2))),
                perParameterRmse=dict(zip(keys, np.sqrt(np.mean(relative**2, axis=0)).tolist())),
                trialRmse=np.sqrt(np.mean(relative**2, axis=1)).tolist(), failed=failed, functionEvaluations=calls)


def grid_reference():
    """Exhaust a declared 11x11 lattice, then compare the continuous solver."""
    c = validate_config(dict(duration=16., controlInterval=8., segments=2, scenarios=[], minDelivery=0.,
                             initialInput=[90., .8], noise={'inlet': .001, 'transfer': .001, 'outlet': .001},
                             objective='E'))
    _, lo, hi, reach = actuator_box(c)
    bounds = np.maximum(lo[-1], lo[0]-reach), np.minimum(hi[-1], hi[0]+reach)
    mesh = [np.linspace(lower, upper, 11) for lower, upper in zip(*bounds)]
    continuous = design(c)['designs'][-1]
    u = np.array([[r['pump'], r['valve']] for r in continuous['schedule']])
    # Grid points use independent adaptive integration with the same physical limits.
    feasible = []
    for values in product(*mesh):
        candidate = np.vstack([c['initialInput'], values])
        _, metrics = reference_metrics(c, candidate, c['nominal'])
        if not metrics['violations']:
            feasible.append((metrics['minInformationSingularValue'], values))
    val, final = max(feasible)
    _, measured = reference_metrics(c, u, c['nominal'])
    return dict(gridSize=121, gridFeasible=len(feasible), gridBest=val, gridFinalInput=list(final),
                continuous=measured['minInformationSingularValue'], continuousFeasible=not measured['violations'])


def run(trials):
    started = perf_counter()
    result = design(DEFAULT)  # The held-out parameters are never passed to this call.
    c = result['config']
    schedules = {s['id']: np.array([[r['pump'], r['valve']] for r in s['schedule']]) for s in result['designs']}
    rng = np.random.default_rng(NOISE_SEED)
    evaluations = {}
    for name, truth in HELD_OUT.items():
        metrics = {}
        draws = None
        for key, u in schedules.items():
            y, info = reference_metrics(c, u, truth)
            if draws is None:
                draws = rng.standard_normal((trials, *y.shape))
            metrics[key] = info | dict(recovery=recovery(c, u, truth, y, draws))
        comparisons, trial_losses = {}, {}
        for key in ('nominal-optimal', 'robust-optimal'):
            error = metrics[key]['recovery']['relativeRmse']
            baselines = ('constant', 'step', 'multistep', 'prbs')
            comparisons[key] = [other for other in baselines
                                if error >= metrics[other]['recovery']['relativeRmse']]
            samples = np.array(metrics[key]['recovery']['trialRmse'])
            trial_losses[key] = {other: int(np.count_nonzero(samples >= metrics[other]['recovery']['trialRmse']))
                                 for other in baselines}
        evaluations[name] = dict(truth=truth, strategies=metrics, noRecoveryImprovementOver=comparisons,
                                 trialsWithoutImprovement=trial_losses)
    return dict(config=c, trials=trials, noiseSeed=NOISE_SEED, schedules={k: u.tolist() for k, u in schedules.items()},
                optimization=result['solvers'], heldOut=evaluations, exhaustiveReference=grid_reference(),
                elapsedSeconds=perf_counter()-started)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trials', type=int, default=8)
    args = parser.parse_args()
    if not 1 <= args.trials <= 50:
        parser.error('--trials must be between 1 and 50')
    print(json.dumps(run(args.trials), indent=2, allow_nan=False))
