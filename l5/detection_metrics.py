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

    def burden(mask):
        observed, flags = mask & valid, mask & alarm
        episodes = spans(times, flags, gap_threshold)
        return dict(samples=int(mask.sum()), observedSamples=int(observed.sum()),
                    alarmSamples=int(flags.sum()), alarmFraction=ratio(int(flags.sum()), int(observed.sum())),
                    alarmEvents=len(episodes), alarmDuration=sum(s['end']-s['start'] for s in episodes))

    if labels is None:
        return dict(version=1, windows=None, events=[], normal=None, preInjection=None, postInjection=None)
    normal, anomaly = np.zeros(len(times), dtype=bool), np.zeros(len(times), dtype=bool)
    events = []
    normal_episodes = []
    for interval in labels['intervals']:
        inside = (times >= interval['start']) & (times <= interval['end'])
        if interval['kind'] == 'normal':
            normal |= inside
            normal_episodes.extend(spans(times, inside & alarm, gap_threshold))
            continue
        if interval['end'] < times[0] or interval['start'] > times[-1]:
            continue
        anomaly |= inside
        onset = interval.get('onset', interval['start'])
        detections = times[inside & alarm]
        first = float(detections[0]) if len(detections) else None
        events.append(dict(onset=onset, start=interval['start'], end=interval['end'],
                           observedSamples=int((inside & valid).sum()),
                           firstDetection=first, delay=first-onset if first is not None else None,
                           followUpSeconds=max(0., min(float(times[-1]), interval['end'])-onset)))
    windows = {}
    for key, horizon in WINDOWS.items():
        hits = sum(v['delay'] is not None and (horizon is None or v['delay'] <= horizon) for v in events)
        windows[key] = dict(detectedEvents=hits, totalEvents=len(events), rate=ratio(hits, len(events)),
                            unobservedEvents=sum(not v['observedSamples'] for v in events),
                            truncatedEvents=sum(v['followUpSeconds'] < (v['end']-v['onset'] if horizon is None else horizon) for v in events))
    normal_burden = burden(normal)
    # Distinct normal annotations remain separate episodes, even when adjacent.
    normal_burden.update(alarmEvents=len(normal_episodes), alarmDuration=sum(s['end']-s['start'] for s in normal_episodes))
    pre = np.zeros(len(times), dtype=bool)
    if events:
        pre = normal & (times < min(v['onset'] for v in events))
    return dict(version=1, windows=windows, events=events, normal=normal_burden,
                preInjection=burden(pre) if events else None, postInjection=burden(anomaly) if events else None)
