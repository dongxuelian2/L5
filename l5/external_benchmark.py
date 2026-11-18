"""Descriptive multi-run summaries; preserve failures and evaluation denominators."""
from __future__ import annotations

import json
from statistics import median

from .detection_metrics import WINDOWS
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
        unresolved = len(members) - len(successful)
        cell = cells[-1]
        cell['unresolvedRuns'] = unresolved
        cell['windows'] = {}
        for key, horizon in WINDOWS.items():
            counts = dict(detectedEvents=0, totalEvents=0, unobservedEvents=0, truncatedEvents=0)
            for task in successful:
                metrics = task['metrics']
                windows = (metrics.get('detection') or {}).get('windows')
                if windows:
                    for name in counts:
                        counts[name] += windows[key][name]
                elif metrics['labelled']:
                    # Legacy records retain per-event delays and the task's analysis cutoff.
                    for event in metrics['labelled']['event'].get('events', []):
                        delay = event['delay']
                        onset = event.get('onset', event['start'])
                        end = min(event['end'], task['config']['analysisRange'][1])
                        counts['totalEvents'] += 1
                        counts['detectedEvents'] += delay is not None and (horizon is None or delay <= horizon)
                        counts['unobservedEvents'] += not event['observedSamples']
                        counts['truncatedEvents'] += end-onset < (event['end']-onset if horizon is None else horizon)
            cell['windows'][key] = dict(**counts, rate=ratio(counts['detectedEvents'], counts['totalEvents']),
                                        unresolvedEvents=unresolved if fault else 0)
        cell['burden'] = {}
        for phase in ('normal', 'preInjection', 'postInjection'):
            selected = [r for t in successful if (r := (t['metrics'].get('detection') or {}).get(phase)) is not None]
            counts = {k:sum(r[k] for r in selected) for k in ('samples','observedSamples','alarmSamples','alarmEvents','alarmDuration')}
            exposure = (sum(r['observedSeconds'] for r in selected)
                        if selected and all('observedSeconds' in r for r in selected) else None)
            cell['burden'][phase] = dict(**counts, alarmFraction=ratio(counts['alarmSamples'],counts['observedSamples']),
                observedSeconds=exposure, episodesPerObservedHour=ratio(3600*counts['alarmEvents'], exposure))
    return dict(cells=cells, rules='Per batch and fixed detector/training configuration. Pooled counts and per-run median/min/max retain separate denominators; missed events have no delay.')
