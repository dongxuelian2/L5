"""Frozen operating-mode recognition and chronological anomaly monitoring."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from itertools import combinations
from math import isfinite

import numpy as np

from .analysis import build_monitor, signal_contributions
from .monitoring import calibrate


DETECTORS = ('robust-maxz', 'pca-q', 'pca-t2')


def _number(value, lower, upper, name, *, inclusive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{name} must be a finite number.')
    try:
        value = float(value)
    except OverflowError as error:
        raise ValueError(f'{name} must be a finite number.') from error
    if not isfinite(value):
        raise ValueError(f'{name} must be a finite number.')
    valid = lower <= value <= upper if inclusive else lower < value < upper
    if not valid:
        raise ValueError(f'{name} is outside its supported range.')
    return value


def _count(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f'{name} must be a positive sample count.')
    return value


def _detector_settings(raw, defaults):
    if not isinstance(raw, dict):
        raise ValueError('Detector settings must be an object.')
    algorithm = raw.get('algorithm', defaults['algorithm'])
    if algorithm not in DETECTORS:
        raise ValueError('Choose Robust Max-Z, PCA-Q, or PCA-T² for regime monitoring.')
    alpha = _number(raw.get('alpha', defaults['alpha']), 0, .5, 'Detector alpha')
    variance = _number(raw.get('variance', defaults['variance']), 0, 1, 'PCA variance')
    if variance < .5:
        raise ValueError('PCA variance must be at least 0.5.')
    return {'algorithm': algorithm, 'alpha': alpha, 'variance': variance}


def _settings(raw, signals, modes):
    if not isinstance(raw, dict):
        raise ValueError('Regime settings must be an object.')
    recognition = raw.get('recognitionSignals', signals)
    if (not isinstance(recognition, (list, tuple)) or not recognition
            or any(name not in signals for name in recognition) or len(set(recognition)) != len(recognition)):
        raise ValueError('Select unique recognition signals from the detector inputs.')
    default = _detector_settings(raw, {'algorithm': 'robust-maxz', 'alpha': .01, 'variance': .9})
    overrides = raw.get('detectors', {})
    if not isinstance(overrides, dict) or any(mode not in modes for mode in overrides):
        raise ValueError('Detector overrides must reference declared operating modes.')
    reference = raw.get('referenceMode', next(iter(modes)))
    if not isinstance(reference, str) or reference not in modes:
        raise ValueError('Choose a declared operating mode for the one-mode baseline.')
    shrinkage = _number(raw.get('shrinkage', .15), .001, 1, 'Covariance shrinkage [0.001, 1]', inclusive=True)
    return {**default, 'recognitionSignals': list(recognition), 'referenceMode': reference,
            'detectors': {mode: _detector_settings(value, default) for mode, value in overrides.items()},
            'recognitionAlpha': _number(raw.get('recognitionAlpha', .01), 0, .5, 'Recognition alpha'),
            'shrinkage': shrinkage, 'minMargin': _number(raw.get('minMargin', 2), 0, float('inf'), 'Recognition margin', inclusive=True),
            'dwell': _count(raw.get('dwell', 4), 'Regime dwell'),
            'persistence': _count(raw.get('persistence', 1), 'Alarm persistence')}


def _matrix(values, width):
    matrix = np.asarray(values, dtype=float)
    if matrix.ndim != 2 or matrix.shape[1] != width or not len(matrix):
        raise ValueError(f'Expected a nonempty matrix of {width} selected signals.')
    return matrix


def _partition(values, width):
    matrix = _matrix(values, width)
    matrix = matrix[np.isfinite(matrix).all(axis=1)]
    if len(matrix) < 30:
        raise ValueError('Every regime needs at least 30 complete fit and 30 complete calibration observations.')
    return matrix


def _scores(monitor, values, covered):
    scores = np.full(len(values), np.nan)
    if covered.any():
        scores[covered] = monitor.score(values[covered])
        if not np.isfinite(scores[covered]).all():
            raise ValueError('Selected measurements produced nonfinite model scores.')
    return scores


@dataclass
class Detector:
    config: dict
    monitor: object
    threshold: float

    @classmethod
    def fit(cls, config, fit, calibration):
        monitor = build_monitor(config['algorithm'], config)
        monitor.fit(fit)
        return cls(config, monitor, calibrate(monitor, calibration, config['alpha']))

    def to_dict(self):
        monitor = self.monitor
        result = {**self.config, 'threshold': self.threshold, 'center': monitor.center.tolist(),
                  'scale': monitor.scale.tolist(), 'metadata': monitor.metadata()}
        if hasattr(monitor, 'components'):
            result.update(loadings=monitor.components.tolist(), eigenvalues=monitor.eigenvalues.tolist(),
                          retainedVariance=monitor.retained_variance)
        return result

    @classmethod
    def from_dict(cls, raw):
        config = {key: raw[key] for key in ('algorithm', 'alpha', 'variance')}
        monitor = build_monitor(config['algorithm'], config)
        monitor.center = np.asarray(raw['center'], dtype=float)
        monitor.scale = np.asarray(raw['scale'], dtype=float)
        monitor.features = len(monitor.center)
        if config['algorithm'] in ('pca-q', 'pca-t2'):
            monitor.components = np.asarray(raw['loadings'], dtype=float)
            monitor.eigenvalues = np.asarray(raw['eigenvalues'], dtype=float)
            monitor.retained_variance = raw['retainedVariance']
        return cls(config, monitor, raw['threshold'])


class RegimeReference:
    def __init__(self, center, covariance, regularized, scale):
        self.center = center
        self.covariance = covariance
        self.regularized = regularized
        self.scale = scale
        self.cholesky = np.linalg.cholesky(regularized)
        self.log_determinant = float(2 * np.log(self.cholesky.diagonal()).sum())

    def score(self, samples):
        standardized = (samples - self.center) / self.scale
        whitened = np.linalg.solve(self.cholesky, standardized.T)
        return np.einsum('ij,ij->j', whitened, whitened)


@dataclass
class FittedRegimes:
    signals: list[str]
    config: dict
    scale: np.ndarray
    references: dict[str, RegimeReference]
    distance_thresholds: dict[str, float]
    detectors: dict[str, Detector]
    counts: dict[str, tuple[int, int]]
    global_detector: Detector
    single_detector: Detector

    def to_dict(self):
        names = self.config['recognitionSignals']
        comparisons = []
        for left, right in combinations(self.references, 2):
            delta = self.references[right].center - self.references[left].center
            standardized = delta / self.scale
            covariance_delta = self.references[right].regularized - self.references[left].regularized
            comparisons.append({'fromMode': left, 'toMode': right, 'meanDistance': float(np.linalg.norm(standardized)),
                                'covarianceDistance': float(np.linalg.norm(covariance_delta)),
                                'signals': [{'signal': name, 'meanDifference': float(d), 'standardizedDifference': float(z)}
                                            for name, d, z in zip(names, delta, standardized)]})
        return {'version': 1, 'signals': list(self.signals), 'config': deepcopy(self.config), 'scale': self.scale.tolist(),
                'modeOrder': list(self.references),
                'modes': {mode: {'center': reference.center.tolist(), 'covariance': reference.covariance.tolist(),
                                 'regularizedCovariance': reference.regularized.tolist(),
                                 'distanceThreshold': self.distance_thresholds[mode], 'fitSamples': self.counts[mode][0],
                                 'calibrationSamples': self.counts[mode][1], 'detector': self.detectors[mode].to_dict()}
                          for mode, reference in self.references.items()},
                'globalDetector': self.global_detector.to_dict(), 'singleDetector': self.single_detector.to_dict(),
                'comparisons': comparisons}

    @classmethod
    def from_dict(cls, raw):
        if raw.get('version') != 1:
            raise ValueError('Unsupported operating regime model version.')
        scale = np.asarray(raw['scale'], dtype=float)
        modes = {mode: raw['modes'][mode] for mode in raw['modeOrder']}
        references = {mode: RegimeReference(np.asarray(item['center'], dtype=float),
                                            np.asarray(item['covariance'], dtype=float),
                                            np.asarray(item['regularizedCovariance'], dtype=float), scale)
                      for mode, item in modes.items()}
        return cls(list(raw['signals']), deepcopy(raw['config']), scale, references,
                   {mode: item['distanceThreshold'] for mode, item in modes.items()},
                   {mode: Detector.from_dict(item['detector']) for mode, item in modes.items()},
                   {mode: (item['fitSamples'], item['calibrationSamples']) for mode, item in modes.items()},
                   Detector.from_dict(raw['globalDetector']), Detector.from_dict(raw['singleDetector']))


def fit_regimes(regimes, signals, config=None):
    """Fit ordered mode definitions from explicit normal fit/calibration matrices."""
    if not isinstance(regimes, dict) or len(regimes) < 2 or any(not isinstance(mode, str) or not mode.strip() for mode in regimes):
        raise ValueError('Define at least two named operating modes.')
    if (not isinstance(signals, (list, tuple)) or not signals or any(not isinstance(name, str) or not name for name in signals)
            or len(set(signals)) != len(signals)):
        raise ValueError('Select unique detector input signals in dataset column order.')
    signals = list(signals)
    settings = _settings({} if config is None else config, signals, regimes)
    indexes = [signals.index(name) for name in settings['recognitionSignals']]
    partitions = {mode: (_partition(fit, len(signals)), _partition(cal, len(signals)))
                  for mode, (fit, cal) in regimes.items()}
    # A common within-mode scale keeps units comparable without letting between-mode
    # location shifts inflate the tolerance on process measurements.
    recognition_fit = {mode: fit[:, indexes] for mode, (fit, _) in partitions.items()}
    centers = {mode: fit.mean(axis=0) for mode, fit in recognition_fit.items()}
    centered = {mode: fit - centers[mode] for mode, fit in recognition_fit.items()}
    degrees = sum(len(fit) - 1 for fit in recognition_fit.values())
    variance = sum(np.einsum('ij,ij->j', data, data) for data in centered.values()) / degrees
    magnitude = np.max([np.abs(fit).max(axis=0) for fit in recognition_fit.values()], axis=0)
    floor = np.maximum(magnitude * (64 * np.finfo(float).eps), 1e-10)
    scale = np.maximum(np.sqrt(variance), floor)
    if not np.isfinite(scale).all():
        raise ValueError('Selected measurements produced nonfinite operating-mode statistics.')

    references, thresholds, detectors, counts = {}, {}, {}, {}
    identity = np.eye(len(indexes))
    shrinkage = settings['shrinkage']
    baseline = _baseline_settings(settings)
    for mode, (fit, calibration) in partitions.items():
        differences = centered[mode]
        standardized = differences / scale
        covariance = (differences.T @ differences) / (len(fit) - 1)
        correlation_scale = (standardized.T @ standardized) / (len(fit) - 1)
        regularized = (1 - shrinkage) * correlation_scale + shrinkage * identity
        if not np.isfinite(covariance).all() or not np.isfinite(regularized).all():
            raise ValueError('Selected measurements produced nonfinite operating-mode covariance.')
        reference = RegimeReference(centers[mode], covariance, regularized, scale)
        references[mode] = reference
        thresholds[mode] = calibrate(reference, calibration[:, indexes], settings['recognitionAlpha'])
        detectors[mode] = Detector.fit(settings['detectors'].get(mode, baseline), fit, calibration)
        counts[mode] = (len(fit), len(calibration))

    global_detector = Detector.fit(baseline, np.concatenate([fit for fit, _ in partitions.values()]),
                                   np.concatenate([cal for _, cal in partitions.values()]))
    single_detector = Detector.fit(baseline, *partitions[settings['referenceMode']])
    return FittedRegimes(signals, settings, scale, references, thresholds, detectors, counts, global_detector, single_detector)


def _baseline_settings(settings):
    return {key: settings[key] for key in ('algorithm', 'alpha', 'variance')}


def _recognize(model, distances, index):
    evidence, supported = {}, []
    for mode, reference in model.references.items():
        distance = float(distances[mode][index])
        if not isfinite(distance):
            return 'insufficient', None, None, {}
        threshold = model.distance_thresholds[mode]
        discriminant = distance + reference.log_determinant
        inside = distance <= threshold
        evidence[mode] = {'distance': distance, 'threshold': threshold, 'discriminant': discriminant, 'supported': inside}
        if inside:
            supported.append((discriminant, mode))
    if not supported:
        return 'unknown', None, None, evidence
    supported.sort()
    margin = supported[1][0] - supported[0][0] if len(supported) > 1 else None
    if margin is not None and (margin == 0 or margin < model.config['minMargin']):
        return 'ambiguous', None, margin, evidence
    return 'supported', supported[0][1], margin, evidence


@dataclass
class AlarmPersistence:
    consecutive: int
    mode: str | None = None
    count: int = 0

    def update(self, score, threshold, mode, gap):
        if gap or mode != self.mode:
            self.count = 0
        self.mode = mode
        self.count = self.count + 1 if score is not None and score > threshold else 0
        return self.count >= self.consecutive


class RecognitionSequence:
    def __init__(self, dwell):
        self.dwell = dwell
        self.active = None
        self.pending = None
        self.count = 0
        self.excursion = None
        self.events = []

    def _close(self, time, outcome):
        if self.pending is not None:
            self.pending.update(outcome=outcome, resolvedTime=time, candidateSamples=self.count)
            if outcome == 'confirmed':
                self.pending['confirmedTime'] = time
            self.events.append(self.pending)
        self.pending = None
        self.count = 0

    def update(self, time, hypothesis, margin, gap, insufficient):
        if gap or insufficient:
            self._close(time, 'transient')
            self.excursion = None
        if hypothesis == self.active:
            self._close(time, 'transient')
            self.excursion = None
            return self.active, False, 0
        if not insufficient and self.excursion is None:
            self.excursion = time
        if hypothesis is None:
            self._close(time, 'transient')
            return None, False, 0

        if self.pending is None or self.pending['toMode'] != hypothesis:
            self._close(time, 'transient')
            self.pending = {'fromMode': self.active, 'toMode': hypothesis, 'startTime': self.excursion,
                            'candidateTime': time, 'confirmedTime': None, 'initialMargin': margin}
        self.pending['endTime'] = time
        self.count += 1
        count = self.count
        switching = self.active is not None
        if count == self.dwell:
            self.active = hypothesis
            self._close(time, 'confirmed')
            self.excursion = None
            return self.active, switching, count
        return None, switching, count


def _value_at(scores, index):
    value = float(scores[index])
    return value if isfinite(value) else None


def _alarm_intervals(model, decisions, values):
    intervals = []
    begin = 0
    while begin < len(decisions):
        first = decisions[begin]
        if not first['alarm']:
            begin += 1
            continue
        mode, kind = first['scoringMode'], first['alarmKind']
        end = begin + 1
        while end < len(decisions):
            row = decisions[end]
            if not row['alarm'] or row['gapBefore'] or row['scoringMode'] != mode or row['alarmKind'] != kind:
                break
            end += 1
        peak = max(range(begin, end), key=lambda index: decisions[index]['score'])
        contributions = signal_contributions(model.detectors[mode].monitor, values[peak], model.signals)
        intervals.append({'start': first['time'], 'end': decisions[end - 1]['time'], 'samples': end - begin,
                          'peakScore': decisions[peak]['score'], 'peakTime': decisions[peak]['time'],
                          'threshold': first['threshold'], 'mode': mode, 'kind': kind,
                          'signals': [item['signal'] for item in contributions[:5]], 'contributions': contributions})
        begin = end
    return intervals


def evaluate_regimes(model, times, values, *, gap_threshold=None):
    """Run a fresh causal sequence using a frozen operating regime model."""
    data = _matrix(values, len(model.signals))
    times = np.asarray(times, dtype=float)
    if times.shape != (len(data),) or not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
        raise ValueError('Evaluation times must be finite, strictly increasing, and match the samples.')
    if gap_threshold is not None:
        gap_threshold = _number(gap_threshold, 0, float('inf'), 'Gap threshold')
    names = model.config['recognitionSignals']
    recognition_data = data[:, [model.signals.index(name) for name in names]]
    recognition_covered = np.isfinite(recognition_data).all(axis=1)
    covered = np.isfinite(data).all(axis=1)
    distances = {mode: _scores(ref, recognition_data, recognition_covered) for mode, ref in model.references.items()}
    scores = {mode: _scores(detector.monitor, data, covered) for mode, detector in model.detectors.items()}
    global_scores = _scores(model.global_detector.monitor, data, covered)
    single_scores = _scores(model.single_detector.monitor, data, covered)

    sequence = RecognitionSequence(model.config['dwell'])
    persistence = model.config['persistence']
    alarm_state, global_state, single_state = (AlarmPersistence(persistence) for _ in range(3))
    decisions = []
    for index, time in enumerate(times.tolist()):
        gap = bool(index and gap_threshold is not None and time - times[index - 1] > gap_threshold)
        recognition, candidate, margin, evidence = _recognize(model, distances, index)
        mode, transition, count = sequence.update(time, candidate, margin, gap, recognition == 'insufficient')
        # Classification uses recognition evidence exclusively. An unsupported or ambiguous
        # observation remains unclassified while the last confirmed detector can still alarm.
        scoring_mode = candidate if candidate is not None else sequence.active
        detector = model.detectors.get(scoring_mode)
        score = _value_at(scores[scoring_mode], index) if detector else None
        threshold = detector.threshold if detector else None
        alarm = alarm_state.update(score, threshold, scoring_mode, gap)
        global_score = _value_at(global_scores, index)
        single_score = _value_at(single_scores, index)
        global_alarm = global_state.update(global_score, model.global_detector.threshold, None, gap)
        single_alarm = single_state.update(single_score, model.single_detector.threshold, None, gap)

        context = 'transition' if transition else 'mode' if mode is not None and score is not None else 'unknown'
        status = 'abnormal' if alarm else 'unknown' if score is None else 'normal' if context == 'mode' else context
        decisions.append({'time': time, 'mode': mode, 'activeMode': sequence.active, 'candidateMode': candidate,
                          'candidateSamples': count, 'scoringMode': scoring_mode, 'recognition': recognition,
                          'evidence': evidence, 'margin': margin, 'transition': transition, 'gapBefore': gap,
                          'status': status, 'alarm': alarm, 'alarmKind': context if alarm else None,
                          'score': score, 'threshold': threshold,
                          'globalScore': global_score, 'globalAlarm': global_alarm, 'globalThreshold': model.global_detector.threshold,
                          'singleScore': single_score, 'singleAlarm': single_alarm, 'singleThreshold': model.single_detector.threshold})

    sequence._close(float(times[-1]), 'pending')
    transitions = [event for event in sequence.events if event['fromMode'] is not None]
    intervals = _alarm_intervals(model, decisions, data)
    summary = {'samples': len(decisions), 'normalSamples': sum(row['status'] == 'normal' for row in decisions),
               'unknownSamples': sum(row['status'] == 'unknown' for row in decisions),
               'unrecognizedSamples': sum(row['mode'] is None for row in decisions),
               'ambiguousSamples': sum(row['recognition'] == 'ambiguous' for row in decisions),
               'insufficientSamples': sum(row['recognition'] == 'insufficient' for row in decisions),
               'transitionSamples': sum(row['transition'] for row in decisions),
               'alarmSamples': sum(row['alarm'] for row in decisions),
               'globalAlarmSamples': sum(row['globalAlarm'] for row in decisions),
               'singleAlarmSamples': sum(row['singleAlarm'] for row in decisions),
               'monitoredSamples': sum(row['score'] is not None for row in decisions),
               'globalMonitoredSamples': int(covered.sum()), 'singleMonitoredSamples': int(covered.sum()),
               'confirmedTransitions': sum(event['outcome'] == 'confirmed' for event in transitions)}
    return {'times': times.tolist(), 'decisions': decisions, 'transitions': transitions,
            'intervals': intervals, 'summary': summary}
