"""Nonlinear tank fault signatures and finite, noise-aware sensor design."""

from __future__ import annotations

from itertools import combinations
import math
from time import perf_counter

import numpy as np

from .models.base import finite
from .models.tanks import CoupledTankModel, FAULTS, SIGNALS, integrate

MODEL = CoupledTankModel()
SENSORS = [s for s in SIGNALS if s['key'] not in ('pump', 'valve')]
KEYS = tuple(s['key'] for s in SENSORS)
DEFAULT_NOISE = (.004, .004, .0015, .0015, .0015)
DEFAULT_COST = (1, 1, 3, 2, 2)
FAULT_KEYS = tuple(key for key in FAULTS if key != 'healthy')
HYPOTHESES = {
    **{key: (key,) for key in FAULT_KEYS},
    'pump_and_valve': ('pump_degradation', 'valve_restriction'),
    'pump_and_leak': ('pump_degradation', 'tank_leak'),
}
DEFAULT_INTENSITIES = dict(zip(FAULT_KEYS, (.25, .25, .22, .04)))
OBJECTIVES = ('separation', 'detectability', 'isolability', 'information')
AGGREGATIONS = ('nominal', 'mean', 'worst')
CONDITIONS = {
    'nominal': {},
    'reduced_pump': {'equilibrium': {'pumpRate': .024}},
    'different_levels': {'parameters': {'initial1': 1.31, 'initial2': .81}},
    'valve_opening': {'equilibrium': {'valve': .8, 'pumpRate': .026}},
    'higher_noise': {'noiseScale': 1.8},
    'parameter_shift': {'equilibrium': {'outlet': .033, 'connection': .037, 'area2': 1.12}},
}
MODEL_FIELDS = tuple(f['key'] for f in MODEL.describe()['configFields']
                     if f['group'] in ('Model parameters', 'Initial conditions') or
                     f['key'] in ('leakCoefficient', 'sensorBias', 'integrationStep'))
WEAK_DISTANCE = 2.
PRIOR_SD = .2


def defaults():
    return dict(
        modelId=MODEL.id, horizon=30, step=.5, onset=4, duration=None,
        sensors=[dict(key=key, noise=noise, cost=cost, mode='available')
                 for key, noise, cost in zip(KEYS, DEFAULT_NOISE, DEFAULT_COST)],
        correlations=np.eye(len(KEYS)).tolist(),
        hypotheses=list(HYPOTHESES)[:-1],
        intensities=DEFAULT_INTENSITIES.copy(),
        conditions=[dict(id=key, parameters={}) for key in CONDITIONS],
        budget=4, maxSensors=3, objective='separation', aggregation='worst',
    )


def bounded(value, low, high, message):
    if not finite(value) or not low <= value <= high:
        raise ValueError(message)
    return float(value)


def covariance(sensors, correlations):
    """Construct physical covariance, validating the dimensionless correlation."""
    if (not isinstance(correlations, list) or len(correlations) != len(KEYS) or
            any(not isinstance(row, list) or len(row) != len(KEYS) or
                any(not finite(value) for value in row) for row in correlations)):
        raise ValueError('Enter a numeric 5 × 5 correlation matrix.')
    corr = np.array(correlations)
    if (np.any(np.abs(corr) > 1) or not np.allclose(corr, corr.T, rtol=0, atol=1e-12) or
            not np.allclose(corr.diagonal(), 1, rtol=0, atol=1e-12) or
            np.linalg.eigvalsh(corr)[0] <= 1e-8):
        raise ValueError('Correlations must be symmetric with unit diagonal and positive eigenvalues above 1e-8.')
    sd = np.array([s['noise'] for s in sensors])
    return (corr + corr.T) / 2 * np.outer(sd, sd)


def equilibrium(parameters):
    """No-spill, healthy equilibrium for a forward-flow operating point."""
    c = {**MODEL.describe()['defaults'], **parameters}
    inlet = c['pumpRate'] * c['pumpControl'] / 100
    level2 = (inlet / (c['outlet'] * c['outletValve']))**2
    level1 = level2 + (inlet / (c['connection'] * c['valve']))**2
    if level1 >= c['tankHeight']:
        raise ValueError('The requested equilibrium would overflow.')
    return dict(initial1=level1, initial2=level2)


def normalize(raw):
    base = defaults()
    if not isinstance(raw, dict) or set(raw) - base.keys():
        raise ValueError('Unknown sensor analysis settings.')
    config = {**base, **raw}
    if config['modelId'] != MODEL.id:
        raise ValueError('Choose the coupled-tank process model.')
    for key, low, high, message in [
        ('horizon', 4, 120, 'Prediction horizon must be 4–120 seconds.'),
        ('step', .1, 5, 'Sample interval must be 0.1–5 seconds.'),
        ('onset', 0, 119, 'Fault onset must be 0–119 seconds.'),
        ('budget', 0, 100000, 'Installation budget must be 0–100000.'),
        ('maxSensors', 1, len(KEYS), 'Maximum sensors must be 1–5.'),
    ]:
        config[key] = bounded(config[key], low, high, message)
    if int(config['maxSensors']) != config['maxSensors']:
        raise ValueError('Maximum sensors must be an integer.')
    config['maxSensors'] = int(config['maxSensors'])
    if config['onset'] >= config['horizon'] or math.ceil(config['horizon'] / config['step']) > 300:
        raise ValueError('Use at most 301 samples and place fault onset before the horizon.')
    if config['duration'] is not None:
        config['duration'] = bounded(config['duration'], .01, 120, 'Fault duration must be 0.01–120 seconds.')
    if config['objective'] not in OBJECTIVES or config['aggregation'] not in AGGREGATIONS:
        raise ValueError('Choose a supported objective and operating-condition aggregation.')

    sensors = config['sensors']
    if (not isinstance(sensors, list) or len(sensors) != len(KEYS) or
            any(not isinstance(s, dict) or set(s) != {'key', 'noise', 'cost', 'mode'} or
                s['mode'] not in ('available', 'required', 'excluded') for s in sensors) or
            any(sum(s['key'] == key for s in sensors) != 1 for key in KEYS)):
        raise ValueError('Declare each candidate sensor once with noise, cost and availability.')
    config['sensors'] = [dict(
        key=key, mode=s['mode'],
        noise=bounded(s['noise'], 1e-7, 10, 'Sensor standard deviations must be 1e-7–10.'),
        cost=bounded(s['cost'], 0, 100000, 'Sensor costs must be 0–100000.'),
    ) for key in KEYS for s in sensors if s['key'] == key]
    cov = covariance(config['sensors'], config['correlations'])

    hypotheses = config['hypotheses']
    if (not isinstance(hypotheses, list) or len(hypotheses) < 2 or
            any(not isinstance(key, str) or key not in HYPOTHESES for key in hypotheses) or
            len(set(hypotheses)) != len(hypotheses)):
        raise ValueError('Select at least two distinct fault hypotheses.')
    intensities = config['intensities']
    if not isinstance(intensities, dict) or set(intensities) != set(FAULT_KEYS):
        raise ValueError('Enter intensities for the four fault mechanisms.')
    config['intensities'] = {key: bounded(value, 0, 1, 'Fault intensities must be 0–1.')
                             for key, value in intensities.items()}

    conditions = config['conditions']
    if (not isinstance(conditions, list) or not 1 <= len(conditions) <= len(CONDITIONS) or
            any(not isinstance(c, dict) or set(c) != {'id', 'parameters'} or
                not isinstance(c['id'], str) or c['id'] not in CONDITIONS or
                not isinstance(c['parameters'], dict) or set(c['parameters']) - set(MODEL_FIELDS)
                for c in conditions) or len({c['id'] for c in conditions}) != len(conditions)):
        raise ValueError('Choose distinct operating conditions and supported model parameters.')
    resolved = []
    for condition in conditions:
        preset = CONDITIONS[condition['id']]
        overrides = condition['parameters']
        parameters = {**preset.get('equilibrium', {}), **preset.get('parameters', {}), **overrides}
        steady = {}
        if 'equilibrium' in preset:
            validated = MODEL.validate(parameters)
            steady = equilibrium(validated)
        parameters = {**steady, **parameters}
        validated = MODEL.validate(dict(
            **parameters, fault='healthy', start=config['onset'], fault_duration=config['duration'],
            duration=config['horizon'], step=config['step'], noise=0, seed=0,
        ))
        resolved.append(dict(id=condition['id'], model=validated, noiseScale=preset.get('noiseScale', 1.)))
    return config, resolved, cov


def simulate(model, intensities):
    rows, _ = integrate(model, faults=intensities)
    return np.array([r['t'] for r in rows]), np.array([[r[key] for key in KEYS] for r in rows])


def signatures(model, names, intensities):
    """Time × sensors snapshots with healthy as row zero."""
    times, healthy = simulate(model, {})
    templates = [healthy, *(simulate(model, {key: intensities[key] for key in HYPOTHESES[name]})[1]
                              for name in names)]
    return times, np.stack(templates)


def sensitivities(model, healthy, parameters, step=1e-3):
    """Second-order forward derivatives at zero intensity, inside the physical range."""
    derivatives, stability = [], []
    for key in parameters:
        at_half, at_step, at_double = [simulate(model, {key: h})[1] for h in (step/2, step, step*2)]
        coarse = (4*(at_step - healthy) - (at_double - healthy))/(2*step)
        fine = (4*(at_half - healthy) - (at_step - healthy))/step
        derivatives.append(fine)
        error = np.linalg.norm(fine-coarse, axis=0)
        norms = np.linalg.norm(fine, axis=0)
        stability.append(dict(fault=key, relativeL2=np.divide(
            error, norms, out=np.zeros_like(error), where=norms > 0).tolist(),
            absoluteL2=error.tolist()))
    return np.stack(derivatives), stability


def whiten(values, chol):
    """Apply each sample's marginal covariance inverse square root."""
    shape = values.shape
    return np.linalg.solve(chol, values.reshape(-1, shape[-1]).T).T.reshape(shape)


def separations(templates):
    count = len(templates)
    distances = np.zeros((count, count))
    a, b = np.triu_indices(count, k=1)
    distances[a, b] = np.linalg.norm((templates[a]-templates[b]).reshape(len(a), -1), axis=1)
    return distances + distances.T


def spectrum(matrix):
    values = np.linalg.svd(matrix, compute_uv=False)
    tolerance = float(values[0] * max(matrix.shape) * np.finfo(float).eps)
    rank = int(np.count_nonzero(values > tolerance))
    return dict(singularValues=values.tolist(), tolerance=tolerance, rank=rank,
                condition=float(values[0]/values[-1]) if rank == matrix.shape[1] else None)


def subset_evidence(condition, indices):
    chol = np.linalg.cholesky(condition['cov'][np.ix_(indices, indices)])
    responses = whiten(condition['responses'][..., indices], chol)
    distances = separations(responses)
    sensitivity = whiten(condition['derivatives'][..., indices], chol)
    summary = spectrum(sensitivity.reshape(len(sensitivity), -1).T)
    fault_responses = responses[1:].reshape(len(responses)-1, -1).T
    information = .5*np.log1p((PRIOR_SD*np.array(summary['singularValues']))**2).sum()
    fault_pairs = distances[1:, 1:][np.triu_indices(len(distances)-1, k=1)]
    det, iso = float(distances[0, 1:].min()), float(fault_pairs.min())
    return dict(separation=min(det, iso), detectability=det, isolability=iso,
                information=float(information), distances=distances.tolist(), spectrum=summary,
                signatureSpectrum=spectrum(fault_responses),
                sensitivityNorms=np.linalg.norm(sensitivity, axis=1).tolist())


def enumerate_subsets(sensors, budget, max_count):
    available = tuple(i for i, sensor in enumerate(sensors) if sensor['mode'] != 'excluded')
    required = {i for i in available if sensors[i]['mode'] == 'required'}
    for count in range(1, min(len(available), max_count)+1):
        for subset in combinations(available, count):
            cost = math.fsum(sensors[i]['cost'] for i in subset)
            # Allow roundoff at decimal budget boundaries without a fixed absolute slack.
            if required.issubset(subset) and cost <= budget + 4*math.ulp(budget):
                yield subset, cost


def rank_subsets(rows, objective):
    """Exact winners and cost/nominal/minimax Pareto frontier for an objective."""
    def compare_score(a, b):
        if math.isclose(a, b, rel_tol=1e-12):
            return 0
        return 1 if a > b else -1

    winners = {}
    for aggregation in AGGREGATIONS:
        optimum = max(row[aggregation][objective] for row in rows)
        tied = [row for row in rows if math.isclose(row[aggregation][objective], optimum, rel_tol=1e-12)]
        winners[aggregation] = min(tied, key=lambda row: (row['cost'], len(row['sensors']), row['sensors']))['sensors']

    def dominates(a, b):
        nominal = compare_score(a['nominal'][objective], b['nominal'][objective])
        worst = compare_score(a['worst'][objective], b['worst'][objective])
        return (a['cost'] <= b['cost'] and nominal >= 0 and worst >= 0 and
                (a['cost'] < b['cost'] or nominal > 0 or worst > 0))

    for row in rows:
        row['pareto'] = not any(dominates(other, row) for other in rows)
    return winners


def analyze(raw):
    """Compute each trajectory once per condition, then score every feasible subset."""
    from .sensor_placement_evaluation import cancellation_study, evaluate

    started = perf_counter()
    config, conditions, cov = normalize(raw)
    candidates = list(enumerate_subsets(config['sensors'], config['budget'], config['maxSensors']))
    if not candidates:
        raise ValueError('No sensor subset satisfies the selected count, budget and required sensors.')
    names = ['healthy', *config['hypotheses']]
    parameters = [key for key in FAULT_KEYS if any(key in HYPOTHESES[name] for name in names[1:])]
    for condition in conditions:
        times, templates = signatures(condition['model'], names[1:], config['intensities'])
        derivatives, stability = sensitivities(condition['model'], templates[0], parameters)
        condition.update(times=times, templates=templates, responses=templates-templates[0],
                         derivatives=derivatives, stability=stability, cov=cov*condition['noiseScale']**2)

    subset_results = []
    for subset, cost in candidates:
        scores = [subset_evidence(condition, subset) for condition in conditions]
        subset_results.append(dict(
            sensors=[KEYS[i] for i in subset], cost=cost, conditions=scores,
            nominal={key: scores[0][key] for key in OBJECTIVES},
            mean={key: math.fsum(score[key] for score in scores)/len(scores) for key in OBJECTIVES},
            worst={key: min(score[key] for score in scores) for key in OBJECTIVES},
        ))
    winners = rank_subsets(subset_results, config['objective'])
    quantitative = evaluate(config, conditions[0], cov, names, subset_results, winners)
    cancellation = cancellation_study(cov)
    snapshots = [dict(
        id=c['id'], model=c['model'], noiseScale=c['noiseScale'], covariance=c['cov'].tolist(),
        times=c['times'].tolist(), templates=c['templates'].tolist(), signatures=c['responses'].tolist(),
        sensitivities=c['derivatives'].tolist(), derivativeStability=c['stability'],
    ) for c in conditions]
    return dict(
        format='l5-sensor-placement-v1', modelVersion=MODEL.version, config=config,
        sensors=SENSORS, hypotheses=names, parameters=parameters, conditions=snapshots,
        subsets=subset_results, winners=winners, evaluation=quantitative, cancellation=cancellation,
        weakDistance=WEAK_DISTANCE, sensitivityStep=.001, informationPriorSd=PRIOR_SD,
        runtimeMs=(perf_counter()-started)*1000,
    )
