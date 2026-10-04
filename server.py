"""Optional API and static server. Standard library only; no credentials in React.

python3 server.py                            local evidence provider
TRIPLENS_MODEL_ENDPOINT=... python3 server.py compatible structured-JSON model
"""
from __future__ import annotations

import argparse
import json
import os
from functools import lru_cache
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from simulation.generate import build_scenario
from simulation.platform import analyze_rows, parse_csv, run_tools

ROOT = Path(__file__).resolve().parent
MAX_BODY = 16_384


@lru_cache(maxsize=1)
def scenario():
    return build_scenario()


def local_brief(prompt: str) -> dict:
    data = scenario()
    return {"schemaVersion": 1, "incidentId": data['id'], "provider": "local", "prompt": prompt,
            "steps": data['analyst']['steps'], "summary": data['analyst']['summary'],
            "limitation": data['analyst']['limitation'], "candidateId": "valve",
            "evidenceTags": ["valve", "flow", "temperature", "pressure"]}


def model_brief(prompt: str) -> dict:
    endpoint = os.environ['TRIPLENS_MODEL_ENDPOINT']
    if urlparse(endpoint).scheme not in ('http', 'https'):
        raise ValueError('Model endpoint must be an HTTP(S) URL.')
    data = scenario()
    evidence = {key: data[key] for key in ('id', 'detections', 'candidates', 'tripTime', 'provenance')}
    evidence['paths'] = data['diagnostics']['paths']
    evidence['counterfactuals'] = [{k: v for k, v in b.items() if k != 'points'} for b in data['branches']]
    schema = local_brief(prompt)
    system = (
        'You are the TripLens incident analyst. Return one JSON object matching the supplied example schema. '
        'Summarize the supplied evidence; do not claim tools were called or a physical plant was controlled. '
        'Use only measured values supplied here. Scores are rule-based support, not probabilities. '
        'The model is a reduced-order process, not Tennessee Eastman. Preserve uncertainty about actuator faults. '
        'Keep schemaVersion=1, incidentId=INC-001, provider=model. steps are concise evidence checks, '
        'not private chain of thought. candidateId is valve, feed or sensor. '
        'evidenceTags are valve, flow, temperature, pressure, separator, purity.\n'
        + json.dumps({"example": schema, "evidence": evidence})
    )
    payload = {"model": os.environ.get('TRIPLENS_MODEL', ''),
               "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
               "response_format": {"type": "json_object"}, "temperature": .2, "max_tokens": 1600}
    if not payload['model']:
        raise ValueError('TRIPLENS_MODEL is required when a model endpoint is configured.')
    headers = {"Content-Type": "application/json"}
    if token := os.environ.get('TRIPLENS_MODEL_API_KEY'):
        headers['Authorization'] = f'Bearer {token}'
    request = Request(endpoint, data=json.dumps(payload).encode(), headers=headers, method='POST')
    with urlopen(request, timeout=40) as response:
        result = json.loads(response.read(1_000_000))
    brief = json.loads(result['choices'][0]['message']['content'])
    validate_brief(brief)
    brief['provider'] = 'model'
    brief['prompt'] = prompt
    return brief


def validate_brief(brief: dict):
    if not isinstance(brief, dict) or brief.get('schemaVersion') != 1 or brief.get('incidentId') != 'INC-001':
        raise ValueError('Invalid incident brief identity.')
    if brief.get('candidateId') not in ('valve', 'feed', 'sensor'):
        raise ValueError('Unknown candidate.')
    if not all(isinstance(brief.get(key), str) for key in ('summary', 'limitation', 'prompt')):
        raise ValueError('Brief text fields are required.')
    if not isinstance(brief.get('steps'), list) or not 1 <= len(brief['steps']) <= 12:
        raise ValueError('Brief must contain 1–12 evidence checks.')
    if not all(isinstance(step, dict) and all(isinstance(step.get(key), str) for key in ('action', 'tool', 'result')) for step in brief['steps']):
        raise ValueError('Invalid evidence step.')
    if not isinstance(brief.get('evidenceTags'), list) or not all(tag in {t['key'] for t in scenario()['tags']} for tag in brief['evidenceTags']):
        raise ValueError('Invalid evidence tag.')


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / 'dist'), **kwargs)

    def send_json(self, status: int, data: dict):
        payload = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == '/api/health':
            return self.send_json(200, {"ok": True, "provider": "model" if os.environ.get('TRIPLENS_MODEL_ENDPOINT') else "local", "schemaVersion": 1})
        if self.path.startswith('/api/'):
            return self.send_json(404, {"error": "Unknown endpoint."})
        return super().do_GET()

    def do_POST(self):
        if self.path not in ('/api/analyze', '/api/replay', '/api/investigate'):
            return self.send_json(404, {"error": "Unknown endpoint."})
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            return self.send_json(400, {"error": "Invalid content length."})
        limit = 2_000_000 if self.path in ('/api/replay', '/api/investigate') else MAX_BODY
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
                if self.path == '/api/replay':
                    if not isinstance(body.get('csv'), str):
                        raise ValueError('A CSV string is required.')
                    return self.send_json(200, analyze_rows(parse_csv(body['csv'])))
                return self.send_json(200, {'schemaVersion': 2, 'provider': 'local',
                                           'trace': run_tools(body.get('rows'), body.get('calls'))})
            except (ValueError, TypeError) as error:
                return self.send_json(400, {'error': str(error)})
        if not isinstance(body, dict) or body.get('incidentId') != 'INC-001':
            return self.send_json(400, {"error": "Unknown incident."})
        prompt = body.get('prompt')
        if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 2000:
            return self.send_json(400, {"error": "Prompt must contain 1–2000 characters."})
        if not os.environ.get('TRIPLENS_MODEL_ENDPOINT') and prompt.strip() != scenario()['analyst']['prompt']:
            return self.send_json(422, {"error": "The local provider supports: " + scenario()['analyst']['prompt']})
        try:
            brief = model_brief(prompt) if os.environ.get('TRIPLENS_MODEL_ENDPOINT') else local_brief(prompt)
            return self.send_json(200, brief)
        except (HTTPError, URLError, TimeoutError, OSError):
            return self.send_json(502, {"error": "Model endpoint unavailable. Check server configuration."})
        except (ValueError, KeyError, IndexError, TypeError):
            return self.send_json(502, {"error": "Model response did not match the incident brief contract."})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='TripLens API and static server')
    parser.add_argument('--port', type=int, default=8787)
    parser.add_argument('--host', default='127.0.0.1')
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f'TripLens available at http://{args.host}:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
