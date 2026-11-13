"""Resilience API, evidence persistence and ordinary Dataset integration."""
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from time import monotonic, sleep
import unittest
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import numpy as np

from l5.workspace import WorkspaceStore
from server import Handler


class ResiliencePersistenceTests(unittest.TestCase):
    def test_resilience_http_workflow(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = WorkspaceStore(root)
            workspace_id = store.create_workspace('Resilience study')['id']
            other_workspace = store.create_workspace('Other study')['id']
            with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
                server.workspace_store = store
                thread = Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base = f'/workspaces/{workspace_id}/resilience'
                opener = build_opener(ProxyHandler({}))

                def request(path, body=None):
                    data = json.dumps(body).encode('utf-8') if body is not None else None
                    req = Request(f'http://127.0.0.1:{server.server_port}/api{path}', data=data,
                                  headers={'Content-Type': 'application/json'})
                    with opener.open(req, timeout=20) as response:
                        return json.load(response) if response.headers.get_content_type() == 'application/json' else response.read().decode('utf-8')

                try:
                    self.assertIn('algorithms', request(f'{base}/catalog'))
                    scenario = dict(duration=50, sample_interval=.25, seed=37, measurement={'signals': ['level1', 'level2']}, faults=[
                        dict(id='pump', type='pump_degradation', target='pump', onset=13.125, recovery=35.1, severity=.6, profile='step'),
                        dict(id='offline', type='communication_blackout', target='all', onset=18, recovery=25, severity=1, profile='temporary'),
                    ])
                    preview = request(f'{base}/preview', {'scenario': scenario})
                    self.assertEqual([event['id'] for event in preview['schedule']], ['pump', 'offline'])
                    saved = request(f'{base}/scenarios', {'name': 'Train <trial>', 'scenario': scenario})
                    self.assertEqual(request(f'{base}/scenarios')['scenarios'], [saved])
                    updated = request(f'{base}/scenarios', {'id': saved['id'], 'name': 'Revised trial', 'scenario': scenario})
                    self.assertEqual(updated['id'], saved['id'])

                    run = request(f'{base}/simulate', {'scenario': scenario, 'name': 'Measured levels'})
                    self.assertEqual(request(f'{base}/runs/{run["id"]}'), run)
                    self.assertTrue(run['observation_packets'])
                    with self.assertRaises(HTTPError) as caught:
                        request(f'/workspaces/{other_workspace}/resilience/runs/{run["id"]}')
                    self.assertEqual(caught.exception.code, 404)
                    dataset = request(f'{base}/export', {'run_id': run['id']})
                    self.assertEqual(request(f'{base}/export', {'run_id': run['id']})['id'], dataset['id'])
                    metadata = dataset['metadata']
                    self.assertNotIn('model', metadata)
                    self.assertEqual(metadata['resilience']['runId'], run['id'])
                    times, values = store.load_data(dataset)
                    frame = int(np.flatnonzero(times == 21)[0])
                    self.assertTrue(np.isnan(values[frame]).all())
                    self.assertEqual({s['name'] for s in store.signals.catalog(workspace_id)}, {'level1', 'level2'})
                    original = root / workspace_id / 'datasets' / dataset['id'] / 'source.csv'
                    self.assertIn('21.0,,', original.read_text(encoding='utf-8').splitlines())

                    body = {'name': 'Study <local>', 'mode': 'grid', 'scenario': scenario,
                            'detectors': [{'algorithm': 'robust-maxz'}],
                            'axes': [{'path': 'faults.pump.severity', 'values': [.2, .6]}]}
                    created = request(f'{base}/campaigns', body)
                    path = f'{base}/campaigns/{created["id"]}'
                    limit = monotonic() + 25
                    while monotonic() < limit:
                        campaign = request(path)
                        if campaign['status'] not in ('queued', 'running'):
                            break
                        sleep(.05)
                    self.assertEqual(campaign['status'], 'completed', campaign)
                    self.assertEqual(campaign['total'], 2)
                    self.assertEqual(campaign['completed'], 2)
                    case_id = campaign['cases'][0]['id']
                    detail = request(f'{path}/cases/{case_id}')
                    self.assertEqual(detail['scenario']['faults'][0]['severity'], .2)
                    self.assertIn('scores', detail['evaluation']['analysis'])
                    self.assertIn('coverage', detail['metrics'])
                    case_dataset = request(f'{base}/export', {'campaign_id': created['id'], 'case_id': case_id})
                    self.assertEqual(case_dataset['metadata']['resilience']['caseId'], case_id)
                    incident = request(f'/workspaces/{workspace_id}/incidents', {
                        'title': 'Review lost coverage', 'source': {'kind': 'dataset', 'datasetId': case_dataset['id']},
                    })
                    self.assertEqual(incident['links'][0]['reference_id'], case_dataset['id'])
                    self.assertEqual(incident['links'][0]['details']['resilience']['caseId'], case_id)
                    html = request(f'{path}/report.html?lang=zh-CN')
                    self.assertIn('事件检出率', html)
                    self.assertIn('Study &lt;local&gt;', html)
                finally:
                    server.shutdown()
                    thread.join()

            restored = WorkspaceStore(root).resilience
            self.assertEqual(restored.scenarios(workspace_id), [updated])
            self.assertEqual(restored.run(workspace_id, run['id'])['observations'], run['observations'])
            self.assertEqual(restored.case(workspace_id, created['id'], case_id)['evaluation'], detail['evaluation'])
            self.assertEqual(restored.campaign(workspace_id, created['id'])['cases'][0]['dataset_id'], case_dataset['id'])

    def test_restart_preserves_completed_case_and_marks_unfinished_work(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = WorkspaceStore(root)
            workspace_id = store.create_workspace('Interrupted study')['id']
            plan = json.dumps(dict(name='Case', phase='study', family='healthy', detector={'algorithm': 'robust-maxz'}, scenario={}))
            with store.connect() as db:
                db.execute('INSERT INTO resilience_campaigns VALUES (?,?,?,?,?,?,?,?,NULL)',
                           ('c', workspace_id, 'Study', 'grid', 'running', '{}', '1', '2'))
                db.executemany('INSERT INTO resilience_cases (id,campaign_id,ordinal,scenario_key,plan,status,metrics) VALUES (?,?,?,?,?,?,?)', [
                    ('ok', 'c', 0, 'key', plan, 'succeeded', '{"coverage":1.0}'),
                    ('wait', 'c', 1, 'key', plan, 'running', None),
                ])
            campaign = WorkspaceStore(root).resilience.campaign(workspace_id, 'c')
            self.assertEqual(campaign['status'], 'interrupted')
            self.assertEqual([case['status'] for case in campaign['cases']], ['succeeded', 'interrupted'])
            self.assertEqual(campaign['cases'][0]['metrics']['coverage'], 1)
