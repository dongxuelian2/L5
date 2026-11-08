"""Reference-based sensor integrity and explicit cross-channel checks.

Offline diagnostics, not causal proof. Only declared normal samples set scales
and limits. Missing/processed observations are never imputed for diagnosis.
"""
from __future__ import annotations

import hashlib
from copy import deepcopy
import numpy as np

from .data_quality import cadence, runs, segment_ids
from .monitoring import MaxZMonitor

VERSION = '1.0.0'
DEFAULTS = dict(window=21, persistence=3, z=6.)


def finite_list(values):
    return [float(v) if np.isfinite(v) else None for v in values]


def scale(values, floor=1e-8):
    x = np.asarray(values)[np.isfinite(values)]
    if not len(x):
        return float(floor)
    monitor = MaxZMonitor()
    if len(x) >= 3:
        monitor.fit(x[:, None])
        return max(float(monitor.scale[0]), float(floor))
    return max(float(np.std(x)), float(floor))


def rolling(times, values, window, gap):
    """Trailing OLS, with resets on missing values or acquisition gaps."""
    mean, slope, noise, spread = [np.full(len(times), np.nan) for _ in range(4)]
    begin = 0
    # O(n * window), bounded to window <= 101 and at most 50,000 rows.
    for i in range(len(times)):
        if not np.isfinite(values[i]):
            begin = i + 1
            continue
        if i and times[i] - times[i-1] > gap:
            begin = i
        if i - begin + 1 < window:
            continue
        x, y = times[i-window+1:i+1], values[i-window+1:i+1]
        x = x - x.mean()
        slope[i] = x @ (y-y.mean()) / (x @ x)
        mean[i] = y.mean()
        noise[i] = np.sqrt(np.mean((y-y.mean()-slope[i]*x)**2))
        spread[i] = np.ptp(y)
    return mean, slope, noise, spread


def persistent(mask, count, times, gap):
    out = np.zeros(len(mask), bool)
    length = 0
    for i, active in enumerate(mask):
        if i and times[i]-times[i-1] > gap:
            length = 0
        length = length + 1 if active else 0
        out[i] = length >= count
    return out


def validate(times, values, columns, raw):
    if not isinstance(raw, dict):
        raise ValueError('Sensor health configuration must be an object.')
    c = {**DEFAULTS, **deepcopy(raw)}
    if set(c)-{'signals', 'baselineRange', 'analysisRange', 'window', 'persistence', 'z', 'relationships', 'model'}:
        raise ValueError('Use only declared sensor diagnostic settings; simulator labels are not accepted.')
    signals = c.get('signals')
    if not isinstance(signals, list) or not 1 <= len(signals) <= 24 or any(not isinstance(s, str) or s not in columns for s in signals) or len(set(signals)) != len(signals):
        raise ValueError('Select 1–24 unique sensor signals from this dataset.')
    if values.shape != (len(times), len(columns)) or len(times) < 90 or len(times) > 50000:
        raise ValueError('Sensor health supports 90–50,000 timestamped rows per run.')
    if not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
        raise ValueError('Sensor health requires strictly increasing unique timestamps; resolve duplicates first.')
    for key, lo, hi in [('window', 5, 101), ('persistence', 1, 20)]:
        if isinstance(c[key], bool) or not isinstance(c[key], int) or not lo <= c[key] <= hi:
            raise ValueError(f'{key} is outside the supported integer range {lo}–{hi}.')
    if isinstance(c['z'], bool) or not isinstance(c['z'], (int, float)) or not np.isfinite(c['z']) or not 3 <= c['z'] <= 12:
        raise ValueError('The diagnostic threshold multiplier must be between 3 and 12.')
    masks = []
    for key in ('baselineRange', 'analysisRange'):
        interval = c.get(key)
        if not isinstance(interval, list) or len(interval) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not np.isfinite(v) for v in interval) or not times[0] <= interval[0] < interval[1] <= times[-1]:
            raise ValueError('Choose valid reference and analysis intervals inside the dataset.')
        masks.append((times >= interval[0]) & (times <= interval[1]))
    if c['baselineRange'][1] >= c['analysisRange'][0] or masks[0].sum() < max(90, 3*c['window']) or masks[1].sum() < c['window']:
        raise ValueError('Use a normal reference of at least max(90, 3 × window) samples strictly before the analysis interval; analyze at least one window.')
    relationships = c.setdefault('relationships', [])
    if not isinstance(relationships, list) or len(relationships) > 8:
        raise ValueError('Use at most eight declared signal relationships.')
    for relation in relationships:
        if not isinstance(relation, dict) or relation.get('kind') not in ('agreement', 'linear') or relation.get('target') not in signals or relation.get('predictor') not in signals or relation['target'] == relation['predictor']:
            raise ValueError('Declare agreement or linear relationships between two distinct selected signals.')
    return c, masks


def diagnose(times, values, columns, raw, *, observed=None):
    times, values = np.asarray(times, float), np.asarray(values, float)
    c, (baseline, target) = validate(times, values, columns, raw)
    names = c['signals']
    data = values[:, [columns.index(s) for s in names]].copy()
    if observed is not None:
        data[~observed[:, [columns.index(s) for s in names]]] = np.nan
    # Exclude future rows even from descriptive summaries and checksums.
    keep = times <= c['analysisRange'][1]
    times, data, baseline, target = times[keep], data[keep], baseline[keep], target[keep]
    gap = cadence(times[baseline])['gapThreshold'] or float('inf')
    gaps = [dict(start=float(times[i]), end=float(times[i+1])) for i in np.flatnonzero(np.diff(times) > gap)]
    w, z = c['window'], c['z']
    fit_end = np.flatnonzero(baseline)[int(baseline.sum()*.7)]
    fit, calibration = baseline & (np.arange(len(times)) < fit_end), baseline & (np.arange(len(times)) >= fit_end)
    indicators, signal_results, relationships, warnings = [], {}, [], []

    def indicator(kind, signals, scores, threshold, *, evidence=None, immediate=False, event_delay=0):
        scores = np.asarray(scores, float)
        active = np.isfinite(scores) & (scores > threshold) & target
        if not immediate:
            active = persistent(active, c['persistence'], times, gap)
        spans = []
        for span in runs(times, active, gap):
            idx = np.flatnonzero(active & (times >= span['start']) & (times <= span['end']))
            peak = idx[np.argmax(scores[idx])]
            spans.append(dict(start=span['start'], end=span['end'], samples=span['count'],
                peakTime=float(times[peak]), detectedAt=float(times[min(idx[0]+event_delay, len(times)-1)]),
                severity=float(scores[peak]/threshold), evidenceValue=float(scores[peak])))
        item = dict(id=f'{kind}:{len(indicators)}', kind=kind, signals=signals,
            threshold=float(threshold), scores=finite_list(scores[target]), intervals=spans, evidence=evidence or {})
        indicators.append(item)
        return active

    for j, name in enumerate(names):
        y = data[:, j]
        ref = y[fit & np.isfinite(y)]
        if len(ref) < 30 or np.isfinite(y[calibration]).sum() < 20:
            raise ValueError(f'{name}: reference needs 30 measured fit and 20 measured calibration values.')
        center, sigma = float(np.median(ref)), scale(ref)
        mean, slope, noise, spread = rolling(times, y, w, gap)
        span = np.full(len(times), np.nan)
        span[w-1:] = times[w-1:] - times[:len(times)-w+1]
        deviation = np.abs(mean-center)/sigma
        drift = np.abs(slope*span)/sigma
        def limit(scores, minimum):
            cal = scores[calibration & np.isfinite(scores)]
            return max(minimum, float(np.quantile(cal, .99))*1.25) if len(cal) else minimum
        indicator('level_shift', [name], deviation, limit(deviation, z), evidence=dict(referenceMedian=center, referenceScale=sigma, interpretation='A level shift can be a sensor offset or a real process change.'))
        indicator('drift', [name], drift, limit(drift, z), evidence=dict(unit='reference scales per window', interpretation='A sustained local slope requires cross-signal evidence for isolation.'))
        noise_limit = limit(noise, max(sigma*3, 1e-8))
        full_reference = baseline & (np.arange(len(times)) >= np.flatnonzero(baseline)[0]+w-1)
        reference_noise = noise[full_reference & np.isfinite(noise)]
        indicator('noise', [name], noise, noise_limit, evidence=dict(unit='signal units', referenceNoise=float(np.median(reference_noise)) if len(reference_noise) else None, interpretation='Local linear detrending removes ramps, but process oscillations can also increase this statistic.'))
        # Flat references do not establish that a future constant value is faulty.
        epsilon = max(abs(center)*1e-10, 1e-10)
        frozen = np.where(np.isfinite(spread), np.where(spread <= epsilon, 2., 0.), np.nan)
        if np.ptp(ref) > epsilon*10:
            indicator('stuck', [name], frozen, 1., immediate=True, evidence=dict(windowSamples=w, tolerance=epsilon, referenceRange=float(np.ptp(ref))))
        else:
            warnings.append(dict(code='constant_reference', signals=[name]))
        spike = np.full(len(times), np.nan)
        for i in range(1, len(times)-1):
            if np.isfinite(y[i-1:i+2]).all() and np.all(np.diff(times[i-1:i+2]) <= gap):
                # Returning neighbours distinguish isolated impulses from steps.
                if abs(y[i+1]-y[i-1]) < 3*sigma:
                    spike[i] = abs(y[i]-(y[i-1]+y[i+1])/2)/sigma
        # Last target sample cannot borrow an unseen future confirmation.
        indicator('spike', [name], spike, z, immediate=True, event_delay=1, evidence=dict(confirmationSamples=1))
        indicator('dropout', [name], (~np.isfinite(y)).astype(float), .5, immediate=True, evidence=dict(unit='missing observation', interpretation='Processed values count as unavailable measured evidence.'))
        signal_results[name] = dict(referenceMedian=center, referenceScale=sigma,
            measuredFraction=float(np.isfinite(y[target]).mean()), observed=finite_list(y[target]),
            segmentIds=segment_ids(times, y, gap)[target].tolist())

    for relation in c['relationships']:
        a, b = names.index(relation['predictor']), names.index(relation['target'])
        x, y = data[:, a], data[:, b]
        valid = fit & np.isfinite(x) & np.isfinite(y)
        if valid.sum() < 30:
            raise ValueError('A declared relationship needs 30 paired normal fit observations.')
        intercept, coefficient = 0., 1.
        if relation['kind'] == 'linear':
            if np.ptp(x[valid]) <= 1e-8:
                raise ValueError('Linear relationships need an excited predictor in the normal reference.')
            coefficient, intercept = np.polyfit(x[valid], y[valid], 1)
        prediction = intercept + coefficient*x
        residual = y-prediction
        offset = float(np.median(residual[valid]))
        residual -= offset
        prediction += offset
        sigma = scale(residual[valid], signal_results[relation['target']]['referenceScale']*.05)
        cal = np.abs(residual[calibration & np.isfinite(residual)])/sigma
        if len(cal) < 20:
            raise ValueError('A declared relationship needs 20 paired normal calibration observations.')
        threshold = max(z, float(np.quantile(cal, .99))*1.25)
        indicator('relationship', [relation['target'], relation['predictor']], np.abs(residual)/sigma, threshold,
            evidence=dict(coefficient=float(coefficient), intercept=float(intercept+offset), residualScale=sigma,
                interpretation='Disagreement identifies a relationship violation, not which channel failed.'))
        relationships.append(dict(**relation, expected=finite_list(prediction[target]), residual=finite_list(residual[target]), scale=sigma))

    physical = None
    if c.get('model') is not None:
        from .sensor_health_tanks import tank_evidence
        physical = tank_evidence(times, data, names, baseline, target, c, indicator)

    if gaps:
        warnings.append(dict(code='acquisition_gaps', signals=names))
    active = np.zeros(int(target.sum()), bool)
    for item in indicators:
        for interval in item['intervals']:
            active |= (times[target] >= interval['start']) & (times[target] <= interval['end'])
    episodes = []
    for span in runs(times[target], active, gap):
        related = [i for i in indicators if any(s['start'] <= span['end'] and s['end'] >= span['start'] for s in i['intervals'])]
        episode = dict(start=span['start'], end=span['end'], samples=span['count'], indicatorIds=[i['id'] for i in related],
            signals=sorted({s for i in related for s in i['signals']}),
            severity=max(s['severity'] for i in related for s in i['intervals'] if s['start'] <= span['end'] and s['end'] >= span['start']),
            detectedAt=min(s['detectedAt'] for i in related for s in i['intervals'] if s['start'] <= span['end'] and s['end'] >= span['start']))
        if physical:
            from .sensor_health_tanks import compare_hypotheses
            episode.update(compare_hypotheses(times, data, names, target, physical, episode, related, c))
        else:
            episode.update(assessment='insufficient_evidence', candidates=[])
        episodes.append(episode)
    if physical:
        # Internal full-resolution arrays are retained only in the saved traces.
        physical = {k: v for k, v in physical.items() if not k.startswith('_')}
    warnings = [dict(code=code, signals=sorted({s for warning in warnings if warning['code'] == code for s in warning['signals']})) for code in dict.fromkeys(w['code'] for w in warnings)]
    return dict(version=VERSION, config=c, times=times[target].tolist(), gaps=gaps, signals=signal_results,
        indicators=indicators, relationships=relationships, physical=physical, episodes=episodes, warnings=warnings,
        reference=dict(times=times[baseline].tolist(), values={s: finite_list(data[baseline, j]) for j, s in enumerate(names)},
            fitSamples=int(fit.sum()), calibrationSamples=int(calibration.sum())),
        sourceDigest=hashlib.sha256(times.astype('<f8').tobytes()+data.astype('<f8').tobytes()).hexdigest(),
        summary=dict(samples=int(target.sum()), flaggedSamples=int(active.sum()), episodes=len(episodes),
            firstDetection=min((e['detectedAt'] for e in episodes), default=None)),
        limitations=['integrity_is_not_causality', 'normal_reference_required', 'single_fault_assumption'] if physical else ['integrity_is_not_causality', 'normal_reference_required', 'no_physical_model'])
