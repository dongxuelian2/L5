"""Local, constrained optimal input design for L5's coupled-tank model."""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import math
from time import perf_counter

import numpy as np
import scipy
from scipy.optimize import minimize
from scipy.signal import max_len_seq

from .models.tanks import CoupledTankModel, FIELDS, SIGNALS, integrate

PARAMETERS = {f['key']: f for f in FIELDS if f['key'] in ('pumpRate', 'connection', 'outlet')}
MEASUREMENTS = {s['key']: s for s in SIGNALS if s['key'] not in ('pump', 'valve')}
ACTUATORS = {s['key']: s for s in SIGNALS if s['key'] in ('pump', 'valve')}
INPUT_SCALE = np.array([100., 1.])
FD_STEP = 2e-4
RANK_RTOL = 1e-7  # On the whitened sensitivity, before squaring its singular values.
D_RIDGE = 1e-6  # Dimensionless; used only in the optimization objective.
FEAS_TOL = 1e-6
MAX_ITERATIONS = 35
STEP_BUDGET = 3_000_000
DEFAULT = dict(
    modelId='coupled-tanks', duration=48., controlInterval=8., segments=6,
    sampleInterval=2., integrationStep=.25, initialLevels=[1.5625, 1.], levelMin=[.1, .1],
    levelMax=[2.4, 2.4], tankHeight=2.5, minDelivery=1.1, terminalLevelTolerance=None,
    initialInput=[100., 1.], terminalInput=None, inputMin=[45., .45], inputMax=[150., 1.],
    maxSlew=[10., .075], maxMovement=[280., 2.], seed=17, objective='D',
    parameters=list(PARAMETERS), noise={'level1': .004, 'level2': .004},
    nominal={'pumpRate': .03, 'connection': .04, 'outlet': .03},
    scenarios=[{'pumpRate': .027, 'connection': .046, 'outlet': .033},
               {'pumpRate': .034, 'connection': .035, 'outlet': .027}],
)


def number(value, key, low, high):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not low <= value <= high):
        raise ValueError(f'{key}: expected a number in [{low}, {high}].')
    return float(value)


def parameter_values(raw):
    if not isinstance(raw, dict) or raw.keys() != PARAMETERS.keys():
        raise ValueError('Specify all three physical coefficients for each parameter configuration.')
    return {k: number(raw[k], k, max(1e-4, f['min']), f['max']) for k, f in PARAMETERS.items()}


def validate_config(raw):
    if not isinstance(raw, dict) or raw.keys() - DEFAULT.keys():
        raise ValueError('Invalid experiment design configuration.')
    c = deepcopy(DEFAULT) | raw
    if c['modelId'] != 'coupled-tanks' or c['objective'] not in ('D', 'E'):
        raise ValueError('Select coupled tanks and either D- or E-optimality.')
    for k, low, high in [('duration', 1, 600), ('controlInterval', .1, 600),
                         ('sampleInterval', .1, 600), ('integrationStep', .025, .25),
                         ('tankHeight', .1, 10), ('minDelivery', 0, 120)]:
        c[k] = number(c[k], k, low, high)
    for k in ('duration', 'controlInterval', 'sampleInterval'):
        c[k] = round(c[k], 9)
    for k, low, high in [('segments', 1, 12), ('seed', 0, 2147483647)]:
        if type(c[k]) is not int or not low <= c[k] <= high:
            raise ValueError(f'{k}: expected an integer in [{low}, {high}].')
    if round((c['segments']-1)*c['controlInterval'], 9) >= c['duration']:
        raise ValueError('The last segment must start before the end of the experiment.')
    samples = math.ceil(c['duration']/c['sampleInterval'])
    if samples > 400 or math.ceil(c['duration']/c['integrationStep']) + samples + c['segments'] > 3000:
        raise ValueError('Use at most 400 sampling intervals and 3,000 integration substeps per model evaluation.')
    for key in ('initialLevels', 'levelMin', 'levelMax', 'initialInput', 'terminalInput',
                'inputMin', 'inputMax', 'maxSlew', 'maxMovement'):
        val = c[key]
        if key == 'terminalInput' and val is None:
            continue
        if not isinstance(val, list) or len(val) != 2:
            raise ValueError(f'{key}: expected two numbers.')
        limits = ([10, 10] if key in ('initialLevels', 'levelMin', 'levelMax') else
                  [150, 1] if key in ('initialInput', 'terminalInput', 'inputMin', 'inputMax') else
                  [15000, 100])
        minimum = [0, .01] if key in ('initialInput', 'terminalInput', 'inputMin', 'inputMax') else [0, 0]
        c[key] = [number(v, key, lo, hi) for v, lo, hi in zip(val, minimum, limits)]
    if any(lo > hi for lo, hi in zip(c['levelMin'], c['levelMax'])):
        raise ValueError('Tank level limits are reversed.')
    if any(lo > hi for lo, hi in zip(c['inputMin'], c['inputMax'])):
        raise ValueError('Actuator limits are reversed.')
    if c['terminalLevelTolerance'] is not None:
        c['terminalLevelTolerance'] = number(c['terminalLevelTolerance'], 'terminalLevelTolerance', 0, 10)
    p, noise, scenarios = c['parameters'], c['noise'], c['scenarios']
    if (not isinstance(p, list) or not p or any(not isinstance(k, str) or k not in PARAMETERS for k in p)
            or len(set(p)) != len(p)):
        raise ValueError('Select one or more unique physical coefficients.')
    if not isinstance(noise, dict) or not noise or noise.keys() - MEASUREMENTS.keys():
        raise ValueError('Select at least one supported measurement.')
    c['noise'] = {k: number(v, k, 1e-6, 1) for k, v in noise.items()}
    if not isinstance(scenarios, list) or len(scenarios) > 4:
        raise ValueError('Provide up to four additional parameter configurations.')
    c['nominal'] = parameter_values(c['nominal'])
    c['scenarios'] = [parameter_values(item) for item in scenarios]
    return c


def schedule_times(c):
    return [round(i*c['controlInterval'], 9) for i in range(c['segments'])]


def actuator_box(c):
    """Return feasible linear reference, box bounds and allowed jumps in physical units."""
    initial, last = np.array(c['initialInput']), c['terminalInput']
    low, high = np.array(c['inputMin']), np.array(c['inputMax'])
    reach = np.array(c['maxSlew'])*c['controlInterval']
    count = c['segments']
    fixed = [initial] if last is None else [initial, np.array(last)]
    if np.any(np.array(fixed) < low) or np.any(np.array(fixed) > high):
        return None
    terminal = fixed[-1]
    difference = np.abs(terminal-initial)
    if np.any(difference > reach*(count-1) + 1e-12) or np.any(difference > np.array(c['maxMovement']) + 1e-12):
        return None
    anchor = np.linspace(initial, terminal, count)
    lower, upper = np.tile(low, (count, 1)), np.tile(high, (count, 1))
    lower[0] = upper[0] = initial
    if last is not None:
        lower[-1] = upper[-1] = terminal
    fixed_channels = (reach == 0) | (np.asarray(c['maxMovement']) == 0)
    lower[:, fixed_channels] = upper[:, fixed_channels] = initial[fixed_channels]
    return anchor, lower, upper, reach


def baselines(c, box):
    anchor, lower, upper, reach = box
    count, middle = c['segments'], (c['segments']+1)//2
    rng = np.random.default_rng(c['seed'])
    # Separate, reproducible maximal-length binary sequences, with seeded phases.
    prbs = np.column_stack([np.roll(max_len_seq(5)[0], int(phase))[:count] for phase in rng.integers(0, 31, 2)])
    indexes = np.arange(count)
    levels = {
        'constant': anchor,
        'step': np.where(indexes[:, None] < middle, anchor[0], np.array([upper[:, 0].max(), lower[:, 1].min()])),
        'multistep': np.where((indexes[:, None]//max(1, count//3)) % 2, c['inputMin'], c['inputMax']),
        'prbs': np.where(prbs, c['inputMax'], c['inputMin']),
    }
    schedules = {}
    for key, desired in levels.items():
        bounded = anchor.copy()
        for i in range(1, count):
            remaining = reach*(count-1-i)
            lo, hi = np.maximum(lower[i], bounded[i-1]-reach), np.minimum(upper[i], bounded[i-1]+reach)
            if c['terminalInput'] is not None:
                lo, hi = np.maximum(lo, anchor[-1]-remaining), np.minimum(hi, anchor[-1]+remaining)
            bounded[i] = np.clip(desired[i], lo, hi)
        movement = np.abs(np.diff(bounded, axis=0)).sum(axis=0)
        minimum = np.abs(anchor[-1]-anchor[0])
        excess = movement-minimum
        # Blend toward a feasible linear reference by convexity of variation.
        ratios = np.divide(np.array(c['maxMovement'])-minimum, excess,
                           out=np.ones(2), where=excess > 1e-12)
        schedules[key] = anchor + np.clip(ratios, 0, 1)*(bounded-anchor)
    return schedules


def simulate(c, inputs, parameters, *, refine=False, monitor=False):
    """Keep observations on the declared grid while resolving every actuator switch."""
    tank = {**parameters, 'fault': 'healthy', 'start': 0, 'noise': 0, 'seed': c['seed'],
            'duration': c['duration'], 'step': min(c['sampleInterval'], 10.),
            'integrationStep': c['integrationStep']/(2 if refine else 1),
            'tankHeight': c['tankHeight'], 'initial1': c['initialLevels'][0], 'initial2': c['initialLevels'][1]}
    model = CoupledTankModel()
    tank = model.validate(tank)
    # The design validator bounds sampling separately from the simulator form.
    tank['step'] = c['sampleInterval']
    schedule = [(t, float(p), float(v)) for t, (p, v) in zip(schedule_times(c), inputs)]
    low, high, low_at, high_at = list(c['initialLevels']), list(c['initialLevels']), [0., 0.], [0., 0.]
    substeps = 0

    def inspect(t, heads):
        nonlocal substeps
        substeps += t > 0
        for i, h in enumerate(heads):
            if h < low[i]:
                low[i], low_at[i] = h, t
            if h > high[i]:
                high[i], high_at[i] = h, t

    rows, physical = integrate(tank, schedule=schedule, inspect_step=inspect if monitor else None)
    return rows, physical, dict(minLevel=low, maxLevel=high, minAt=low_at, maxAt=high_at, substeps=substeps)


def observations(rows, channels):
    return np.array([[r[k] for k in channels] for r in rows])


def sensitivities(c, inputs, parameters, *, refine=False, difference=FD_STEP):
    """Second-order differences with respect to theta / nominal theta."""
    derivatives = []
    baseline = None
    for key in c['parameters']:
        h = difference*c['nominal'][key]
        center = parameters[key]
        minimum = max(1e-4, PARAMETERS[key]['min'])
        maximum = PARAMETERS[key]['max']

        def sample(value):
            rows, _, _ = simulate(c, inputs, parameters | {key: value}, refine=refine)
            return observations(rows, c['noise'])

        if minimum <= center-h and center+h <= maximum:
            difference_values = sample(center+h)-sample(center-h)
        else:
            # Stay inside the model's coefficient range at either edge.
            sign = 1 if center-h < minimum else -1
            if baseline is None:
                baseline = sample(center)
            difference_values = sign*(4*(sample(center+sign*h)-baseline)-(sample(center+sign*2*h)-baseline))
        derivatives.append(difference_values/(2*difference))
    return np.stack(derivatives, axis=-1)


def information(sensitivity, noise, relative_tolerance=RANK_RTOL):
    whitened = (sensitivity/np.asarray(noise)[None, :, None]).reshape(-1, sensitivity.shape[-1])
    # Obtain a complete parameter basis even when there are fewer measurements than parameters.
    _, singular, directions = np.linalg.svd(whitened, full_matrices=whitened.shape[0] < whitened.shape[1])
    singular = np.pad(singular, (0, directions.shape[0]-len(singular)))
    threshold = singular[0]*relative_tolerance
    rank = int(np.count_nonzero(singular > threshold))
    return whitened.T @ whitened, singular, directions, rank, threshold


def objective_value(singular, objective):
    eigenvalues = singular**2
    return float(np.log(eigenvalues+D_RIDGE).sum()) if objective == 'D' else float(eigenvalues[-1])


def input_margins(c, u):
    delta = np.abs(np.diff(u, axis=0))
    movement = delta.sum(axis=0)
    maximum = delta.max(axis=0, initial=0.)
    margins = dict(
        inputLower=((u-np.array(c['inputMin'])).min(axis=0)/INPUT_SCALE).tolist(),
        inputUpper=((np.array(c['inputMax'])-u).min(axis=0)/INPUT_SCALE).tolist(),
        slew=((np.array(c['maxSlew'])*c['controlInterval']-maximum)/INPUT_SCALE).tolist(),
        movement=((np.array(c['maxMovement'])-movement)/INPUT_SCALE).tolist(),
        initialInput=(-np.abs(u[0]-np.array(c['initialInput']))/INPUT_SCALE).tolist(),
    )
    if c['terminalInput'] is not None:
        margins['terminalInput'] = (-np.abs(u[-1]-np.array(c['terminalInput']))/INPUT_SCALE).tolist()
    return margins, movement.tolist(), (maximum/c['controlInterval']).tolist()


def state_margins(c, physical, extrema):
    end = physical[-1]
    margins = dict(
        levelLower=(np.array(extrema['minLevel'])-c['levelMin']).tolist(),
        levelUpper=(np.array(c['levelMax'])-extrema['maxLevel']).tolist(),
        overflow=(c['tankHeight']-np.array(extrema['maxLevel'])).tolist(),
        delivery=[end['delivered']-c['minDelivery']],
    )
    if c['terminalLevelTolerance'] is not None:
        margins['terminalLevel'] = (c['terminalLevelTolerance'] -
                                    np.abs(np.array([end['level1'], end['level2']])-c['initialLevels'])).tolist()
    return margins


def minimum_margin(margins):
    return min(value for values in margins.values() for value in values)


def score(c, inputs, parameters, *, detail=False):
    # Use the finer state trajectory for hard limits, including during optimization.
    rows, physical, extrema = simulate(c, inputs, parameters, refine=True, monitor=True)
    margins = state_margins(c, physical, extrema)
    derivative = sensitivities(c, inputs, parameters, refine=detail)
    noise = list(c['noise'].values())
    if not detail:
        _, singular, _, _, _ = information(derivative, noise)
        return objective_value(singular, c['objective']), [v for pair in margins.values() for v in pair]

    finer = sensitivities(c, inputs, parameters, refine=True, difference=FD_STEP/2)
    discrepancy = (derivative-finer)/np.asarray(noise)[None, :, None]
    norm = np.linalg.norm(finer/np.asarray(noise)[None, :, None])
    disagreement = np.linalg.norm(discrepancy)/max(norm, 1e-30)
    # Treat differentiation disagreement as a numerical resolution floor.
    rank_rtol = max(RANK_RTOL, 2*float(disagreement))
    fim, singular, directions, rank, cutoff = information(finer, noise, rank_rtol)
    covariance = None
    if rank == len(c['parameters']):
        covariance = (directions.T/singular**2) @ directions
        sd = np.sqrt(np.diag(covariance))
        covariance = (covariance/sd[:, None]/sd[None, :]).tolist()
    scales = np.array([c['nominal'][k] for k in c['parameters']])
    weak_directions = directions[rank:] if rank < len(singular) else directions[-1:]
    selected = observations(rows, c['noise'])
    rng = np.random.default_rng(c['seed'])
    measured = selected+rng.standard_normal(selected.shape)*noise
    return dict(
        parameters=parameters, objective=objective_value(singular, c['objective']), rank=rank,
        singularValues=singular.tolist(), eigenvalues=(singular**2).tolist(),
        logDet=float(2*np.log(singular).sum()) if rank == len(singular) else None,
        condition=float((singular[0]/singular[-1])**2) if rank == len(singular) else None,
        matrix=fim.tolist(), physicalMatrix=(fim/scales[:, None]/scales[None, :]).tolist(),
        correlation=covariance, weakDirections=weak_directions.tolist(), rankThreshold=float(cutoff),
        differenceDisagreement=float(disagreement), sensitivity=finer.tolist(),
        structurallyAbsent=[k for k in c['parameters'] if k != 'pumpRate' and list(c['noise']) == ['inlet']],
        times=[r['t'] for r in rows], response={s: [r[s] for r in rows] for s in MEASUREMENTS},
        observations={s: measured[:, i].tolist() for i, s in enumerate(c['noise'])},
        sampledInputs={s: [r[s] for r in rows] for s in ACTUATORS},
        margins=margins, feasible=minimum_margin(margins) >= -FEAS_TOL,
        delivered=physical[-1]['delivered'], spilled=physical[-1]['spilled'],
        massResidual=max(abs(r['massResidual']) for r in physical), extrema=extrema,
    )


def assess(c, name, u, scenarios):
    margins, movement, slew = input_margins(c, u)
    reports = {key: score(c, u, p, detail=True) for key, p in scenarios.items()}
    input_ok = minimum_margin(margins) >= -FEAS_TOL
    failed = [key for key, report in reports.items() if not report['feasible']]
    weakest = min(reports, key=lambda key: reports[key]['objective'])
    return dict(id=name, schedule=[dict(start=t, pump=p, valve=v)
                                  for t, (p, v) in zip(schedule_times(c), u.tolist())],
                duration=c['duration'], inputMargins=margins, inputFeasible=input_ok,
                movement=movement, maxSlew=slew, reports=reports, feasible=input_ok and not failed,
                violatedScenarios=failed, worstScenario=weakest, worstObjective=reports[weakest]['objective'])


class EvaluationBudgetReached(Exception):
    pass


def solve(c, box, starts, scenarios):
    """Solve a local constrained problem; retain candidate evidence on failure."""
    anchor, lower, upper, reach = box
    xlo, xhi = (lower/INPUT_SCALE).ravel(), (upper/INPUT_SCALE).ravel()
    free = xhi > xlo
    base = (anchor/INPUT_SCALE).ravel()

    def unpack(x):
        u = base.copy()
        u[free] = x[:free.sum()]
        return u.reshape(anchor.shape)*INPUT_SCALE

    tic = perf_counter()
    count = 0
    per_simulation = math.ceil(c['duration']/c['integrationStep']) + math.ceil(c['duration']/c['sampleInterval']) + c['segments']
    budget = min(640, STEP_BUDGET//(per_simulation*(3+2*len(c['parameters']))*len(scenarios)))
    best = None

    def actuator_margins(u):
        delta = np.diff(u, axis=0)
        return np.concatenate([((reach-delta)/INPUT_SCALE).ravel(), ((reach+delta)/INPUT_SCALE).ravel(),
                               (np.array(c['maxMovement'])-np.abs(delta).sum(axis=0))/INPUT_SCALE])

    @lru_cache(maxsize=64)
    def evaluate(x):
        nonlocal count, best
        if count >= budget:
            raise EvaluationBudgetReached
        count += 1
        u = unpack(np.asarray(x))
        pairs = [score(c, u, p) for p in scenarios.values()]
        objective, state = np.array([p[0] for p in pairs]), np.array([p[1] for p in pairs]).ravel()
        margin = min(state.min(), actuator_margins(u).min())
        key = (margin >= -FEAS_TOL, min(0., margin+FEAS_TOL), objective.min())
        if best is None or key > best[0]:
            best = (key, u, float(margin))
        return objective, state

    def key(u):
        criterion, margin = evaluate(tuple((u/INPUT_SCALE).ravel()[free]))
        return (min(margin) >= -FEAS_TOL, min(0., min(margin)+FEAS_TOL), min(criterion))

    start_id = max(starts, key=lambda key_id: key(starts[key_id]))
    x0 = (starts[start_id]/INPUT_SCALE).ravel()[free]
    scale = max(1., abs(float(min(evaluate(tuple(x0))[0]))))
    robust = len(scenarios) > 1

    def scores(x):
        return evaluate(tuple(x[:free.sum()]))

    def margins(x):
        criteria, state = scores(x)
        out = [actuator_margins(unpack(x)), state]
        if robust:
            out.append(criteria/scale-x[-1])
        return np.concatenate(out)

    if free.any():
        bounds = list(zip(xlo[free], xhi[free]))
        start = x0
        if robust:
            start = np.r_[x0, min(scores(x0)[0])/scale]
            bounds.append((None, None))
        try:
            result = minimize(
                (lambda x: -x[-1]) if robust else (lambda x: -scores(x)[0][0]/scale),
                start, method='SLSQP', bounds=bounds, constraints=[dict(type='ineq', fun=margins)],
                options=dict(maxiter=MAX_ITERATIONS, ftol=2e-7, eps=1e-5),
            )
            candidate = unpack(result.x)
            diagnostics = dict(success=bool(result.success), status=int(result.status), message=str(result.message),
                               iterations=int(result.nit), functionEvaluations=int(result.nfev),
                               solverObjective=float(-result.fun*scale), solverMinMargin=float(min(margins(result.x))))
        except EvaluationBudgetReached:
            key, candidate, margin = best
            diagnostics = dict(success=False, status=None, message='Model evaluation budget exhausted',
                               iterations=None, functionEvaluations=None,
                               solverObjective=float(key[2]), solverMinMargin=margin)
    else:
        candidate = anchor
        objective, margin = evaluate(tuple(x0))
        diagnostics = dict(success=bool(min(margin) >= -FEAS_TOL), status=None, message='Fixed actuator schedule',
                           iterations=0, functionEvaluations=0, solverObjective=float(min(objective)),
                           solverMinMargin=float(min(margin)))
    return candidate, dict(**diagnostics, start=start_id, candidateEvaluations=count, candidateBudget=budget,
                           elapsedSeconds=perf_counter()-tic, objectiveScale=scale)


def design(raw):
    c = validate_config(raw)
    box = actuator_box(c)
    result = dict(format='l5-excitation-design-v1', config=c, status='completed', designs=[], solvers={},
                  diagnostics=dict(optimizer='SLSQP', scipyVersion=scipy.__version__, maxIterations=MAX_ITERATIONS,
                                   dRidge=D_RIDGE, rankRelativeTolerance=RANK_RTOL, differenceStep=FD_STEP,
                                   auditDifferenceStep=FD_STEP/2, stateIntegrationStep=c['integrationStep']/2,
                                   feasibilityTolerance=FEAS_TOL))
    if box is None:
        return result | dict(status='infeasible-actuators')
    scenarios = {'nominal': c['nominal']} | {f'scenario-{i}': p for i, p in enumerate(c['scenarios'], 1)}
    starts = baselines(c, box)
    reports = {key: assess(c, key, u, scenarios) for key, u in starts.items()}
    result['designs'].extend(reports.values())
    optimizations = {'nominal-optimal': {'nominal': c['nominal']}}
    if len(scenarios) > 1:
        optimizations['robust-optimal'] = scenarios

    for name, targets in optimizations.items():
        u, solver = solve(c, box, starts, targets)
        candidate = assess(c, name, u, scenarios)

        def audited_key(item):
            selected = [item['reports'][k] for k in targets]
            feasible = item['inputFeasible'] and all(s['feasible'] for s in selected)
            margin = min(minimum_margin(item['inputMargins']), *(minimum_margin(s['margins']) for s in selected))
            return (feasible, min(0., margin+FEAS_TOL), min(s['objective'] for s in selected))

        best = max([candidate, *reports.values()], key=audited_key)
        solver.update(auditedStatus='feasible' if audited_key(best)[0] else 'no-feasible-candidate',
                      selected=best['id'] if best is not candidate else 'solver',
                      auditedObjective=audited_key(best)[2],
                      candidateSchedule=candidate['schedule'],
                      candidateInputMargins=candidate['inputMargins'],
                      candidateAudit={k: {field: s[field] for field in ('objective', 'margins', 'feasible')}
                                      for k, s in candidate['reports'].items()})
        result['solvers'][name] = solver
        result['designs'].append(best | {'id': name})
    return result
