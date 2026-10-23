"""Synchronous anomaly analysis, fitted and calibrated on the user's normal interval."""
from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter

import numpy as np

from .monitoring import MaxZMonitor, PCAMonitor, calibrate, split_normal_training

ALGORITHMS = {'robust-maxz': 'Robust Max-Z', 'pca-q': 'PCA-Q', 'pca-t2': 'PCA-T²'}


def run_analysis(times: np.ndarray, values: np.ndarray, columns: list[str], config: dict) -> dict:
    started = perf_counter()
    signals = config.get('signals')
    if not isinstance(signals, list) or not signals or len(set(signals)) != len(signals) or any(s not in columns for s in signals):
        raise ValueError('Select one or more unique numeric signals from this dataset.')
    algorithm = config.get('algorithm', 'robust-maxz')
    if algorithm not in ALGORITHMS:
        raise ValueError('Choose Max-Z, PCA-Q or PCA-T².')
    data = values[:, [columns.index(s) for s in signals]]

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
    if len(normal) < 100:
        raise ValueError('Select at least 100 normal samples (70% fit / 30% calibration).')
    split = int(len(normal) * .7)
    # Fit preprocessing only on the fit partition, never the calibration or target rows.
    if not np.isfinite(normal[:split]).any(axis=0).all():
        raise ValueError('Every selected signal needs measurements in the first 70% of the normal baseline.')
    medians = np.nanmedian(normal[:split], axis=0)
    imputed = {'baseline': int(np.isnan(normal).sum()), 'analysis': int(np.isnan(target).sum())}
    normal = np.where(np.isfinite(normal), normal, medians)
    target = np.where(np.isfinite(target), target, medians)
    fit, calibration = split_normal_training(normal)
    alpha = float(config.get('alpha', .01))
    variance = float(config.get('variance', .9))
    if not 0 < alpha < .5:
        raise ValueError('Calibration alpha must be between 0 and 0.5.')
    monitor = MaxZMonitor() if algorithm == 'robust-maxz' else PCAMonitor(algorithm.split('-')[1], variance=variance)
    monitor.fit(fit)
    threshold = calibrate(monitor, calibration, alpha)
    scores = monitor.score(target)
    if not np.isfinite(scores).all():
        raise ValueError('Signal magnitudes produced nonfinite scores; check the selected measurements.')
    flags = scores > threshold
    target_times = times[target_mask]
    starts = np.flatnonzero(flags & ~np.r_[False, flags[:-1]])
    ends = np.flatnonzero(flags & ~np.r_[flags[1:], False])
    intervals = []
    for a, b in zip(starts, ends):
        peak = int(a + np.argmax(scores[a:b + 1]))
        intervals.append({'start': float(target_times[a]), 'end': float(target_times[b]),
                          'samples': int(b - a + 1), 'peakScore': float(scores[peak]),
                          'peakTime': float(target_times[peak]),
                          'signals': monitor.explain(target[peak], signals, count=min(5, len(signals)))})
    peak_index = int(np.argmax(scores))
    config = {**config, 'algorithm': algorithm, 'alpha': alpha, 'variance': variance,
              'missingValues': 'fit-partition median', 'fitFraction': .7}
    return {'config': config, 'algorithmLabel': ALGORITHMS[algorithm], 'times': target_times.tolist(),
            'scores': scores.tolist(), 'threshold': threshold, 'intervals': intervals,
            'relatedSignals': monitor.explain(target[peak_index], signals, count=min(10, len(signals))),
            'summary': {'analysisSamples': len(target), 'baselineSamples': len(normal),
                        'fitSamples': len(fit), 'calibrationSamples': len(calibration),
                        'flaggedSamples': int(flags.sum()), 'peakScore': float(scores[peak_index]),
                        'firstDetection': float(target_times[starts[0]]) if len(starts) else None,
                        'imputedValues': imputed},
            'model': {**monitor.metadata(), 'center': monitor.center.tolist(), 'scale': monitor.scale.tolist(),
                      'imputationMedians': medians.tolist(),
                      **({'loadings': monitor.components.tolist(), 'eigenvalues': monitor.eigenvalues.tolist()}
                         if isinstance(monitor, PCAMonitor) else {})},
            'completedAt': datetime.now(timezone.utc).isoformat(), 'durationMs': round((perf_counter() - started) * 1000, 2)}
