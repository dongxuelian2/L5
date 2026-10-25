"""Fit/calibration on declared normal datasets; fresh scoring per test sequence."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from time import perf_counter

import numpy as np

from .analysis import ALGORITHMS, build_monitor, score_analysis
from .monitoring import calibrate


def file_hash(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def snapshot(store, dataset):
    folder = store.root / dataset['workspace_id'] / 'datasets' / dataset['id']
    return {**dataset, 'sha256': file_hash(folder / 'series.npz'), 'sourceCsvSha256': file_hash(folder / 'source.csv')}


def window(times, interval, *, minimum=1):
    check_range(interval, times[0], times[-1])
    lo, hi = interval
    mask = (times >= lo) & (times <= hi)
    if mask.sum() < minimum:
        raise ValueError(f'This partition requires at least {minimum} observations.')
    return mask


def check_range(interval, start, end):
    if not isinstance(interval, list) or len(interval) != 2 or any(isinstance(v, bool) or not isinstance(v, (float, int)) for v in interval):
        raise ValueError('Each fit, calibration and test range needs two finite dataset-native times.')
    lo, hi = interval
    if not np.isfinite(interval).all() or not start <= lo <= hi <= end:
        raise ValueError('Fit, calibration and test ranges must be inside their own dataset time axis.')


def mapping_for(reference, dataset, names, raw=None):
    """Original names/units or an explicit one-to-one map; no positional guesses."""
    columns = {c['name']: c for c in dataset['metadata']['columns']}
    source_columns = {c['name']: c for c in reference['metadata']['columns']}
    mapping = {name: name for name in names} if raw is None else raw
    if not isinstance(mapping, dict) or set(mapping) != set(names) or any(not isinstance(v, str) or v not in columns for v in mapping.values()) or len(set(mapping.values())) != len(names):
        raise ValueError('Provide a one-to-one input signal mapping by original column name.')
    left = reference['metadata'].get('external', {}).get('schema')
    right = dataset['metadata'].get('external', {}).get('schema')
    left_model, right_model = reference['metadata'].get('model'), dataset['metadata'].get('model')
    if left != right or (left and any(key != value for key, value in mapping.items())):
        raise ValueError('Incompatible external signal schemas; an explicitly verified schema adapter is required.')
    if bool(left_model) != bool(right_model) or (left_model and (left_model['id'], left_model.get('version')) != (right_model['id'], right_model.get('version'))):
        raise ValueError('Cross-model input mapping requires a verified schema adapter.')
    for name in names:
        if name not in source_columns or (source_columns[name].get('unit') or '') != (columns[mapping[name]].get('unit') or ''):
            raise ValueError('Mapped input signals must have matching physical units and verified original names.')
    return {name: mapping[name] for name in names}


def validate_training(store, workspace_id, raw):
    training = raw.get('training')
    if not isinstance(training, dict) or set(training) != {'fit', 'calibration'}:
        raise ValueError('Specify normal fit and calibration dataset references.')
    names = raw.get('signals')
    if not isinstance(names, list) or not names or any(not isinstance(s, str) for s in names) or len(set(names)) != len(names):
        raise ValueError('Select unique input signal names in fit order.')
    clean, datasets = {}, {}
    for key in ('fit', 'calibration'):
        item = training[key]
        if not isinstance(item, dict):
            raise ValueError('Each training reference needs datasetId and range.')
        dataset = store.dataset(item.get('datasetId', ''))
        if dataset['workspace_id'] != workspace_id:
            raise ValueError('All training datasets must belong to this workspace.')
        external = dataset['metadata'].get('external')
        if external and (external['split'] != 'training' or external['faultNumber'] != 0):
            raise ValueError('TEP fitting/calibration requires fault-free training runs; test or faulty sources cannot train a detector.')
        axis = dataset['metadata']['time']
        check_range(item.get('range'), axis['start'], axis['end'])
        reference = datasets.get('fit', dataset)
        mapping = mapping_for(reference, dataset, names, item.get('signalMapping'))
        clean[key] = dict(datasetId=dataset['id'], range=[float(v) for v in item['range']], signalMapping=mapping)
        datasets[key] = dataset
    fit, cal = clean['fit'], clean['calibration']
    def sequence(dataset):
        return dataset['metadata'].get('external', {}).get('sequenceId', dataset['id'])
    if sequence(datasets['fit']) == sequence(datasets['calibration']) and fit['range'][1] >= cal['range'][0]:
        raise ValueError('Fit and calibration must be disjoint and chronological within the same source run.')
    return clean, datasets


def validate_test(store, workspace_id, raw, training, datasets):
    dataset = store.dataset(raw.get('datasetId', ''))
    if dataset['workspace_id'] != workspace_id:
        raise ValueError('The test dataset must belong to this workspace.')
    source = dataset['metadata'].get('external', {})
    if any(dataset['id'] == d['id'] or (source.get('sequenceId') and source['sequenceId'] == d['metadata'].get('external', {}).get('sequenceId')) for d in datasets.values()):
        raise ValueError('Test runs must be independent of both fit and calibration sources, including re-imported copies.')
    if source and source['split'] != 'testing':
        raise ValueError('Use official testing runs for independent TEP evaluation.')
    axis = dataset['metadata']['time']
    check_range(raw.get('analysisRange'), axis['start'], axis['end'])
    mapping = mapping_for(datasets['fit'], dataset, raw['signals'], raw.get('signalMapping'))
    return dataset, mapping


def selected(store, dataset, interval, mapping, policy, *, minimum=1):
    times, values = store.load_data(dataset)
    mask = window(times, interval, minimum=minimum)
    names = [c['name'] for c in dataset['metadata']['columns']]
    indexes = [names.index(value) for value in mapping.values()]
    data = values[mask][:, indexes].copy()
    observed = store.observation_mask(dataset)[mask][:, indexes]
    if policy == 'measured':
        data[~observed] = np.nan
    elif policy != 'processed':
        raise ValueError('Choose measured or processed observations.')
    return times[mask], data


def cadence(times):
    periods = np.diff(times)
    if len(periods) and (np.any(periods <= 0) or not np.allclose(periods, periods[0], rtol=1e-5, atol=1e-7)):
        raise ValueError('Temporal algorithms require regular, strictly increasing sample times in each independent partition.')
    return float(periods[0]) if len(periods) else None


@dataclass
class FittedDetector:
    monitor: object
    threshold: float
    medians: np.ndarray
    policy: object
    fit_samples: int
    calibration_samples: int
    missing: int
    period: float | None
    provenance: dict
    duration_ms: float
    key: str


def training_key(config):
    # Test identities, ranges, labels and measurements never enter this key.
    keys = ('training', 'signals', 'algorithm', 'alpha', 'variance', 'smoothing', 'reference', 'window', 'lags', 'rate', 'guard', 'maxShift', 'observationPolicy', 'minCoverage', 'requiredSignals')
    return hashlib.sha256(json.dumps({k: config[k] for k in keys if k in config}, sort_keys=True).encode()).hexdigest()


def fit_detector(store, workspace_id, config):
    from benchmarks.coverage import CoveragePolicy
    started = perf_counter()
    training, datasets = validate_training(store, workspace_id, config)
    names = config['signals']
    algorithm = config.get('algorithm')
    if algorithm not in ALGORITHMS:
        raise ValueError('Choose an available detection algorithm.')
    policy = CoveragePolicy(float(config.get('minCoverage', .9)), tuple(config.get('requiredSignals', [])), tuple(names))
    observations = config.get('observationPolicy', 'measured')
    fit_times, fit = selected(store, datasets['fit'], training['fit']['range'], training['fit']['signalMapping'], observations, minimum=30)
    cal_times, cal = selected(store, datasets['calibration'], training['calibration']['range'], training['calibration']['signalMapping'], observations, minimum=30)
    if not np.isfinite(fit).any(axis=0).all():
        raise ValueError('Every selected signal needs finite measurements in normal fit data.')
    medians = np.nanmedian(fit, axis=0)
    monitor = build_monitor(algorithm, config)
    temporal = getattr(monitor, 'history_dependent', False)
    period = cadence(fit_times) if temporal else None
    if temporal and cadence(cal_times) != period:
        raise ValueError('Temporal fit and calibration sampling intervals must agree.')
    required = [names.index(s) for s in policy.required_channels]
    covered_arrays = []
    missing = 0
    for data in (fit, cal):
        observed = np.isfinite(data)
        covered = observed.mean(axis=1) >= policy.min_observed_fraction
        if required:
            covered &= observed[:, required].all(axis=1)
        if temporal and not covered.all():
            raise ValueError('Temporal fitting/calibration needs fully covered contiguous training sequences.')
        data = data[covered]
        if len(data) < 30:
            raise ValueError('Need at least 30 covered fit and 30 covered calibration rows.')
        missing += int((~np.isfinite(data)).sum())
        covered_arrays.append(np.where(np.isfinite(data), data, medians))
    fit, cal = covered_arrays
    monitor.fit(fit)
    threshold = calibrate(monitor, cal, float(config.get('alpha', .01)))
    sources = {key: dict(**training[key], dataset=snapshot(store, dataset)) for key, dataset in datasets.items()}
    provenance = dict(version=1, sources=sources, stateReset='Each test run and abstention boundary starts fresh; calibration state is never carried into test.',
                      featureOrder=names, protocol='Normal fit statistics, independent normal calibration quantile, frozen before test scoring.')
    return FittedDetector(monitor, threshold, medians, policy, len(fit), len(cal), missing, period, provenance,
                          round((perf_counter()-started)*1000, 2), training_key(config))


def score_detector(store, workspace_id, config, fitted):
    started = perf_counter()
    stress = config.get('stress') or {}
    if any(stress.get(k) for k in ('missingFraction', 'noise', 'offset', 'missingSignals')):
        raise ValueError('Independent evaluation scores original test measurements. Use an explicitly derived dataset for a declared perturbation.')
    if training_key(config) != fitted.key:
        raise ValueError('Fitted model does not match the declared training and detector configuration.')
    # Validation reads dataset metadata only; training never receives test arrays.
    training, datasets = validate_training(store, workspace_id, config)
    dataset, mapping = validate_test(store, workspace_id, config, training, datasets)
    times, target = selected(store, dataset, config['analysisRange'], mapping, config.get('observationPolicy', 'measured'))
    if fitted.period is not None and len(times) > 1 and cadence(times) != fitted.period:
        raise ValueError('Temporal test sampling interval must match the fitted model.')
    observed = np.isfinite(target)
    missing = int((~observed).sum())
    target = np.where(observed, target, fitted.medians)
    effective = {**config, 'training': training, 'signalMapping': mapping, 'baselineRange': training['fit']['range']}
    result = score_analysis(fitted.monitor, fitted.threshold, target, observed, times, list(mapping.values()), effective,
        fitted.policy, fitted.medians, fit_samples=fitted.fit_samples, calibration_samples=fitted.calibration_samples,
        baseline_samples=fitted.fit_samples+fitted.calibration_samples,
        imputed=dict(baseline=fitted.missing, analysis=missing), started=started)
    result['training'] = {**fitted.provenance, 'modelKey': fitted.key, 'fitDurationMs': fitted.duration_ms,
                          'test': dict(dataset=snapshot(store, dataset), range=config['analysisRange'], signalMapping=mapping)}
    result['external'] = dataset['metadata'].get('external')
    return result
