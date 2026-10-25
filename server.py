"""Local L5 Workspace API, analysis engine, example APIs and static server.

python3 server.py                            local evidence provider
TRIPLENS_MODEL_ENDPOINT=... python3 server.py compatible structured-JSON model
"""
from __future__ import annotations

import argparse
import json
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError

from simulation.platform import SYNTHETIC_SCHEMA, analyze_rows, parse_csv, run_tools
from l5.api import dispatch
from l5.assistant import local_brief, model_brief, validate_brief
from l5.workspace import WorkspaceStore

ROOT = Path(__file__).resolve().parent


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / 'dist'), **kwargs)

    def send_json(self, status: int, data: dict):
        payload = json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if dispatch(self, 'GET'):
            return
        if self.path == '/api/health':
            return self.send_json(200, {"ok": True, "provider": "model" if os.environ.get('TRIPLENS_MODEL_ENDPOINT') else "local", "schemaVersion": 1})
        if self.path.startswith('/api/'):
            return self.send_json(404, {"error": "Unknown endpoint."})
        return super().do_GET()

    def do_POST(self):
        if dispatch(self, 'POST'):
            return
        if self.path not in ('/api/analyze', '/api/replay', '/api/investigate'):
            return self.send_json(404, {"error": "Unknown endpoint."})
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            return self.send_json(400, {"error": "Invalid content length."})
        limit = int(os.environ.get('L5_MAX_REQUEST_BYTES', 256 * 1024 * 1024))
        if not 0 < length <= limit:
            return self.send_json(413, {"error": f"Request body must be 1–{limit} bytes."})
        try:
            body = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self.send_json(400, {"error": "Invalid JSON."})
        if self.path in ('/api/replay', '/api/investigate'):
            try:
                if not isinstance(body, dict):
                    raise ValueError('Request must be a JSON object.')
                if body.get('signalSchemaId', SYNTHETIC_SCHEMA.id) != SYNTHETIC_SCHEMA.id:
                    raise ValueError('This API requires the TripLens 18-signal schema; external TEP research is separate.')
                if self.path == '/api/replay':
                    if not isinstance(body.get('csv'), str):
                        raise ValueError('A CSV string is required.')
                    return self.send_json(200, analyze_rows(parse_csv(body['csv'])))
                return self.send_json(200, {'schemaVersion': 2, 'provider': 'local',
                                           'trace': run_tools(body.get('rows'), body.get('calls'))})
            except (ValueError, TypeError, OverflowError) as error:
                return self.send_json(400, {'error': str(error)})
        try:
            if not isinstance(body, dict):
                raise ValueError('Request must be an object.')
            prompt = body.get('prompt')
            if not isinstance(prompt, str) or not prompt.strip():
                raise ValueError('Enter a question or select a tool.')
            if body.get('simulationId'):
                session, rows = self.server.workspace_store.runtime.window(body['simulationId'], body)
                self.server.workspace_store.runtime.model(session, 'diagnosis')
                context = dict(id=session['id'], rows=rows, calls=body.get('calls'))
            else:
                if not isinstance(body.get('incidentId'), str) or not body['incidentId']:
                    raise ValueError('Provide a simulationId or an incidentId with observed rows.')
                context = dict(id=body['incidentId'], rows=body.get('rows'), calls=body.get('calls'))
            brief = model_brief(prompt, context) if os.environ.get('TRIPLENS_MODEL_ENDPOINT') else local_brief(prompt, context)
            if body.get('simulationId'):
                brief['record'] = self.server.workspace_store.runtime.record(body['simulationId'], 'assistant', body, dict(brief))
            return self.send_json(200, brief)
        except (HTTPError, URLError, TimeoutError, OSError):
            return self.send_json(502, {'error':'Model endpoint unavailable. Check server configuration.'})
        except (ValueError, KeyError, IndexError, TypeError) as error:
            return self.send_json(400, {'error':str(error)})

    def do_PATCH(self):
        if not dispatch(self, 'PATCH'):
            self.send_json(404, {'error': 'Unknown endpoint.'})

    def do_DELETE(self):
        if not dispatch(self, 'DELETE'):
            self.send_json(404, {'error': 'Unknown endpoint.'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='L5 Workspace API and static server')
    parser.add_argument('--port', type=int, default=8787)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--data-dir', type=Path, default=Path(os.environ.get('L5_DATA_DIR', ROOT / 'data')))
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.workspace_store = WorkspaceStore(args.data_dir)
    print(f'L5 available at http://{args.host}:{args.port} · data: {server.workspace_store.root}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
