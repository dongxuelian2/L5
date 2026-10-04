import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from server import Handler, local_brief, validate_brief


class QuietHandler(Handler):
    def log_message(self, *args):
        pass


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'TRIPLENS_MODEL_ENDPOINT': ''})
        self.env.start()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), QuietHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.env.stop()

    def post(self, body):
        request = Request(self.base + '/api/analyze', data=body, headers={'Content-Type': 'application/json'})
        try:
            response = urlopen(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def test_local_contract_over_http(self):
        status, brief = self.post(json.dumps({'incidentId': 'INC-001', 'prompt': 'Why is reactor pressure rising?'}).encode())
        self.assertEqual(status, 200)
        validate_brief(brief)
        self.assertEqual(brief['provider'], 'local')
        self.assertEqual(brief['candidateId'], 'valve')

    def test_invalid_input_is_rejected(self):
        for payload, expected in [(b'{', 400), (b'[]', 400), (b'{}', 400), (b'x' * 17000, 413)]:
            with self.subTest(payload=payload[:12]):
                self.assertEqual(self.post(payload)[0], expected)

    def test_local_scope_is_explicit(self):
        status, _ = self.post(json.dumps({'incidentId': 'INC-001', 'prompt': 'An unrelated question'}).encode())
        self.assertEqual(status, 422)

    def test_http_model_adapter_with_loopback_fixture(self):
        received = []

        class ModelHandler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                received.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                data = json.dumps({'choices': [{'message': {'content': json.dumps(local_brief('test'))}}]}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        upstream = ThreadingHTTPServer(('127.0.0.1', 0), ModelHandler)
        worker = threading.Thread(target=upstream.serve_forever, daemon=True)
        worker.start()
        try:
            with patch.dict(os.environ, {'TRIPLENS_MODEL_ENDPOINT': f'http://127.0.0.1:{upstream.server_port}/v1/chat/completions', 'TRIPLENS_MODEL': 'fixture-model'}):
                status, brief = self.post(json.dumps({'incidentId': 'INC-001', 'prompt': 'Why is reactor pressure rising?'}).encode())
            self.assertEqual(status, 200)
            self.assertEqual(brief['provider'], 'model')
            self.assertEqual(received[0]['response_format'], {'type': 'json_object'})
            self.assertEqual(received[0]['model'], 'fixture-model')
        finally:
            upstream.shutdown()
            upstream.server_close()
            worker.join()

    def test_csv_replay_uses_observed_data_over_http(self):
        from simulation.platform import KEYS, simulate, Config
        rows=simulate(Config(fault='pump_loss'))
        columns=['t',*KEYS]
        csv_text=','.join(columns)+'\n'+'\n'.join(','.join(str(r[k]) for k in columns) for r in rows)
        request=Request(self.base+'/api/replay',data=json.dumps({'csv':csv_text}).encode(),headers={'Content-Type':'application/json'})
        with urlopen(request,timeout=10) as response:
            result=json.load(response)
        self.assertEqual(result['diagnosis']['candidates'][0]['id'],'pump_loss')
        request=Request(self.base+'/api/replay',data=b'{"csv":"t,bad\\n0,1"}',headers={'Content-Type':'application/json'})
        with self.assertRaises(HTTPError) as caught:urlopen(request,timeout=5)
        self.assertEqual(caught.exception.code,400)
        caught.exception.close()

    def test_structured_investigation_plan_endpoint(self):
        from simulation.platform import simulate, Config
        body={'rows':simulate(Config()),'calls':[{'tool':'inspect_controller','args':{}}]}
        request=Request(self.base+'/api/investigate',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
        with urlopen(request,timeout=10) as response:result=json.load(response)
        self.assertEqual(result['trace'][0]['result']['id'],'TIC-101')
        self.assertEqual(result['provider'],'local')

    def test_schema_rejects_unknown_evidence(self):
        brief = local_brief('test')
        brief['evidenceTags'] = ['invented-signal']
        with self.assertRaises(ValueError):
            validate_brief(brief)
