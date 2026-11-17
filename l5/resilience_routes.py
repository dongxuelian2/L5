"""Workspace-scoped resilience endpoints and offline campaign reports."""
from urllib.parse import parse_qs


def route(handler, service, method, workspace_id, parts, body, query):
    if method == 'GET':
        if parts == ['catalog']:
            from .resilience_evaluation import campaign_catalog
            from .resilience_simulation import scenario_catalog
            service.store.workspace(workspace_id)
            return {**scenario_catalog(), **campaign_catalog()}, 200
        if parts == ['scenarios']:
            return {'scenarios': service.scenarios(workspace_id)}, 200
        if parts == ['runs']:
            return {'runs': service.runs(workspace_id)}, 200
        if parts == ['campaigns']:
            return {'campaigns': service.campaigns(workspace_id)}, 200
        if len(parts) == 2 and parts[0] == 'runs':
            return service.run(workspace_id, parts[1]), 200
        if len(parts) >= 2 and parts[0] == 'campaigns':
            if len(parts) == 2:
                return service.campaign(workspace_id, parts[1]), 200
            if len(parts) == 4 and parts[2] == 'cases':
                return service.case(workspace_id, parts[1], parts[3]), 200
            if len(parts) == 3 and parts[2] == 'report.html':
                campaign = service.campaign(workspace_id, parts[1])
                options = parse_qs(query)
                payload = report(campaign)
                filename = f'l5-resilience-{campaign["id"]}.html' if options.get('download') == ['1'] else None
                handler.send_content(200, 'text/html', payload, filename=filename)
                return None, None
    elif method == 'POST' and len(parts) == 1:
        operations = {'scenarios': (service.save_scenario, 200 if body.get('id') else 201),
                      'simulate': (service.simulate, 201), 'campaigns': (service.create_campaign, 202),
                      'export': (service.export, 200)}
        if parts[0] in operations:
            operation, status = operations[parts[0]]
            return operation(workspace_id, body), status
        if parts == ['preview']:
            from .resilience_simulation import preview_scenario
            service.store.workspace(workspace_id)
            return preview_scenario(body.get('scenario')), 200
    return None, 404


def report(campaign):
    from .reports import CSS, e, table, technical

    def cell(value):
        if isinstance(value, float):
            value = f'{value:.5g}'
        return e('—' if value is None else value)

    fields = [('eventDetectionRate', 'Event detection rate'),
              ('meanDelay', 'Mean delay (s)'),
              ('missedEvents', 'Missed events'),
              ('unobservedEvents', 'Unobserved events'),
              ('coverage', 'Coverage')]
    rows = []
    for case in campaign['cases']:
        metrics = case['metrics'] or {}
        detector = case['detector']
        rows.append([cell(case['name']), cell(case['phase']), cell(case['family']),
                     cell(f"{detector['algorithm']} ({', '.join(detector.get('signals', []))})"),
                     cell(case['status']), *[cell(metrics.get(field)) for field, _ in fields],
                     cell((metrics.get('normal') or {}).get('alarmFraction')),
                     cell(metrics.get('searchScores', {}).get(case.get('objective'))),
                     cell(case['runtime_ms']), cell(case['error'])])
    title = e(campaign['name'])
    heads = ['Case', 'Phase', 'Family', 'Detector', 'Status',
             *[label for _, label in fields], 'Normal alarm fraction',
             'Search score', 'Runtime (ms)', 'Error']
    explanation = 'Alarm episodes are matched one-to-one to active events by alarm onset. A match is temporal evidence. Use coverage and the observation and detector traces to interpret misses. Search cases are exploratory.'
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} · L5</title>'
            f'<style>{CSS}</style></head><body><main><div class="brand">L5 / RESILIENCE TESTING</div>'
            f'<h1>{title}</h1><p>{e(campaign["mode"])} · {e(campaign["status"])} · {campaign["completed"]}/{campaign["total"]}</p>'
            f'<p>{e(explanation)}</p>{table(heads, rows)}<h2>Saved campaign definition</h2>'
            f'{technical(campaign["definition"])}</main></body></html>')
