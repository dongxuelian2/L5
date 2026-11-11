"""Local HTTP entry points for fitted operating regimes and saved runs."""
from urllib.parse import parse_qs


def route(handler, service, method, parts, body, query):
    if parts[1] == 'regime-runs':
        if len(parts) == 3 and method == 'GET':
            return service.run(parts[2]), 200
        return None, 404
    workspace, path = parts[2], parts[4:]
    if path == ['fit'] and method == 'POST':
        return service.fit(workspace, body), 201
    if path == ['models'] and method == 'GET':
        return {'models': service.models(workspace)}, 200
    if len(path) == 2 and path[0] == 'models' and method == 'GET':
        return service.model(workspace, path[1]), 200
    if path == ['runs']:
        if method == 'GET':
            return {'runs': service.runs(workspace)}, 200
        if method == 'POST':
            return service.execute(workspace, body), 201
    if len(path) >= 2 and path[0] == 'runs':
        run_id = path[1]
        if len(path) == 2 and method == 'GET':
            return service.run(run_id, workspace), 200
        if path[2:] == ['incidents'] and method == 'POST':
            return service.link_incident(workspace, run_id, body), 201
        if path[2:] == ['report.html'] and method == 'GET':
            from .regime_report import render_regime_report
            params = parse_qs(query)
            run = service.run(run_id, workspace)
            content = render_regime_report(run, locale=params.get('lang', ['en'])[0]).encode('utf-8')
            handler.send_response(200)
            handler.send_header('Content-Type', 'text/html; charset=utf-8')
            handler.send_header('Content-Length', str(len(content)))
            handler.send_header('Cache-Control', 'no-store')
            if params.get('download') == ['1']:
                handler.send_header('Content-Disposition', f'attachment; filename="l5-regime-{run_id}.html"')
            handler.end_headers()
            handler.wfile.write(content)
            return None
    return None, 404
