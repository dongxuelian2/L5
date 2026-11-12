"""Alarm workspace endpoints and offline downloads."""
from urllib.parse import parse_qs


def alarm_route(handler, alarms, method, parts, body, query):
    if len(parts) == 4 and parts[1] == 'workspaces':
        if method == 'GET':
            return dict(sessions=alarms.list(parts[2])), 200
        if method == 'POST':
            return alarms.create(parts[2], body), 201
    if len(parts) < 3 or parts[1] != 'alarm-sessions':
        return None, 404
    identity = parts[2]
    if len(parts) == 3 and method == 'GET':
        return alarms.get(identity), 200
    if len(parts) == 6 and method == 'POST':
        if parts[3] == 'events' and parts[5] == 'actions':
            return alarms.event_action(identity, parts[4], body), 200
        if parts[3] == 'groups' and parts[5] == 'incident':
            return alarms.incident(identity, parts[4], body), 200
    if len(parts) == 4 and method == 'GET' and parts[3] in ('report.html', 'history.json'):
        from .alarm_reports import render_alarm_report
        from .alarm_sessions import encode

        view = alarms.get(identity)
        params = parse_qs(query)
        filename = parts[3]
        if filename == 'history.json':
            mime, payload = 'application/json', encode(view).encode('utf-8')
        else:
            mime = 'text/html'
            payload = render_alarm_report(view, params.get('lang', ['en'])[0]).encode('utf-8')
        handler.send_response(200)
        handler.send_header('Content-Type', mime + '; charset=utf-8')
        handler.send_header('Content-Length', str(len(payload)))
        handler.send_header('Cache-Control', 'no-store')
        if filename == 'history.json' or params.get('download') == ['1']:
            handler.send_header('Content-Disposition', f'attachment; filename="l5-alarm-{view["id"]}-{filename}"')
        handler.end_headers()
        handler.wfile.write(payload)
        return None, None
    return None, 404
