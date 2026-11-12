"""Project saved detector evidence into operational alarms without rerunning detectors."""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from hashlib import sha256
import json
from math import floor, isfinite


DEFAULT_PRIORITIES = [
    ('high', 'High'), ('medium', 'Medium'), ('low', 'Low'), ('unclassified', 'Unclassified'),
]


def _label(value):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 200:
        raise ValueError('Enter a nonempty alarm policy label of at most 200 characters.')
    return value.strip()


def _number(value, *, minimum=0, integer=False):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or value < minimum or value > 1e15 or not isfinite(value) or (integer and int(value) != value)):
        raise ValueError('Enter valid nonnegative alarm policy numbers and positive window and sample limits.')
    return int(value) if integer else float(value)


def _objects(value):
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError('Enter alarm priorities, mappings and relationships as lists of objects.')
    return value


def _signal(value):
    if not isinstance(value, dict):
        raise ValueError('Select both endpoints of each alarm signal relationship.')
    return _label(value.get('datasetId')), _label(value.get('signal'))


def _signal_record(key):
    return dict(datasetId=key[0], signal=key[1])


def normalize_policy(body=None):
    """Validate user policy. Priority order is supplied by the operator."""
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ValueError('Enter a valid alarm policy.')
    priorities = [dict(id=_label(item.get('id')), label=_label(item.get('label'))) for item in
                  _objects(body.get('priorities', [dict(id=i, label=label) for i, label in DEFAULT_PRIORITIES]))]
    ids = {p['id'] for p in priorities}
    if not ids or len(ids) != len(priorities):
        raise ValueError('Define at least one alarm priority with a unique ID.')
    default = _label(body.get('defaultPriority', priorities[-1]['id']))
    if default not in ids:
        raise ValueError('Choose a configured default alarm priority.')
    mappings = {}
    for item in _objects(body.get('mappings', [])):
        key = _signal(item)
        if key in mappings:
            raise ValueError('Map each dataset signal at most once in an alarm policy.')
        priority = _label(item['priority']) if item.get('priority') not in (None, '') else None
        if priority is not None and priority not in ids:
            raise ValueError('Choose a configured priority for each alarm signal mapping.')
        equipment = _label(item['equipment']) if item.get('equipment') not in (None, '') else None
        mappings[key] = dict(**_signal_record(key), equipment=equipment, priority=priority)
    relationships = set()
    for item in _objects(body.get('relationships', [])):
        left, right = _signal(item.get('left')), _signal(item.get('right'))
        if left == right:
            raise ValueError('Choose different endpoints for an alarm signal relationship.')
        relationships.add(tuple(sorted((left, right))))
    equipment_grouping = body.get('groupByEquipment', False)
    if not isinstance(equipment_grouping, bool):
        raise ValueError('Choose whether equipment membership can group alarms.')
    escalation = body.get('escalationSeconds')
    return dict(
        priorities=priorities, defaultPriority=default, mappings=[mappings[k] for k in sorted(mappings)],
        relationships=[dict(left=_signal_record(a), right=_signal_record(b)) for a, b in sorted(relationships)],
        groupByEquipment=equipment_grouping,
        proximitySeconds=_number(body.get('proximitySeconds', 0)),
        repeatWindowSeconds=_number(body.get('repeatWindowSeconds', 0)),
        minSamples=_number(body.get('minSamples', 1), minimum=1, integer=True),
        minDurationSeconds=_number(body.get('minDurationSeconds', 0)),
        maxShelveSeconds=_number(body.get('maxShelveSeconds', 86400), minimum=1),
        escalationSeconds=None if escalation is None else _number(escalation, minimum=1),
        floodWindowSeconds=_number(body.get('floodWindowSeconds', 60), minimum=1),
    )


def _interval_bounds(result):
    """Match saved intervals to sample indices, including duplicate timestamps."""
    times, intervals = result['times'], result['intervals']
    states = result.get('states')
    if states is not None:
        runs = []
        start = None
        for i, state in enumerate(states):
            if state == 'alarm' and start is None:
                start = i
            elif state != 'alarm' and start is not None:
                runs.append((start, i - 1))
                start = None
        if start is not None:
            runs.append((start, len(times) - 1))
        if len(runs) == len(intervals) and all(
            times[a] == alarm['start'] and times[b] == alarm['end']
            for (a, b), alarm in zip(runs, intervals)
        ):
            return states, runs

    # Older results retained interval bounds without per-sample decisions.
    # The declared sample count disambiguates equal timestamps at boundaries.
    inferred = ['normal'] * len(times) if states is None else None
    bounds, first = [], 0
    for interval in intervals:
        start = bisect_left(times, interval['start'], lo=first)
        end = bisect_right(times, interval['end'], lo=start) - 1
        samples = interval.get('samples', end - start + 1)
        while (states is not None and start <= end and states[start] != 'alarm'):
            start += 1
        end = min(end, start + samples - 1)
        if end < start or times[start] != interval['start'] or times[end] != interval['end']:
            raise ValueError('Saved analysis contains incompatible alarm evidence.')
        if inferred is not None:
            inferred[start:end + 1] = ['alarm'] * (end - start + 1)
        bounds.append((start, end))
        first = end + 1
    return inferred if states is None else states, bounds


def _observation_spans(times, states, gap):
    """Index the same closed observed spans used by the incident timeline."""
    indices = [None] * len(times)
    spans = []
    first = None
    for i, state in enumerate(states):
        if first is not None and (state == 'abstain' or (gap and times[i] - times[i - 1] > gap)):
            spans.append((first, i - 1))
            first = None
        if state != 'abstain':
            if first is None:
                first = i
            indices[i] = len(spans)
    if first is not None:
        spans.append((first, len(times) - 1))
    return spans, indices


def _fragments(start, end, span_ids, states):
    i = start
    while i <= end:
        if states[i] != 'alarm':
            i += 1
            continue
        first, span = i, span_ids[i]
        i += 1
        while i <= end and span_ids[i] == span and states[i] == 'alarm':
            i += 1
        yield first, i - 1


def extract_events(result, dataset, clock):
    """Preserve each saved alarm sample, splitting acquisition gaps explicitly."""
    times, scores = result['times'], result['scores']
    offset = clock['offset']
    gap = dataset['metadata'].get('quality', {}).get('gapThreshold')
    fractions = result.get('observedFraction')
    states, bounds = _interval_bounds(result)
    spans, span_ids = _observation_spans(times, states, gap)
    abstained = states.count('abstain')
    coverage = (len(times) - abstained) / len(times) if times else None
    quality = dict(gapThreshold=gap, coverageFraction=coverage, abstainedSamples=abstained)
    provenance = {key: result[key] for key in ('createdAt', 'completedAt', 'contributionMetric',
        'experiment', 'transformation', 'training', 'external') if key in result}
    provenance.update(clockReference=clock.get('reference'),
                      stateBasis='detector-states' if result.get('states') is not None else 'saved-intervals')
    threshold = result['threshold']
    events = []
    for index, (interval, (begin, finish)) in enumerate(zip(result['intervals'], bounds)):
        contribution_index = max(range(begin, finish + 1), key=scores.__getitem__)
        contributions = interval.get('contributions', [])
        magnitude = max((item['value'] for item in contributions if isfinite(item['value'])), default=None)
        signals = list(interval['signals'])
        # Saved top-five contributors are context. Small contributions from a
        # common multivariate input set are weak evidence of a shared alarm.
        affected = ([item['signal'] for item in contributions if item['value'] == magnitude]
                    if magnitude is not None and magnitude > 0 else signals[:1])
        for fragment, (a, b) in enumerate(_fragments(begin, finish, span_ids, states)):
            peak = max(range(a, b + 1), key=scores.__getitem__)
            span_start, span_end = spans[span_ids[a]]
            clear_time = None
            if b + 1 == len(times):
                measured_state, end_reason = 'active', 'analysis-end'
            elif gap and times[b + 1] - times[b] > gap:
                measured_state, end_reason = 'unknown', 'data-gap'
            elif states[b + 1] == 'abstain':
                measured_state, end_reason = 'unknown', 'abstention'
            elif states[b + 1] == 'normal':
                measured_state, end_reason = 'cleared', 'normal-sample'
                clear_time = times[b + 1] + offset
            else:
                measured_state, end_reason = 'active', 'saved-boundary'
            events.append(dict(
                id=f"{result['id']}:{index}:{fragment}", analysisId=result['id'], analysisName=result['name'],
                datasetId=result['datasetId'], datasetName=dataset['name'],
                detector=result['config']['algorithm'], detectorLabel=result['algorithmLabel'],
                axisId=clock['axisId'], clockKey=clock['key'], offset=offset,
                intervalIndex=index, fragmentIndex=fragment, startIndex=a, endIndex=b, peakIndex=peak,
                start=times[a] + offset, end=times[b] + offset, peakTime=times[peak] + offset,
                nativeStart=times[a], nativeEnd=times[b], nativePeakTime=times[peak],
                nativeContributionTime=interval['peakTime'], samples=b - a + 1,
                durationSeconds=times[b] - times[a], peakScore=scores[peak], threshold=threshold,
                peakAboveThreshold=scores[peak] - threshold,
                peakMagnitude=magnitude if peak == contribution_index else None,
                signals=signals, affectedSignals=affected,
                contributions=contributions,
                observedSpan=[times[span_start] + offset, times[span_end] + offset],
                observedFraction=sum(fractions[a:b + 1]) / (b - a + 1) if fractions is not None else None,
                measuredState=measured_state, endReason=end_reason, clearTime=clear_time,
                quality=quality, provenance=provenance,
            ))
    return events


def _affected(event):
    return event.get('affectedSignals', event['signals'])


def _source(event):
    return event['datasetId'], event['detector'], tuple(sorted(set(_affected(event))))


def _enrich(event, mappings, ranks, policy):
    keys = {(event['datasetId'], signal) for signal in _affected(event)}
    configured = [mappings[key] for key in keys if key in mappings]
    priorities = [item['priority'] for item in configured if item['priority'] is not None]
    return {**event,
        'priority': min(priorities, key=ranks.__getitem__) if priorities else policy['defaultPriority'],
        'equipment': sorted({item['equipment'] for item in configured if item['equipment'] is not None}),
        'policyEligible': (event['samples'] >= policy['minSamples']
                           and event['durationSeconds'] >= policy['minDurationSeconds'])}


def _relation(left, right, left_keys, right_keys, left_source, right_source, explicit, policy):
    gap = max(0., right['start'] - left['end'])
    repeat = gap > 0 and left_source == right_source
    if gap:
        limit = policy['repeatWindowSeconds'] if repeat else policy['proximitySeconds']
        if gap > limit or any(a > left['end'] or b < right['start']
                              for a, b in (left['observedSpan'], right['observedSpan'])):
            return None
    shared = left_keys & right_keys
    related = {(a, b) for a in left_keys for b in explicit[a] & right_keys}
    equipment = sorted(set(left['equipment']) & set(right['equipment'])) if policy['groupByEquipment'] else []
    reasons = []
    if shared:
        reasons.append('shared-signal')
    if related:
        reasons.append('explicit-relationship')
    if equipment:
        reasons.append('shared-equipment')
    if not gap and (shared or related) and left['detector'] != right['detector']:
        reasons.append('detector-agreement')
    if repeat:
        reasons.append('repeat')
    if not reasons:
        return None
    return dict(leftId=left['id'], rightId=right['id'], temporal='proximity' if gap else 'overlap',
                gapSeconds=gap, reasons=reasons, equipment=equipment,
                signals=[_signal_record(k) for k in sorted(shared | {k for pair in related for k in pair})],
                explicitPairs=[dict(left=_signal_record(a), right=_signal_record(b)) for a, b in sorted(related)])


def _correlate_axis(events, explicit, policy, ranks):
    signal_keys = [{(event['datasetId'], s) for s in _affected(event)} for event in events]
    sources = [_source(event) for event in events]
    own_keys, sought_keys = [], []
    for event, signals, source in zip(events, signal_keys, sources):
        # Query only configured evidence neighborhoods. Time alone has no key.
        shared = {('signal', *signal) for signal in signals}
        if policy['groupByEquipment']:
            shared.update(('equipment', equipment) for equipment in event['equipment'])
        if policy['repeatWindowSeconds'] and signals:
            shared.add(('repeat', *source))
        neighbors = {('signal', *related) for signal in signals for related in explicit[signal]}
        own_keys.append(sorted(shared) if event['policyEligible'] else [])
        sought_keys.append(sorted(shared | neighbors) if event['policyEligible'] else [])

    proximity, repeat_window = policy['proximitySeconds'], policy['repeatWindowSeconds']
    by_end, uniform_source, uniform_span = defaultdict(list), {}, {}
    if proximity or repeat_window:
        for i, (event, source) in enumerate(zip(events, sources)):
            for key in own_keys[i]:
                repeat_key = key[0] == 'repeat'
                if not (repeat_window if repeat_key else proximity):
                    continue
                by_end[key].append((event['end'], i))
                if repeat_key:
                    span = event['observedSpan']
                    if uniform_span.setdefault(key, span) != span:
                        uniform_span[key] = None
                elif uniform_source.setdefault(key, source) != source:
                    uniform_source[key] = None
        for values in by_end.values():
            values.sort()
    parent = list(range(len(events)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    edges, overlap = [], {}
    for i, event in enumerate(events):
        candidates = set()
        for key in sought_keys[i]:
            prior = overlap.get(key)
            if prior is not None and prior[0] >= event['start']:
                # Same-key predecessors covering this point already belong to
                # one component, so a single witness preserves connectivity.
                candidates.add(prior[1])
            repeat_key = key[0] == 'repeat'
            limit = repeat_window if repeat_key else proximity
            if limit and (repeat_key or uniform_source.get(key) != sources[i]):
                values = by_end[key]
                lower = max(event['start'] - limit, event['observedSpan'][0])
                first = bisect_left(values, (lower, -1))
                last = bisect_left(values, (event['start'], -1), lo=first)
                if first < last and uniform_span.get(key) is not None:
                    # Repeats inside one observation span and this window
                    # already connect with each other by the same repeat rule.
                    candidates.add(values[last - 1][1])
                else:
                    candidates.update(j for _, j in values[first:last])
        for j in sorted(candidates):
            a, b = root(i), root(j)
            if a == b:
                continue
            relation = _relation(events[j], event, signal_keys[j], signal_keys[i], sources[j],
                                 sources[i], explicit, policy)
            if relation is not None:
                parent[max(a, b)] = min(a, b)
                edges.append((i, relation))
        for key in own_keys[i]:
            value = (event['end'], i)
            if key not in overlap or value > overlap[key]:
                overlap[key] = value

    members, explanations = defaultdict(list), defaultdict(list)
    for i, event in enumerate(events):
        members[root(i)].append(event)
    for i, edge in edges:
        explanations[root(i)].append(edge)
    groups = []
    for i, items in members.items():
        ids = [e['id'] for e in items]
        identity = sha256(json.dumps(sorted(ids), separators=(',', ':')).encode()).hexdigest()[:24]
        groups.append(dict(id=identity, axisId=items[0]['axisId'], start=items[0]['start'],
            end=max(e['end'] for e in items), eventIds=ids, relationships=explanations[i],
            priority=min((e['priority'] for e in items), key=ranks.__getitem__)))
    return groups


def group_alarms(events, policy):
    """Return deterministic connected groups and the pairwise evidence that joined them."""
    ranks = {p['id']: index for index, p in enumerate(policy['priorities'])}
    mappings = {_signal(item): item for item in policy['mappings']}
    explicit = defaultdict(set)
    for item in policy['relationships']:
        left, right = _signal(item['left']), _signal(item['right'])
        explicit[left].add(right)
        explicit[right].add(left)
    enriched = [_enrich(event, mappings, ranks, policy) for event in sorted(
        events, key=lambda e: (e['axisId'], e['start'], e['end'], e['id']))]
    axes = defaultdict(list)
    for event in enriched:
        axes[event['axisId']].append(event)
    groups = [group for axis in axes.values() for group in _correlate_axis(axis, explicit, policy, ranks)]
    return dict(events=enriched, groups=groups)


def _window_load(events, groups, start, end, width):
    """Sweep exact closed endpoints and emit fixed-width arrival windows."""
    changes = defaultdict(lambda: [0, 0, 0])
    for event in events:
        changes[event['start']][0] += 1
        changes[event['end']][1] += 1
    for group in groups:
        changes[group['start']][2] += 1

    bins = []

    def append(first, stop, arrivals, group_arrivals, peak):
        if first >= stop:
            return
        if (bins and not (arrivals or group_arrivals or bins[-1]['arrivals'] or bins[-1]['groupArrivals'])
                and bins[-1]['peakConcurrent'] == peak):
            bins[-1]['windowCount'] += stop - first
            bins[-1]['end'] = start + stop * width
        else:
            bins.append(dict(start=start + first * width, end=start + stop * width,
                windowCount=stop - first, arrivals=arrivals, groupArrivals=group_arrivals,
                peakConcurrent=peak, arrivalsPerHour=arrivals * 3600 / width))

    def window_index(time):
        index = floor((time - start) / width)
        # Compare with the displayed boundaries when float division rounds a
        # boundary to the adjacent window.
        if time < start + index * width:
            return index - 1
        if time >= start + (index + 1) * width:
            return index + 1
        return index

    index, active, arrivals, group_arrivals, peak = 0, 0, 0, 0, 0
    for time, (starts, ends, group_starts) in sorted(changes.items()):
        current = window_index(time)
        if current > index:
            append(index, index + 1, arrivals, group_arrivals, peak)
            append(index + 1, current, 0, 0, active)
            index, arrivals, group_arrivals, peak = current, 0, 0, active
        active += starts
        peak = max(peak, active)
        active -= ends
        arrivals += starts
        group_arrivals += group_starts
    append(index, index + 1, arrivals, group_arrivals, peak)
    append(index + 1, window_index(end) + 1, 0, 0, active)
    return bins


def flood_metrics(events, groups, policy, acknowledgements=None, axes=None):
    """Compute load by compatible axis using arrivals, including raw point events."""
    acknowledgements = acknowledgements or {}
    bounds = {axis['id']: (axis['start'], axis['end']) for axis in axes or ()}
    grouped_events, grouped_groups = defaultdict(list), defaultdict(list)
    for event in events:
        grouped_events[event['axisId']].append(event)
    for group in groups:
        grouped_groups[group['axisId']].append(group)
    metrics = []
    width = policy['floodWindowSeconds']
    for axis in sorted(bounds.keys() | grouped_events.keys()):
        items, related = grouped_events[axis], grouped_groups[axis]
        first, last = bounds.get(axis, (None, None))
        start = min([e['start'] for e in items] + ([first] if first is not None else []), default=0.)
        end = max([e['end'] for e in items] + ([last] if last is not None else []), default=start)
        bins = _window_load(items, related, start, end, width)
        equipment = Counter(name for e in items for name in (e['equipment'] or [None]))
        signals = Counter((e['datasetId'], s) for e in items for s in set(_affected(e)))
        durations = sum(e['durationSeconds'] for e in items)
        delays = [acknowledgements[e['id']] for e in items if e['id'] in acknowledgements]
        metrics.append(dict(axisId=axis, windowSeconds=width, anchor=start, start=start, end=end,
            rawEventCount=len(items), groupCount=len(related), bins=bins,
            peakArrivalCount=max(b['arrivals'] for b in bins),
            peakArrivalsPerHour=max(b['arrivalsPerHour'] for b in bins),
            peakConcurrent=max(b['peakConcurrent'] for b in bins),
            repeatedEventCount=len(items) - len({_source(e) for e in items}),
            byEquipment=[dict(equipment=k, count=equipment[k]) for k in sorted(equipment, key=lambda k: k or '')],
            bySignal=[dict(**_signal_record(k), count=signals[k]) for k in sorted(signals)],
            totalDurationSeconds=durations, meanDurationSeconds=durations / len(items) if items else None,
            acknowledgedCount=len(delays),
            meanAcknowledgementDelaySeconds=sum(delays) / len(delays) if delays else None))
    return dict(rawEventCount=len(events), groupCount=len(groups), axes=metrics)
