"""Portable study summary and fault-3 controls using the existing HTML charts."""
from __future__ import annotations

from .report_locale import fragment as r, localized_report, text as report_text

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


@localized_report
def render_study_report(store, study):
    summary = training_summary(study)
    parts = [f"""{r('<!doctype html><html lang="en"><meta charset="utf-8"><title>')}{e(study['protocol']['name'])}</title><style>{CSS}</style>""",
        r('<body><div class="toolbar"><button onclick="window.print()">Print / Save A4 PDF</button><span>Offline saved TEP study</span></div><main>'),
        f"""{r('<div class="brand">L5 / TEP RESEARCH</div><h1>')}{e(study['protocol']['name'])}</h1>""",
        f"{r('<p>Study ')}{e(study['id'])}{r(' · protocol SHA-256 ')}{e(study['protocolHash'])}{r('. Status counts: ')}{e(study['statusCounts'])}</p>",
        r('<p>Every declared event is retained in the early/eventual denominator. Missed and unobserved events have undefined delay. Failed tasks are unresolved outcomes. Eventual detection is a nominal alarm inside the fault interval; it does not establish fault-specific discrimination.</p>'),
        r('<h2>Normal-training configurations and fixed parameters</h2>'), parameters(study['protocol']['configurations']),
        parameters(dict(algorithms=study['protocol']['algorithms'])), r('<h2>Training sensitivity and normal alarm burden</h2>')]
    rows = []
    for record in summary:
        normal = record['normal'] or {}
        rows.append([e(record['configuration']), e(record['algorithm']), n(record['thresholds']['median']),
            e(f"{normal.get('alarmSamples', 0)}/{normal.get('observedSamples', 0)}"), e(normal.get('alarmEvents',0)), n(normal.get('alarmDuration')),
            *[e(f"{record['detection'][key]['detectedEvents']}/{record['detection'][key]['totalEvents']}") for key in ('1800','3600','14400','eventual')],
            e(record['rankByEarlyDetection'])])
    parts.append(table([r('Config'),r('Method'),r('Threshold'),r('Normal alarm samples'),r('Normal episodes'),r('Normal duration (s)'),r('≤30m'),r('≤1h'),r('≤4h'),r('Eventual'),r('30m rank (ties)')], rows))
    parts.append(r('<h2>Fault × method, with every batch pooled within its configuration</h2>'))
    rows = []
    for c in study['cells']:
        rows.append([e(c['configuration']), e(c['faultNumber']), e(c['algorithm']), e(f"{c['succeeded']}/{c['plannedRuns']}"), e(c['failed']),
            *[e(f"{c['windows'][key]['detectedEvents']}/{c['windows'][key]['totalEvents']}") for key in ('1800','3600','14400','eventual')],
            n(c['sample']['recall']), n(c['delay']['median']), e(c['delayDistribution']['missed']), n(c['burden']['postInjection']['alarmFraction']),
            e(c['burden']['preInjection']['alarmSamples'])])
    parts.append(table([r('Config'),r('Fault'),r('Method'),r('Succeeded/planned'),r('Failed'),r('≤30m'),r('≤1h'),r('≤4h'),r('Eventual'),r('Sample recall'),r('Detected-only median delay (s)'),r('Missed'),r('Post-onset alarm fraction'),r('Pre-onset FP')],rows))
    parts.append(r('<h2>Fault 3: normal-background control</h2>'))
    for simulation_run in (1,2,3):
        control = store.tep_studies.fault3(study['workspaceId'], study['id'], simulation_run)
        parts.extend([f"{r('<h3>Testing run ')}{simulation_run}{r(' · shared elapsed seconds</h3>')}", f"<p>{e(control['interpretation'])}</p>", technical(control['diagnostics'])])
        for pair in control['configurations']:
            parts.extend([f"{r('<h4>Configuration ')}{e(pair['configuration'])} · DPCA-Q</h4>",
                chart(r('Normal and fault 3 · DPCA-Q'), pair['normal']['times'],
                    [dict(label=r('Normal Testing'),values=pair['normal']['scores']),dict(label=r('Fault 3 Testing'),values=pair['fault']['scores'])],
                    threshold=pair['threshold'], intervals=pair['fault']['intervals'], unit=r('DPCA Q statistic'),
                    markers=[dict(time=control['onset'],label=r('Published injection')),dict(time=control['targetTime'],label=r('PR22 late alarm'))]),
                table([r('Series'),r('Main variables at 167580 s'),r('Score correlation after injection'),r('Local score correlation')],
                    [[report_text(key), e(', '.join(v['signal']+'='+n(v['value']) for v in values)), n(pair['scoreCorrelation']),n(pair['localScoreCorrelation'])] for key,values in pair['contributionsAtTarget'].items()]),
                r('<details><summary>Other methods at the PR22 alarm time</summary>')+technical(pair['otherMethodsAtTarget'])+'</details>'])
        for signal in control['raw'][:6]:
            parts.append(chart(signal['signal']+r(' · original measurements'), signal['times'],
                [dict(label=r('Normal Testing'),values=signal['normal']),dict(label=r('Fault 3 Testing'),values=signal['fault'])],
                markers=[dict(time=control['onset'],label=r('Published injection')),dict(time=control['targetTime'],label=r('PR22 late alarm'))]))
        parts.append(r('<details><summary>All normal runs and fault-3 runs · alarm peaks and nominal detections</summary>')+technical(control['controls'])+'</details>')
    parts.extend([r('<h2>Execution and reproducibility</h2>'), technical(study['batches']),
        r('<details><summary>All execution attempts (latest full run plus explicit retry ancestry supplies the matrix)</summary>')+technical(study['attempts'])+'</details>',
        r('<details><summary>Complete predeclared protocol</summary>')+technical(study['protocol'])+'</details>',
        r('<p>Alarm duration sums last minus first sampled times in each contiguous span. One-point alarms have zero duration; this does not estimate continuous physical alarm occupation between samples.</p>'),
        '<ul>'+''.join('<li>'+e(v)+'</li>' for v in study['protocol']['limitations'])+'</ul>', '</main></body></html>'])
    return ''.join(parts)
