"""Local-only HTTP surface for connecting and reading from OPC UA sources."""
from ipaddress import ip_address
from urllib.parse import parse_qs, urlsplit


def loopback(host):
    if not host:
        return False
    if host.lower() == 'localhost':
        return True
    try:
        address = ip_address(host)
        return (getattr(address, 'ipv4_mapped', None) or address).is_loopback
    except ValueError:
        return False


def allowed(handler, method):
    """Prevent remote clients and browser DNS rebinding from reaching the collector."""
    host = handler.headers.get('Host', '')
    origin = handler.headers.get('Origin')
    try:
        if not loopback(handler.client_address[0]) or not loopback(urlsplit('//' + host).hostname):
            return False
        if origin is not None:
            parsed = urlsplit(origin)
            if parsed.scheme not in ('http', 'https') or not loopback(parsed.hostname):
                return False
    except ValueError:
        return False
    return method != 'POST' or handler.headers.get_content_type() == 'application/json'


def route(gateway, method, workspace, path, body, query_string):
    query = parse_qs(query_string, keep_blank_values=True)

    def argument(name, default=None):
        return query.get(name, [default])[0]

    if method == 'GET' and path == ['status']:
        return gateway.status(workspace), 200
    if method == 'POST' and path == ['connect']:
        return gateway.connect(workspace, body), 200
    if method == 'POST' and path == ['disconnect']:
        return gateway.disconnect(workspace), 200
    if method == 'GET' and path == ['browse']:
        return dict(nodes=gateway.node_request(workspace, 'browse', argument('node_id'))), 200
    if method == 'GET' and path == ['read']:
        return gateway.node_request(workspace, 'read', argument('node_id')), 200
    if path == ['sessions']:
        if method == 'GET':
            return dict(sessions=gateway.sessions(workspace)), 200
        if method == 'POST':
            return gateway.start(workspace, body), 201
    if path and path[0] == 'sessions' and len(path) >= 2:
        identity = path[1]
        if len(path) == 2 and method == 'GET':
            return gateway.session(workspace, identity), 200
        if path[2:] == ['samples'] and method == 'GET':
            cursors = {key: int(query[key][0]) for key in ('before_id', 'after_id', 'before_event_id', 'after_event_id') if key in query}
            return gateway.samples(workspace, identity, start=argument('start'), end=argument('end'),
                                   limit=argument('limit', 1000), include_latest=argument('include_latest') == '1', **cursors), 200
        if path[2:] == ['stop'] and method == 'POST':
            return gateway.stop(workspace, identity), 200
        if path[2:] == ['dataset'] and method == 'POST':
            return gateway.dataset(workspace, identity, body), 201
    return None, 404
