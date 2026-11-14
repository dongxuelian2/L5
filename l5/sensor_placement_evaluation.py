"""Predeclared noisy holdouts and a reproducible tank-level cancellation experiment."""

from __future__ import annotations

from itertools import combinations
import math
from statistics import NormalDist
from time import perf_counter

import numpy as np

from .experiment_evaluation import ratio
from .sensor_placement import KEYS, WEAK_DISTANCE, separations, signatures, simulate, whiten

CALIBRATION_SEED = 1729
HOLDOUT_SEED = 42139
CALIBRATION_TRIALS = 2048
TRIALS = 96  # per truth and holdout cohort
ALPHA = .05
FIT_QUANTILE = .99
LOG_LIKELIHOOD_MARGIN = math.log(3)
PAIR_LIMITS = {'weakDistance': WEAK_DISTANCE, 'equalPriorErrorAtWeakDistance':
               .5 * math.erfc(WEAK_DISTANCE / (2 * math.sqrt(2)))}
Z_ALPHA = NormalDist().inv_cdf(1-ALPHA)


def gaussian_noise(rng, cov, shape):
    return rng.standard_normal(shape) @ np.linalg.cholesky(cov).T


def cancellation_study(cov):
    """Fit one valve intensity to minimize Tank 1 RMS, then freeze it across stresses."""
    from .sensor_placement import MODEL

    model = MODEL.validate(dict(duration=12, step=.5, start=2, fault_duration=None, noise=0, seed=0))
    times, healthy = simulate(model, {})
    pump = .35
    after = times >= model['start']

    def error(valve):
        signal = simulate(model, {'pump_degradation': pump, 'valve_restriction': valve})[1]
        return np.linalg.norm((signal-healthy)[after, 0])

    # Bounded one-dimensional search. The objective uses only Tank 1 clean
    # model evidence and is independent of the held-out detector evaluation.
    lo, hi = .0, 1.
    # The smooth interior minimum is bracketed by a reproducible coarse scan.
    grid = np.linspace(lo, hi, 31)
    coarse_index = min(range(len(grid)), key=lambda i: error(grid[i]))
    lo, hi = grid[max(0, coarse_index-1)], grid[min(len(grid)-1, coarse_index+1)]
    for _ in range(28):
        a, b = lo + (hi-lo)/3, hi - (hi-lo)/3
        if error(a) <= error(b):
            hi = b
        else:
            lo = a
    valve = (lo + hi)/2
    names = ['pump_degradation', 'valve_restriction', 'pump_and_valve']
    layouts = [(0,), (1,), (0, 1), (0, 1, 2, 3, 4)]
    variants = [
        ('cancellation_nominal', {}, 1., 1.),
        ('cancellation_noise', {}, 1., 2.),
        ('cancellation_milder', {}, .5, 1.),
        ('cancellation_stronger', {}, 1.5, 1.),
        ('cancellation_short', {'fault_duration': 2.}, 1., 1.),
        ('cancellation_long', {'fault_duration': 7.}, 1., 1.),
        ('cancellation_shift', {'initial1': 1.59, 'initial2': .98, 'pumpRate': .029}, 1., 1.),
    ]
    cases = []
    for identity, changes, severity, noise in variants:
        case_model = {**model, **changes}
        _, templates = signatures(case_model, names,
                                   {'pump_degradation': pump*severity, 'valve_restriction': valve*severity})
        metrics = []
        for indices in layouts:
            chol = np.linalg.cholesky(cov[np.ix_(indices, indices)]) * noise
            distances = separations(whiten((templates-templates[0])[..., indices], chol))
            combined = distances[-1]
            nearest = int(np.argmin(combined[1:-1]))+1
            metrics.append(dict(sensors=[KEYS[i] for i in indices], detectability=float(combined[0]),
                                isolability=float(combined[nearest]), competitor=names[nearest-1],
                                detectionPower=NormalDist().cdf(float(combined[0])-Z_ALPHA),
                                nearestPairError=NormalDist().cdf(-float(combined[nearest])/2),
                                distances=distances.tolist()))
        cases.append(dict(id=identity, model=case_model, noiseScale=noise,
                          pumpIntensity=pump*severity, valveIntensity=valve*severity, metrics=metrics,
                          templates=templates.tolist()))
        if identity == 'cancellation_nominal':
            nominal = templates
    tank1 = np.linalg.norm((nominal[1:]-nominal[0])[:, after, 0], axis=1) / np.sqrt(after.sum())
    return dict(times=times.tolist(), templates=nominal.tolist(), hypotheses=['healthy', *names],
                covariance=cov.tolist(), tank1Rms=tank1.tolist(), cases=cases, alpha=ALPHA, **PAIR_LIMITS)


def log_scores(observed, templates):
    """Centered, whitened flattened trajectories; returns log L(fault)/L(healthy)."""
    offsets = templates[1:]
    return observed @ offsets.T - .5*np.sum(offsets**2, axis=1)


def predictions(observed, templates, threshold, fit_limit):
    scores = log_scores(observed, templates)
    best = np.argmax(scores, axis=1)
    ordered = np.sort(scores, axis=1)
    detected = ordered[:, -1] > threshold
    residual = observed - templates[1:][best]
    plausible = np.sum(residual**2, axis=1) <= fit_limit
    classified = detected & plausible & (ordered[:, -1] - ordered[:, -2] >= LOG_LIKELIHOOD_MARGIN)
    return detected, np.where(classified, best+1, np.where(detected, -1, 0)), scores


def cohort_metrics(templates, observations, names, threshold, fit_limit):
    count = len(names)
    trial_count = observations.shape[1]
    observed = observations.reshape(count*trial_count, -1)
    detected, predicted, scores = predictions(observed, templates, threshold, fit_limit)
    detected = detected.reshape(count, trial_count)
    predicted = predicted.reshape(count, trial_count)
    scores = scores.reshape(count, trial_count, -1)
    confusion = [[int(np.count_nonzero(row == j)) for j in (*range(count), -1)] for row in predicted]
    pairwise = []
    for a, b in combinations(range(1, count), 2):
        # Binary diagnostic among two known alternatives. Misses and ambiguous
        # decisions remain in the denominator. Pair selection is predeclared.
        diff = scores[[a, b], :, a-1] - scores[[a, b], :, b-1]
        ambiguous = np.abs(diff) < LOG_LIKELIHOOD_MARGIN
        correct = (diff[0] >= LOG_LIKELIHOOD_MARGIN).sum() + (diff[1] <= -LOG_LIKELIHOOD_MARGIN).sum()
        pairwise.append(dict(faults=[names[a], names[b]], accuracy=float(correct/(2*trial_count)),
                             ambiguousRate=float(ambiguous.mean())))
    faults = detected[1:]
    accepted = int((predicted[1:] > 0).sum())
    correct = sum(confusion[i][i] for i in range(1, count))
    return dict(
        trialsPerHypothesis=trial_count, falseAlarmRate=float(detected[0].mean()),
        detectionRate=float(faults.mean()), detectionByFault=faults.mean(axis=1).tolist(),
        classificationAccuracy=correct/faults.size, accuracyAmongClassified=ratio(correct, accepted),
        ambiguousRate=float((predicted[1:] == -1).mean()), unclassifiedRate=float((predicted[1:] <= 0).mean()),
        counts=confusion, pairwise=pairwise,
    )


def holdout_cases(config, nominal, cov, names):
    """Freeze the design before generating these distinct scenario cohorts."""
    rng = np.random.default_rng(HOLDOUT_SEED)
    base = nominal['model']
    duration = base['fault_duration']
    timing = max(.01, (base['duration']-base['start'])*.68) if duration is None else max(.01, duration*.72)
    shifted_onset = min(base['start'] + .27*base['step'], (base['start']+base['duration'])/2)
    cases = [
        ('holdout_noise_only', {}, 1., 1.),
        ('holdout_timing', {'start': shifted_onset, 'fault_duration': timing}, .85, 1.),
        ('holdout_mismatch', {'area2': base['area2']*1.07, 'connection': base['connection']*.97,
                             'outlet': base['outlet']*1.025}, 1.08, 1.3),
    ]
    for identity, params, severity, noise in cases:
        model = {**base, **params}
        intensities = {key: min(1., value*severity) for key, value in config['intensities'].items()}
        _, truth = signatures(model, names[1:], intensities)
        observations = truth[:, None] + gaussian_noise(
            rng, cov*(nominal['noiseScale']*noise)**2, (len(names), TRIALS, *truth.shape[1:]))
        yield dict(id=identity, model=model, intensities=intensities, noiseScale=nominal['noiseScale']*noise,
                   representative=observations[:, 0].tolist()), truth, observations


def evaluate(config, nominal, cov, names, rows, winners):
    available = [s['key'] for s in config['sensors'] if s['mode'] != 'excluded']
    minimal = available[:1]
    # Fixed engineering order picks levels first, followed by transfer, outlet,
    # and inlet. Only feasible rows may be the cost-limited baseline.
    order = ('level1', 'level2', 'transfer', 'outlet', 'inlet')
    baseline = max(rows, key=lambda r: (len(r['sensors']), tuple(k in r['sensors'] for k in order)))
    layouts = dict(single_sensor=minimal, all_sensors=available, cost_baseline=baseline['sensors'],
                   nominal_optimum=winners['nominal'], mean_optimum=winners['mean'],
                   minimax_optimum=winners['worst'])
    costs = {s['key']: s['cost'] for s in config['sensors']}
    samples = nominal['templates'].shape[1]
    calibration = gaussian_noise(np.random.default_rng(CALIBRATION_SEED), nominal['cov'],
                                 (CALIBRATION_TRIALS, samples, len(KEYS)))
    holdouts = list(holdout_cases(config, nominal, cov, names))
    results = {}
    for layout in dict.fromkeys(tuple(sensors) for sensors in layouts.values()):
        started = perf_counter()
        indices = tuple(KEYS.index(key) for key in layout)
        chol = np.linalg.cholesky(nominal['cov'][np.ix_(indices, indices)])
        healthy = nominal['templates'][0][:, indices]
        templates = whiten(nominal['responses'][..., indices], chol).reshape(len(names), -1)
        normal = whiten(calibration[..., indices], chol).reshape(CALIBRATION_TRIALS, -1)
        threshold = float(np.quantile(log_scores(normal, templates).max(axis=1), 1-ALPHA, method='higher'))
        fit_limit = float(np.quantile(np.sum(normal**2, axis=1), FIT_QUANTILE, method='higher'))
        distances = separations(templates)
        cohorts = []
        for case, truth, observations in holdouts:
            whitened = whiten(observations[..., indices] - healthy, chol)
            actual_cov = cov[np.ix_(indices, indices)] * case['noiseScale']**2
            actual = whiten((truth-truth[0])[..., indices], np.linalg.cholesky(actual_cov))
            actual_distances = separations(actual)
            cohorts.append(dict(id=case['id'], **cohort_metrics(templates, whitened, names, threshold, fit_limit),
                                trueMinimumSeparation=float(actual_distances[np.triu_indices(len(names), k=1)].min())))
        results[layout] = dict(sensors=list(layout), cost=math.fsum(costs[key] for key in layout),
                               threshold=threshold, fitLimit=fit_limit,
                               minimumSeparation=float(distances[np.triu_indices(len(names), k=1)].min()),
                               cohorts=cohorts, runtimeMs=(perf_counter()-started)*1000)
    return dict(calibrationSeed=CALIBRATION_SEED, holdoutSeed=HOLDOUT_SEED, calibrationTrials=CALIBRATION_TRIALS,
                targetFalseAlarm=ALPHA, fitQuantile=FIT_QUANTILE, logLikelihoodMargin=LOG_LIKELIHOOD_MARGIN,
                chosenLayout={'nominal': 'nominal_optimum', 'mean': 'mean_optimum', 'worst': 'minimax_optimum'}[config['aggregation']],
                cohorts=[case for case, _, _ in holdouts],
                layouts=[dict(id=key, **results[tuple(layout)]) for key, layout in layouts.items()])
