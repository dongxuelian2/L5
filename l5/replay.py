"""Chronological, prefix-scoped monitoring of saved process observations."""
from __future__ import annotations

from bisect import bisect_left
from collections import OrderedDict
import math
from threading import Lock
from uuid import uuid4

import numpy as np

from benchmarks.coverage import CoveragePolicy

from .analysis import ALGORITHMS, build_monitor, contribution_matrix, model_parameters, project_analysis, ranked_contributions
from .data_quality import cadence, segment_ids
from .independent import check_range, snapshot
from .monitoring import calibrate, split_normal_training
from .workspace import now

DETECTORS = ('robust-maxz', 'pca-q', 'ewma', 'cusum')
FRAME_ROWS = 360
ALARM_PAGE = 20
MAX_ROWS = 100_000
MAX_SIGNALS = 12


def finite_number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


class ReplaySession:
    def __init__(self, store, dataset, body):
        self.id, self.created_at = uuid4().hex, now()
        self.lock = Lock()
        self.dataset = dataset
        metadata = dataset['metadata']
        if metadata.get('transformation'):
            raise ValueError('Replay requires an original dataset or a saved simulation. Derived values can use future measurements.')
        columns = [column['name'] for column in metadata['columns']]
        signals = body.get('signals')
        if (not isinstance(signals, list) or not 1 <= len(signals) <= MAX_SIGNALS
                or any(not isinstance(s, str) or s not in columns for s in signals)
                or len(set(signals)) != len(signals)):
            raise ValueError('Select 1–12 unique replay signals from the dataset.')
        algorithm = body.get('algorithm')
        if algorithm not in DETECTORS:
            raise ValueError('Choose a replay detector.')
        alpha, persistence = body.get('alpha', .01), body.get('persistence', 1)
        if not finite_number(alpha) or not 0 < alpha < .5:
            raise ValueError('Calibration alpha must be between 0 and 0.5.')
        if type(persistence) is not int or persistence < 1:
            raise ValueError('Alarm persistence must be a positive whole number.')
        config = dict(datasetId=dataset['id'], signals=signals, algorithm=algorithm, alpha=alpha,
                      persistence=persistence, fitFraction=.7, observationPolicy='measured', minCoverage=1)
        for key, default in {'pca-q': {'variance': .9}, 'ewma': {'smoothing': .25},
                             'cusum': {'reference': .5}}.get(algorithm, {}).items():
            value = body.get(key, default)
            if not finite_number(value):
                raise ValueError('Detector parameters must be finite numbers.')
            config[key] = value

        times, values = store.load_data(dataset)
        order = np.argsort(times, kind='stable')
        times = times[order]
        baseline, target = body.get('baselineRange'), body.get('analysisRange')
        for interval in (baseline, target):
            check_range(interval, times[0], times[-1])
        if baseline[1] >= target[0]:
            raise ValueError('The normal baseline must finish before the analysis window starts.')
        config.update(baselineRange=baseline, analysisRange=target)
        normal_start, normal_end = times.searchsorted(baseline[0]), times.searchsorted(baseline[1], side='right')
        first, end = times.searchsorted(target[0]), times.searchsorted(target[1], side='right')
        if not 1 <= end - first <= MAX_ROWS:
            raise ValueError('Select a replay window with 1–100,000 observations.')
        indexes = [columns.index(signal) for signal in signals]
        normal = values[np.ix_(order[normal_start:normal_end], indexes)]
        if not np.isfinite(normal).all():
            raise ValueError('The normal training window needs complete measurements for every selected signal.')
        if int(len(normal) * .7) < 30 or len(normal) - int(len(normal) * .7) < 30:
            raise ValueError('Select enough normal samples for at least 30 fit and 30 calibration observations.')
        fit, calibration = split_normal_training(normal, config['fitFraction'])
        self.monitor = build_monitor(algorithm, config)
        self.monitor.fit(fit)
        self.threshold = calibrate(self.monitor, calibration, alpha)
        self.fit_samples, self.calibration_samples = len(fit), len(calibration)
        self.gap_threshold = cadence(times[normal_start:normal_end])['gapThreshold']
        self.config = config
        self.model = model_parameters(self.monitor)
        source = snapshot(store, dataset)
        self.source = {k: source[k] for k in ('id', 'name', 'workspace_id', 'created_at', 'sha256', 'sourceCsvSha256')}
        self.source['time'] = metadata['time']
        self.source['simulationId'] = metadata.get('model', {}).get('simulationId')

        self.times = times[first:end].copy()
        self.values = values[np.ix_(order[first:end], indexes)]
        self.observed = np.isfinite(self.values)
        self.weights = np.zeros_like(self.values)
        self.scores = np.zeros(len(self.times))
        self.states = []
        self.history = self.monitor.new_state() if self.monitor.history_dependent else None
        self.run = 0
        self.alarm_starts = []
        self.alarm_stops = []
        self.saved_analyses = {}
        self.saved_incidents = {}

    def describe(self):
        return dict(id=self.id, createdAt=self.created_at, config=self.config, model=self.model,
                    dataset=self.source, threshold=self.threshold, fitSamples=self.fit_samples,
                    calibrationSamples=self.calibration_samples, sampleCount=len(self.times),
                    start=float(self.times[0]), end=float(self.times[-1]), alarmPageSize=ALARM_PAGE)

    def advance(self, through):
        first = len(self.states)
        if through <= first:
            return
        valid = self.observed[first:through].all(axis=1)
        values = self.values[first:through]
        weights = np.zeros_like(values)
        scores = np.zeros(len(values))
        # Score contiguous measured spans in chunks. A missing observation
        # clears history; playback time alone never adds observations.
        history = self.history.copy() if self.history is not None else None
        boundaries = np.r_[0, np.flatnonzero(valid[1:] != valid[:-1]) + 1, len(valid)]
        for a, b in zip(boundaries[:-1], boundaries[1:]):
            if not valid[a]:
                if history is not None:
                    history.fill(0)
                continue
            span = values[a:b]
            if history is None:
                weights[a:b] = contribution_matrix(self.monitor, span)
                scores[a:b] = self.monitor.score(span)
            else:
                weights[a:b] = self.monitor.score_chunk(span, history)
                scores[a:b] = weights[a:b].max(axis=1)
        if not np.isfinite(scores).all() or not np.isfinite(weights).all():
            raise ValueError('Signal magnitudes produced nonfinite scores; check the selected measurements.')
        self.history = history
        self.weights[first:through], self.scores[first:through] = weights, scores
        previous = self.states[-1] if self.states else 'normal'
        for index, (covered, score) in enumerate(zip(valid, scores), first):
            self.run = self.run + 1 if covered and score > self.threshold else 0
            state = 'abstain' if not covered else 'alarm' if self.run >= self.config['persistence'] else 'normal'
            if state == 'alarm' and previous != 'alarm':
                self.alarm_starts.append(index)
            elif state != 'alarm' and previous == 'alarm':
                self.alarm_stops.append(index)
            self.states.append(state)
            previous = state

    def series(self, first, through):
        times, values = self.times[first:through], self.values[first:through]
        states = self.states[first:through]
        scores = np.where(np.array(states) == 'abstain', np.nan, self.scores[first:through])
        def optional(array):
            return [float(value) if np.isfinite(value) else None for value in array]
        return dict(first=first, times=times.tolist(), scores=optional(scores), states=states,
                    values={name: optional(values[:, i]) for i, name in enumerate(self.config['signals'])},
                    scoreSegments=segment_ids(times, scores, self.gap_threshold).tolist(),
                    signalSegments={name: segment_ids(times, values[:, i], self.gap_threshold).tolist()
                                    for i, name in enumerate(self.config['signals'])})

    def alarm(self, index, through):
        first = self.alarm_starts[index]
        stop = self.alarm_stops[index] if index < len(self.alarm_stops) else through
        end = min(stop, through)
        peak = first + int(np.argmax(self.scores[first:end]))
        contributions = ranked_contributions(self.weights[peak], self.config['signals'])
        start_time, end_time = float(self.times[first]), float(self.times[end - 1])
        closed = stop < through
        status = ('recovered' if self.states[stop] == 'normal' else 'interrupted') if closed else 'active'
        return dict(id=first, start=start_time, end=end_time, samples=end-first,
                    durationSeconds=end_time-start_time, peakIndex=peak, peakTime=float(self.times[peak]),
                    peakScore=float(self.scores[peak]), signals=[c['signal'] for c in contributions[:5]],
                    contributions=contributions, status=status, transitionTime=float(self.times[stop]) if closed else None)

    def frame(self, body):
        at, page = body.get('at'), body.get('alarmPage', 0)
        if not finite_number(at) or type(page) is not int or page < 0:
            raise ValueError('Replay needs a finite playhead and a valid alarm page.')
        through = int(self.times.searchsorted(at, side='right'))
        if not through:
            raise ValueError('Seek within the replay time range.')
        self.advance(through)
        count = bisect_left(self.alarm_starts, through)
        last = max(0, count - page * ALARM_PAGE)
        alarms = [self.alarm(i, through) for i in range(last - 1, max(0, last - ALARM_PAGE) - 1, -1)]
        return dict(through=through, nextTime=float(self.times[through]) if through < len(self.times) else None,
                    alarmCount=count, alarms=alarms, series=self.series(max(0, through-FRAME_ROWS), through))

    def seen(self, body):
        through = body.get('through')
        if type(through) is not int or not 1 <= through <= len(self.states):
            raise ValueError('Select an observed replay position.')
        return through

    def selected_alarm(self, body, through):
        identity = body.get('alarmId')
        if type(identity) is int and 0 <= identity < through:
            index = bisect_left(self.alarm_starts, identity)
            if index < len(self.alarm_starts) and self.alarm_starts[index] == identity:
                return index, self.alarm(index, through)
        raise ValueError('Select an alarm observed at the current replay position.')

    def evidence(self, body):
        through = self.seen(body)
        _, alarm = self.selected_alarm(body, through)
        peak = alarm['peakIndex']
        return dict(alarm=alarm, series=self.series(max(0, peak-12), min(through, peak+13)))

    def export(self, body):
        through = self.seen(body)
        speed = body.get('playbackSpeed', 1)
        if not finite_number(speed) or speed <= 0:
            raise ValueError('Playback speed must be positive and finite.')
        return dict(schemaVersion=1, **self.describe(), observedThrough=float(self.times[through-1]),
                    playbackSpeed=speed, observations=self.series(0, through),
                    alarms=[self.alarm(i, through) for i in range(bisect_left(self.alarm_starts, through))])

    def preserve(self, store, body):
        through = self.seen(body)
        index, alarm = self.selected_alarm(body, through)
        key = (through, index)
        if key in self.saved_incidents:
            return store.incidents.get(self.saved_incidents[key])
        workspace = self.dataset['workspace_id']
        if through not in self.saved_analyses:
            signals = self.config['signals']
            config = {**self.config, 'analysisRange': [float(self.times[0]), float(self.times[through-1])]}
            result = project_analysis(self.monitor, self.threshold, self.scores[:through], self.states[:through],
                self.weights[:through], self.observed[:through], self.times[:through], signals, config,
                CoveragePolicy(1, (), tuple(signals)), None,
                fit_samples=self.fit_samples, calibration_samples=self.calibration_samples,
                baseline_samples=self.fit_samples+self.calibration_samples, imputed={'baseline': 0, 'analysis': 0})
            result['replay'] = dict(id=self.id, observedSamples=through, dataset=self.source)
            result['intervals'] = [self.alarm(i, through) for i in range(bisect_left(self.alarm_starts, through))]
            name = f"Replay · {ALGORITHMS[self.config['algorithm']]} · {self.dataset['name']}"[:160]
            self.saved_analyses[through] = store.save_analysis(workspace, self.dataset, result, name)['id']
        analysis_id = self.saved_analyses[through]
        title = f"{ALGORITHMS[self.config['algorithm']]} · {alarm['start']:g} s · {self.dataset['name']}"[:160]
        incident = store.incidents.create(workspace, dict(title=title, start_time=alarm['start'], end_time=alarm['end'],
            source=dict(kind='interval', analysisId=analysis_id, intervalIndex=index)))
        self.saved_incidents[key] = incident['id']
        return incident


class ReplayService:
    def __init__(self, store):
        self.store = store
        self.sessions = OrderedDict()
        self.lock = Lock()

    def create(self, workspace, body):
        dataset = self.store.dataset(body.get('datasetId', ''))
        if dataset['workspace_id'] != workspace:
            raise ValueError('Dataset belongs to a different workspace.')
        session = ReplaySession(self.store, dataset, body)
        with self.lock:
            self.sessions[session.id] = session
            if len(self.sessions) > 6:
                self.sessions.popitem(last=False)
        return session.describe()

    def operate(self, workspace, identity, operation, body):
        self.store.workspace(workspace)
        with self.lock:
            session = self.sessions.get(identity)
            if session is None or session.dataset['workspace_id'] != workspace:
                raise KeyError('Replay session is unavailable. Prepare a new replay.')
            self.sessions.move_to_end(identity)
        with session.lock:
            if operation == 'incident':
                return session.preserve(self.store, body)
            return {'frame': session.frame, 'evidence': session.evidence, 'export': session.export}[operation](body)
