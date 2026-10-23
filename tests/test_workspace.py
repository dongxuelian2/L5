"""The durable user workflow and a known anomaly, using a newly generated CSV."""
from pathlib import Path
from tempfile import TemporaryDirectory
from http.server import ThreadingHTTPServer
import json
import threading
import unittest
from urllib.request import Request, build_opener, ProxyHandler

import numpy as np

from l5.datasets import prepare_csv
from l5.monitoring import MaxZMonitor
from l5.workspace import WorkspaceStore
from server import Handler


def industrial_csv():
    rng = np.random.default_rng(42)
    values = rng.normal(size=(600, 3)) * [.2, 1.5, .05] + [80, 300, 4]
    values[400:460, 0] += 8
    lines = ['timestamp,reactor_temp,feed_rate,vibration,batch']
    for i, row in enumerate(values):
        signals = [str(v) for v in row]
        if i in (30, 300):
            signals[1] = ''
        lines.append(f'2026-10-23T08:{i // 60:02d}:{i % 60:02d}Z,' + ','.join(signals) + ',A')
    return '\n'.join(lines)


class WorkspaceWorkflowTests(unittest.TestCase):
    def test_import_analyze_restart_and_manage_workspace(self):
        with TemporaryDirectory() as folder:
            store = WorkspaceStore(Path(folder))
            workspace = store.create_workspace('Reactor campaign')
            dataset = store.import_dataset(workspace['id'], {'filename': 'new-reactor.csv', 'csv': industrial_csv()})
            self.assertEqual(dataset['metadata']['rowCount'], 600)
            self.assertEqual(dataset['metadata']['missingCount'], 2)
            self.assertEqual(dataset['metadata']['time']['kind'], 'datetime')
            self.assertEqual(dataset['metadata']['ignoredColumns'], ['batch'])
            signals = [c['name'] for c in dataset['metadata']['columns']]
            request = {'datasetId': dataset['id'], 'signals': signals, 'baselineRange': [0, 199],
                       'analysisRange': [200, 599], 'algorithm': 'robust-maxz', 'alpha': .01}
            result = store.analyze(workspace['id'], request)
            self.assertEqual(result['contributionMetric'], 'absolute-robust-z')
            self.assertAlmostEqual(result['signalContributions'][0]['value'], result['summary']['peakScore'])
            peak_time = result['peakTime']
            times, values = store.load_data(dataset)
            sample = values[np.flatnonzero(times == peak_time)[0]]
            z = np.abs((sample - result['model']['center']) / result['model']['scale'])
            for contribution in result['signalContributions']:
                self.assertAlmostEqual(contribution['value'], z[signals.index(contribution['signal'])])
            self.assertTrue(any(i['start'] <= 400 and i['end'] >= 459 for i in result['intervals']))
            self.assertEqual(result['intervals'][np.argmax([i['peakScore'] for i in result['intervals']])]['signals'][0], 'reactor_temp')
            restored = WorkspaceStore(Path(folder))
            self.assertEqual(restored.result(result['id']), result)
            self.assertEqual(restored.jobs(workspace['id'])[0]['config']['signals'], signals)
            self.assertEqual(restored.series(dataset['id'], ['feed_rate'])['values']['feed_rate'][30], None)
            for algorithm in ('pca-q', 'pca-t2'):
                pca = restored.analyze(workspace['id'], {**request, 'algorithm': algorithm})
                self.assertTrue(np.isfinite(pca['scores']).all())
                self.assertGreater(pca['summary']['flaggedSamples'], 0)
                self.assertEqual(len(pca['signalContributions']), len(signals))
                if algorithm == 'pca-q':
                    self.assertAlmostEqual(sum(c['value'] for c in pca['signalContributions']), pca['summary']['peakScore'])
                else:
                    self.assertEqual(pca['contributionMetric'], 'model-leverage')
                    model = pca['model']
                    peak = values[np.flatnonzero(times == pca['peakTime'])[0]]
                    peak = np.where(np.isfinite(peak), peak, model['imputationMedians'])
                    z = (peak - model['center']) / model['scale']
                    loadings = np.asarray(model['loadings'])
                    expected = np.abs(loadings.T @ ((z @ loadings.T) / np.sqrt(model['eigenvalues'])))
                    for contribution in pca['signalContributions']:
                        self.assertAlmostEqual(contribution['value'], expected[signals.index(contribution['signal'])])
            restored.rename_workspace(workspace['id'], 'Campaign 2')
            self.assertEqual(restored.list_workspaces()[0]['name'], 'Campaign 2')
            restored.delete_workspace(workspace['id'])
            self.assertEqual(restored.list_workspaces(), [])
            self.assertFalse((Path(folder) / workspace['id']).exists())

    def test_single_signal_generated_time_and_robust_score(self):
        metadata, times, values = prepare_csv('pressure\n1\n2\n3\n4\n', {'timeColumn': None, 'sampleInterval': .5})
        self.assertEqual(metadata['rowCount'], 4)
        np.testing.assert_allclose(times, [0, .5, 1, 1.5])
        monitor = MaxZMonitor()
        monitor.fit(values)
        np.testing.assert_allclose(monitor.score([[2.5], [5.4652]]), [0, 2], rtol=1e-5)

    def test_target_does_not_change_model_or_threshold(self):
        with TemporaryDirectory() as folder:
            store = WorkspaceStore(Path(folder))
            workspace = store.create_workspace('Baseline isolation')
            dataset = store.import_dataset(workspace['id'], {'csv': industrial_csv()})
            request = {'datasetId': dataset['id'], 'signals': ['reactor_temp'], 'baselineRange': [0, 199],
                       'analysisRange': [200, 399], 'algorithm': 'robust-maxz'}
            before = store.analyze(workspace['id'], request)
            after = store.analyze(workspace['id'], {**request, 'analysisRange': [400, 459]})
            self.assertEqual(before['model'], after['model'])
            self.assertEqual(before['threshold'], after['threshold'])
            with self.assertRaisesRegex(ValueError, 'finish before'):
                store.analyze(workspace['id'], {**request, 'analysisRange': [190, 300]})


class WorkspaceHTTPTests(unittest.TestCase):
    def test_complete_workflow_across_http_server_restart(self):
        with TemporaryDirectory() as folder:
            def start():
                service = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
                service.workspace_store = WorkspaceStore(Path(folder))
                thread = threading.Thread(target=service.serve_forever, daemon=True)
                thread.start()
                return service, thread

            def request(path, body=None, method=None):
                req = Request(f'http://127.0.0.1:{service.server_port}/api{path}',
                              data=json.dumps(body).encode() if body is not None else None,
                              headers={'Content-Type': 'application/json'}, method=method)
                with build_opener(ProxyHandler({})).open(req, timeout=15) as response:
                    return json.load(response)

            service, thread = start()
            try:
                workspace = request('/workspaces', {'name': 'HTTP restart acceptance'})
                wid = workspace['id']
                preview = request('/datasets/preview', {'csv': industrial_csv()})
                self.assertEqual(preview['metadata']['rowCount'], 600)
                dataset = request(f'/workspaces/{wid}/datasets', {'filename': 'new.csv', 'csv': industrial_csv()})
                request(f'/workspaces/{wid}/datasets', {'filename': 'second.csv', 'csv': 'clock_ms;load\n0;2\n500;3\n1000;4\n',
                                                       'timeColumn': 'clock_ms', 'timeUnit': 'milliseconds'})
                result = request(f'/workspaces/{wid}/analyses', {'datasetId': dataset['id'], 'signals': ['reactor_temp', 'feed_rate'],
                                 'baselineRange': [0, 199], 'analysisRange': [200, 599], 'algorithm': 'robust-maxz'})
            finally:
                service.shutdown(); service.server_close(); thread.join()
            service, thread = start()
            try:
                self.assertEqual(request('/workspaces')['workspaces'][0]['id'], wid)
                self.assertEqual(len(request(f'/workspaces/{wid}/datasets')['datasets']), 2)
                self.assertEqual(request(f'/analyses/{result["id"]}'), result)
                self.assertEqual(request(f'/workspaces/{wid}/analyses')['jobs'][0]['id'], result['id'])
                self.assertEqual(len(request(f'/datasets/{dataset["id"]}/series?signal=reactor_temp&start=400&end=459')['times']), 60)
                request(f'/workspaces/{wid}', {'name': 'Reopened project'}, method='PATCH')
                self.assertEqual(request(f'/workspaces/{wid}')['name'], 'Reopened project')
                request(f'/workspaces/{wid}', method='DELETE')
                self.assertEqual(request('/workspaces')['workspaces'], [])
            finally:
                service.shutdown(); service.server_close(); thread.join()


if __name__ == '__main__':
    unittest.main()
