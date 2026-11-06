"""The bundled case uses the real simulation, experiment, incident and report APIs."""
from time import monotonic, sleep
from urllib.request import build_opener, ProxyHandler

from tests.test_incidents import IncidentHTTPFixture


class GuidedDemoTests(IncidentHTTPFixture):
    def test_guided_case_from_simulation_to_resumable_offline_report(self):
        guide = '/guided-demo'
        self.assertIsNone(self.request(guide)['session'])
        self.request(guide + '/run', {}, expected=404)
        self.assertEqual(self.request('/workspaces')['workspaces'], [])

        state = self.request(guide, {'locale': 'en'})
        session, plan = state['session'], state['plan']
        workspace, dataset = session['workspaceId'], session['datasetId']
        self.assertEqual(self.request(guide, {'locale': 'zh-CN'}), state)
        self.request(guide + '/incident', {}, expected=400)
        data = self.request(f'/datasets/{dataset}')
        self.assertEqual(data['metadata']['model']['id'], 'coupled-tanks')
        self.assertEqual(data['metadata']['model']['config']['fault'], 'pump_degradation')
        self.assertLess(plan['baselineRange'][1], plan['analysisRange'][0])
        self.assertLess(plan['analysisRange'][0], plan['onset'])
        before, after = [self.request(f'/datasets/{dataset}/sample?at={at}&signal=inlet&signal=pump')['values']
                         for at in (plan['onset'] - plan['step'], plan['onset'])]
        self.assertLess(after['inlet'], before['inlet'])
        self.assertEqual(after['pump'], before['pump'])

        run_id = self.request(guide + '/run', {})['session']['runId']
        self.assertEqual(self.request(guide + '/run', {})['session']['runId'], run_id)
        deadline = monotonic() + 10
        while True:
            run = self.request(f'/experiment-runs/{run_id}')
            if run['status'] not in ('queued', 'running'):
                break
            self.assertLess(monotonic(), deadline, 'guided experiment did not finish')
            sleep(.05)
        self.assertEqual(run['status'], 'completed')
        self.assertEqual(run['snapshot']['labels']['source'], 'model-simulation')
        self.assertEqual([t['algorithm'] for t in run['tasks']], ['robust-maxz', 'ewma'])
        for task in run['tasks']:
            result = self.request(f'/analyses/{task["result_id"]}')
            self.assertEqual(result['datasetId'], dataset)
            self.assertEqual(result['config']['signals'], plan['signals'])
            self.assertEqual(result['experiment']['runId'], run_id)
            self.assertGreaterEqual(result['summary']['firstDetection'], plan['onset'])
            self.assertTrue(result['intervals'][0]['contributions'])
            self.assertEqual(task['metrics']['labelled']['event']['detectedEvents'], 1)

        state = self.request(guide + '/incident', {'locale': 'en'})
        incident_id = state['session']['incidentId']
        self.assertEqual(self.request(guide + '/incident', {}), state)
        incident = f'/incidents/{incident_id}'
        view = self.request(incident + '/timeline')
        self.assertEqual({a['id'] for a in view['analyses']}, {t['result_id'] for t in run['tasks']})
        self.assertEqual({link['kind'] for link in view['incident']['links']}, {'analysis', 'dataset', 'simulation'})
        self.request(incident, {'conclusion': 'Observed flow loss with steady pump command.'}, method='PATCH')

        self.stop()
        self.start()
        self.assertEqual(self.request(guide), state)
        self.assertEqual(len(self.request(f'/experiments/{session["experimentId"]}/runs')['runs']), 1)
        for locale, heading in (('en', 'Robust Max-Z'), ('zh-CN', '稳健最大 Z 分数')):
            url = f'http://127.0.0.1:{self.service.server_port}/api{incident}/report.html?lang={locale}&download=1'
            with build_opener(ProxyHandler({})).open(url, timeout=30) as response:
                report = response.read().decode('utf-8')
                self.assertIn('attachment;', response.headers['Content-Disposition'])
            self.assertIn(heading, report)
            self.assertIn('EWMA', report)
            self.assertIn('Observed flow loss with steady pump command.', report)
            self.assertIn('<svg', report)

        self.request(f'/workspaces/{workspace}', method='DELETE')
        self.assertIsNone(self.request(guide)['session'])
