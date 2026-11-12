"""Evaluate saved-result correlation against independently scripted incidents."""
from __future__ import annotations

import json
from collections import Counter
from time import perf_counter

from l5.alarms import extract_events, flood_metrics, group_alarms, normalize_policy


def detector_trace(name, dataset, detector, signal, episodes, *, offset=0, axis='utc',
                   abstain=(), gaps=(), secondary=()):
    """Build an AnalysisResult and keep the scripted physical labels outside it."""
    labels = {t: cause for start, end, cause in episodes for t in range(start, end + 1)}
    times = [t for t in range(min(labels) - 2, max(labels) + 3) if t not in gaps]
    states = ['abstain' if t in abstain else 'alarm' if t in labels else 'normal' for t in times]
    scores = [0. if state == 'abstain' else 8. if state == 'alarm' else 1. for state in states]
    signals = [signal, *secondary]
    contributions = [dict(signal=signal, value=8.), *(dict(signal=s, value=.4) for s in secondary)]
    intervals = []
    for index, state in enumerate(states):
        if state != 'alarm':
            continue
        t = times[index]
        if index and states[index - 1] == 'alarm':
            intervals[-1]['end'] = t
            intervals[-1]['samples'] += 1
        else:
            intervals.append(dict(start=t, end=t, samples=1, peakTime=t, peakScore=8.,
                                  signals=signals, contributions=contributions))
    result = dict(id=name, datasetId=dataset, name=name, algorithmLabel=detector,
                  config=dict(algorithm=detector, signals=sorted(signals)), times=times, states=states,
                  observedFraction=[0. if state == 'abstain' else 1. for state in states],
                  scores=scores, threshold=3., intervals=intervals)
    source = dict(id=dataset, name=dataset, metadata=dict(quality=dict(gapThreshold=2.)))
    clock = dict(key='dataset:' + dataset, axisId=axis, offset=offset, label=axis)
    return result, source, clock, labels


def operational_scenario():
    traces = [
        # The pump bearing fails once. It causes three separated vibration
        # excursions and a concurrent low-flow response on a second recorder.
        detector_trace('pump-z', 'plant', 'max-z', 'vibration',
                       [(100, 102, 'bearing'), (105, 106, 'bearing'), (109, 109, 'bearing')], secondary=['valve']),
        detector_trace('pump-ewma', 'plant', 'ewma', 'vibration', [(101, 104, 'bearing')], secondary=['valve']),
        detector_trace('flow-q', 'flow', 'pca-q', 'flow', [(21, 24, 'bearing')], offset=80),
        # The valve jams on the same pump skid, while an unrelated tank
        # overflow overlaps both faults. Their fault labels come from this script.
        detector_trace('valve-z', 'plant', 'max-z', 'valve', [(102, 105, 'stuck-valve')], secondary=['vibration']),
        detector_trace('tank-z', 'plant', 'max-z', 'level', [(103, 108, 'overflow')]),
        # This other experiment has identical relative seconds and signal names.
        detector_trace('bench-z', 'bench', 'max-z', 'vibration', [(100, 102, 'bench-slip')],
                       axis='dataset:bench'),
        # One temperature upset straddles an acquisition gap. A later pulse in
        # the same trace is separated by an explicit abstention.
        detector_trace('heat-z', 'plant', 'max-z', 'temperature',
                       [(201, 209, 'heater-upset'), (211, 211, 'background-heat')],
                       gaps=range(203, 208), abstain=(210,)),
        detector_trace('background-z', 'plant', 'max-z', 'pressure', [(103, 103, 'background-pressure')]),
    ]
    mappings = [
        dict(datasetId='plant', signal='vibration', equipment='Pump skid'),
        dict(datasetId='plant', signal='valve', equipment='Pump skid'),
        dict(datasetId='flow', signal='flow', equipment='Pump skid'),
        dict(datasetId='plant', signal='level', equipment='Tank'),
        dict(datasetId='plant', signal='temperature', equipment='Heater'),
    ]
    relationships = [
        dict(left=dict(datasetId='plant', signal='vibration'), right=dict(datasetId='flow', signal='flow')),
        dict(left=dict(datasetId='plant', signal='vibration'), right=dict(datasetId='bench', signal='vibration')),
    ]
    return traces, dict(mappings=mappings, relationships=relationships, proximitySeconds=2,
                        repeatWindowSeconds=4, floodWindowSeconds=60)


def flood_scenario(cycles=300):
    traces, mappings = [], []
    for equipment in range(4):
        signal = f'flow-{equipment}'
        faults = [(10 * i, 10 * i + 2, f'equipment-{equipment}-fault-{i}') for i in range(cycles)]
        mappings.append(dict(datasetId='plant', signal=signal, equipment=f'Unit {equipment}'))
        for detector in ('max-z', 'pca-q', 'ewma'):
            traces.append(detector_trace(f'{signal}-{detector}', 'plant', detector, signal, faults))
    traces.append(detector_trace('noise-z', 'plant', 'max-z', 'noise',
                                 [(10 * i + 5, 10 * i + 5, f'background-{i}') for i in range(cycles)]))
    return traces, dict(mappings=mappings, proximitySeconds=2, repeatWindowSeconds=4, floodWindowSeconds=60)


def pairs(count):
    return count * (count - 1) // 2


def evaluate(scenario):
    traces, settings = scenario
    policy = normalize_policy(settings)
    events, truth = [], {}
    alarm_samples = sum(result['states'].count('alarm') for result, *_ in traces)
    started = perf_counter()
    for result, dataset, clock, labels in traces:
        for event in extract_events(result, dataset, clock):
            truth[event['id']] = labels[event['nativeStart']]
            events.append(event)
    grouped = group_alarms(events, policy)
    groups = grouped['groups']
    flood = flood_metrics(grouped['events'], groups, policy)
    elapsed = perf_counter() - started

    actual_pairs = sum(pairs(len(group['eventIds'])) for group in groups)
    truth_pairs = sum(pairs(count) for count in Counter(truth.values()).values())
    matched_pairs = sum(pairs(count) for group in groups
                        for count in Counter(truth[i] for i in group['eventIds']).values())
    raw = len(events)
    return dict(rawEventCount=raw, groupCount=len(groups), trueRelatedPairs=matched_pairs,
                incorrectMergePairs=actual_pairs - matched_pairs, incorrectSplitPairs=truth_pairs - matched_pairs,
                eventPreserved=Counter(truth.keys()) == Counter(i for group in groups for i in group['eventIds']),
                alarmSamplesPreserved=alarm_samples == sum(event['samples'] for event in events),
                workloadReductionFraction=(raw - len(groups)) / raw if raw else 0.,
                axes=[dict(axisId=axis['axisId'], windowSeconds=axis['windowSeconds'],
                           peakArrivalCount=axis['peakArrivalCount'], peakConcurrent=axis['peakConcurrent'])
                      for axis in flood['axes']],
                elapsedMs=round(elapsed * 1000, 2))


if __name__ == '__main__':
    traces, settings = operational_scenario()
    print(json.dumps(dict(operational=evaluate((traces, settings)),
                          equipmentGrouping=evaluate((traces, {**settings, 'groupByEquipment': True})),
                          flood=evaluate(flood_scenario())), indent=2))
