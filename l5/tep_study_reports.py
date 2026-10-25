"""Portable study summary and fault-3 controls using the existing HTML charts."""
from __future__ import annotations

from .external_benchmark import distribution
from .reports import CSS, chart, e, n, parameters, table, technical


def training_summary(study):
    rows = []
    for configuration in study['protocol']['configurations']:
        for algorithm in [a['algorithm'] for a in study['protocol']['algorithms']]:
            tasks = [t for t in study['tasks'] if t.get('configuration', t.get('benchmark', {}).get('configuration')) == configuration
                     and t['algorithm'] == algorithm and t['status'] == 'succeeded']
            thresholds = [t.get('threshold', t['metrics']['training'].get('threshold')) for t in tasks]
            fits = {t['metrics']['training'].get('fitId') for t in tasks}
            normal = next((c for c in study['cells'] if c['configuration'] == configuration and c['algorithm'] == algorithm and c['faultNumber'] == 0), None)
            faults = [c for c in study['cells'] if c['configuration'] == configuration and c['algorithm'] == algorithm and c['faultNumber'] != 0]
            rows.append(dict(configuration=configuration, algorithm=algorithm, thresholds=distribution(thresholds), fitIds=sorted(f for f in fits if f),
                fitDurationMs=distribution([t['metrics']['training']['fitDurationMs'] for t in tasks]),
                normal=normal['burden']['normal'] if normal else None,
                detection={key: dict(detectedEvents=sum(c['windows'][key]['detectedEvents'] for c in faults),
                    totalEvents=sum(c['windows'][key]['totalEvents'] for c in faults)) for key in ('1800','3600','14400','eventual')},
                sampleRecall=distribution([c['sample']['recall'] for c in faults]),
                rankByEarlyDetection=None))
    for configuration in study['protocol']['configurations']:
        selected = [r for r in rows if r['configuration'] == configuration]
        counts = sorted({r['detection']['1800']['detectedEvents'] for r in selected}, reverse=True)
        for row in selected:
            row['rankByEarlyDetection'] = counts.index(row['detection']['1800']['detectedEvents'])+1
    return rows


def render_study_report(store, study):
    summary = training_summary(study)
    parts = [f'<!doctype html><html lang="en"><meta charset="utf-8"><title>{e(study["protocol"]["name"])}</title><style>{CSS}</style>',
        '<body><div class="toolbar"><button onclick="window.print()">Print / Save A4 PDF</button><span>Offline saved TEP study</span></div><main>',
        f'<div class="brand">L5 / TEP RESEARCH</div><h1>{e(study["protocol"]["name"])}</h1>',
        f'<p>Study {e(study["id"])} · protocol SHA-256 {e(study["protocolHash"])}. Status counts: {e(study["statusCounts"])}</p>',
        '<p>Every declared event is retained in the early/eventual denominator. Missed and unobserved events have undefined delay. Failed tasks are unresolved outcomes. Eventual detection is a nominal alarm inside the fault interval; it does not establish fault-specific discrimination.</p>',
        '<h2>Normal-training configurations and fixed parameters</h2>', parameters(study['protocol']['configurations']),
        parameters(dict(algorithms=study['protocol']['algorithms'])), '<h2>Training sensitivity and normal alarm burden</h2>']
    rows = []
    for record in summary:
        normal = record['normal'] or {}
        rows.append([e(record['configuration']), e(record['algorithm']), n(record['thresholds']['median']),
            e(f'{normal.get("alarmSamples",0)}/{normal.get("observedSamples",0)}'), e(normal.get('alarmEvents',0)), n(normal.get('alarmDuration')),
            *[e(f'{record["detection"][key]["detectedEvents"]}/{record["detection"][key]["totalEvents"]}') for key in ('1800','3600','14400','eventual')],
            e(record['rankByEarlyDetection'])])
    parts.append(table(['Config','Method','Threshold','Normal alarm samples','Normal episodes','Normal duration (s)','≤30m','≤1h','≤4h','Eventual','30m rank (ties)'], rows))
    parts.append('<h2>Fault × method, with every batch pooled within its configuration</h2>')
    rows = []
    for c in study['cells']:
        rows.append([e(c['configuration']), e(c['faultNumber']), e(c['algorithm']), e(f'{c["succeeded"]}/{c["plannedRuns"]}'), e(c['failed']),
            *[e(f'{c["windows"][key]["detectedEvents"]}/{c["windows"][key]["totalEvents"]}') for key in ('1800','3600','14400','eventual')],
            n(c['sample']['recall']), n(c['delay']['median']), e(c['delayDistribution']['missed']), n(c['burden']['postInjection']['alarmFraction']),
            e(c['burden']['preInjection']['alarmSamples'])])
    parts.append(table(['Config','Fault','Method','Succeeded/planned','Failed','≤30m','≤1h','≤4h','Eventual','Sample recall','Detected-only median delay (s)','Missed','Post-onset alarm fraction','Pre-onset FP'],rows))
    parts.append('<h2>Fault 3: normal-background control</h2>')
    for simulation_run in (1,2,3):
        control = store.tep_studies.fault3(study['workspaceId'], study['id'], simulation_run)
        parts.extend([f'<h3>Testing run {simulation_run} · shared elapsed seconds</h3>', f'<p>{e(control["interpretation"])}</p>', technical(control['diagnostics'])])
        for pair in control['configurations']:
            parts.extend([f'<h4>Configuration {e(pair["configuration"])} · DPCA-Q</h4>',
                chart('Normal and fault 3 · DPCA-Q', pair['normal']['times'],
                    [dict(label='Normal Testing',values=pair['normal']['scores']),dict(label='Fault 3 Testing',values=pair['fault']['scores'])],
                    threshold=pair['threshold'], intervals=pair['fault']['intervals'], unit='DPCA Q statistic',
                    markers=[dict(time=control['onset'],label='Published injection'),dict(time=control['targetTime'],label='PR22 late alarm')]),
                table(['Series','Main variables at 167580 s','Score correlation after injection','Local score correlation'],
                    [[key, e(', '.join(v['signal']+'='+n(v['value']) for v in values)), n(pair['scoreCorrelation']),n(pair['localScoreCorrelation'])] for key,values in pair['contributionsAtTarget'].items()]),
                '<details><summary>Other methods at the PR22 alarm time</summary>'+technical(pair['otherMethodsAtTarget'])+'</details>'])
        for signal in control['raw'][:6]:
            parts.append(chart(signal['signal']+' · original measurements', signal['times'],
                [dict(label='Normal Testing',values=signal['normal']),dict(label='Fault 3 Testing',values=signal['fault'])],
                markers=[dict(time=control['onset'],label='Published injection'),dict(time=control['targetTime'],label='PR22 late alarm')]))
        parts.append('<details><summary>All normal runs and fault-3 runs · alarm peaks and nominal detections</summary>'+technical(control['controls'])+'</details>')
    parts.extend(['<h2>Execution and reproducibility</h2>', technical(study['batches']),
        '<details><summary>All execution attempts (latest full run plus explicit retry ancestry supplies the matrix)</summary>'+technical(study['attempts'])+'</details>',
        '<details><summary>Complete predeclared protocol</summary>'+technical(study['protocol'])+'</details>',
        '<p>Alarm duration sums last minus first sampled times in each contiguous span. One-point alarms have zero duration; this does not estimate continuous physical alarm occupation between samples.</p>',
        '<ul>'+''.join('<li>'+e(v)+'</li>' for v in study['protocol']['limitations'])+'</ul>', '</main></body></html>'])
    return ''.join(parts)
