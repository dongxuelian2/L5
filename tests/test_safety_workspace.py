"""Safety persistence, exports and Incident evidence through the local API."""
import csv
from io import StringIO
import json
from urllib.request import ProxyHandler, build_opener

from tests.test_incidents import IncidentHTTPFixture


class SafetyWorkspaceTests(IncidentHTTPFixture):
    def download(self, path):
        with build_opener(ProxyHandler({})).open(
                f'http://127.0.0.1:{self.service.server_port}/api{path}', timeout=30) as response:
            self.assertIn('attachment;', response.headers['Content-Disposition'])
            return response.read().decode('utf-8')

    def test_csv_versions_restart_exports_and_observed_evidence(self):
        wid, other = self.workspace('Safety'), self.workspace('Other')
        dataset = self.request(f'/workspaces/{wid}/datasets',
                               {'csv': 'time,level\n0,1\n1,3\n2,\n3,3\n4,1\n5,1\n6,1',
                                'name': 'Level history'}, expected=201)
        signal = dataset['metadata']['columns'][0]['id']
        self.request(f'/signals/{signal}', {'unit': 'm'}, method='PATCH')
        limit = dict(id='level-max', name='液位上限', kind='value', unit='cm',
                     terms=[{'signalId': signal}], upper=250, warningUpper=200)
        base = f'/workspaces/{wid}/safety'
        configuration = self.request(base + '/configurations',
                                     dict(datasetId=dataset['id'], name='Rated envelope', constraints=[limit]), expected=201)
        address = base + '/configurations/' + configuration['id']
        updated = dict(datasetId=dataset['id'], name='Raised limit', constraints=[{**limit, 'upper': 300}], revision=1)
        self.assertEqual(self.request(address, updated, method='PATCH')['revision'], 2)
        self.request(address, updated, method='PATCH', expected=400)
        self.assertEqual(self.request(address + '?revision=1'), configuration)
        self.assertEqual(self.request(base + '/configurations')['configurations'][0]['revision'], 2)
        request = dict(datasetId=dataset['id'], name='Recorded excursion', configurationId=configuration['id'],
                       configurationRevision=1, forecast={})
        unsaved = self.request(base + '/evaluate', request)
        self.assertNotIn('id', unsaved)
        self.assertEqual(unsaved['forecast']['status'], 'unavailable')
        saved = self.request(base + '/assessments', request, expected=201)
        address = base + '/assessments/' + saved['id']
        observed = saved['observed'][0]
        self.assertEqual(observed['maximumExceedance'], 50)
        self.assertEqual(observed['coverage']['evaluatedSamples'], 6)
        self.assertEqual([(i['start'], i['end']) for i in observed['rawViolationIntervals']], [(1, 1), (3, 3)])
        self.assertEqual(saved['source']['signals'][0]['id'], signal)
        self.assertEqual(saved['configuration']['revision'], 1)

        incident = self.request(f'/workspaces/{wid}/incidents', {'title': 'Review limit breach'}, expected=201)
        foreign = self.request(f'/workspaces/{other}/incidents', {'title': 'Different workspace'}, expected=201)
        evidence = dict(incidentId=incident['id'], kind='observed', constraintId='level-max', intervalIndex=0, raw=True)
        self.request(address + '/incident-evidence', {**evidence, 'incidentId': foreign['id']}, expected=400)
        self.request(address + '/incident-evidence', {**evidence, 'intervalIndex': 9}, expected=400)
        for _ in range(2):
            linked = self.request(address + '/incident-evidence', evidence, expected=201)
        self.assertEqual(len(linked['links']), 1)
        self.assertEqual(linked['links'][0]['details']['assessmentId'], saved['id'])
        view = self.request(f"/incidents/{incident['id']}/timeline")
        event = next(e for e in view['events'] if e['kind'] == 'safety-observed')
        self.assertEqual(event['start'], 1)
        self.assertTrue(event['safety']['raw'])

        self.stop()
        self.start()
        self.assertEqual(self.request(address), saved)
        self.assertEqual(json.loads(self.download(address + '/export?format=json')), saved)
        rows = list(csv.DictReader(StringIO(self.download(address + '/export?format=csv'))))
        self.assertEqual(len(rows), 7)
        self.assertEqual(rows[1]['margin'], '-50.0')
        self.assertEqual(rows[2]['value'], '')
        self.assertIn('实测运行约束', self.download(address + '/export?format=markdown&lang=zh-CN'))
        self.assertIn('液位上限', self.download(address + '/export?format=markdown&lang=en'))

    def test_prediction_is_attached_to_recorded_lane_with_model_cutoff(self):
        wid = self.workspace('Coupled tank')
        session = self.request('/simulations', dict(workspaceId=wid, modelId='coupled-tanks',
            config=dict(duration=100, start=40, noise=0, pumpControl=150)), expected=201)
        dataset = self.request(f"/simulations/{session['id']}/save", {'workspaceId': wid})
        signal = next(c['id'] for c in dataset['metadata']['columns'] if c['name'] == 'level1')
        limit = dict(id='level-max', name='Tank 1 operating maximum', kind='value', unit='m',
                     terms=[{'signalId': signal}], upper=1.6)
        base = f'/workspaces/{wid}/safety'
        assessment = self.request(base + '/assessments', dict(datasetId=dataset['id'], constraints=[limit],
            forecast=dict(asOf=0, horizonSeconds=30, stepSeconds=.2)), expected=201)
        forecast = assessment['forecast']
        self.assertEqual(forecast['status'], 'available')
        self.assertEqual(forecast['observedThrough'], 0)
        self.assertGreater(forecast['constraints'][0]['timeToViolation'], 0)
        incident = self.request(f'/workspaces/{wid}/incidents', {'title': 'Predictive review'}, expected=201)
        self.request(base + f"/assessments/{assessment['id']}/incident-evidence", dict(incidentId=incident['id'],
            kind='predicted', constraintId=limit['id'], intervalIndex=0), expected=201)
        view = self.request(f"/incidents/{incident['id']}/timeline")
        event = next(e for e in view['events'] if e['kind'] == 'safety-predicted')
        self.assertIsNone(event['start'])
        self.assertIsNone(event['axisId'])
        self.assertEqual(event['safety']['asOf'], 0)
        self.assertGreater(event['safety']['interval']['start'], 0)
        with build_opener(ProxyHandler({})).open(
                f"http://127.0.0.1:{self.service.server_port}/api/incidents/{incident['id']}/report.html?lang=en",
                timeout=30) as response:
            self.assertIn('Predicted constraint violation', response.read().decode('utf-8'))
