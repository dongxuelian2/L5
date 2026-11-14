"""Workspace HTTP endpoints and offline report exports."""

import json
from urllib.parse import parse_qs

from .report_locale import fragment as local, localized_report, text
from .reports import CSS, chart, e, n, table, technical


@localized_report
def render_report(run):
    result = run['analysis']
    config = result['config']
    objective = config['objective']
    profile = config['aggregation']
    conditions = result['conditions']
    objective_label = text('sensor-objective-' + objective)
    sensor_names = {item['key']: text(item['label']) for item in result['sensors']}

    def layout(keys):
        return e(' + '.join(sensor_names[key] for key in keys))

    parts = [
        local('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'),
        e(run['name']), '</title><style>', CSS, '</style></head><body>',
        local('<div class="toolbar"><button onclick="window.print()">Print / Save A4 PDF</button></div><main>'),
        '<h1>', e(run['name']), '</h1><p>', e(run['created_at']), ' · ', e(run['id']), '</p>',
        local('<p>Distances use independent Gaussian samples and the declared cross-sensor covariance. Weak separation is flagged below 2.</p>'),
        local('<p>Detection compares against healthy operation. Isolation compares competing fault hypotheses. State observability concerns reconstruction of internal states and is outside this analysis.</p>'),
        local('<h2>Exact sensor subset comparison</h2>'),
        '<p>', e(objective_label), ' · ', e(text('sensor-aggregation-' + profile)), '</p>',
        table([text('Sensor layout'), text('Installation cost'), text('sensor-aggregation-nominal'),
               text('sensor-aggregation-mean'), text('sensor-aggregation-worst'), text('Pareto frontier')], [
            [layout(row['sensors']), e(n(row['cost'])), e(n(row['nominal'][objective])),
             e(n(row['mean'][objective])), e(n(row['worst'][objective])), e('✓' if row['pareto'] else '—')]
            for row in sorted(result['subsets'], key=lambda row: -row[profile][objective])
        ]),
        local('<h2>Held-out noisy observations</h2>'),
        table([text('Comparison'), text('Sensor layout'), text('Operating condition'), text('Detection rate'),
               text('False alarm rate'), text('Classification accuracy'), text('Ambiguous rate')], [
            [e(text('sensor-layout-' + row['id'])), layout(row['sensors']), e(text('sensor-condition-' + cohort['id'])),
             *(e(f"{cohort[k]:.1%}") for k in ('detectionRate', 'falseAlarmRate', 'classificationAccuracy', 'ambiguousRate'))]
            for row in result['evaluation']['layouts'] for cohort in row['cohorts']
        ]),
        local('<h2>Pump and valve cancellation experiment</h2>'),
        table([text('Operating condition'), text('Sensor layout'), text('Detectability'), text('Isolability')], [
            [e(text('sensor-condition-' + case['id'])), layout(row['sensors']),
             e(n(row['detectability'])), e(n(row['isolability']))]
            for case in result['cancellation']['cases'] for row in case['metrics']
        ]),
    ]
    cancellation = result['cancellation']
    for i, sensor in enumerate(result['sensors'][:2]):
        parts.append(chart(sensor_names[sensor['key']], cancellation['times'], [
            dict(label=text('sensor-fault-' + key), values=[row[i] for row in values])
            for key, values in zip(cancellation['hypotheses'], cancellation['templates'])
        ], unit=sensor['unit']))
    parts.extend([
        local('<h2>Saved analysis settings</h2>'),
        technical(dict(config=config, modelVersion=result['modelVersion'],
                       resolvedConditions=[dict(id=c['id'], model=c['model'], covariance=c['covariance']) for c in conditions],
                       winners=result['winners'], runtimeMs=result['runtimeMs'])),
        '</main></body></html>',
    ])
    return ''.join(parts)


def route(handler, service, method, workspace_id, tail, body, query):
    if not tail:
        if method == 'GET':
            return dict(runs=service.list(workspace_id), **service.options()), 200, False
        if method == 'POST':
            return service.run(workspace_id, body), 201, False
    if len(tail) == 1 and method == 'GET':
        return service.get(workspace_id, tail[0]), 200, False
    if len(tail) == 2:
        identity, action = tail
        if method == 'POST' and action == 'dataset':
            return service.dataset(workspace_id, identity, body), 201, False
        if method == 'GET' and action in ('analysis.json', 'report.html'):
            run = service.get(workspace_id, identity)
            params = parse_qs(query)
            if action == 'analysis.json':
                payload = json.dumps(run, ensure_ascii=False, allow_nan=False, indent=2)
                content_type = 'application/json'
            else:
                payload = render_report(run, locale=params.get('lang', ['en'])[0])
                content_type = 'text/html'
            encoded = payload.encode('utf-8')
            handler.send_response(200)
            handler.send_header('Content-Type', f'{content_type}; charset=utf-8')
            handler.send_header('Content-Length', str(len(encoded)))
            handler.send_header('Cache-Control', 'no-store')
            if action == 'analysis.json' or params.get('download') == ['1']:
                handler.send_header('Content-Disposition', f'attachment; filename="l5-sensor-{identity}-{action}"')
            handler.end_headers()
            handler.wfile.write(encoded)
            return None, 200, True
    return None, 404, False
