"""Incident views derived from saved sources, with explicit, compatible clocks.

No detection is rerun here. Intervals retain their original result indices and
scores. Relative clocks remain independent unless explicitly associated.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .workspace import now


def origin_seconds(origin):
    return datetime.fromisoformat(origin.replace('Z', '+00:00')).timestamp() if origin else 0


def clock_for_key(store, key):
    if key.startswith('dataset:'):
        return store.signals.clock(key.split(':', 1)[1])
    if key.startswith('simulation:'):
        session = store.runtime.get(key.split(':', 1)[1])
        if session.get('datasetId'):
            return {**store.signals.clock(session['datasetId']), 'key': key}
        return dict(key=key, axisId=key, offset=0, label=session['title'])
    if key.startswith('origin:'):
        return dict(key=key, axisId='utc', offset=origin_seconds(key[7:]), label='UTC 绝对时间')
    return dict(key=key, axisId=key, offset=0, label='事件独立时间轴')


def source_clock(store, source):
    detail = source['details']
    key = 'dataset:' + detail['datasetId'] if detail.get('datasetId') else 'simulation:' + detail['simulationId']
    return clock_for_key(store, key)


def incident_clock(store, incident):
    key = 'origin:' + incident['time_origin'] if incident.get('time_origin') else incident.get('time_axis_key') or 'incident:' + incident['id']
    return clock_for_key(store, key)


def observed_spans(result, offset, gap_threshold=None):
    """Closed spans of evaluated samples; abstention gaps are never normal data."""
    spans, start, last = [], None, None
    for t, state in zip(result['times'], result.get('states', ['normal'] * len(result['times']))):
        if start is not None and gap_threshold and t + offset - last > gap_threshold:
            spans.append([start, last])
            start = None
        if state == 'abstain':
            if start is not None:
                spans.append([start, last])
                start = None
        else:
            last = t + offset
            if start is None:
                start = last
    if start is not None:
        spans.append([start, last])
    return spans


def compare_intervals(analyses):
    """Partition linked alarms within jointly evaluated time, retaining point alarms.

    Duration is last-sample minus first-sample seconds, never inferred cadence.
    Unique means one selected analysis alarms while all selected analyses have
    observations. A different observation window or an abstention is not a miss.
    """
    if not analyses:
        return dict(segments=[], common=[], unique=[], firstDetection=None, firstAlarmSpread=None)
    boundaries = set()
    for a in analyses:
        for start, end in a['observedSpans']:
            boundaries.update((start, end))
        for interval in a['intervals']:
            boundaries.update((interval['start'], interval['end']))
    cuts = sorted(boundaries)

    def classify(t):
        observed = [a['id'] for a in analyses if any(start <= t <= end for start, end in a['observedSpans'])]
        active = [a['id'] for a in analyses if any(i['start'] <= t <= i['end'] for i in a['intervals'])]
        if not active:
            return None
        kind = 'uncompared' if len(observed) < len(analyses) else 'common' if len(active) == len(analyses) and len(active) > 1 else 'unique' if len(active) == 1 and len(analyses) > 1 else 'partial'
        return dict(kind=kind, analysisIds=active)

    segments = []
    for start, end in zip(cuts, cuts[1:]):
        part = classify((start + end) / 2)
        if part:
            if segments and segments[-1]['end'] == start and all(segments[-1][k] == v for k, v in part.items()):
                segments[-1]['end'] = end
            else:
                segments.append(dict(start=start, end=end, **part))
    # Closed intervals can share only one endpoint. Keep those contacts, as well
    # as one-sample alarms, even though their measured duration is zero.
    for t in cuts:
        part = classify(t)
        if part and not any(s['start'] <= t <= s['end'] and all(s[k] == v for k, v in part.items()) for s in segments):
            segments.append(dict(start=t, end=t, **part))
    segments.sort(key=lambda s: (s['start'], s['end']))
    firsts = [min(i['start'] for i in a['intervals']) for a in analyses if a['intervals']]
    return dict(segments=segments, common=[s for s in segments if s['kind'] == 'common'],
                unique=[s for s in segments if s['kind'] == 'unique'],
                firstDetection=min(firsts) if firsts else None,
                firstAlarmSpread=max(firsts) - min(firsts) if len(firsts) > 1 else None)


def investigation(store, identity, selected=None):
    incident = store.incidents.get(identity)
    axes, events, analyses = {}, [], []
    datasets = {d['id']: d for d in store.datasets(incident['workspace_id'])}
    link_by_id = {l['id']: l for l in incident['links']}

    def add_clock(clock):
        if clock['axisId'] not in axes:
            axes[clock['axisId']] = dict(id=clock['axisId'], label=clock['label'],
                origin='1970-01-01T00:00:00Z' if clock['axisId'] == 'utc' else None, start=None, end=None)
        return clock

    def event(key, kind, title, clock=None, start=None, end=None, **details):
        clock = add_clock(clock) if clock else None
        start = start + clock['offset'] if start is not None and clock else None
        end = end + clock['offset'] if end is not None and clock else start
        item = dict(id=key, kind=kind, title=title, axisId=clock['axisId'] if clock else None, start=start, end=end, **details)
        events.append(item)
        if clock and start is not None:
            axis = axes[clock['axisId']]
            axis['start'] = min(axis['start'], start) if axis['start'] is not None else start
            axis['end'] = max(axis['end'], end if end is not None else start) if axis['end'] is not None else end

    primary = add_clock(incident_clock(store, incident))
    if incident['start_time'] is not None:
        event('incident-range', 'incident', incident['title'], primary, incident['start_time'], incident['end_time'], target='information')
    grouped = {}
    truth_datasets = set()
    for link in incident['links']:
        clock = add_clock(source_clock(store, link))
        detail = link['details']
        dataset_id = detail.get('datasetId')
        external = datasets.get(dataset_id, {}).get('metadata', {}).get('external')
        if external and dataset_id not in truth_datasets and external.get('faultOnsetSeconds') is not None:
            truth_datasets.add(dataset_id)
            event('truth:' + dataset_id, 'truth', f'数据集已知故障 {external["faultNumber"]} · sample {external["faultOnsetSample"]}',
                  clock, external['faultOnsetSeconds'], linkId=link['id'], content=external['timeConvention'], target='source')
        if detail.get('analysisId'):
            grouped.setdefault(detail['analysisId'], []).append(link)
        if detail.get('simulationId'):
            run, window = detail.get('run'), detail.get('observationWindow')
            if run:
                request, result = run['request'], run['result']
                cutoff = result.get('observedThrough', result.get('asOf', request.get('asOf')))
                event('run:' + run['id'], 'experiment' if run['kind'] == 'intervention' else 'investigation',
                      '干预实验' if run['kind'] == 'intervention' else '工具调查', clock, cutoff,
                      linkId=link['id'], recordedAt=run['createdAt'], observationWindow=[request.get('windowStart', 0), cutoff],
                      actionAt=result.get('at'), hypothesis=request.get('hypothesis'), target='source')
            elif window:
                event('window:' + link['id'], 'investigation', '过程模型工作假设', clock, window['asOf'],
                      linkId=link['id'], recordedAt=link['created_at'], observationWindow=[window['windowStart'], window['asOf']],
                      hypothesis=window.get('hypothesis'), target='source')

    for analysis_id, links in grouped.items():
        result = store.result(analysis_id)
        clock = source_clock(store, links[0])
        full = next((l for l in links if l['kind'] == 'analysis'), None)
        selected_indices = range(len(result['intervals'])) if full else sorted({int(l['selector']) for l in links})
        intervals = []
        for index in selected_indices:
            interval = result['intervals'][index]
            link = next((l for l in links if l['kind'] == 'interval' and int(l['selector']) == index), full)
            normalized = {**interval, 'start': interval['start'] + clock['offset'], 'end': interval['end'] + clock['offset'],
                          'peakTime': interval['peakTime'] + clock['offset'], 'index': index, 'linkId': link['id']}
            intervals.append(normalized)
            event(f'interval:{analysis_id}:{index}', 'alarm', result['algorithmLabel'] + ' · 异常区间', clock,
                  interval['start'], interval['end'], peakTime=normalized['peakTime'], peakScore=interval['peakScore'],
                  analysisId=analysis_id, intervalIndex=index, linkId=link['id'], recordedAt=result['createdAt'],
                  signals=interval['signals'], target='source')
        analyses.append(dict(id=analysis_id, result=result, axisId=clock['axisId'], offset=clock['offset'],
            datasetId=result['datasetId'], datasetName=datasets[result['datasetId']]['name'],
            scope='完整分析' if full else '已关联区间', linkId=(full or links[0])['id'], intervals=intervals,
            observedSpans=observed_spans(result, clock['offset'], datasets[result['datasetId']]['metadata']['quality']['gapThreshold'])))

    for entry in incident['entries']:
        link = link_by_id.get(entry['source_link_id'])
        clock = clock_for_key(store, entry['observed_axis_key']) if entry.get('observed_axis_key') else source_clock(store, link) if link else primary
        event('entry:' + entry['id'], entry['kind'], entry['title'], clock if entry['observed_at'] is not None else None,
              entry['observed_at'], entryId=entry['id'], linkId=entry['source_link_id'],
              recordedAt=entry['created_at'], updatedAt=entry['updated_at'], stance=entry['stance'],
              hypothesisId=entry['hypothesis_id'], content=entry['content'], target='entry')
    history = store.incidents.history(identity)
    for change in history:
        keys = change['changes']
        title = '结论更新' if 'conclusion' in keys else '状态变更' if 'status' in keys else '事件信息更新'
        event('history:' + change['id'], 'conclusion' if 'conclusion' in keys else 'status', title,
              recordedAt=change['recorded_at'], changes=keys, target='conclusion' if 'conclusion' in keys else 'information')

    ids = {a['id'] for a in analyses}
    if selected is not None and any(i not in ids for i in selected):
        raise ValueError('只能比较此事件实际关联的分析。')
    selected = ids if selected is None else set(selected)
    comparisons = []
    for axis in axes.values():
        members = [a for a in analyses if a['axisId'] == axis['id'] and a['id'] in selected]
        if members:
            comparisons.append(dict(axisId=axis['id'], analysisIds=[a['id'] for a in members], **compare_intervals(members)))
        if axis['start'] is None:
            axis['start'], axis['end'] = 0, 1
    events.sort(key=lambda e: (e['axisId'] or '~recorded', e['start'] if e['start'] is not None else float('inf'), e.get('recordedAt', ''), e['id']))
    return dict(incident=incident, workspace=store.workspace(incident['workspace_id']), generatedAt=now(),
                axes=list(axes.values()), primaryAxisId=primary['axisId'], events=events, analyses=analyses,
                comparisons=comparisons, datasets=[datasets[did] for did in dict.fromkeys(
                    l['details']['datasetId'] for l in incident['links'] if l['details'].get('datasetId'))], history=history)
