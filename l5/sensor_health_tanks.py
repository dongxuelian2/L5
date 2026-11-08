"""Coupled-tank constraint residuals and competing single-fault corrections.

Receives measurements and a strict physical-parameter allowlist, never a simulator
session, fault label, onset, injected severity, hidden states or future rows.
"""
from __future__ import annotations

import numpy as np

from .sensor_health import finite_list, scale
from .data_quality import segment_ids

PARAMETERS = dict(area1=1., area2=1., connection=.04, outlet=.03, outletValve=1., pumpRate=.03, tankHeight=2.5)
ROLES = ('level1', 'level2', 'inlet', 'transfer', 'outlet', 'pump', 'valve')


def validate_model(model, names):
    if not isinstance(model, dict) or set(model)-{'kind', 'mapping', 'parameters'} or model.get('kind') != 'coupled-tanks':
        raise ValueError('Choose the supported coupled-tanks model with explicit signal mapping and physical parameters.')
    mapping, supplied = model.get('mapping'), model.get('parameters', {})
    if not isinstance(mapping, dict) or set(mapping) != set(ROLES) or any(v not in names for v in mapping.values()) or len(set(mapping.values())) != len(ROLES):
        raise ValueError('Map all seven tank roles to distinct selected measured signals.')
    if not isinstance(supplied, dict) or set(supplied)-PARAMETERS.keys():
        raise ValueError('Only declared geometry and nominal hydraulic parameters are diagnostic inputs; fault labels are prohibited.')
    p = {**PARAMETERS, **supplied}
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not np.isfinite(v) or not 0 < v <= 100 for v in p.values()):
        raise ValueError('Tank geometry and nominal coefficients must be finite and positive, at most 100.')
    model['parameters'] = p
    return mapping, p


def tank_evidence(times, data, names, baseline, target, c, indicator):
    mapping, p = validate_model(c['model'], names)
    d = {key: data[:, names.index(mapping[key])] for key in ROLES}
    h1, h2, qi, qt, qo = (d[k] for k in ('level1', 'level2', 'inlet', 'transfer', 'outlet'))
    w = c['window']
    measured = np.isfinite(np.column_stack(list(d.values()))).all(axis=1)
    typical = float(np.median(np.diff(times[baseline])))
    safe = measured & (d['valve'] > .005) & (qo > 0) & (h1 > .01) & (h2 > .01) & (h1 < p['tankHeight']) & (h2 < p['tankHeight'])
    expected2 = (qo/(p['outlet']*p['outletValve']))**2
    expected1 = expected2 + np.sign(qt)*(qt/(p['connection']*d['valve']))**2
    expected1, expected2 = np.where(safe, expected1, np.nan), np.where(safe, expected2, np.nan)
    mass = []
    for level, flow, area in [(h1, qi-qt, p['area1']), (h2, qt-qo, p['area2'])]:
        residual = np.full(len(times), np.nan)
        for i in range(w-1, len(times)):
            a = i-w+1
            if safe[a:i+1].all() and np.all(np.diff(times[a:i+1]) <= 5*typical):
                residual[i] = (np.trapezoid(flow[a:i+1], times[a:i+1])-area*(level[i]-level[a]))/(times[i]-times[a])
        mass.append(residual)
    split = np.flatnonzero(baseline)[int(baseline.sum()*.7)]
    baseline_valve = float(np.nanmedian(d['valve'][baseline & measured & (np.arange(len(times)) < split)]))
    residuals = np.column_stack([h1-expected1, h2-expected2, *mass,
        p['pumpRate']*d['pump']/100-qi, baseline_valve-d['valve']])
    residuals[~safe] = np.nan
    keys = ['hydraulic1', 'hydraulic2', 'balance1', 'balance2', 'pump_capacity', 'valve_opening']
    units = ['m', 'm', 'm³/s', 'm³/s', 'm³/s', 'fraction']
    floors = [1e-5, 1e-5, 1e-5, 1e-5, p['pumpRate']*.005, .005]
    fit = baseline & (np.arange(len(times)) < split) & (np.arange(len(times)) >= np.flatnonzero(baseline)[0]+w-1)
    cal = baseline & (np.arange(len(times)) >= split)
    centers, scales, traces = [], [], []
    for j, key in enumerate(keys):
        r = residuals[:, j]
        valid = fit & np.isfinite(r)
        calibration = cal & np.isfinite(r)
        if valid.sum() < 30 or calibration.sum() < 20:
            raise ValueError('Tank diagnosis requires paired, unsaturated reference measurements for 30 fit and 20 calibration samples.')
        center = float(np.median(r[valid]))
        sigma = scale(r[valid], floors[j])
        scores = np.abs(r-center)/sigma
        threshold = max(c['z'], float(np.quantile(scores[calibration], .99))*1.25)
        indicator('model_residual', [mapping[k] for k in ROLES], scores, threshold, evidence=dict(constraint=key, residualScale=sigma, referenceResidual=center, fitSamples=int(valid.sum()), calibrationSamples=int(calibration.sum()), unit=units[j]))
        centers.append(center); scales.append(sigma)
        traces.append(dict(key=key, unit=units[j], values=finite_list(r[target]-center), segmentIds=segment_ids(times, r, 5*typical)[target].tolist(), scale=sigma, threshold=threshold*sigma))
    return dict(kind='coupled-tanks', residuals=traces, mapping=mapping, parameters=p,
        expected={mapping['level1']: finite_list(expected1[target]), mapping['level2']: finite_list(expected2[target])},
        segmentIds={mapping['level1']: segment_ids(times, expected1, 5*typical)[target].tolist(), mapping['level2']: segment_ids(times, expected2, 5*typical)[target].tolist()},
        measuredCoverage=float(np.isfinite(residuals[target]).all(axis=1).mean()),
        states=['evaluated' if available else 'insufficient_evidence' for available in np.isfinite(residuals[target]).all(axis=1)],
        assumptions=['known_tank_parameters', 'independent_flow_measurements', 'valve_change_ambiguity', 'unsaturated_tanks'],
        _residuals=residuals-np.asarray(centers), _scales=np.asarray(scales))


def compare_hypotheses(times, data, names, target, physical, episode, related, c):
    interval = target & (times >= episode['start']) & (times <= episode['end'])
    available = interval & np.isfinite(physical['_residuals']).all(axis=1)
    coverage = float(available.sum()/max(1, interval.sum()))
    if available.sum() < max(10, c['persistence']) or coverage < .6:
        return dict(assessment='insufficient_evidence', candidates=[], evidenceCoverage=coverage)
    r = physical['_residuals'][available].copy()
    scales = physical['_scales']
    t = times[available]; x = t-t.mean()
    # A clipped squared loss avoids one isolated impulse dominating an episode.
    def loss(a):
        return float(np.mean(np.minimum((a/scales)**2, 900)))
    healthy = loss(r)
    candidates = []
    def candidate(key, category, corrected, parameters, constraints, complexity=1.):
        fit = loss(corrected)
        candidates.append(dict(key=key, category=category, fitError=fit, penalizedError=fit+complexity,
            improvement=(healthy-fit)/max(healthy, 1e-9), parameters=parameters, constraints=constraints))
    candidate('healthy', 'normal', r, {}, [], 0)
    for j, role in enumerate(('level1', 'level2')):
        bias = float(np.mean(r[:, j]))
        corrected = r.copy(); corrected[:, j] -= bias
        candidate(f'{role}_offset', 'sensor', corrected, dict(offset=bias), [f'hydraulic{j+1}', f'balance{j+1}'])
        if x@x > 0:
            slope = float(x@r[:, j]/(x@x))
            corrected = r.copy(); corrected[:, j] -= bias+slope*x
            corrected[:, j+2] += physical['parameters'][f'area{j+1}']*slope
            candidate(f'{role}_drift', 'sensor', corrected, dict(offsetAtCenter=bias, rate=slope, centerTime=float(t.mean())), [f'hydraulic{j+1}', f'balance{j+1}'], 2.)
        signal = physical['mapping'][role]
        strong = any(i['kind'] in ('stuck', 'noise', 'spike') and signal in i['signals'] and
            sum(s['samples'] for s in i['intervals'] if s['start'] <= episode['end'] and s['end'] >= episode['start']) >= .3*episode['samples'] for i in related)
        if strong:
            corrected = r.copy(); corrected[:, j] = 0
            # Flow-derived hydraulic level provides an independent sensor correction.
            full_error = physical['_residuals'][:, j]
            rate = np.full(len(times), np.nan); w = c['window']
            rate[w-1:] = (full_error[w-1:]-full_error[:len(times)-w+1])/(times[w-1:]-times[:len(times)-w+1])
            corrected[:, j+2] += physical['parameters'][f'area{j+1}']*rate[available]
            if np.isfinite(corrected).all():
                candidate(f'{role}_integrity', 'sensor', corrected, {}, [f'hydraulic{j+1}', f'balance{j+1}', 'integrity_indicator'], 3.)
    for key, col in [('pump_degradation', 4), ('valve_restriction', 5), ('tank_leak', 2)]:
        amount = max(0., float(np.mean(r[:, col])))
        corrected = r.copy(); corrected[:, col] -= amount
        candidate(key, 'process', corrected, dict(unexplainedRate=amount) if col == 2 else dict(capacityLoss=amount), [physical['residuals'][col]['key']])
    candidates.sort(key=lambda a: a['penalizedError'])
    best, second = candidates[:2]
    # Scores compare explanatory corrections, not posterior causal probabilities.
    assessment = best['category'] if best['key'] != 'healthy' and best['improvement'] >= .4 and best['fitError'] < 9 and second['penalizedError']-best['penalizedError'] > .25 else 'insufficient_evidence'
    return dict(assessment=assessment, candidates=candidates, evidenceCoverage=coverage,
        lossDefinition='mean clipped squared standardized constraint residual; complexity penalty per hypothesis')
