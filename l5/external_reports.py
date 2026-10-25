"""Offline report sections for independent-run experiments."""
from .independent import file_hash
from .reports import chart, e, lanes, n, parameters, table, technical


def independent_run(store, run):
    snapshot, tasks = run['snapshot'], run['tasks']
    parts = [f'<h2>Independent benchmark batch {e(run["id"])}</h2>',
             f'<p>Status: {e(run["status"])} · {run["completed"]}/{len(tasks)} tasks finished · total {n(run["duration_ms"])} ms</p>',
             '<h3>Frozen normal training and calibration</h3>', parameters(snapshot['config']['training']),
             '<p>Test trajectories never participate in preprocessing, model fitting or threshold selection. Each score call starts with fresh temporal/adaptive state.</p>']
    for key, reference in snapshot['config']['training'].items():
        source = snapshot['datasets'][reference['datasetId']]
        parts.append(f'<details><summary>{e(key)} · {e(source["name"])} · SHA-256 {e(source["sha256"])}</summary>'+technical(source['metadata'].get('external') or source['metadata'])+'</details>')
    all_rows = []
    for task in tasks:
        dataset = snapshot['datasets'][task['config']['datasetId']]
        metrics = task['metrics'] or {}
        labelled, behavior = metrics.get('labelled'), metrics.get('behavior')
        sample, event = (labelled['sample'], labelled['event']) if labelled else ({}, {})
        all_rows.append([e(dataset['name']), e(task['algorithm']), e(task['status']) + ('<br>'+e(task['error']) if task['error'] else ''),
            e(' / '.join(str(sample.get(k, '—')) for k in ('TP', 'FP', 'TN', 'FN'))),
            e(' / '.join(n(sample.get(k)) for k in ('precision', 'recall', 'f1', 'falseAlarmRate'))),
            e(f'{event.get("detectedEvents", "—")} / {event.get("eligibleEvents", "—")} / {event.get("missedEvents", "—")}'),
            e(n(event.get('firstDetectionDelay'))),
            e(f'{behavior["validSamples"]}/{behavior["totalSamples"]}; {behavior["abstainedSamples"]} abstain') if behavior else '—',
            e(n(behavior['alarmDuration'])) if behavior else '—', e(n(behavior['durationMs'])) if behavior else '—'])
    parts.extend(['<h3>All predeclared runs and algorithms</h3>', table(['Test run', 'Method', 'Status', 'TP / FP / TN / FN', 'Precision / recall / F1 / FAR', 'Hit / eligible / missed events', 'First delay (s)', 'Valid / total / abstain', 'Alarm duration (s)', 'Score time (ms)'], all_rows)])
    for plan in snapshot['config']['testDatasets']:
        dataset = snapshot['datasets'][plan['datasetId']]
        external = dataset['metadata'].get('external')
        onset = external.get('faultOnsetSeconds') if external else None
        markers = [dict(time=onset, label='Published fault onset')] if onset is not None else []
        members = [t for t in tasks if t['config']['datasetId'] == dataset['id'] and t['status'] == 'succeeded']
        results = [(t, store.result(t['result_id'])) for t in members]
        parts.extend([f'<h3>{e(dataset["name"])} · independent test trajectory</h3>', technical(external or dict(datasetId=dataset['id'], sha256=dataset['sha256'])),
            '<h4>Published labels (evaluation only)</h4>', technical(snapshot['testLabels'][dataset['id']])])
        folder = store.root / dataset['workspace_id'] / 'datasets' / dataset['id']
        if (folder / 'series.npz').is_file() and file_hash(folder / 'series.npz') == dataset['sha256']:
            times, values = store.load_data(dataset)
            selected = (times >= plan['analysisRange'][0]) & (times <= plan['analysisRange'][1])
            columns = [c['name'] for c in dataset['metadata']['columns']]
            signals = list(dict.fromkeys(s for _, result in results for s in result['relatedSignals'][:3]))[:8]
            if not signals:
                signals = columns[:4]
            parts.append('<h4>Original measurements · selected key variables</h4>')
            for signal in signals:
                raw = values[selected, columns.index(signal)]
                parts.append(chart(signal, times[selected].tolist(), [dict(label=signal, values=raw.tolist())], markers=markers))
            parts.append('<p>Figures show up to eight key variables. All 52 original input identities are retained; Workspace and Signal Explorer provide every channel.</p>')
        else:
            parts.append('<p>Input hash mismatch: raw measurement charts omitted. Saved detector results are retained.</p>')
        if results:
            parts.append(lanes([dict(result=result, intervals=result['intervals']) for task, result in results], dict(origin=None, label='Dataset-native seconds')))
        for task, result in results:
            parts.extend([f'<h4>{e(result["algorithmLabel"])} · {e(task["id"])}</h4>',
                parameters(result['config']), chart(result['algorithmLabel'], result['times'],
                    [dict(label=result['algorithmLabel'], values=[None if state == 'abstain' else score for state, score in zip(result['states'], result['scores'])])],
                    threshold=result['threshold'], intervals=result['intervals'], markers=markers, unit='Method-specific score'),
                table(['Signal', 'Contribution', 'Metric'], [[e(c['signal']), n(c['value']), e(result.get('contributionMetric'))] for c in result['signalContributions'][:10]]),
                '<details><summary>Saved evaluation and training provenance</summary>'+technical(dict(evaluation=task['metrics'], training={k: v for k, v in result.get('training', {}).items() if k not in ('sources', 'test')}))+ '</details>'])
    parts.append('<details><summary>Reproducibility engine and input hashes</summary>'+technical(dict(engine=snapshot['engine'], datasets={k: v['sha256'] for k, v in snapshot['datasets'].items()}, config=snapshot['config']))+'</details>')
    return ''.join(parts)
