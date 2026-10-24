"""Workspace HTTP routes for the local modular monolith."""
from __future__ import annotations

import json
import os
import traceback
from urllib.parse import parse_qs, urlparse

from .datasets import prepare_csv, series_preview


def dispatch(handler, method: str) -> bool:
    url = urlparse(handler.path)
    parts = url.path.strip('/').split('/')
    if len(parts) < 2 or parts[0] != 'api' or parts[1] not in ('workspaces', 'datasets', 'analyses', 'simulations'):
        return False
    store = handler.server.workspace_store
    try:
        body = {}
        if method in ('POST', 'PATCH'):
            length = int(handler.headers.get('Content-Length', '0'))
            limit = int(os.environ.get('L5_MAX_REQUEST_BYTES', 256 * 1024 * 1024))
            if not 0 < length <= limit:
                handler.send_json(413, {'error': f'Request exceeds the configured {limit}-byte server budget (L5_MAX_REQUEST_BYTES).'})
                return True
            body = json.loads(handler.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError('Request must be a JSON object.')
        result, status = None, 200
        if parts[1] == 'simulations':
            runtime = store.runtime
            if parts == ['api', 'simulations', 'catalog'] and method == 'GET':
                from .runtime import catalog
                result = catalog()
            elif len(parts) == 2:
                if method == 'POST':
                    result, status = runtime.create(body), 201
                elif method == 'GET':
                    query = parse_qs(url.query)
                    result = {'simulations':runtime.list(query.get('workspaceId', [None])[0])}
            elif len(parts) == 3 and method == 'GET':
                result = runtime.get(parts[2])
            elif len(parts) == 4:
                identity, operation = parts[2:]
                if operation == 'runs' and method == 'GET':
                    result = {'runs':runtime.runs(identity)}
                elif method == 'POST':
                    operations = {'analysis':runtime.analysis, 'tools':runtime.tools,
                                  'interventions':runtime.intervene, 'save':runtime.save}
                    if operation in operations:
                        result = operations[operation](identity, body)
        elif parts == ['api', 'workspaces']:
            if method == 'GET':
                result = {'workspaces': store.list_workspaces()}
            elif method == 'POST':
                result, status = store.create_workspace(body.get('name')), 201
        elif len(parts) == 3 and parts[1] == 'workspaces':
            if method == 'GET':
                result = store.workspace(parts[2])
            elif method == 'PATCH':
                result = store.rename_workspace(parts[2], body.get('name'))
            elif method == 'DELETE':
                store.delete_workspace(parts[2])
                result = {'deleted': True}
        elif len(parts) == 4 and parts[1] == 'workspaces':
            if parts[3] == 'datasets':
                if method == 'GET':
                    result = {'datasets': store.datasets(parts[2])}
                elif method == 'POST':
                    result, status = store.import_dataset(parts[2], body), 201
            elif parts[3] == 'analyses':
                if method == 'GET':
                    result = {'jobs': store.jobs(parts[2])}
                elif method == 'POST':
                    result, status = store.analyze(parts[2], body), 201
        elif parts == ['api', 'datasets', 'preview'] and method == 'POST':
            metadata, times, values = prepare_csv(body.get('csv'), body)
            names = [c['name'] for c in metadata['columns'][:4]]
            result = {'metadata': metadata, 'series': series_preview(times, values[:, :4], names)}
        elif len(parts) == 3 and parts[1] == 'datasets' and method == 'GET':
            result = store.dataset(parts[2])
        elif len(parts) == 4 and parts[1] == 'datasets' and parts[3] == 'series' and method == 'GET':
            query = parse_qs(url.query)
            result = store.series(parts[2], query.get('signal'),
                                  float(query['start'][0]) if 'start' in query else None,
                                  float(query['end'][0]) if 'end' in query else None)
        elif len(parts) == 3 and parts[1] == 'analyses' and method == 'GET':
            result = store.result(parts[2])
        handler.send_json(status if result is not None else 404, result if result is not None else {'error': 'Unknown workspace endpoint.'})
    except KeyError as error:
        handler.send_json(404, {'error': str(error.args[0])})
    except (ValueError, TypeError, OverflowError) as error:
        handler.send_json(400, {'error': str(error)})
    except Exception:
        traceback.print_exc()
        handler.send_json(500, {'error': 'Unable to complete the operation. See the local server log.'})
    return True
