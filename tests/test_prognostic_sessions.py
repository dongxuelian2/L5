"""The prognostics workflow through the real workspace repository and HTTP service."""
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from l5.workspace import WorkspaceStore
from server import Handler


@contextmanager
def running_api(store):
    with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
        server.workspace_store = store
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        opener = build_opener(ProxyHandler({}))

        def call(path, body=None):
            request = Request(f'http://127.0.0.1:{server.server_port}/api{path}',
                              None if body is None else json.dumps(body).encode('utf-8'),
                              {'Content-Type': 'application/json'})
            with opener.open(request, timeout=25) as response:
                payload = response.read().decode('utf-8')
                return response.status, json.loads(payload) if response.headers.get_content_type() == 'application/json' else payload

        try:
            yield call
        finally:
            server.shutdown()
            worker.join()


class PrognosticSessionTests(unittest.TestCase):
    def test_demo_save_reopen_export_and_link_to_incident(self):
        with TemporaryDirectory() as folder:
            store = WorkspaceStore(Path(folder))
            workspace = store.create_workspace('Pump train')['id']
            scope = f'/workspaces/{workspace}/prognostics'
            incident = store.incidents.create(workspace, {'title': 'Pump capacity decline'})['id']
            scenario = store.scenarios.save(workspace, {'modelId': 'coupled-tanks', 'name': 'Training rig',
                'config': {'pumpRate': .04, 'pumpControl': 80, 'fault': 'pump_degradation'}})
            store.scenarios.save(workspace, {'config': {'pumpRate': .06}}, scenario['id'])
            with running_api(store) as api:
                status, demo = api(scope + '/benchmark', {'scenarioId': scenario['id'], 'scenarioVersion': 1})
                self.assertEqual(status, 201)
                dataset_id = demo['dataset']['id']
                self.assertEqual(demo['defaults']['datasetId'], dataset_id)
                self.assertNotIn('replay_config', demo['dataset']['metadata']['prognosticBenchmark'])
                provenance = demo['dataset']['metadata']['prognosticBenchmark']['provenance']
                self.assertEqual(provenance['scenario']['version'], 1)
                self.assertEqual(provenance['nominal_flow'], .04)
                self.assertEqual(store.series(dataset_id, ['pump'])['values']['pump'][0], 80)
                condition = next(s for s in store.signals.catalog(workspace) if s['name'] == 'capacity_loss')
                self.assertEqual(condition['unit'], 'fraction')

                config = {**demo['defaults'], 'name': 'Forecast A', 'probabilityHorizons': [20, 100, 300]}
                status, fit = api(scope + '/fit', config)
                self.assertEqual(status, 200)
                self.assertEqual(fit['forecast']['status'], 'ok')
                self.assertEqual(fit['source']['signal']['id'], condition['id'])
                self.assertEqual([p['horizon'] for p in fit['forecast']['rul']['probabilities']], [20, 100, 300])
                self.assertTrue(fit['maintenance']['options'])

                status, saved = api(scope + '/sessions', {**config, 'includeEvaluation': True})
                self.assertEqual(status, 201)
                self.assertEqual(fit['forecast'], saved['forecast'])
                self.assertEqual(len(saved['evaluation']['trajectories']), 24)
                self.assertEqual({m['method'] for m in saved['evaluation']['models']}, {'linear', 'stochastic'})
                path = scope + '/sessions/' + saved['id']
                self.assertEqual(api(scope + '/sessions')[1]['sessions'][0]['id'], saved['id'])
                self.assertEqual(api(path + '/session.json')[1], saved)
                self.assertIn('first_passage_cdf', api(path + '/forecast.csv')[1])
                self.assertIn('expected_cost', api(path + '/maintenance.csv')[1])
                linked = api(path + '/incidents', {'incidentId': incident})[1]
                self.assertEqual(linked['links'][0]['details']['sessionId'], saved['id'])
                timeline = api('/incidents/' + incident + '/timeline')[1]
                event = next(e for e in timeline['events'] if e['kind'] == 'prognostic')
                self.assertEqual(event['start'], fit['forecast']['cutoff'])
                self.assertEqual(event['observationWindow'], [config['start'], config['cutoff']])
                self.assertIn('Forecast A', api('/incidents/' + incident + '/report.html?lang=en')[1])

                other = store.create_workspace('Other train')['id']
                with self.assertRaises(HTTPError) as error:
                    api(f'/workspaces/{other}/prognostics/sessions/{saved["id"]}')
                self.assertEqual(error.exception.code, 404)
                error.exception.close()
            restored = WorkspaceStore(Path(folder))
            self.assertEqual(restored.prognostics.get(workspace, saved['id']), saved)
            self.assertEqual(restored.incidents.get(incident)['links'][0]['details']['sessionId'], saved['id'])

    def test_fit_uses_only_observations_and_maintenance_available_at_cutoff(self):
        with TemporaryDirectory() as folder:
            store = WorkspaceStore(Path(folder))
            workspace = store.create_workspace('Pump test')['id']
            rows = 'time,wear\n0,0.04\n1,0.08\n2.5,0.10\n4,\n5,0.17\n7,0.21\n8.5,0.24\n'
            original = store.import_dataset(workspace, {'csv': rows + '9,0.27\n10,0.31\n'})
            changed = store.import_dataset(workspace, {'csv': rows + '9,0.48\n10,0.50\n'})
            request = dict(datasetId=original['id'], assetId='p1', assetName='Pump 1', method='linear',
                           indicator=dict(signal='wear', definition='Loss in normalized flow', unit='fraction', failure_threshold=.5),
                           cutoff=8.5, horizon=20)
            original_fit = store.prognostics.fit(workspace, request)['forecast']
            changed_fit = store.prognostics.fit(workspace, {**request, 'datasetId': changed['id'],
                'events': [{'time': 9.5, 'action': 'replace'}]})['forecast']
            self.assertEqual(original_fit, changed_fit)
            self.assertTrue(any(row['value'] is None for row in original_fit['history']))
            self.assertTrue(all(row['time'] <= 8.5 for row in original_fit['history']))
            insufficient = store.prognostics.fit(workspace, {**request, 'start': 6, 'cutoff': 6})['forecast']
            self.assertEqual(insufficient['status'], 'insufficient_data')
            self.assertIsNone(insufficient['rul']['median'])
            failed = store.prognostics.fit(workspace, {**request, 'cutoff': 10, 'endStatus': 'failed', 'failureTime': 10})
            self.assertEqual(failed['forecast']['status'], 'threshold_reached')
            self.assertEqual(len(failed['maintenance']['options']), 1)

    def test_transformed_condition_rejects_forward_bin_aggregates_in_its_lineage(self):
        with TemporaryDirectory() as folder:
            store = WorkspaceStore(Path(folder))
            workspace = store.create_workspace('Transform and forecast')['id']
            raw = store.import_dataset(workspace, {'csv': 'time,wear\n0,1\n.5,2\n1,3\n1.5,99\n2,5\n3,6\n'})

            def transform(dataset, inputs, outputs=()):
                columns = {c['name']: c['id'] for c in dataset['metadata']['columns']}
                sources = [dict(signalId=columns[name], key=key, resampling=method, sourceUnit='1', unit='1')
                           for name, key, method in inputs]
                definition = store.transformations.save(workspace, dict(name='Condition signals', config=dict(
                    sources=sources, grid=dict(intervalSeconds=1), derived=list(outputs))))
                return store.transformations.execute(definition['id'], {})

            signals = transform(raw, [('wear', 'bucket', 'mean'), ('wear', 'direct', 'nearest')],
                                [dict(key='calculated', expression='bucket * 2', unit='1')])
            nested = transform(signals, [('calculated', 'nested', 'nearest')])
            request = dict(datasetId=signals['id'], assetName='Pump', method='linear', cutoff=2, horizon=5,
                           indicator=dict(signal='direct', definition='Normalized wear', unit='1', failure_threshold=20))
            fit = store.prognostics.fit(workspace, request)
            self.assertEqual([r['value'] for r in fit['forecast']['history']], [1, 3, 5])
            for dataset, signal in ((signals, 'bucket'), (signals, 'calculated'), (nested, 'nested')):
                with self.subTest(signal=signal), self.assertRaisesRegex(ValueError, 'forward-bin aggregation'):
                    store.prognostics.fit(workspace, {**request, 'datasetId': dataset['id'],
                        'indicator': {**request['indicator'], 'signal': signal}})


if __name__ == '__main__':
    unittest.main()
