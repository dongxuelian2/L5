"""Standalone incident reports. Figures are inline SVG from saved data."""
from __future__ import annotations


from datetime import datetime, timezone
from html import escape
import json
import math

import numpy as np

from .labels import display_label
from .incident_timeline import investigation
from .data_quality import segment_ids


STATUS = {'open': 'Open', 'investigating': 'Investigating', 'resolved': 'Conclusion recorded', 'archived': 'Archived'}
KINDS = {'alarm': 'Alarm', 'note': 'Investigation note', 'evidence': 'Evidence', 'hypothesis': 'Hypothesis', 'experiment': 'Intervention experiment',
         'investigation': 'Tool investigation', 'status': 'Status change', 'conclusion': 'Conclusion update', 'incident': 'Incident range',
         'prognostic': 'Prognostic forecast', 'safety-observed': 'Observed constraint violation', 'safety-predicted': 'Predicted constraint violation'}
STANCE = {'support': 'Supports', 'oppose': 'Opposes', 'neutral': 'Undecided'}
METRIC = {'absolute-quadratic-term': 'Absolute channel term in the covariance quadratic form', 'absolute-robust-z': 'Absolute robust z-score', 'squared-residual': 'PCA-Q standardized squared residual',
          'model-leverage': 'PCA-T² model-space contribution (descriptive ranking; does not sum to T²)', 'history-contribution': 'History-based channel contribution',
          'regime-detector-specific': 'Regime detector contributions'}
PROGNOSTIC_STATUS = {'ok': 'Forecast available', 'insufficient_data': 'There are too few usable measurements to fit this model.',
                     'not_identifiable': 'This model is not identifiable from the selected history.',
                     'numerical_failure': 'The model could not complete the numerical fit.',
                     'threshold_reached': 'The failure threshold has already been reached at the cutoff.',
                     'beyond_horizon': 'The median first-passage time exceeds the forecast horizon.'}


def e(value):
    return escape(str(value) if value is not None else 'Not recorded', quote=True)


def n(value):
    if value is None:
        return 'Not detected'
    return f'{value:.6g}' if isinstance(value, (int, float)) else str(value)


def timestamp(value, axis=None):
    if value is None:
        return 'Undetermined'
    if axis and axis.get('origin'):
        return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec='milliseconds').replace('T', ' ', 1).replace('+00:00', ' UTC')
    return n(value) + ' s'


def recorded_time(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('T', ' ').replace('+00:00', ' UTC')


def table(heads, rows, css_class=''):
    return '<table' + (f' class="{css_class}"' if css_class else '') + '><thead><tr>' + ''.join(f'<th>{e(h)}</th>' for h in heads) + '</tr></thead><tbody>' + ''.join(
        '<tr>' + ''.join(f'<td>{cell}</td>' for cell in row) + '</tr>' for row in rows) + '</tbody></table>'


def prose(value):
    return '<p class="prose">' + e(value or 'Not yet recorded.') + '</p>'


def technical(value):
    return '<pre>' + e(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)) + '</pre>'


def parameters(value):
    labels = {'datasetId': 'Dataset ID', 'signals': 'Analysis variables', 'algorithm': 'Detection algorithm', 'alpha': 'Calibration α',
              'baselineRange': 'Normal baseline (s)', 'analysisRange': 'Analysis range (s)', 'fitFraction': 'Fit fraction',
              'minCoverage': 'Minimum observed fraction', 'persistence': 'Alarm confirmation samples', 'requiredSignals': 'Required observed variables',
              'hypothesis': 'Hypothesis', 'asOf': 'Observation cutoff (s)', 'windowStart': 'Observation start (s)',
              'mode': 'Model mode', 'at': 'Intervention time (s)', 'horizon': 'Forecast end (s)', 'actions': 'Intervention actions',
              'parameters': 'Control parameters', 'calls': 'Investigation tools', 'fittedParameters': 'Fitted model parameters', 'fitError': 'Fit error',
              'variance': 'Retained variance fraction', 'name': 'Analysis name', 'missingValues': 'Missing-value handling', 'sessionId': 'Simulation session ID',
              'fault': 'Fault template', 'start': 'Fault onset (s)', 'severity': 'Fault severity', 'delay': 'Actuator delay (s)',
              'noise': 'Measurement noise multiplier', 'response': 'Controller response multiplier', 'operating': 'Initial temperature offset (°C)',
              'seed': 'Random seed', 'duration': 'Simulation duration (s)', 'step': 'Integration step (s)', 'observedThrough': 'Observation cutoff (s)'}
    return table(['Parameter', 'Saved value'], [[e(labels.get(k, k)), e(json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else 'Not recorded' if v is None else v)] for k, v in value.items()], 'parameters')


def chart(title, times, lines, *, axis=None, threshold=None, intervals=(), unit=None, domain=None, markers=()):
    unit = unit if unit is not None else 'Original values (source provides no units)'
    valid = [v for line in lines for v in line['values'] if v is not None and math.isfinite(v)]
    if not times or not valid:
        return f"<p>{e(title)}: no displayable observations in this window.</p>"
    width, height, left, right, top, bottom = 760, 220, 70, 18, 24, 44
    low, high = domain or (min(valid), max(valid))
    if threshold is not None:
        low, high = min(low, threshold), max(high, threshold)
    pad = max((high-low) * .08, abs(high) * .002, .001)
    low, high = low-pad, high+pad
    first, last = times[0], times[-1]
    def x(t): return left + (t-first) / (last-first or 1) * (width-left-right)
    def y(v): return top + (high-v) / (high-low) * (height-top-bottom)
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="{e(title)}"><title>{e(title)}</title>',
           f'<text x="{left}" y="13">{e(unit)}</text>']
    for f in (0, .5, 1):
        yy = top + f * (height-top-bottom)
        svg.append(f'<line x1="{left}" x2="{width - right}" y1="{yy}" y2="{yy}" stroke="#dce3e6"/><text x="{left - 8}" y="{yy + 4}" text-anchor="end">{n(high - f * (high - low))}</text>')
    for interval in intervals:
        a, b = max(first, interval['start']), min(last, interval['end'])
        if a <= b:
            svg.append(f'<rect x="{x(a):.2f}" y="{top}" width="{max(2, x(b) - x(a)):.2f}" height="{height - top - bottom}" fill="#c8563c" opacity=".13"/>')
    if threshold is not None:
        svg.append(f'''<line x1="{left}" x2="{width - right}" y1="{y(threshold):.2f}" y2="{y(threshold):.2f}" stroke="#ac6b11" stroke-dasharray="6 4"/><text x="{width - right}" y="{y(threshold) - 5:.2f}" text-anchor="end">Threshold {n(threshold)}</text>''')
    for marker in markers:
        if first <= marker['time'] <= last:
            svg.append(f'''<line x1="{x(marker['time']):.2f}" x2="{x(marker['time']):.2f}" y1="{top}" y2="{height - bottom}" stroke="#3b78a1" stroke-dasharray="3 3"/><text x="{x(marker['time']) + 4:.2f}" y="{top + 12}" fill="#3b78a1">{e(marker['label'])}</text>''')
    for line in lines:
        values = line['values']
        # Preserve extrema and explicit missing samples when reducing score paths.
        indices = {0, len(values)-1}
        step = max(1, math.ceil(len(values)/400))
        for start in range(0, len(values), step):
            chunk = range(start, min(start+step, len(values)))
            finite = [i for i in chunk if values[i] is not None]
            missing = [i for i in chunk if values[i] is None]
            if finite:
                indices.update((min(finite, key=lambda i: values[i]), max(finite, key=lambda i: values[i])))
            if missing:
                indices.update((missing[0], missing[-1]))
        points, connected, previous_segment = [], False, None
        segments = line.get('segmentIds')
        for i in sorted(indices):
            if values[i] is None:
                connected = False
                continue
            points.append(f"{('L' if connected and (segments is None or previous_segment == segments[i]) else 'M')}{x(times[i]):.2f},{y(values[i]):.2f}")
            connected = True
            previous_segment = segments[i] if segments is not None else None
        svg.append(f'''<path d="{' '.join(points)}" fill="none" stroke="{line.get('color', '#246b63')}" stroke-width="1.4"/>''')
    # Elapsed seconds keep long UTC labels out of the plot. Caption gives UTC origin.
    for fraction in (0, .25, .5, .75, 1):
        value = first + fraction * (last-first)
        svg.append(f'''<text x="{x(value):.2f}" y="{height - 23}" text-anchor="{('start' if fraction == 0 else 'end' if fraction == 1 else 'middle')}">{n(value - first)}</text>''')
    svg.append(f'''<text x="{(width + left - right) / 2}" y="{height - 5}" text-anchor="middle">Time relative to this chart’s start (s)</text></svg>''')
    legend = ' · '.join(f"""<span style="color:{line.get('color', '#246b63')}">━ {e(line['label'])}</span>""" for line in lines)
    shading = 'Shading indicates linked alarms; ' if intervals else ''
    return f"""<figure><figcaption>{e(title)}</figcaption>{''.join(svg)}<p class="caption">{legend}<br>Start: {e(timestamp(first, axis))}; end: {e(timestamp(last, axis))}.{shading}Missing values / abstain retain gaps.</p></figure>"""


def lanes(analyses, axis):
    intervals = [i for a in analyses for i in a['intervals']]
    if not intervals:
        return '<p>No linked alarm intervals for the selected source.</p>'
    first, last = min(i['start'] for i in intervals), max(i['end'] for i in intervals)
    x = lambda t: 180 + (t-first)/(last-first or 1)*550
    height = 40 + 36*len(analyses)
    svg = [f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 {height}" role="img" aria-label="Detection interval comparison"><title>Anomaly intervals of linked analyses</title>"""]
    for index, a in enumerate(analyses):
        yy = 10 + index*36
        label = display_label(a['result']['algorithmLabel'])
        svg.append(f'<text x="0" y="{yy + 14}">{e(label[:22])} [{index + 1}]</text><line x1="180" x2="730" y1="{yy + 10}" y2="{yy + 10}" stroke="#dce3e6"/>')
        for i in a['intervals']:
            svg.append(f'''<rect x="{x(i['start']):.2f}" y="{yy}" width="{max(3, x(i['end']) - x(i['start'])):.2f}" height="20" rx="2" fill="#327e74"/><circle cx="{x(i['peakTime']):.2f}" cy="{yy + 10}" r="3" fill="#e3ad46"/>''')
    svg.append(f'<text x="180" y="{height - 5}">0 s</text><text x="730" y="{height - 5}" text-anchor="end">{n(last - first)} s</text></svg>')
    return '<figure><figcaption>Alarm intervals and peaks of linked analyses</figcaption>' + ''.join(svg) + f"""<p class="caption">{e(axis['label'])}; start {e(timestamp(first, axis))}; gold points indicate original score peaks. Compare timing and alarm states only.</p></figure>"""


CSS = '''
@page { size:A4; margin:16mm 15mm 18mm; @bottom-right { content:counter(page); font-size:9pt; color:#667; } }
* { box-sizing:border-box; } body { margin:0; color:#203239; background:#e9eef0; font:14px/1.65 Arial,sans-serif; }
main { max-width:960px; margin:24px auto; padding:42px 50px; background:white; }
.toolbar { max-width:960px; margin:20px auto; display:flex; gap:18px; align-items:center; }
button { cursor:pointer; border:0; border-radius:4px; background:#246b63; color:white; padding:12px 22px; font:inherit; }
.brand { color:#246b63; font-weight:bold; letter-spacing:2px; border-bottom:3px solid #246b63; padding-bottom:14px; }
h1 { font-size:30px; line-height:1.35; margin:26px 0 16px; } h2 { font-size:21px; border-bottom:1px solid #c7d5d7; padding:18px 0 8px; margin:22px 0 15px; }
h3 { font-size:16px; margin:22px 0 8px; } h4 { margin:18px 0 6px; } h1,h2,h3,h4,figcaption { break-after:avoid; }
p { margin:8px 0 14px; } .prose { white-space:pre-wrap; overflow-wrap:anywhere; orphans:3; widows:3; }
.meta { display:grid; grid-template-columns:1fr 1fr; gap:8px 22px; color:#506169; font-size:12px; } .meta span { overflow-wrap:anywhere; }
.summary { background:#eef5f3; border-left:4px solid #327e74; padding:14px 18px; margin-top:22px; }
table { width:100%; border-collapse:collapse; margin:12px 0 20px; font-size:11px; table-layout:fixed; } th,td { padding:8px 6px; border-bottom:1px solid #dce3e6; text-align:left; vertical-align:top; overflow-wrap:anywhere; }
th { background:#edf2f3; font-weight:600; } thead { display:table-header-group; } tr { break-inside:avoid; }
.parameters td,.parameters th { padding:5px 6px; font-size:10px; line-height:1.5; }
figure { margin:18px 0 22px; border:1px solid #d5dfe1; padding:10px; break-inside:avoid; } figcaption { font-size:13px; font-weight:bold; overflow-wrap:anywhere; margin-bottom:8px; }
svg { width:100%; height:auto; display:block; } svg text { font:10px Arial,sans-serif; fill:#506169; }
.caption,.muted { color:#62757e; font-size:11px; } .caption { line-height:1.5; margin:6px 0 0; } a { color:#246b63; text-decoration:none; }
pre { font:10px/1.5 monospace; white-space:pre-wrap; overflow-wrap:anywhere; background:#f4f6f7; padding:12px; }
.evidence { border-left:3px solid #b0c8c2; padding-left:14px; } .opposed { border-color:#b97161; }
.timeline td:first-child { width:24%; } footer { border-top:1px solid #c7d5d7; margin-top:30px; padding-top:12px; color:#62757e; font-size:10px; }
@media print { body { background:white; font-size:10pt; } main { width:auto; max-width:none; margin:0; padding:0; } .toolbar { display:none; } h1 { font-size:24pt; } h2 { font-size:15pt; } h3 { font-size:12pt; } figure { max-width:100%; } pre { background:none; } * { print-color-adjust:exact; -webkit-print-color-adjust:exact; } }
'''


def render_report(store, identity):
    view = investigation(store, identity)
    incident, workspace = view['incident'], view['workspace']
    axes = {a['id']: {**a, 'label': 'UTC absolute time' if a['origin'] else
                     'Independent incident time axis' if a['id'].startswith('incident:') else a['label']}
            for a in view['axes']}
    datasets = {d['id']: d for d in view['datasets']}
    analysis_datasets = {a['id']: a['datasetId'] for a in view['analyses']}
    def event_title(item):
        if item['kind'] == 'alarm':
            analysis = next(a for a in view['analyses'] if a['id'] == item['analysisId'])
            return display_label(analysis['result']['algorithmLabel']) + ' · Anomaly interval'
        if item['id'].startswith('truth:'):
            external = datasets[item['id'][6:]]['metadata']['external']
            return 'Published dataset fault ' + str(external['faultNumber']) + ' · sample ' + str(external['faultOnsetSample'])
        return display_label(item['title']) if item['kind'] in ('status', 'conclusion', 'experiment', 'investigation') else item['title']

    def safety_summary(safety):
        interval = safety['interval']
        label = 'Raw threshold breach' if safety['raw'] else display_label(KINDS['safety-' + safety['kind']])
        fields = [label, f"{n(interval['start'])}–{n(interval['end'])} s",
                  f"Maximum exceedance {n(interval['maximumExceedance'])} {safety['unit']}"]
        if safety['kind'] == 'predicted':
            fields.extend((f"Forecast observation cutoff (s) {n(safety['asOf'])}",
                           f"Forecast origin (s) {n(safety['forecastOrigin'])}",
                           f"Time to violation (s) {n(safety['timeToViolation'])}"))
        return ' · '.join(fields)

    def signal_label(dataset_id, name):
        column = next((c for c in datasets[dataset_id]['metadata']['columns'] if c['name'] == name), {})
        return (column.get('displayName') or name) + (f" ({column['unit']})" if column.get('unit') else '')
    def peak_stat(analysis):
        peak = max(analysis['intervals'], key=lambda i: i['peakScore'], default={})
        threshold = analysis['result']['threshold'] if not analysis['result'].get('regimeRunId') else None
        return n(peak.get('rawPeakScore', peak.get('peakScore'))) + ' / ' + n(peak.get('threshold', threshold))
    primary = axes[view['primaryAxisId']]
    from .incident_timeline import incident_clock
    offset = incident_clock(store, incident)['offset']
    start, end = (incident[k] + offset if incident[k] is not None else None for k in ('start_time', 'end_time'))
    parts = [f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(incident['title'])} · L5 investigation report</title><style>{CSS}</style></head><body>""",
        '<div class="toolbar"><button onclick="window.print()">Print / Save PDF</button><span>A4 with default margins is recommended. All charts are embedded for offline reading.</span></div><main>',
        f"""<div class="brand">L5 / Industrial operation analysis and fault investigation</div><h1>Incident investigation report<br>{e(incident['title'])}</h1>""",
        f"""<div class="meta"><span>Incident ID: {e(identity)}</span><span>Investigation status: {e(display_label(STATUS[incident['status']]))}</span><span>Workspace:{e(workspace['name'])}</span><span>Generated: {e(recorded_time(view['generatedAt']))}</span><span>Incident start: {e(timestamp(start, primary))}</span><span>Incident end: {e(timestamp(end, primary))}</span><span>Time axis: {e(primary['label'])}</span><span>Content updated: {e(recorded_time(incident['updated_at']))}</span></div>""",
        '<div class="summary"><h3>Incident overview</h3>' + prose(incident['description']) + '<h3>Recorded conclusion</h3>' + prose(incident['conclusion']) + '</div>',
        '<p class="muted">This report reads persisted incidents, analysis results, original measurements and investigation records. Missing judgments remain unrecorded. Algorithm scores retain their original scales; contributions indicate statistical association. Sources with timezones align in UTC; relative sources use saved explicit references and offsets, otherwise they retain independent clocks.</p>',
        '<h2>1. Incident timeline</h2>']
    for axis in axes.values():
        events = [v for v in view['events'] if v['axisId'] == axis['id'] and v['start'] is not None]
        if not events:
            continue
        parts.append('<h3>' + e(axis['label']) + '</h3>')
        rows = []
        for item in events:
            detail = display_label(item.get('content', '')) if item['kind'] == 'truth' else item.get('content', '')
            if item.get('diagnosticAssessment'):
                detail = '{0} · severity {1}'.format(display_label(item['diagnosticAssessment']), n(item['diagnosticSeverity']))
            if item['kind'] == 'alarm':
                detail = f"Peak {timestamp(item['peakTime'], axis)}; original score {n(item.get('rawPeakScore', item['peakScore']))}; variables: " + ', '.join(signal_label(analysis_datasets[item['analysisId']], s) for s in item['signals'])
            if item.get('safety'):
                detail = safety_summary(item['safety'])
            if item.get('observationWindow'):
                detail = 'Observation window ' + ' - '.join(n(v) for v in item['observationWindow']) + ' s · ' + display_label(item.get('hypothesis') or '')
                if item.get('actionAt') is not None:
                    detail += '; intervention time ' + n(item['actionAt']) + ' s'
            target = 'entry-' + item['entryId'] if item.get('entryId') else 'analysis-' + item['analysisId'] if item.get('analysisId') else 'source-' + item.get('linkId', '')
            time = timestamp(item['start'], axis) + (' → ' + timestamp(item['end'], axis) if item['end'] != item['start'] else '')
            rows.append([e(time), f"""<a href="#{e(target)}">{e(display_label(KINDS.get(item['kind'], item['kind'])))} · {e(event_title(item))}</a>""", e(detail), e(recorded_time(item['recordedAt']) if item.get('recordedAt') else 'Incident range')])
        parts.append('<div class="timeline">' + table(['Actual observation time / range', 'Record', 'Content', 'Record created'], rows) + '</div>')
    parts.append('<h3>Investigation actions and records without observation times</h3>')
    recorded = sorted([v for v in view['events'] if v['start'] is None], key=lambda v: v.get('recordedAt', ''))
    rows = []
    labels = {'status': 'Status', 'conclusion': 'Conclusion', 'title': 'Title', 'description': 'Overview', 'start_time': 'Start time', 'end_time': 'End time', 'time_origin': 'Time origin', 'time_axis_key': 'Time source'}
    for item in recorded:
        detail = display_label(item.get('content', '')) if item['kind'] == 'truth' else item.get('content', '')
        if item.get('safety'):
            detail = safety_summary(item['safety'])
        if item.get('changes'):
            detail = '\n'.join(labels.get(k, k) + ': ' + str(display_label(STATUS.get(v['before'], v['before'])) if k == 'status' and v['before'] is not None else v['before'] if v['before'] is not None else 'Not set') + ' → ' + str(display_label(STATUS.get(v['after'], v['after'])) if k == 'status' else v['after']) for k, v in item['changes'].items())
        rows.append([e(recorded_time(item['recordedAt'])), e(event_title(item)), '<span class="prose">' + e(detail) + '</span>'])
    parts.append(table(['Record time (separate from equipment observation time)', 'Investigation action', 'Saved content / changes'], rows) if rows else '<p>No records of this kind.</p>')
    parts.append('<h2>2. Monitoring and analysis comparison</h2><p class="muted">Statistics include only intervals linked to this incident, or every interval of a linked full analysis. Duration is the last minus first sample time; a one-point alarm has 0 s duration. Common / unique intervals are classified only within joint valid observations. Abstain and time outside the window do not count as no alarm.</p>')
    for group in view['comparisons']:
        axis = axes[group['axisId']]
        members = [a for a in view['analyses'] if a['id'] in group['analysisIds']]
        parts.append('<h3>' + e(axis['label']) + '</h3>')
        parts.append(lanes(members, axis))
        parts.append(table(['Analysis / dataset', 'Scope', 'First alarm / peak time', 'Interval count / duration', 'Original peak / threshold', 'Main variables'], [
            [f"""<a href="#analysis-{a['id']}">{e(a['result']['name'])}</a><br>{e(a['datasetName'])}<br>{e(display_label(a['result']['algorithmLabel']))}""", e(display_label(a['scope'])),
             e(timestamp(min((i['start'] for i in a['intervals']), default=None), axis)) + '<br>' + e(timestamp(max(a['intervals'], key=lambda i: i['peakScore'])['peakTime'], axis) if a['intervals'] else 'Not detected'),
             str(len(a['intervals'])) + ' / ' + n(sum(i['end']-i['start'] for i in a['intervals'])) + ' s',
             peak_stat(a),
             e(', '.join(signal_label(a['datasetId'], s) for s in a['result']['relatedSignals'][:5]))] for a in members]))
        spread = n(group['firstAlarmSpread']) + ' s' if group['firstAlarmSpread'] is not None else 'Not applicable (requires two analyses with alarms)'
        parts.append(f"<p>First alarm: {e(timestamp(group['firstDetection'], axis))}; first-alarm spread between analyses with alarms: {e(spread)}.</p>")
        if len(members) > 1:
            names = {a['id']: a['result']['name'] for a in members}
            parts.append(table(['Comparison class', 'Start', 'End', 'Duration', 'Detecting analyses'], [
                [e({'common': 'Detected by all', 'unique': 'Unique detection', 'partial': 'Detected by some', 'uncompared': 'No joint observations; not compared'}[s['kind']]),
                 e(timestamp(s['start'], axis)), e(timestamp(s['end'], axis)), n(s['end']-s['start']) + ' s', e(', '.join(names[i] for i in s['analysisIds']))] for s in group['segments']]))
    if not view['analyses']:
        parts.append('<p>No anomaly detection analyses are linked to this incident yet.</p>')
    parts.append('<h2>3. Key curves, detection metrics and variable contributions</h2>')
    for a in view['analyses']:
        result, axis = a['result'], axes[a['axisId']]
        parts.append(f"""<h3 id="analysis-{a['id']}">{e(result['name'])} · {e(display_label(result['algorithmLabel']))}</h3>""")
        external = result.get('external') or datasets[a['datasetId']]['metadata'].get('external')
        onset = external.get('faultOnsetSeconds') if external else None
        markers = [dict(time=onset+a['offset'], label='Known dataset fault injection')] if onset is not None else []
        if external:
            parts.append('<h4>Original external source and known fault labels</h4>'+technical(external))
        if result.get('training'):
            parts.append('<h4>Normal fit, calibration and independent test sources</h4>'+technical(result['training']))
            if result.get('experiment'):
                run = store.experiments.run(result['experiment']['runId'])
                task = next((t for t in run['tasks'] if t['id'] == result['experiment']['taskId']), None)
                if task:
                    parts.append('<h4>Saved experiment evaluation (labels separate from hypotheses)</h4>'+technical(task['metrics']))
        times = [t + a['offset'] for t in result['times']]
        scores = [None if result.get('states', [])[i:i+1] == ['abstain'] else v for i, v in enumerate(result['scores'])]
        gap = result['config'].get('gapThreshold', datasets[a['datasetId']]['metadata']['quality']['gapThreshold'])
        segments = segment_ids(np.asarray(times), np.asarray([np.nan if v is None else v for v in scores]), gap).tolist()
        score_unit = result['model']['score'] if result.get('regimeRunId') else 'Original algorithm score (each method has its own scale)'
        parts.append(chart('Anomaly score and fixed threshold · ' + a['datasetName'], times, [dict(label=display_label(result['algorithmLabel']), values=scores, segmentIds=segments, color='#b45742')],
                           axis=axis, threshold=result['threshold'], intervals=a['intervals'], markers=markers, unit=score_unit))
        summary = result['summary']
        parts.append(f"""<p class="muted">Fit {summary['fitSamples']} samples; calibration {summary['calibrationSamples']} samples; analysis {summary['analysisSamples']} samples; alarm {summary['flaggedSamples']}  samples; abstain {summary.get('abstainedSamples', 0)} samples. These metrics describe the full analysis.</p>""")
        parts.append(table(['Linked interval start', 'End', 'Peak time', 'Peak score / samples'], [
            [e(timestamp(i['start'], axis)), e(timestamp(i['end'], axis)), e(timestamp(i['peakTime'], axis)), n(i.get('rawPeakScore', i['peakScore'])) + ' / ' + str(i['samples'])] for i in a['intervals']]))
        peak = max(a['intervals'], key=lambda i: i['peakScore']) if a['intervals'] else None
        contributions = (peak or {}).get('contributions') or result.get('signalContributions', [])
        parts.append('<h4>Key variables · ' + e(display_label(METRIC.get(result.get('contributionMetric'), 'Saved variable ranking'))) + '</h4>')
        parts.append(table(['Variable', 'Contribution (retains the method’s meaning)'], [[e(signal_label(a['datasetId'], c['signal'])), n(c['value'])] for c in contributions[:10]]))
        if not result.get('regimeRunId'):
            parts.append('<p class="muted">Contributions use the linked peak with the highest original score, or the full-analysis peak when there are no linked alarms. Contributions from different methods cannot be added or directly ranked together.</p>')
        native_range = result['config']['analysisRange']
        if a['intervals'] and a['scope'] != 'Full analysis':
            lo, hi = min(i['start'] for i in a['intervals'])-a['offset'], max(i['end'] for i in a['intervals'])-a['offset']
            padding = max((hi-lo)*.15, (native_range[1]-native_range[0])*.02)
            native_range = [max(native_range[0], lo-padding), min(native_range[1], hi+padding)]
        signals = list(dict.fromkeys([c['signal'] for c in contributions[:3]] or result['relatedSignals'][:3]))
        if signals:
            series = store.series(a['datasetId'], signals, *native_range)
            for signal in signals:
                unit = next((c.get('unit') for c in datasets[a['datasetId']]['metadata']['columns'] if c['name'] == signal), None)
                label = signal_label(a['datasetId'], signal)
                parts.append(chart('Original variable trends · ' + label, [t+a['offset'] for t in series['times']],
                    [dict(label=label, values=series['values'][signal], segmentIds=series['segmentIds'][signal])], axis=axis, intervals=a['intervals'], markers=markers, unit=unit or 'Original values (source provides no units)'))
            parts.append(f"""<p class="muted">{e(a['datasetName'])}; displaying {series['displayRows']} / {series['sourceRows']} samples. Long sequences use extrema-preserving display sampling; detection uses the full data.</p>""")
    # Standalone dataset links still contribute genuine observed charts to a report without analyses.
    analyzed = {a['datasetId'] for a in view['analyses']}
    observed_sources = {l['details']['datasetId'] for l in incident['links']
                        if l['kind'] != 'prognostic' and l['details'].get('datasetId')}
    observed_sources = {link['details'].get('datasetId') for link in incident['links'] if link['kind'] != 'safety-predicted'}
    for dataset in view['datasets']:
        if dataset['id'] in analyzed or dataset['id'] not in observed_sources:
            continue
        from .incident_timeline import clock_for_key
        clock = clock_for_key(store, 'dataset:' + dataset['id'])
        series = store.series(dataset['id'])
        for signal, values in series['values'].items():
            label = signal_label(dataset['id'], signal)
            unit = next((c.get('unit') for c in dataset['metadata']['columns'] if c['name'] == signal), '')
            parts.append(chart(dataset['name'] + ' · ' + label, [t+clock['offset'] for t in series['times']], [dict(label=label, values=values, segmentIds=series['segmentIds'][signal])], axis=axes.get(clock['axisId']), unit=unit or 'Original values (source provides no units)'))
    from .sensor_health_reports import diagnostic_sections
    parts.extend(diagnostic_sections(store, incident, axes))
    parts.append('<h2>4. Investigation evidence and hypotheses</h2>')
    entries = incident['entries']
    for entry in sorted(entries, key=lambda v: (v['kind'] != 'hypothesis', v['created_at'])):
        parts.append(f"""<h3 id="entry-{entry['id']}">{e(display_label(KINDS[entry['kind']]))} · {e(entry['title'])}</h3>""")
        if entry['kind'] == 'evidence':
            hypothesis = next((v['title'] for v in entries if v['id'] == entry['hypothesis_id']), None)
            parts.append(f"<p>{e(display_label(STANCE[entry['stance']]))}:{e(hypothesis or 'No hypothesis linked yet')}</p>")
        parts.append('<div class="evidence' + (' opposed' if entry['stance'] == 'oppose' else '') + '">' + prose(entry['content']) + '</div>')
        source = next((l for l in incident['links'] if l['id'] == entry['source_link_id']), None)
        observation = next(v for v in view['events'] if v.get('entryId') == entry['id'])
        parts.append(f"""<p class="muted">Actual observation: {e(timestamp(observation['start'], axes.get(observation['axisId'])))}; created: {e(recorded_time(entry['created_at']))}; updated: {e(recorded_time(entry['updated_at']))}; source: {e(source['details']['title'] if source else 'Manual record / source unlinked')}; record ID: {e(entry['id'])}</p>""")
        if entry['kind'] == 'hypothesis':
            for stance in STANCE:
                related = [v for v in entries if v['hypothesis_id'] == entry['id'] and v['stance'] == stance]
                parts.append('<p>' + e(display_label(STANCE[stance])) + 'Evidence: ' + (', '.join(f"""<a href="#entry-{v['id']}">{e(v['title'])}</a>""" for v in related) or 'Not yet recorded') + '</p>')
    if not entries and not any(link['details'].get('safety') for link in incident['links']):
        parts.append('<p>No investigation evidence or hypotheses have been saved yet.</p>')
    for link in incident['links']:
        if link['kind'] != 'prognostic':
            continue
        session = store.prognostics.get(incident['workspace_id'], link['reference_id'])
        forecast, config = session['forecast'], session['config']
        indicator, rul = config['indicator'], forecast['rul']
        missing_bound = 'Beyond forecast horizon' if forecast['distribution'] else 'Unavailable'

        def bound(key):
            return n(rul[key]) if rul[key] is not None else missing_bound

        parts.append(f"""<h3 id="source-{link['id']}">Prognostic forecast · {e(session['name'])}</h3>""")
        parts.append(prose('Threshold forecasts are conditional on the saved model and operating assumptions.'))
        parts.append(table(['Parameter', 'Saved value'], [
            ['Asset', e(config['assetName'])], ['Condition indicator', e(indicator['definition'])],
            ['Failure threshold', e(f"{n(indicator['failure_threshold'])} {indicator['unit']}")],
            ['Forecast status', e(display_label(PROGNOSTIC_STATUS[forecast['status']]))],
            ['Median RUL (s)', e(bound('median'))], ['RUL prediction interval (s)', e(' – '.join(bound(k) for k in ('lower', 'upper')))],
            ['Prognostic session ID', e(session['id'])]]))
        if forecast['distribution']:
            parts.append(chart('First-passage probability', [d['time'] for d in forecast['distribution']],
                [dict(label='First-passage probability', values=[d['probability'] for d in forecast['distribution']])],
                unit='Probability', domain=(0, 1)))
    for link in incident['links']:
        detail = link['details']
        if safety := detail.get('safety'):
            parts.append(f"""<h3 id="source-{e(link['id'])}">{e(safety['constraintName'])}</h3>""")
            parts.append(prose(safety_summary(safety)))
            parts.append(prose(f"Safety assessment {detail['title']} · {detail['assessmentId']}"))
    simulation_links = [l for l in incident['links'] if l['kind'] in ('simulation', 'run')]
    if simulation_links:
        parts.append('<h2>5. Simulation investigation and intervention comparison</h2>')
        for link in simulation_links:
            detail = link['details']
            parts.append(f"""<h3 id="source-{link['id']}">{e(detail['title'])}</h3>""")
            session = store.runtime.get(detail['simulationId'])
            parts.append('<h4>Model and scenario provenance</h4>' + parameters(dict(modelId=session['modelId'], modelVersion=session['modelVersion'],
                modelName=session['modelDescriptor']['name'], scenarioId=session['scenarioId'], scenarioVersion=session['scenarioVersion'])))
            parts.append('<h4>Process model configuration</h4>' + parameters(session['config']))
            parts.append(table(['Signal','Unit'], [[e(display_label(s.get('label', s.get('tag', s['key'])))), e(display_label(s.get('unit','Unknown')))] for s in session['modelDescriptor']['signals']]))
            run = detail.get('run')
            if not run:
                parts.append('<p>Saved observation context: </p>' + parameters(detail.get('observationWindow', {})))
                continue
            parts.append(f"<p>Experiment ID: {e(run['id'])}; type: {e(display_label(run['kind']))}; recorded: {e(recorded_time(run['createdAt']))}</p><h4>Experiment parameters and observation window</h4>" + parameters(run['request']))
            result = run['result']
            if run['kind'] == 'intervention' and result.get('format') == 'model-forecast-v1':
                paths = [result['baseline'], *result['branches']]
                definitions = result['metricDefinitions']
                parts.append(table(['Action', *[e(display_label(m['label'])+' ('+display_label(m['unit'])+')') for m in definitions]],
                    [[e(display_label(p.get('action')) or 'No-intervention baseline'), *[n(p['metrics'][m['key']]) for m in definitions]] for p in paths]))
                for signal in result['signalDefinitions']:
                    parts.append(chart(display_label(signal.get('label', signal['key'])), paths[0]['times'],
                        [dict(label=display_label(p.get('action')) or 'No-intervention baseline', values=p['values'][signal['key']], color=['#a34e3b','#246b63','#536daf','#9565a6','#957123'][i % 5]) for i,p in enumerate(paths)], unit=display_label(signal['unit'])))
                parts.append(prose(display_label(result['uncertainty'])))
            elif run['kind'] == 'intervention':
                paths = [result['baseline'], *result['branches']]
                parts.append(table(['Action', 'Peak physical pressure kPa', 'Predicted limit-crossing time s', 'Production loss %', 'Quality loss pp', 'Utility use %·s'], [
                    [e(display_label(p.get('action', 'No-intervention baseline'))), n(p['physicalPeak']), n(p['trip']), n(p['productionLoss']), n(p['qualityLoss']), n(p['utilityCost'])] for p in paths]))
                colors = ['#a34e3b', '#246b63', '#536daf', '#9565a6', '#957123']
                # Runtime branches use the same simulation cadence. Retain each grid if a historical result differs.
                same_grid = all(p['times'] == paths[0]['times'] for p in paths)
                domain = [min(v for p in paths for v in p['pressure']), max(v for p in paths for v in p['pressure'])]
                for group in [paths] if same_grid else [[p] for p in paths]:
                    parts.append(chart('Intervention comparison · physical pressure', group[0]['times'], [dict(label=display_label(p.get('action', 'No-intervention baseline')), values=p['pressure'], color=colors[i % len(colors)]) for i, p in enumerate(group)], threshold=result['threshold'], unit='Physical pressure (kPa)', domain=domain))
                parts.append('<p class="muted">Curve colors correspond in order to: ' + e(' · '.join(display_label(p.get('action', 'No-intervention baseline')) for p in paths)) + '. Forecasts are conditional on the saved model mode, hypothesis and observation cutoff.</p>')
                parts.append('<h4>Fitted parameters and recovery windows</h4>' + parameters({k: result[k] for k in ('mode', 'hypothesis', 'observedThrough', 'at', 'horizon', 'fitError', 'fittedParameters') if k in result}))
                if result.get('search'):
                    search = result['search']
                    parts.append(f"<p>Recovery-window search resolution: {e(n(search['resolution']))} s; computed {e(search['evaluated'])} simulations. These boundaries refer only to the searched grid.</p>")
                    parts.append(table(['Action', 'Latest recoverable start (s)', 'Recoverable intervals (s)'], [[e(display_label(action.get('name', action['id']))), n(action['latest']), e('; '.join(' - '.join(n(t) for t in span) for span in action['intervals']) or 'Not detected')] for action in search['actions']]))
            else:
                if result.get('summary'):
                    parts.append(prose(result['summary'] if result.get('provider') == 'local' else result['summary']))
                for trace in result.get('trace', []):
                    parts.append('<h4>' + e(display_label(trace['tool'])) + '</h4>' + technical(trace))
                if result.get('limitation'):
                    parts.append(prose(display_label(result['limitation']) if result.get('provider') == 'local' else result['limitation']))
    parts.append(f"<h2>{(6 if simulation_links else 5)}. Investigation conclusion and main evidence</h2><p>Current status: " + e(display_label(STATUS[incident['status']])) + '</p>' + prose(incident['conclusion']))
    evidence = [v for v in entries if v['kind'] == 'evidence']
    parts.append('<p>Saved evidence: ' + (', '.join(f"""<a href="#entry-{v['id']}">{e(v['title'])}</a>({e(display_label(STANCE[v['stance']]))})""" for v in evidence) or 'Not yet recorded') + '</p>')
    for item in view['analyses']:
        analysis = item['result']
        if analysis['config'].get('industrialStudy') and analysis.get('experiment'):
            from .industrial_study import saved_evidence
            run = store.experiments.run(analysis['experiment']['runId'])
            evidence = saved_evidence(store, run['id'])
            if evidence:
                parts.append('<h2>Mode 1 cooling-water investigation</h2>')
                diagnosis = evidence['diagnosis']
                if diagnosis:
                    parts.append(prose(f"Closest trajectory: {diagnosis['hypothesis']}. Observed through {diagnosis['cutoff']} s."))
                    parts.append(table(['Hypothesis', 'RMS whitened residual', 'Estimated onset (s)'],
                        [[e(role), n(value), e(diagnosis['estimatedOnsets'].get(role))] for role, value in diagnosis['distances'].items()]))
                parts.append(table(['Simulated trajectory', 'Temperature MAE (°C)', 'Valve travel (pp)', 'Peak pressure (kPa gauge)'],
                    [[e(role), n(c['reactorTemperatureMAE']), n(c['coolingValveTravel']), n(c['peakReactorPressure'])]
                     for role, c in evidence['comparison'].items()]))
                parts.extend(prose(assumption) for assumption in evidence['assumptions'])
                task = next(t for t in run['tasks'] if t['result_id'] == analysis['id'])
                parts.append('<details><summary>Detection metrics, source runs and model provenance</summary>' +
                             technical(task['metrics']['detection']) + technical(evidence['sources']) + technical(analysis['model']) + '</details>')
    parts.append('<h2>Appendix. Data, parameters and linked records</h2>')
    for dataset in view['datasets']:
        lineage = dataset['metadata'].get('transformation')
        if lineage:
            parts.append('<h3>Derived data provenance and processing: ' + e(dataset['name']) + '</h3>')
            parts.append(prose(f"Transformation: {lineage['definitionName']}; version: {lineage['revision']}; execution: {lineage['executionId']}; created: {lineage['createdAt']}."))
            parts.append(table(['Source dataset', 'Identifier', 'Original numerical file SHA-256'], [[e(s['datasetName']), e(s['datasetId']), e(s['sha256'])] for s in lineage['sources']]))
            parts.append(table(['Output variable', 'Original signal ID', 'Unit conversion', 'Resampling / maximum gap', 'Missing values / duplicate times'], [
                [e(s['displayName']) + ' / ' + e(s['key']), e(s['signalId']), e(s['sourceUnit'] or 'Unspecified') + ' → ' + e(s['unit'] or 'Unspecified'),
                 e(s['resampling']) + ' / ' + e(n(s['maxGapSeconds'])) + ' s', e(json.dumps(s['missing'], ensure_ascii=False)) + ' / ' + e(s['duplicatePolicy'])]
                for s in lineage['config']['sources']]))
            for output in lineage['config']['derived']:
                parts.append(prose(output['displayName'] + ': ' + output['key'] + ' = ' + output['expression']))
            parts.append(prose('Interpolated, held and filled values retain their processing markers. The observation policy defines which values count toward coverage. Statistical fills use valid observations from the output window. Select a healthy interval for the baseline.'))
            parts.append(technical(dict(grid=lineage['grid'], quality=lineage['quality'], sourceSimulations=lineage['sourceSimulations'], definition=lineage['config'])))
    parts.append(table(['Dataset / identifier', 'Sampling and time metadata', 'Variable / original column'], [[e(d['name']) + '<br>' + e(d['id']), e(json.dumps(dict(source=d['metadata']['time'], browsingClock=d['metadata']['clock']), ensure_ascii=False)) + '<br>' + str(d['metadata']['rowCount']) + ' rows', e(', '.join(signal_label(d['id'], c['name']) + ' / ' + c['name'] for c in d['metadata']['columns']))] for d in view['datasets']]))
    for a in view['analyses']:
        parts.append('<h3>' + e(a['result']['name']) + '</h3><p>Analysis ID: ' + e(a['id']) + '; contribution meaning: ' + e(display_label(METRIC.get(a['result'].get('contributionMetric'), 'Historical ranking'))) + '</p>' + parameters(a['result']['config']))
        if a['result'].get('experiment'):
            parts.append('<h4>Source analysis experiment / run / task</h4>' + technical(a['result']['experiment']))
    parts.append(table(['Linked record ID', 'Type', 'Original record ID / interval index', 'Created'], [[e(l['id']), e(l['kind']), e(l['reference_id']) + '<br>' + e(l['selector']), e(recorded_time(l['created_at']))] for l in incident['links']]))
    parts.append(f"<footer>L5 industrial incident investigation · {e(identity)} · Generated {e(recorded_time(view['generatedAt']))}<br>Standalone offline report; regeneration reads the latest saved content. Investigation conclusions retain the user’s original text.</footer></main></body></html>")
    return ''.join(parts)
