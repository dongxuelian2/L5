"""Workspace-scoped predictive maintenance HTTP endpoints."""
from .prognostic_sessions import export_session


def dispatch_prognostics(handler, store, method, workspace, path, body):
    service = store.prognostics
    if method == 'POST':
        if path == ['fit']:
            return service.fit(workspace, body), 200
        if path == ['benchmark']:
            return service.benchmark(workspace, body), 201
        if path == ['evaluate']:
            return service.evaluate(workspace), 200
        if path == ['sessions']:
            return service.save(workspace, body), 201
        if len(path) == 3 and path[0] == 'sessions' and path[2] == 'incidents':
            service.get(workspace, path[1])
            incident = store.incidents.row(body.get('incidentId', ''))
            if incident['workspace_id'] != workspace:
                raise ValueError('Incident belongs to a different workspace.')
            return store.incidents.add_link(incident['id'], dict(kind='prognostic', sessionId=path[1])), 201
    if method == 'GET':
        if path == ['sessions']:
            return dict(sessions=service.list(workspace)), 200
        if len(path) == 2 and path[0] == 'sessions':
            return service.get(workspace, path[1]), 200
        if len(path) == 3 and path[0] == 'sessions' and path[2] in ('forecast.csv', 'maintenance.csv', 'session.json'):
            session = service.get(workspace, path[1])
            content_type, text = export_session(session, path[2])
            data = text.encode('utf-8')
            handler.send_response(200)
            handler.send_header('Content-Type', content_type + '; charset=utf-8')
            handler.send_header('Content-Length', str(len(data)))
            handler.send_header('Content-Disposition', f'attachment; filename="l5-{session["id"]}-{path[2]}"')
            handler.send_header('Cache-Control', 'no-store')
            handler.end_headers()
            handler.wfile.write(data)
            return None, None
    return None, 404
