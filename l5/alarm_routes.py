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
            mime, payload = 'application/json', encode(view)
        else:
            mime = 'text/html'
            payload = render_alarm_report(view)
        filename = f'l5-alarm-{view["id"]}-{filename}' if filename == 'history.json' or params.get('download') == ['1'] else None
        handler.send_content(200, mime, payload, filename=filename)
        return None, None
    return None, 404
