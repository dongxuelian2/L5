"""HTTP routing for saved experiments and immutable dataset label versions."""
from urllib.parse import parse_qs


def route(store, method, parts, body):
    service = store.experiments
    result, status = None, 200
    if parts[1] == 'experiments':
        if len(parts) == 3:
            if method == 'GET':
                result = service.get(parts[2])
            elif method == 'PATCH':
                previous = service.get(parts[2])
                result = service.save(previous['workspace_id'], body, parts[2])
        elif len(parts) == 4:
            if parts[3] == 'copy' and method == 'POST':
                result, status = service.copy(parts[2]), 201
            elif parts[3] == 'runs':
                if method == 'GET':
                    service.get(parts[2])
                    result = dict(runs=service.runs(parts[2]))
                elif method == 'POST':
                    result, status = service.execute(parts[2], body), 202
            elif parts[3] == 'comparison' and method == 'POST':
                result = service.comparison(parts[2], body)
    elif parts[1] == 'experiment-runs':
        if len(parts) == 3 and method == 'GET':
            result = service.run(parts[2])
        elif len(parts) == 4 and parts[3] == 'incidents' and method == 'POST':
            result, status = service.link_incident(parts[2], body), 201
    return result, status


def report(handler, store, identity, query):
    from .experiment_reports import render_experiment_report
    params = parse_qs(query)
    payload = render_experiment_report(store, identity, params.get('run', [None])[0]).encode('utf-8')
    handler.send_response(200)
    handler.send_header('Content-Type', 'text/html; charset=utf-8')
    handler.send_header('Content-Length', str(len(payload)))
    handler.send_header('Cache-Control', 'no-store')
    if params.get('download') == ['1']:
        handler.send_header('Content-Disposition', f'attachment; filename="l5-experiment-{identity}.html"')
    handler.end_headers()
    handler.wfile.write(payload)
