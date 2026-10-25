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
    if len(parts) < 2 or parts[0] != 'api' or parts[1] not in ('workspaces', 'datasets', 'analyses', 'simulations', 'models', 'scenarios', 'incidents', 'signals', 'transformations', 'units', 'experiments', 'experiment-runs', 'external'):
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
        if parts == ['api', 'external', 'tep', 'sources'] and method == 'GET':
            result = store.tep.sources()
        elif parts == ['api', 'external', 'tep', 'protocol'] and method == 'GET':
            from .tep_import import PROTOCOL
            result = PROTOCOL
        elif parts == ['api', 'external', 'tep', 'preview'] and method == 'POST':
            result = store.tep.preview(body)
        elif parts[1] == 'models' and method == 'GET':
            from .models import catalog, resolve
            if len(parts) == 2:
                result = {'models': catalog()}
            elif len(parts) == 3:
                result = resolve(parts[2]).describe()
        elif parts[1] == 'scenarios':
            if len(parts) == 3:
                if method == 'GET':
                    query = parse_qs(url.query)
                    result = store.scenarios.get(parts[2], int(query['version'][0]) if 'version' in query else None)
                elif method == 'PATCH':
                    previous = store.scenarios.get(parts[2])
                    result = store.scenarios.save(previous['workspaceId'], body, parts[2])
            elif len(parts) == 4:
                if parts[3] == 'versions' and method == 'GET':
                    result = {'versions': store.scenarios.versions(parts[2])}
                elif parts[3] == 'copy' and method == 'POST':
                    result, status = store.scenarios.copy(parts[2], body), 201
                elif parts[3] == 'run' and method == 'POST':
                    result, status = store.runtime.create({**body, 'scenarioId': parts[2]}), 201
        elif parts[1] == 'experiments' and len(parts) == 4 and parts[3] == 'report.html' and method == 'GET':
            from .experiment_routes import report
            report(handler, store, parts[2], url.query)
            return True
        elif parts[1] in ('experiments', 'experiment-runs'):
            from .experiment_routes import route
            result, status = route(store, method, parts, body)
        elif parts == ['api', 'units'] and method == 'GET':
            from .units import catalog
            result = {'units': catalog()}
        elif parts[1] == 'transformations':
            if len(parts) == 3:
                definition = store.transformations.get(parts[2])
                if method == 'GET':
                    result = definition
                elif method == 'PATCH':
                    result = store.transformations.save(definition['workspace_id'], body, parts[2])
            elif len(parts) == 4 and method == 'POST':
                if parts[3] == 'execute':
                    result, status = store.transformations.execute(parts[2], body), 201
                elif parts[3] == 'preview':
                    definition = store.transformations.get(parts[2])
                    result = store.transformations.preview(definition['workspace_id'], definition['config'])
        elif parts[1] == 'signals' and len(parts) == 3 and method == 'PATCH':
            result = store.signals.update_signal(parts[2], body)
        elif parts[1] == 'incidents':
            incidents = store.incidents
            if len(parts) == 3:
                if method == 'GET':
                    result = incidents.get(parts[2])
                elif method == 'PATCH':
                    result = incidents.update(parts[2], body)
            elif len(parts) == 4:
                if parts[3] == 'timeline' and method == 'GET':
                    from .incident_timeline import investigation
                    query = parse_qs(url.query, keep_blank_values=True)
                    result = investigation(store, parts[2], [v for v in query['analysis'] if v] if 'analysis' in query else None)
                elif parts[3] == 'report.html' and method == 'GET':
                    from .reports import render_report
                    payload = render_report(store, parts[2]).encode('utf-8')
                    handler.send_response(200)
                    handler.send_header('Content-Type', 'text/html; charset=utf-8')
                    handler.send_header('Content-Length', str(len(payload)))
                    handler.send_header('Cache-Control', 'no-store')
                    if parse_qs(url.query).get('download') == ['1']:
                        handler.send_header('Content-Disposition', f'attachment; filename="l5-incident-{parts[2]}.html"')
                    handler.end_headers()
                    handler.wfile.write(payload)
                    return True
                elif parts[3] == 'entries':
                    if method == 'GET':
                        result = {'entries': incidents.entries(parts[2])}
                    elif method == 'POST':
                        result, status = incidents.save_entry(parts[2], body), 201
                elif parts[3] == 'links':
                    if method == 'GET':
                        result = {'links': incidents.links(parts[2])}
                    elif method == 'POST':
                        result, status = incidents.add_link(parts[2], body), 201
            elif len(parts) == 5:
                if parts[3] == 'entries':
                    if method == 'PATCH':
                        result = incidents.save_entry(parts[2], body, parts[4])
                    elif method == 'DELETE':
                        result = incidents.remove_entry(parts[2], parts[4])
                elif parts[3] == 'links' and method == 'DELETE':
                    result = incidents.remove_link(parts[2], parts[4])
        elif parts[1] == 'simulations':
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
            elif len(parts) == 5 and parts[3] == 'runs' and method == 'GET':
                result = runtime.run(parts[2], parts[4])
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
            if parts[3] == 'model-research' and method == 'GET':
                from .model_research import research
                result = research(store, parts[2])
            elif parts[3] == 'scenarios':
                if method == 'GET':
                    result = {'scenarios': store.scenarios.list(parts[2])}
                elif method == 'POST':
                    result, status = store.scenarios.save(parts[2], body), 201
            elif parts[3] == 'experiments':
                if method == 'GET':
                    result = {'experiments': store.experiments.list(parts[2])}
                elif method == 'POST':
                    result, status = store.experiments.save(parts[2], body), 201
            elif parts[3] == 'transformations':
                if method == 'GET':
                    result = {'transformations': store.transformations.list(parts[2])}
                elif method == 'POST':
                    result, status = store.transformations.save(parts[2], body), 201
            elif parts[3] == 'signals' and method == 'GET':
                result = {'signals': store.signals.catalog(parts[2])}
            elif parts[3] == 'explore' and method == 'POST':
                result = store.signals.explore(parts[2], body)
            elif parts[3] == 'cursor' and method == 'POST':
                result = store.signals.cursor(parts[2], body)
            elif parts[3] == 'views':
                if method == 'GET':
                    result = {'views': store.signals.views(parts[2])}
                elif method == 'POST':
                    result, status = store.signals.save_view(parts[2], body), 201
            elif parts[3] == 'incidents':
                if method == 'GET':
                    query = parse_qs(url.query)
                    result = {'incidents': store.incidents.list(parts[2], status=query.get('status', [None])[0],
                        start=float(query['start'][0]) if 'start' in query else None,
                        end=float(query['end'][0]) if 'end' in query else None, q=query.get('q', [''])[0])}
                elif method == 'POST':
                    result, status = store.incidents.create(parts[2], body), 201
            elif parts[3] == 'datasets':
                if method == 'GET':
                    result = {'datasets': store.datasets(parts[2])}
                elif method == 'POST':
                    result, status = store.import_dataset(parts[2], body), 201
            elif parts[3] == 'analyses':
                if method == 'GET':
                    result = {'jobs': store.jobs(parts[2])}
                elif method == 'POST':
                    result, status = store.analyze(parts[2], body), 201
        elif len(parts) == 5 and parts[1] == 'workspaces' and parts[3:] == ['experiments', 'preview'] and method == 'POST':
            result = store.experiments.preview(parts[2], body.get('config'))
        elif len(parts) == 5 and parts[1] == 'workspaces' and parts[3:] == ['external', 'tep'] and method == 'POST':
            result, status = store.tep.import_runs(parts[2], body), 201
        elif len(parts) == 6 and parts[1] == 'workspaces' and parts[3:] == ['external', 'tep', 'experiment'] and method == 'POST':
            result, status = store.tep.create_case(parts[2]), 201
        elif len(parts) == 5 and parts[1] == 'workspaces' and parts[3:] == ['transformations', 'preview'] and method == 'POST':
            result = store.transformations.preview(parts[2], body.get('config'))
        elif len(parts) == 5 and parts[1] == 'workspaces' and parts[3] == 'views' and method == 'PATCH':
            result = store.signals.save_view(parts[2], body, parts[4])
        elif parts == ['api', 'datasets', 'preview'] and method == 'POST':
            metadata, times, values = prepare_csv(body.get('csv'), body)
            names = [c['name'] for c in metadata['columns'][:4]]
            result = {'metadata': metadata, 'series': series_preview(times, values[:, :4], names)}
        elif len(parts) == 3 and parts[1] == 'datasets' and method == 'GET':
            result = store.dataset(parts[2])
        elif len(parts) == 4 and parts[1] == 'datasets' and parts[3] == 'labels':
            if method == 'GET':
                result = {'labels': store.experiments.label_sets(parts[2])}
            elif method == 'POST':
                result, status = store.experiments.save_labels(parts[2], body), 201
        elif len(parts) == 5 and parts[1] == 'datasets' and parts[3] == 'labels' and parts[4] in ('triplens', 'simulation') and method == 'POST':
            result, status = store.experiments.simulation_labels(parts[2], body), 201
        elif len(parts) == 4 and parts[1] == 'datasets' and parts[3] == 'quality' and method == 'GET':
            result = store.dataset(parts[2])['metadata']['quality']
        elif len(parts) == 4 and parts[1] == 'datasets' and parts[3] == 'time-reference':
            if method == 'GET':
                result = store.signals.clock(parts[2])
            elif method == 'PATCH':
                result = store.signals.set_reference(parts[2], body)
        elif len(parts) == 4 and parts[1] == 'datasets' and parts[3] == 'series' and method == 'GET':
            query = parse_qs(url.query)
            result = store.series(parts[2], query.get('signal'),
                                  float(query['start'][0]) if 'start' in query else None,
                                  float(query['end'][0]) if 'end' in query else None)
        elif len(parts) == 4 and parts[1] == 'datasets' and parts[3] == 'sample' and method == 'GET':
            query = parse_qs(url.query)
            result = store.sample(parts[2], float(query.get('at', ['0'])[0]), query.get('signal'))
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
