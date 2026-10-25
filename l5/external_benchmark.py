"""Descriptive multi-run summaries; preserve failures and evaluation denominators."""
from __future__ import annotations

import json
from statistics import median

from .experiment_evaluation import ratio


def distribution(values):
    values = [v for v in values if v is not None]
    return dict(n=len(values), median=median(values) if values else None,
                minimum=min(values) if values else None, maximum=max(values) if values else None)


def summarize(tasks):
    groups = {}
    for task in tasks:
        external = task.get('external')
        if not external:
            continue
        # Different study candidates, training protocols and batches stay separate.
        parameters = {k: v for k, v in task['config'].items() if k not in ('datasetId', 'analysisRange', 'baselineRange', 'labelSetId', 'signalMapping', 'name')}
        condition = json.dumps(parameters, sort_keys=True)
        key = (task['run_id'], external['faultNumber'], task['algorithm'], condition)
        groups.setdefault(key, []).append(task)
    cells = []
    for (run_id, fault, algorithm, condition), members in groups.items():
        successful = [t for t in members if t['status'] == 'succeeded' and t['metrics']]
        labelled = [t['metrics']['labelled'] for t in successful if t['metrics']['labelled']]
        counts = {k: sum(m['sample'][k] for m in labelled) for k in ('TP', 'FP', 'TN', 'FN')}
        events = {k: sum(m['event'][k] for m in labelled) for k in ('eligibleEvents', 'detectedEvents', 'missedEvents', 'unobservedEvents', 'falseAlarmEvents')}
        tp, fp, tn, fn = (counts[k] for k in ('TP', 'FP', 'TN', 'FN'))
        total = sum(t['metrics']['behavior']['totalSamples'] for t in successful)
        valid = sum(t['metrics']['behavior']['validSamples'] for t in successful)
        cells.append(dict(runId=run_id, faultNumber=fault, algorithm=algorithm, condition=condition,
            runCount=len(members), succeeded=len(successful), failed=sum(t['status'] in ('failed', 'interrupted') for t in members),
            labelledRuns=len(labelled), sample={**counts, 'precision': ratio(tp, tp+fp), 'recall': ratio(tp, tp+fn),
                'f1': ratio(2*tp, 2*tp+fp+fn), 'falseAlarmRate': ratio(fp, fp+tn)},
            event={**events, 'recall': ratio(events['detectedEvents'], events['eligibleEvents'])},
            coverage=ratio(valid, total), abstainFraction=ratio(total-valid, total),
            delay=distribution([m['event']['firstDetectionDelay'] for m in labelled]),
            recall=distribution([m['sample']['recall'] for m in labelled]),
            falseAlarmRate=distribution([m['sample']['falseAlarmRate'] for m in labelled]),
            alarmDuration=distribution([t['metrics']['behavior']['alarmDuration'] for t in successful]),
            durationMs=distribution([t['metrics']['behavior']['durationMs'] for t in successful]),
            taskIds=[t['id'] for t in members]))
        # Derive early counts from immutable historical event records as well as
        # newly saved metrics; PR22 records need no mutation or detector rerun.
        windows = {}
        records = [event for m in labelled for event in m['event'].get('events', [])]
        unresolved = len(members)-len(successful)
        for key, horizon in (('1800',1800),('3600',3600),('14400',14400),('eventual',None)):
            total = len(records)+(unresolved if fault else 0)
            hits = sum(v['delay'] is not None and (horizon is None or v['delay'] <= horizon) for v in records)
            windows[key] = dict(detectedEvents=hits, totalEvents=total, rate=ratio(hits,total),
                unobservedEvents=sum(not v['observedSamples'] for v in records), unresolvedEvents=unresolved if fault else 0,
                truncatedEvents=sum(v.get('followUpSeconds',v['end']-v.get('onset',v['start'])) < horizon for v in records) if horizon is not None else 0)
        cells[-1]['windows'] = windows
        phase_records = [t['metrics'].get('detection') for t in successful if t['metrics'].get('detection')]
        if phase_records:
            cells[-1]['burden'] = {}
            for phase in ('normal','preInjection','postInjection'):
                selected = [r[phase] for r in phase_records if r[phase] is not None]
                counts = {k:sum(r[k] for r in selected) for k in ('samples','observedSamples','alarmSamples','alarmEvents','alarmDuration')}
                cells[-1]['burden'][phase] = {**counts,'alarmFraction':ratio(counts['alarmSamples'],counts['observedSamples'])}
    return dict(cells=cells, rules='Per batch and fixed detector/training configuration. Pooled counts and per-run median/min/max retain separate denominators; missed events have no delay.')
