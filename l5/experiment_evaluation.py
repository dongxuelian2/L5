"""Detection behavior and explicitly labelled evaluation, on native dataset seconds.

Intervals are closed. Unlabelled and abstained samples never enter a confusion
matrix. Event recall counts only truth events with at least one evaluable sample;
false-alarm events count contiguous alarms on explicitly normal observations.
"""
from __future__ import annotations

import math
import numpy as np


RULES = {
    'time': 'Closed intervals in dataset-native elapsed seconds; clock and label version are snapshotted.',
    'samples': 'Only explicitly labelled, non-abstained samples enter TP/FP/TN/FN. Unlabelled time is unknown, never normal.',
    'scope': 'Precision and F1 apply only to reviewed intervals. Positive-only labels cannot measure false alarms outside those intervals; false alarm rate is undefined without evaluated normal samples.',
    'events': 'Truth events with any evaluated samples are eligible. A hit needs an alarm sample inside that event. Events without observations are excluded and counted separately.',
    'falseAlarmEvents': 'Contiguous alarm samples inside explicit normal labels; split at label, abstention and acquisition gaps. This is not sample-level FP.',
    'delay': 'First alarm sample inside each truth event minus its original start, even if the evaluation window starts later. Missed or unobserved events have null delay.',
    'duration': 'Sum of last minus first sample times in contiguous alarm spans; point alarms have zero duration. Acquisition gaps are excluded.',
    'scores': 'Scores, thresholds and contribution magnitudes retain each algorithm’s own scale; they are not an accuracy ranking.',
}


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def validate_intervals(intervals, time_range):
    if not isinstance(intervals, list) or not intervals or len(intervals) > 2000:
        raise ValueError('Provide 1–2000 explicit normal/anomaly label intervals.')
    clean = []
    for item in intervals:
        if not isinstance(item, dict) or item.get('kind') not in ('normal', 'anomaly'):
            raise ValueError('Each label interval needs kind normal or anomaly.')
        start, end = item.get('start'), item.get('end')
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (start, end)):
            raise ValueError('Label times must be finite dataset-native seconds.')
        if not time_range[0] <= start <= end <= time_range[1]:
            raise ValueError('Label intervals must lie inside the dataset time range.')
        interval = dict(kind=item['kind'], start=float(start), end=float(end))
        if 'onset' in item:
            onset = item['onset']
            if isinstance(onset, bool) or not isinstance(onset, (int, float)) or not math.isfinite(onset) or onset > start:
                raise ValueError('An original truth onset must be finite and no later than the labelled event start.')
            interval['onset'] = float(onset)
        clean.append(interval)
    clean.sort(key=lambda i: (i['start'], i['end']))
    if any(a['end'] >= b['start'] for a, b in zip(clean, clean[1:])):
        raise ValueError('Closed label intervals must not overlap or share endpoints.')
    return clean


def spans(times, mask, gap_threshold=None):
    result, start, last = [], None, None
    for t, active in zip(times, mask):
        if start is not None and (not active or (gap_threshold and t - last > gap_threshold)):
            result.append(dict(start=float(start), end=float(last)))
            start = None
        if active:
            if start is None:
                start = t
            last = t
    if start is not None:
        result.append(dict(start=float(start), end=float(last)))
    return result


def evaluate(result, labels=None, gap_threshold=None):
    times = np.asarray(result['times'])
    states = np.asarray(result['states'])
    alarm, valid = states == 'alarm', states != 'abstain'
    alarms = spans(times, alarm, gap_threshold)
    behavior = dict(totalSamples=len(times), validSamples=int(valid.sum()), abstainedSamples=int((~valid).sum()),
                    coverageFraction=float(valid.mean()), alarmSamples=int(alarm.sum()),
                    alarmFraction=ratio(int(alarm.sum()), int(valid.sum())),
                    alarmTotalFraction=float(alarm.mean()), alarmIntervalCount=len(alarms), alarmSpans=alarms,
                    alarmDuration=sum(s['end'] - s['start'] for s in alarms),
                    firstDetection=float(times[alarm][0]) if alarm.any() else None,
                    durationMs=result['durationMs'], relatedSignals=result['relatedSignals'])
    from .detection_metrics import detection_metrics
    detection = detection_metrics(result, labels, gap_threshold)
    if labels is None:
        return dict(behavior=behavior, labelled=None, detection=detection)
    truth = np.full(len(times), -1, dtype=int)
    label_index = np.full(len(times), -1, dtype=int)
    for index, interval in enumerate(labels['intervals']):
        mask = (times >= interval['start']) & (times <= interval['end'])
        truth[mask] = int(interval['kind'] == 'anomaly')
        label_index[mask] = index
    evaluated = valid & (truth >= 0)
    tp = int((evaluated & alarm & (truth == 1)).sum())
    fp = int((evaluated & alarm & (truth == 0)).sum())
    tn = int((evaluated & ~alarm & (truth == 0)).sum())
    fn = int((evaluated & ~alarm & (truth == 1)).sum())
    sample = dict(TP=tp, FP=fp, TN=tn, FN=fn, precision=ratio(tp, tp+fp), recall=ratio(tp, tp+fn),
                  f1=ratio(2*tp, 2*tp+fp+fn), falseAlarmRate=ratio(fp, fp+tn),
                  evaluatedSamples=int(evaluated.sum()), unlabelledSamples=int((truth < 0).sum()),
                  labelledAbstainedSamples=int(((truth >= 0) & ~valid).sum()))
    events = []
    for index, interval in enumerate(labels['intervals']):
        if interval['kind'] != 'anomaly' or interval['end'] < times[0] or interval['start'] > times[-1]:
            continue
        inside = label_index == index
        observed = inside & valid
        detections = times[inside & alarm]
        first = float(detections[0]) if len(detections) else None
        events.append(dict(**interval, observedSamples=int(observed.sum()),
                           abstainedSamples=int((inside & ~valid).sum()), detected=first is not None,
                           firstDetection=first, delay=first-interval.get('onset', interval['start']) if first is not None else None))
    eligible = [event for event in events if event['observedSamples']]
    hits = sum(event['detected'] for event in eligible)
    # Distinct normal annotation intervals are separate evaluation episodes.
    false_events = []
    for index, interval in enumerate(labels['intervals']):
        if interval['kind'] == 'normal':
            false_events.extend(spans(times, (label_index == index) & alarm, gap_threshold))
    event = dict(eligibleEvents=len(eligible), detectedEvents=hits, missedEvents=len(eligible)-hits,
                 unobservedEvents=len(events)-len(eligible), recall=ratio(hits, len(eligible)),
                 falseAlarmEvents=len(false_events), falseAlarmSpans=false_events, events=events,
                 firstDetectionDelay=next((v['delay'] for v in events if v['delay'] is not None), None))
    return dict(behavior=behavior, detection=detection, labelled=dict(labelSetId=labels['id'], version=labels['version'],
                                               source=labels['source'], sample=sample, event=event))
