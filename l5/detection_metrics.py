"""Time-scale detection and alarm burden on saved, explicitly labelled results.

Every in-scope truth event enters every detection denominator, including missed
and wholly abstained events. Unobserved/truncated follow-up is reported rather
than silently removed. Durations use the existing last-minus-first convention.
"""
from __future__ import annotations

import numpy as np

from .experiment_evaluation import ratio, spans

WINDOWS = {'1800': 1800, '3600': 3600, '14400': 14400, 'eventual': None}


def detection_metrics(result, labels, gap_threshold=None):
    times = np.asarray(result['times'], dtype=float)
    states = np.asarray(result['states'])
    valid, alarm = states != 'abstain', states == 'alarm'

    def phase_burden(intervals, before=None):
        samples = observed = alarms = episodes = 0
        duration = exposure = 0.
        for interval in intervals:
            mask = (times >= interval['start']) & (times <= interval['end'])
            if before is not None:
                mask &= times < before
            flags = spans(times, mask & alarm, gap_threshold)
            measured = spans(times, mask & valid, gap_threshold)
            samples += int(mask.sum())
            observed += int((mask & valid).sum())
            alarms += int((mask & alarm).sum())
            episodes += len(flags)
            duration += sum(s['end'] - s['start'] for s in flags)
            exposure += sum(s['end'] - s['start'] for s in measured)
        return dict(samples=samples, observedSamples=observed, alarmSamples=alarms,
                    alarmFraction=ratio(alarms, observed), alarmEvents=episodes, alarmDuration=duration,
                    observedSeconds=exposure, episodesPerObservedHour=ratio(3600 * episodes, exposure))

    if labels is None:
        return dict(version=2, windows=None, events=[], normal=None, preInjection=None, postInjection=None)
    normal = [i for i in labels['intervals'] if i['kind'] == 'normal']
    anomalies = [i for i in labels['intervals'] if i['kind'] == 'anomaly'
                 and i['end'] >= times[0] and i['start'] <= times[-1]]
    events = []
    for interval in anomalies:
        inside = (times >= interval['start']) & (times <= interval['end'])
        observed = times[inside & valid]
        onset = interval.get('onset', interval['start'])
        detections = times[inside & alarm]
        first = float(detections[0]) if len(detections) else None
        events.append(dict(onset=onset, start=interval['start'], end=interval['end'],
                           observedSamples=len(observed), firstObserved=float(observed[0]) if len(observed) else None,
                           firstDetection=first, delay=first-onset if first is not None else None,
                           followUpSeconds=max(0., min(float(times[-1]), interval['end'])-onset)))
    windows = {}
    for key, horizon in WINDOWS.items():
        hits = sum(v['delay'] is not None and (horizon is None or v['delay'] <= horizon) for v in events)
        windows[key] = dict(detectedEvents=hits, totalEvents=len(events), rate=ratio(hits, len(events)),
                            unobservedEvents=sum(v['firstObserved'] is None or
                                (horizon is not None and v['firstObserved'] - v['onset'] > horizon) for v in events),
                            truncatedEvents=sum(v['followUpSeconds'] < (v['end']-v['onset'] if horizon is None else horizon) for v in events))
    return dict(version=2, windows=windows, events=events, normal=phase_burden(normal),
                preInjection=phase_burden(normal, min(v['onset'] for v in events)) if events else None,
                postInjection=phase_burden(anomalies) if events else None)
