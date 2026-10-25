"""Synchronous anomaly analysis, fitted and calibrated on the user's normal interval."""
from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter

import numpy as np

from .monitoring import MaxZMonitor, PCAMonitor, calibrate, split_normal_training

ALGORITHMS = {'robust-maxz': 'Robust Max-Z', 'pca-q': 'PCA-Q', 'pca-t2': 'PCA-T²',
              'ewma': 'EWMA', 'cusum': 'Page CUSUM', 'window-cusum': 'Finite-window CUSUM',
              'dpca-q': 'Dynamic PCA-Q', 'dpca-t2': 'Dynamic PCA-T²',
              'adaptive-maxz': 'Adaptive Max-Z · Experimental'}


def build_monitor(algorithm, config):
    from benchmarks.temporal import EWMAMonitor, CUSUMMonitor
    from benchmarks.window_cusum import WindowCUSUMMonitor
    from benchmarks.dynamic_pca import DynamicPCAMonitor
    from benchmarks.adaptive import AdaptiveMaxZMonitor
    if algorithm == 'robust-maxz':
        return MaxZMonitor()
    if algorithm in ('pca-q', 'pca-t2'):
        return PCAMonitor(algorithm.split('-')[1], variance=float(config.get('variance', .9)))
    if algorithm == 'ewma':
        return EWMAMonitor(smoothing=float(config.get('smoothing', .25)))
    if algorithm == 'cusum':
        return CUSUMMonitor(reference=float(config.get('reference', .5)))
    if algorithm == 'window-cusum':
        return WindowCUSUMMonitor(window=config.get('window', 12), reference=float(config.get('reference', .5)))
    if algorithm in ('dpca-q', 'dpca-t2'):
        return DynamicPCAMonitor(algorithm.split('-')[1], lags=config.get('lags', 2), variance=float(config.get('variance', .9)))
    return AdaptiveMaxZMonitor(rate=float(config.get('rate', .02)), guard_z=float(config.get('guard', 2.5)), max_center_shift_z=float(config.get('maxShift', 1.5)))


def contribution_matrix(monitor, target):
    if hasattr(monitor, '_features_at_each_time'):
        return monitor._features_at_each_time(target)
    if hasattr(monitor, '_contributions'):
        return monitor._contributions(target)
    if hasattr(monitor, '_lag_matrix'):
        projected, residual = monitor._decompose(target)
        weights = residual ** 2 if monitor.mode == 'q' else np.abs((projected / np.sqrt(monitor.eigenvalues)) @ monitor.components)
        return weights.reshape(len(target), monitor.lags + 1, monitor.features).sum(axis=1)
    z = (target - monitor.center) / monitor.scale
    if isinstance(monitor, MaxZMonitor):
        return np.abs(z)
    projected = z @ monitor.components.T
    return (z - projected @ monitor.components) ** 2 if monitor.mode == 'q' else np.abs((projected / np.sqrt(monitor.eigenvalues)) @ monitor.components)



def signal_contributions(monitor, sample: np.ndarray, names: list[str]) -> list[dict]:
    z = (sample - monitor.center) / monitor.scale
    if isinstance(monitor, MaxZMonitor):
        weights = np.abs(z)
    else:
        projected = z @ monitor.components.T
        if monitor.mode == 'q':
            weights = (z - projected @ monitor.components) ** 2
        else:
            # Same descriptive leverage used by PCAMonitor.explain (not additive T²).
            weights = np.abs(monitor.components.T @ (projected / np.sqrt(monitor.eigenvalues)))
    order = sorted(range(len(names)), key=lambda i: (-float(weights[i]), i))
    return [{'signal': names[i], 'value': float(weights[i])} for i in order]


def run_analysis(times: np.ndarray, values: np.ndarray, columns: list[str], config: dict, *, observed=None) -> dict:
    started = perf_counter()
    config = dict(config)
    signals = config.get('signals')
    if not isinstance(signals, list) or not signals or len(set(signals)) != len(signals) or any(s not in columns for s in signals):
        raise ValueError('Select one or more unique numeric signals from this dataset.')
    algorithm = config.get('algorithm', 'robust-maxz')
    if algorithm not in ALGORITHMS:
        raise ValueError('Choose an available detection algorithm.')
    defaults = {'ewma':{'smoothing':.25}, 'cusum':{'reference':.5},
                'window-cusum':{'window':12,'reference':.5}, 'dpca-q':{'lags':2}, 'dpca-t2':{'lags':2},
                'adaptive-maxz':{'rate':.02,'guard':2.5,'maxShift':1.5}}
    for key, value in defaults.get(algorithm, {}).items():
        config.setdefault(key, value)
    data = values[:, [columns.index(s) for s in signals]]
    observation_policy = config.get('observationPolicy', 'measured')
    if observation_policy not in ('measured', 'processed'):
        raise ValueError('Choose measured observations or explicitly include processed values.')
    processed_count = 0
    if observed is not None:
        selected_mask = observed[:, [columns.index(s) for s in signals]]
        processed_count = int(np.sum(np.isfinite(data) & ~selected_mask))
        if observation_policy == 'measured':
            data = np.where(selected_mask, data, np.nan)
        config['observationPolicy'] = observation_policy

    def window(key: str):
        interval = config.get(key)
        if not isinstance(interval, list) or len(interval) != 2:
            raise ValueError(f'{key} needs a start and end time in seconds.')
        lo, hi = map(float, interval)
        if not np.isfinite([lo, hi]).all() or not times[0] <= lo <= hi <= times[-1]:
            raise ValueError(f'{key} must be inside the dataset time range, with start ≤ end.')
        mask = (times >= lo) & (times <= hi)
        if not mask.any():
            raise ValueError(f'{key} contains no samples.')
        config[key] = [lo, hi]
        return mask

    normal_mask, target_mask = window('baselineRange'), window('analysisRange')
    if config['baselineRange'][1] >= config['analysisRange'][0]:
        raise ValueError('The normal baseline must finish before the analysis window starts.')
    normal, target = data[normal_mask].copy(), data[target_mask].copy()
    fit_fraction = float(config.get('fitFraction', .7))
    if not .5 <= fit_fraction <= .9:
        raise ValueError('Fit fraction must be between 0.5 and 0.9.')
    split = int(len(normal) * fit_fraction)
    if split < 30 or len(normal)-split < 30:
        raise ValueError('Select enough normal samples for at least 30 fit and 30 calibration observations.')
    # Fit preprocessing only on the fit partition, never the calibration or target rows.
    if not np.isfinite(normal[:split]).any(axis=0).all():
        raise ValueError('Every selected signal needs measurements in the fit partition of the normal baseline.')
    medians = np.nanmedian(normal[:split], axis=0)
    # Artificial stress affects the target only; fit and calibration stay unchanged.
    stress = config.get('stress') or {}
    if not isinstance(stress, dict):
        raise ValueError('Stress parameters must be an object.')
    probability, noise, offset = (float(stress.get(k, 0)) for k in ('missingFraction', 'noise', 'offset'))
    if not np.isfinite([probability, noise, offset]).all() or not 0 <= probability <= 1 or noise < 0:
        raise ValueError('Missing fraction must be in [0,1]; noise must be nonnegative; stress values must be finite.')
    missing_signals = stress.get('missingSignals', [])
    if not isinstance(missing_signals, list) or any(s not in signals for s in missing_signals):
        raise ValueError('Stress signals must be selected analysis signals.')
    seed = stress.get('seed', 1)
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        raise ValueError('Stress seed must be a nonnegative integer.')
    rng = np.random.default_rng(seed)
    healthy_scale = np.nanstd(normal[:split], axis=0)
    target += rng.normal(size=target.shape) * healthy_scale * noise + healthy_scale * offset
    target[rng.random(target.shape) < probability] = np.nan
    for signal in missing_signals:
        target[:, signals.index(signal)] = np.nan
    original_mask = np.isfinite(target)
    imputed = {'baseline': int(np.isnan(normal).sum()), 'analysis': int(np.isnan(target).sum())}
    baseline_observed = np.isfinite(normal)
    normal = np.where(baseline_observed, normal, medians)
    target = np.where(np.isfinite(target), target, medians)
    fit, calibration = split_normal_training(normal, fit_fraction)
    alpha = float(config.get('alpha', .01))
    variance = float(config.get('variance', .9))
    if not 0 < alpha < .5:
        raise ValueError('Calibration alpha must be between 0 and 0.5.')
    monitor = build_monitor(algorithm, config)
    if getattr(monitor, 'history_dependent', False):
        for sequence in (times[normal_mask], times[target_mask]):
            periods = np.diff(sequence)
            if len(periods) and (np.any(periods <= 0) or not np.allclose(periods, periods[0], rtol=1e-5, atol=1e-7)):
                raise ValueError('Temporal algorithms require regular, strictly increasing sample times.')
    from benchmarks.coverage import CoveragePolicy, decide, score_with_observation_resets
    required = config.get('requiredSignals', [])
    if not isinstance(required, list):
        raise ValueError('Required signals must be a list.')
    policy = CoveragePolicy(float(config.get('minCoverage', .9)), tuple(required), tuple(signals))
    if observed is not None:
        # Keep synthetic values out of measured-only fitting/calibration. Temporal models
        # need contiguous sequence history, so require a fully covered baseline for them.
        required_indexes = [signals.index(s) for s in required]
        covered = baseline_observed.mean(axis=1) >= policy.min_observed_fraction
        if required_indexes:
            covered &= baseline_observed[:, required_indexes].all(axis=1)
        if getattr(monitor, 'history_dependent', False) and not covered.all():
            raise ValueError('Temporal analysis needs a fully observed baseline. Choose another window or explicitly include processed values.')
        fit, calibration = fit[covered[:split]], calibration[covered[split:]]
        if len(fit) < 30 or len(calibration) < 30:
            raise ValueError('Need at least 30 covered fit and 30 covered calibration rows. Extend the baseline or explicitly include processed values.')
    monitor.fit(fit)
    threshold = calibrate(monitor, calibration, alpha)
    return score_analysis(monitor, threshold, target, original_mask, times[target_mask], signals,
        {**config, 'algorithm': algorithm, 'alpha': alpha, 'variance': variance, 'fitFraction': fit_fraction},
        policy, medians, fit_samples=len(fit), calibration_samples=len(calibration), baseline_samples=len(normal),
        imputed=imputed, processed_count=processed_count, observation_policy=observation_policy,
        observed=observed is not None, started=started)


def score_analysis(monitor, threshold, target, original_mask, target_times, signals, config, policy, medians, *,
                   fit_samples, calibration_samples, baseline_samples, imputed, processed_count=0,
                   observation_policy='measured', observed=False, started=None):
    """Shared saved AnalysisResult projection for single- and cross-dataset paths."""
    from benchmarks.coverage import decide, score_with_observation_resets
    started = perf_counter() if started is None else started
    algorithm = config['algorithm']
    alpha, variance, fit_fraction = config.get('alpha', .01), config.get('variance', .9), config.get('fitFraction', .7)
    required = list(policy.required_channels)
    persistence = config.get('persistence', 1)
    scores = score_with_observation_resets(monitor, target, original_mask, policy)
    states = decide(scores, original_mask, threshold=threshold, consecutive=persistence, policy=policy)
    weights = np.zeros_like(target)
    valid = np.array([state != 'abstain' for state in states])
    # Explanations restart at the same observation gaps as temporal scores.
    begin = 0
    while begin < len(target):
        if not valid[begin]:
            begin += 1
            continue
        end = begin + 1
        while end < len(target) and valid[end]:
            end += 1
        weights[begin:end] = contribution_matrix(monitor, target[begin:end])
        begin = end
    def contributions_at(index):
        order = sorted(range(len(signals)), key=lambda i: (-float(weights[index,i]), i))
        return [dict(signal=signals[i], value=float(weights[index,i])) for i in order]

    if not np.isfinite(scores).all():
        raise ValueError('Signal magnitudes produced nonfinite scores; check the selected measurements.')
    flags = np.array([s == 'alarm' for s in states])
    starts = np.flatnonzero(flags & ~np.r_[False, flags[:-1]])
    ends = np.flatnonzero(flags & ~np.r_[flags[1:], False])
    intervals = []
    for a, b in zip(starts, ends):
        peak = int(a + np.argmax(scores[a:b + 1]))
        contributions = contributions_at(peak)
        intervals.append({'start': float(target_times[a]), 'end': float(target_times[b]),
                          'samples': int(b - a + 1), 'peakScore': float(scores[peak]),
                          'peakTime': float(target_times[peak]),
                          'signals': [item['signal'] for item in contributions[:5]],
                          'contributions': contributions})
    peak_index = int(np.argmax(np.where(valid, scores, -np.inf))) if valid.any() else 0
    contributions = contributions_at(peak_index)
    config = {**config, 'algorithm': algorithm, 'alpha': alpha, 'variance': variance,
              'missingValues': 'fit-partition median', 'fitFraction': fit_fraction, 'minCoverage': policy.min_observed_fraction, 'requiredSignals': required, 'persistence': persistence}
    return {'config': config, 'algorithmLabel': ALGORITHMS[algorithm], 'times': target_times.tolist(),
            'scores': scores.tolist(), 'states': list(states), 'observedFraction': original_mask.mean(axis=1).tolist(), 'threshold': threshold, 'intervals': intervals,
            'relatedSignals': [item['signal'] for item in contributions[:10]],
            'signalContributions': contributions, 'peakTime': float(target_times[peak_index]),
            'contributionMetric': {'robust-maxz': 'absolute-robust-z', 'pca-q': 'squared-residual',
                                   'pca-t2': 'model-leverage', 'dpca-q': 'squared-residual', 'dpca-t2': 'model-leverage'}.get(algorithm, 'history-contribution'),
            'summary': {'analysisSamples': len(target), 'baselineSamples': baseline_samples,
                        'fitSamples': fit_samples, 'calibrationSamples': calibration_samples,
                        'flaggedSamples': int(flags.sum()), 'peakScore': float(scores[peak_index]),
                        'firstDetection': float(target_times[starts[0]]) if len(starts) else None,
                        'imputedValues': imputed, 'abstainedSamples': int(sum(s == 'abstain' for s in states)), 'coverageFraction': float(valid.mean()),
                        **({'processedInputValues': processed_count, 'observationPolicy': observation_policy} if observed else {})},
            'model': {**monitor.metadata(), 'center': monitor.center.tolist(), 'scale': monitor.scale.tolist(),
                      'imputationMedians': medians.tolist(),
                      **({'loadings': monitor.components.tolist(), 'eigenvalues': monitor.eigenvalues.tolist()}
                         if hasattr(monitor, 'components') else {}),
                      **({'lagPaddingCenter': monitor.pad_center.tolist()} if hasattr(monitor, 'pad_center') else {})},
            'completedAt': datetime.now(timezone.utc).isoformat(), 'durationMs': round((perf_counter() - started) * 1000, 2)}
