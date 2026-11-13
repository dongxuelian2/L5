"""HTTP endpoints for local safety assessments."""
from .safety_reports import export


def route(handler, service, method, workspace_id, tail, body, query):
    result, status = None, 200
    if tail == ['configurations']:
        if method == 'GET':
            result = dict(configurations=service.configurations(workspace_id))
        elif method == 'POST':
            result, status = service.save_configuration(workspace_id, body), 201
    elif len(tail) == 2 and tail[0] == 'configurations':
        if method == 'GET':
            revision = query.get('revision', [None])[0]
            result = service.get_configuration(workspace_id, tail[1], int(revision) if revision is not None else None)
        elif method == 'PATCH':
            result = service.save_configuration(workspace_id, body, tail[1])
    elif tail == ['assessments']:
        if method == 'GET':
            result = dict(assessments=service.assessments(workspace_id))
        elif method == 'POST':
            result, status = service.save_assessment(workspace_id, body), 201
    elif tail == ['evaluate'] and method == 'POST':
        result = service.evaluate(workspace_id, body)
    elif len(tail) >= 2 and tail[0] == 'assessments':
        identity = tail[1]
        if len(tail) == 2 and method == 'GET':
            result = service.get_assessment(workspace_id, identity)
        elif tail[2:] == ['incident-evidence'] and method == 'POST':
            result, status = service.attach(workspace_id, identity, body), 201
        elif tail[2:] == ['export'] and method == 'GET':
            assessment = service.get_assessment(workspace_id, identity)
            content, extension, media_type = export(assessment, query.get('format', ['json'])[0], query.get('lang', ['en'])[0])
            payload = content.encode('utf-8')
            handler.send_response(200)
            handler.send_header('Content-Type', f'{media_type}; charset=utf-8')
            handler.send_header('Content-Disposition', f'attachment; filename="l5-safety-{assessment["id"]}.{extension}"')
            handler.send_header('Content-Length', str(len(payload)))
            handler.send_header('Cache-Control', 'no-store')
            handler.end_headers()
            handler.wfile.write(payload)
            return True
    handler.send_json(status if result is not None else 404, result if result is not None else {'error': 'Unknown safety endpoint.'})
    return True
