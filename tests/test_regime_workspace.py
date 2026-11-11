"""Local HTTP workflow for frozen regime models and their saved evidence."""
from urllib.request import ProxyHandler, build_opener

import numpy as np

from test_incidents import IncidentHTTPFixture


class RegimeWorkspaceTests(IncidentHTTPFixture):
    def import_values(self, workspace, name, values, times=None, columns='load,temperature,pressure'):
        if times is None:
            times = range(len(values))
        csv = f'time,{columns}\n' + '\n'.join(
            ','.join(map(str, [i, *row])) for i, row in zip(times, values))
        return self.request(f'/workspaces/{workspace}/datasets', dict(name=name, csv=csv), expected=201)['id']

    def fit_request(self, dataset):
        def ref(start, end):
            return dict(datasetId=dataset, range=[start, end])

        return dict(name='Normal envelope <baseline>', signals=['load', 'temperature', 'pressure'],
                    recognition=dict(recognitionSignals=['load'], dwell=3, persistence=2),
                    modes=[dict(id='low', label='Low load', fit=[ref(0, 39), ref(40, 69)], calibration=ref(70, 129)),
                           dict(id='high', label='高负荷', fit=ref(130, 199), calibration=ref(200, 259),
                                detector=dict(algorithm='pca-q', alpha=.025))])

    def test_fit_evaluate_reopen_report_and_link_interval(self):
        workspace = self.workspace()
        rng = np.random.default_rng(341)
        low = rng.normal(0, .25, size=(210, 3))
        high = rng.normal(0, .25, size=(220, 3)) + [9, 2, 1]
        high[175:193, 2] += 12
        values = np.concatenate([low[:130], high[:130], low[130:], high[130:]])
        data = self.import_values(workspace, 'Process measurements', values)
        prefix = f'/workspaces/{workspace}/regimes'
        labels = self.request(f'/datasets/{data}/labels', dict(timeBasis='dataset-seconds', timeSource='Test log',
            intervals=[dict(kind='normal', start=0, end=384), dict(kind='anomaly', start=385, end=402),
                       dict(kind='normal', start=403, end=429)]), expected=201)
        fit = self.fit_request(data)
        fit['modes'][0]['fit'][0]['labelSetId'] = labels['id']
        model = self.request(prefix + '/fit', fit, expected=201)
        self.assertEqual(model['model']['modeOrder'], ['low', 'high'])
        self.assertEqual(model['model']['modes']['high']['detector']['algorithm'], 'pca-q')
        self.assertEqual(model['model']['modes']['low']['fitSamples'], 70)
        self.assertEqual(model['labelSets'][labels['id']]['version'], 1)
        self.assertEqual(len(model['sources'][data]['sourceCsvSha256']), 64)
        evaluation = dict(modelId=model['id'], evaluation=dict(datasetId=data, range=[260, 429], labelSetId=labels['id']))
        run = self.request(prefix + '/runs', evaluation, expected=201)
        self.assertEqual(run['protocol'], 'chronological-holdout')
        self.assertEqual(run['times'], run['series']['time'])
        self.assertEqual(run['decisions'][10]['mode'], 'low')
        transition = next(item for item in run['transitions'] if item['outcome'] == 'confirmed')
        self.assertEqual((transition['fromMode'], transition['toMode']), ('low', 'high'))
        self.assertLess(transition['candidateTime'], transition['confirmedTime'])
        self.assertEqual(run['metrics']['regime']['detection']['windows']['eventual']['detectedEvents'], 1)
        self.assertEqual(run['metrics']['regime']['behavior']['validSamples'], run['summary']['monitoredSamples'])
        index = next(i for i, interval in enumerate(run['intervals']) if 385 <= interval['start'] <= 402)
        with self.subTest('incident evidence'):
            link = self.request(prefix + f'/runs/{run["id"]}/incidents', dict(intervalIndex=index), expected=201)
            evidence = link['links'][0]['details']
            self.assertEqual(evidence['analysisId'], run['analysisId'])
            self.assertEqual(evidence['interval']['peakTime'], run['intervals'][index]['peakTime'])
            self.assertEqual(evidence['interval']['rawPeakScore'], run['intervals'][index]['peakScore'])
            self.assertEqual(len(self.request(f'/incidents/{link["id"]}/timeline')['analyses']), 1)
            self.assertEqual(len(self.request(prefix + f'/runs/{run["id"]}/incidents',
                             dict(intervalIndex=index, incidentId=link['id']), expected=201)['links']), 1)
        self.stop()
        self.start()
        self.assertEqual(self.request(prefix + f'/models/{model["id"]}'), model)
        self.assertEqual(self.request(f'/regime-runs/{run["id"]}'), run)
        self.assertEqual(self.request(prefix + '/runs')['runs'][0]['id'], run['id'])
        self.assertEqual(self.request(f'/analyses/{run["analysisId"]}')['regimeRunId'], run['id'])
        repeated = self.request(prefix + '/runs', evaluation, expected=201)
        self.assertEqual(repeated['decisions'], run['decisions'])
        self.assertEqual(repeated['intervals'], run['intervals'])
        url = f'http://127.0.0.1:{self.service.server_port}/api{prefix}/runs/{run["id"]}/report.html?lang=zh-CN&download=1'
        with build_opener(ProxyHandler({})).open(url, timeout=10) as response:
            self.assertIn('attachment', response.headers['Content-Disposition'])
            html = response.read().decode()
        self.assertIn('运行工况监测报告', html)
        self.assertIn('Normal envelope &lt;baseline&gt;', html)
        self.assertIn('<svg', html)

    def test_rejects_training_overlap_wrong_labels_and_copied_evaluation(self):
        workspace = self.workspace()
        values = np.random.default_rng(38).normal(size=(300, 3))
        dataset = self.import_values(workspace, 'Training dataset', values)
        copy = self.import_values(workspace, 'Copied data', values)
        prefix = f'/workspaces/{workspace}/regimes'
        fit = self.fit_request(dataset)
        fit['modes'][1]['fit']['range'][0] = 129
        self.assertIn('disjoint', self.request(prefix + '/fit', fit, expected=400)['error'])
        fit = self.fit_request(dataset)
        labels = self.request(f'/datasets/{dataset}/labels', dict(timeBasis='dataset-seconds', timeSource='Reviewed',
            intervals=[dict(kind='anomaly', start=0, end=69)]), expected=201)
        fit['modes'][0]['fit'][0]['labelSetId'] = labels['id']
        self.assertIn('normal interval', self.request(prefix + '/fit', fit, expected=400)['error'])
        model = self.request(prefix + '/fit', self.fit_request(dataset), expected=201)
        for source, interval, error in [(dataset, [259, 299], 'start after'), (copy, [260, 299], 're-imported')]:
            body = dict(modelId=model['id'], evaluation=dict(datasetId=source, range=interval))
            self.assertIn(error, self.request(prefix + '/runs', body, expected=400)['error'])
        other = self.workspace('Other workspace')
        self.request(f'/workspaces/{other}/regimes/models/{model["id"]}', expected=404)
        self.assertEqual(self.request(prefix + '/runs')['runs'], [])
        self.assertEqual(self.request(f'/workspaces/{workspace}/analyses')['jobs'], [])

    def test_fit_cadence_is_frozen_and_test_suffix_cannot_change_prefix(self):
        workspace = self.workspace()
        rng = np.random.default_rng(18)
        low = rng.normal(0, .1, size=(130, 3))
        high = rng.normal(0, .1, size=(130, 3)) + [4, 2, 1]
        train = self.import_values(workspace, 'Training', np.concatenate([low, high]))
        prefix = f'/workspaces/{workspace}/regimes'
        model = self.request(prefix + '/fit', self.fit_request(train), expected=201)
        self.assertEqual(model['config']['gapThreshold'], 5)
        values = np.concatenate([low[:6], high[:6], high[6:26]])
        common_times = [0, 1, 2, 3, 4, 5, 6, 21, 22, 23, 24, 25]

        def run(name, cadence, mapping=None):
            times = common_times + [25 + (i + 1) * cadence for i in range(20)]
            columns = ','.join(mapping.values()) if mapping else 'load,temperature,pressure'
            dataset = self.import_values(workspace, name, values, times, columns)
            body = dict(modelId=model['id'], evaluation=dict(datasetId=dataset, range=[times[0], times[-1]], signalMapping=mapping))
            return self.request(prefix + '/runs', body, expected=201)

        aliases = dict(load='load_pv', temperature='temperature_pv', pressure='pressure_pv')
        first, second = run('Dense', 1), run('Sparse', 30, aliases)
        self.assertEqual(first['protocol'], 'distinct-dataset')
        self.assertEqual(first['decisions'][:12], second['decisions'][:12])
        self.assertTrue(first['decisions'][7]['gapBefore'])
        self.assertEqual(first['decisions'][7]['candidateSamples'], 1)
        projected = self.request(f'/analyses/{second["id"]}')
        self.assertEqual(projected['config']['signals'], list(aliases.values()))
        self.assertEqual(projected['summary']['analysisSamples'], len(values))
