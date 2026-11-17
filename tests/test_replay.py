from http.server import ThreadingHTTPServer
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from urllib.request import build_opener, ProxyHandler, Request

import numpy as np

from l5.analysis import run_analysis
from l5.replay import DETECTORS
from l5.workspace import WorkspaceStore
from server import Handler


class ReplayTests(unittest.TestCase):
    def setUp(self):
        folder = self.enterContext(TemporaryDirectory())
        self.store = WorkspaceStore(Path(folder))
        self.workspace = self.store.create_workspace('Reactor campaign')['id']

    def dataset(self, target):
        normal = [(i, np.sin(i), np.cos(i / 3)) for i in range(100)]
        # The source is deliberately out of order. Equal timestamps keep file order.
        source = [*target, *reversed(normal)]
        csv = 't,temperature,flow\n' + '\n'.join(','.join(map(str, row)) for row in source)
        return self.store.import_dataset(self.workspace, {'name': 'Reactor', 'csv': csv})

    def config(self, dataset, **changes):
        return {**dict(datasetId=dataset['id'], signals=['temperature', 'flow'], algorithm='robust-maxz',
                       baselineRange=[0, 99], analysisRange=[100, dataset['metadata']['time']['end']],
                       alpha=.05, persistence=1), **changes}

    def start(self, dataset, **changes):
        return self.store.replays.create(self.workspace, self.config(dataset, **changes))

    def operate(self, session, operation, **body):
        return self.store.replays.operate(self.workspace, session['id'], operation, body)

    def test_timestamp_order_ties_irregular_intervals_and_no_future_evidence(self):
        target = [(127, 0, 0), (110, 20, 0), (110, 22, 0), (112.5, 25, 0), (125, 0, 0)]
        dataset = self.dataset(target)
        session = self.start(dataset, persistence=2)
        another = self.start(self.dataset([(127, 0, 0), *target[1:-1], (125, 500, 800)]), persistence=2)
        self.assertEqual(session['threshold'], another['threshold'])
        self.assertEqual(session['model'], another['model'])
        first = self.operate(session, 'frame', at=110)
        self.assertEqual(first['series']['times'], [110, 110])
        self.assertEqual(first['series']['values']['temperature'], [20, 22])
        self.assertEqual(first['series']['states'], ['normal', 'alarm'])
        self.assertEqual(first['nextTime'], 112.5)
        self.assertEqual(self.operate(session, 'frame', at=112), first)
        self.assertEqual(first, self.operate(another, 'frame', at=110))
        self.assertEqual(first['alarms'][0]['status'], 'active')
        self.assertIsNone(first['alarms'][0]['transitionTime'])
        with self.assertRaisesRegex(ValueError, 'observed replay position'):
            self.operate(session, 'export', through=3)
        later = self.operate(session, 'frame', at=127)
        alarm = later['alarms'][0]
        self.assertEqual((alarm['start'], alarm['end'], alarm['durationSeconds']), (110, 112.5, 2.5))
        self.assertEqual((alarm['status'], alarm['transitionTime']), ('recovered', 125))
        self.assertEqual(self.operate(session, 'frame', at=110), first)
        evidence = self.operate(session, 'evidence', alarmId=alarm['id'], through=first['through'])
        self.assertEqual(evidence['alarm'], first['alarms'][0])
        self.assertEqual(evidence['series']['times'], [110, 110])
        with self.assertRaisesRegex(ValueError, 'baseline must finish'):
            self.start(dataset, baselineRange=[0, 110])

    def test_temporal_state_chunking_restart_and_batch_equivalence(self):
        target = [(i, 9 if 104 <= i < 113 or 125 <= i <= 129 else 0, i % 3 / 8) for i in range(100, 140)]
        target[11] = (111, '', 0)
        dataset = self.dataset(target)
        times, values = self.store.load_data(dataset)
        for detector in DETECTORS:
            with self.subTest(detector=detector):
                config = self.config(dataset, algorithm=detector, persistence=2, minCoverage=1)
                batch = run_analysis(times, values, config['signals'], config)
                session = self.store.replays.create(self.workspace, config)
                for at in (100, 106, 110, 111, 112, 128, 139):
                    self.operate(session, 'frame', at=at)
                export = self.operate(session, 'export', through=40, playbackSpeed=10)
                self.assertEqual(export['threshold'], batch['threshold'])
                series = export['observations']
                self.assertEqual(series['states'], batch['states'])
                covered = np.array([score is not None for score in series['scores']])
                np.testing.assert_allclose(np.array(series['scores'], dtype=float)[covered], np.array(batch['scores'])[covered])
                self.assertIsNone(series['scores'][11])
                self.assertEqual(series['states'][12], 'normal')  # Pending persistence was cleared.
                self.assertEqual(export['alarms'][0]['status'], 'interrupted')
                self.assertEqual(export['alarms'][0]['transitionTime'], 111)
                restarted = self.store.replays.create(self.workspace, config)
                self.operate(restarted, 'frame', at=139)
                direct = self.operate(restarted, 'export', through=40, playbackSpeed=1)
                self.assertEqual(series, direct['observations'])
                self.assertEqual(export['alarms'], direct['alarms'])
                before = self.operate(session, 'frame', at=107)
                self.assertEqual(before['series']['scores'], series['scores'][:8])
                self.assertEqual(before['alarms'][0]['status'], 'active')

    def test_http_replay_evidence_and_durable_incident_report(self):
        dataset = self.dataset([(100, 20, 0), (101, 30, 0), (105, 0, 0), (106, 500, 0)])
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.workspace_store = self.store
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        opener = build_opener(ProxyHandler({}))
        root = f'http://127.0.0.1:{server.server_port}/api'

        def post(path, body):
            req = Request(root + path, json.dumps(body).encode(), {'Content-Type': 'application/json'})
            with opener.open(req, timeout=5) as response:
                return json.load(response)

        path = f'/workspaces/{self.workspace}/replays'
        session = post(path, self.config(dataset))
        path += f'/{session["id"]}'
        frame = post(path + '/frame', {'at': 105})
        select = {'through': frame['through'], 'alarmId': frame['alarms'][0]['id']}
        evidence = post(path + '/evidence', select)
        exported = post(path + '/export', {'through': frame['through']})
        incident = post(path + '/incident', select)
        self.assertEqual(post(path + '/incident', select)['id'], incident['id'])
        restored = WorkspaceStore(self.store.root)
        link = restored.incidents.get(incident['id'])['links'][0]
        analysis = restored.result(link['reference_id'])
        self.assertEqual(link['kind'], 'interval')
        self.assertEqual(analysis['intervals'][int(link['selector'])], evidence['alarm'])
        self.assertEqual(analysis['scores'], exported['observations']['scores'])
        self.assertEqual(analysis['times'], [100, 101, 105])
        self.assertEqual(analysis['replay']['dataset']['sha256'], exported['dataset']['sha256'])
        with opener.open(root + f'/incidents/{incident["id"]}/report.html?lang=en', timeout=5) as response:
            report = response.read().decode()
        self.assertIn('Reactor', report)
        self.assertIn('temperature', report)

    def test_saved_coupled_tank_observations_are_replayable(self):
        runtime = self.store.runtime
        simulation = runtime.create({'workspaceId': self.workspace, 'modelId': 'coupled-tanks', 'config': {
            'fault': 'tank_leak', 'start': 60, 'duration': 85, 'step': .2, 'seed': 17,
        }})
        dataset = runtime.save(simulation['id'], {'workspaceId': self.workspace})
        signals = [item['name'] for item in dataset['metadata']['columns'][:2]]
        session = self.start(dataset, signals=signals, baselineRange=[0, 55], analysisRange=[55.2, 85])
        self.assertEqual(session['dataset']['simulationId'], simulation['id'])
        frame = self.operate(session, 'frame', at=85)
        self.assertEqual(frame['through'], session['sampleCount'])
        self.assertGreater(frame['alarmCount'], 0)


if __name__ == '__main__':
    unittest.main()
