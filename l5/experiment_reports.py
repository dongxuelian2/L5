"""Offline experiment research reports built exclusively from persisted runs."""
from __future__ import annotations

from .report_locale import fragment as r, localized_report, text as report_text

import numpy as np
from .data_quality import segment_ids
from .experiments import file_hash
from .experiment_evaluation import RULES
from .reports import CSS, chart, e, lanes, n, parameters, prose, table, technical
from .workspace import now


@localized_report
def render_experiment_report(store, identity, run_id=None):
    experiment = store.experiments.get(identity)
    runs = [store.experiments.run(run['id']) for run in experiment['runs'] if run_id is None or run['id'] == run_id]
    if run_id and not runs:
        raise ValueError('Report run must belong to this experiment.')
    parts = [f"""{r('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>')}{e(experiment['name'])}{r(' · L5 Experiment Report</title><style>')}{CSS}</style></head><body>""",
             r('<div class="toolbar"><button onclick="window.print()">Print / Save A4 PDF</button><span>Offline HTML · saved experiment evidence</span></div>'),
             f"""{r('<main><div class="brand">L5 / EXPERIMENT RESEARCH REPORT</div><h1>')}{e(experiment['name'])}</h1>""",
             f"""{r('<p class="muted">Experiment ')}{e(identity)}{r(' · definition revision ')}{experiment['revision']}{r(' · generated ')}{e(now())}</p>""",
             prose(experiment['description']), r('<h2>Research notes and conclusion</h2>'),
             r('<h3>Saved observations</h3>'), prose(experiment['notes']), r('<h3>Saved conclusion</h3>'), prose(experiment['conclusion']),
             r('<p>Conclusion references: ') + e(', '.join(experiment['conclusion_run_ids']) or r('No run references recorded')) + '</p>',
             r('<h2>Evaluation and comparison rules</h2>'), table([r('Topic'), r('Rule')], [[e(report_text(k)), e(report_text(v))] for k, v in RULES.items()]),
             r('<p>Unlabelled statistics describe detector behavior. They do not estimate detection accuracy. Null ratios mean the denominator is zero.</p>')]
    if not runs:
        parts.append(r('<p>No saved executions. The editable definition below has not produced research results.</p>'))
    if experiment['records']:
        parts.append(r('<h3>Saved research record history</h3>'))
        for record in reversed(experiment['records']):
            parts.extend([f"{r('<details><summary>Revision ')}{record['revision']} · {e(record['created_at'])} · {e(record['id'])}</summary>",
                          prose(record['notes']), prose(record['conclusion']), r('<p>Run references: ') + e(', '.join(record['run_ids'])) + '</p></details>'])
    for run in reversed(runs):
        snapshot, tasks = run['snapshot'], run['tasks']
        if snapshot.get('datasets'):
            from .external_reports import independent_run
            parts.append(independent_run(store, run))
            continue
        dataset = snapshot['dataset']
        parts.extend([f"{r('<h2>Run ')}{e(run['id'])}</h2>",
            f"{r('<p>Status: ')}{e(report_text(run['status']))}{r(' · revision ')}{snapshot['experiment']['revision']}{r(' · started ')}{e(run['started_at'])}{r(' · completed ')}{e(run['completed_at'])}{r(' · elapsed ')}{e(n(run['duration_ms']))} ms</p>",
            f"{r('<p>Dataset: ')}{e(dataset['name'])} ({e(dataset['id'])}) · SHA-256 {e(dataset['sha256'])}</p>",
            r('<h3>Inputs, baseline and observation policy</h3>'), parameters(snapshot['config']),
            r('<h3>Signal metadata and time source</h3>'), technical(dict(signals=dataset['metadata']['columns'], time=dataset['metadata']['time'], clock=dataset['metadata']['clock'])),
            r('<h3>Dataset provenance</h3>'), technical(dict(sourceCsvSha256=dataset['sourceCsvSha256'],
                transformation=dataset['metadata'].get('transformation'), model=dataset['metadata'].get('model'))),
            r('<h3>Task results</h3>'), table([r('Method / task'), r('Parameters'), r('Status / result'), r('First alarm / spans / duration'), r('Samples / coverage'), r('Compute / wall ms')], [
                [e(task['algorithm']) + '<br>' + e(task['id']),
                 e({k: v for k, v in task['config'].items() if k not in ('signals', 'datasetId', 'baselineRange', 'analysisRange')}),
                 e(report_text(task['status'])) + '<br>' + e(task['result_id']) + ('<br>' + e(task['error']) if task['error'] else ''),
                 e(f"{n(task['metrics']['behavior']['firstDetection'])} / {task['metrics']['behavior']['alarmIntervalCount']} / {n(task['metrics']['behavior']['alarmDuration'])} s") if task['metrics'] else '—',
                 e(f"{task['metrics']['behavior']['alarmSamples']}{r(' alarm / ')}{task['metrics']['behavior']['abstainedSamples']}{r(' abstain / ')}{n(task['metrics']['behavior']['coverageFraction'])}") if task['metrics'] else '—',
                 e(f"{(n(task['metrics']['behavior']['durationMs']) if task['metrics'] else '—')} / {n(task['duration_ms'])}")] for task in tasks])])
        successful = [task for task in tasks if task['status'] == 'succeeded']
        results = {task['id']: store.result(task['result_id']) for task in successful}
        path = store.root / dataset['workspace_id'] / 'datasets' / dataset['id'] / 'series.npz'
        if path.is_file() and file_hash(path) == dataset['sha256']:
            times, values = store.load_data(dataset)
            start, end = snapshot['config']['analysisRange']
            selected = (times >= start) & (times <= end)
            names = [column['name'] for column in dataset['metadata']['columns']]
            parts.append(r('<h3>Dataset measurements in the analysis window</h3>'))
            for signal in snapshot['config']['signals'][:8]:
                column = dataset['metadata']['columns'][names.index(signal)]
                raw = values[selected, names.index(signal)]
                parts.append(chart(column.get('displayName') or signal, times[selected].tolist(),
                    [dict(label=signal, values=[float(value) if np.isfinite(value) else None for value in raw],
                          segmentIds=segment_ids(times[selected], raw, dataset['metadata'].get('quality', {}).get('gapThreshold')).tolist())], unit=column.get('unit') or r('Dataset numerical units')))
            if len(snapshot['config']['signals']) > 8:
                parts.append(r('<p>Measurement figures show the first eight selected signals. All signal identities and metadata remain in the input snapshot.</p>'))
        else:
            parts.append(r('<p>Dataset hash no longer matches the saved input. Measurement figures are omitted; saved AnalysisResults remain the detection evidence.</p>'))
        if successful:
            alarm_lanes = []
            for task in successful:
                result = results[task['id']]
                intervals = []
                for span in task['metrics']['behavior']['alarmSpans']:
                    indices = [i for i, time in enumerate(result['times']) if span['start'] <= time <= span['end']]
                    peak = max(indices, key=lambda i: result['scores'][i])
                    intervals.append({**span, 'peakTime': result['times'][peak]})
                alarm_lanes.append(dict(result=result, intervals=intervals))
            parts.extend([r('<h3>Alarm timeline · native dataset seconds</h3>'), lanes([
                *alarm_lanes], dict(label=r('Dataset-native seconds'), origin=None))])
            # Compare only saved intervals under the same run snapshot clock.
            comparison = store.experiments.comparison(identity, dict(taskIds=[task['id'] for task in successful[:12]]))
            for group in comparison['groups']:
                parts.extend([r('<h3>Common / unique alarm spans</h3>'),
                    f"{r('<p>Matching windows: ')}{e(group['matchingWindows'])}{r('; matching observation spans: ')}{e(group['matchingCoverage'])}{r('; matching inputs / baseline: ')}{e(group['matchingInputs'])}{r('; matching truth versions: ')}{e(group['matchingLabelSets'])}{r('. Detailed comparison includes up to 12 tasks.</p>')}",
                    table([r('Classification'), r('Start / end (clock seconds)'), r('Task IDs')], [
                        [e(segment['kind']), e(f"{n(segment['start'])} / {n(segment['end'])}"), e(', '.join(segment['analysisIds']))] for segment in group['segments']]),
                    r('<h3>Agreement on exact shared, evaluated timestamps</h3>'), technical(group['agreement'])])
        if snapshot['labels']:
            labels = snapshot['labels']
            parts.extend([r('<h3>Truth label version</h3>'), technical(labels),
                r('<h3>Sample evaluation</h3>'), table([r('Task'), 'TP / FP / TN / FN', r('Precision / recall / F1'), r('False alarm rate'), r('Evaluated / unknown / labelled abstain')], [
                    [e(task['id']), e(' / '.join(str(task['metrics']['labelled']['sample'][k]) for k in ('TP', 'FP', 'TN', 'FN'))),
                     e(' / '.join(n(task['metrics']['labelled']['sample'][k]) if task['metrics']['labelled']['sample'][k] is not None else 'undefined' for k in ('precision', 'recall', 'f1'))),
                     e(task['metrics']['labelled']['sample']['falseAlarmRate']),
                     e(' / '.join(str(task['metrics']['labelled']['sample'][k]) for k in ('evaluatedSamples', 'unlabelledSamples', 'labelledAbstainedSamples')))] for task in successful]),
                r('<h3>Event evaluation · separate from sample confusion counts</h3>'),
                table([r('Task'), r('Detected / missed / unobserved truth events'), r('False alarm events'), r('First delay (s)')], [
                    [e(task['id']), e(' / '.join(str(task['metrics']['labelled']['event'][k]) for k in ('detectedEvents', 'missedEvents', 'unobservedEvents'))),
                     e(task['metrics']['labelled']['event']['falseAlarmEvents']), e(task['metrics']['labelled']['event']['firstDetectionDelay'])] for task in successful])])
        for task in successful:
            result = results[task['id']]
            values = [None if state == 'abstain' else score for state, score in zip(result['states'], result['scores'])]
            parts.extend([f"<h3>{e(result['algorithmLabel'])} · {e(task['id'])}</h3>",
                parameters(result['config']), chart(result['name'], result['times'], [dict(label=result['algorithmLabel'], values=values)],
                    threshold=result['threshold'], intervals=task['metrics']['behavior']['alarmSpans'], unit=r('Method-specific detection score')),
                r('<h4>Key variable contributions · method-specific units</h4>'),
                table([r('Signal'), r('Contribution'), r('Metric')], [[e(c['signal']), e(n(c['value'])), e(result.get('contributionMetric'))] for c in result.get('signalContributions', [])]),
                r('<details><summary>Saved evaluation details</summary>') + technical(task['metrics']) + '</details>'])
        parts.extend([r('<h3>Technical appendix · reproducibility snapshot</h3>'), technical(dict(
            experiment=snapshot['experiment'], engine=snapshot['engine'], datasetId=dataset['id'],
            datasetSha256=dataset['sha256'], runId=run['id'], retryOf=run['retry_of'],
            taskResults=[dict(taskId=task['id'], analysisId=task['result_id']) for task in tasks]))])
    parts.extend([r('<h2>Current editable definition</h2>'), technical(experiment['config']),
                  r('<footer>L5 · Generated from saved definitions, immutable run inputs, AnalysisResults and saved conclusions. Figures retain separate score scales. No remote resources are required.</footer></main></body></html>')])
    return ''.join(parts)
