from http.server import ThreadingHTTPServer
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import numpy as np

from l5.models.tanks import integrate
from l5.sensor_placement import (
    KEYS, MODEL, analyze, defaults, enumerate_subsets, normalize, rank_subsets, sensitivities,
    separations, signatures, spectrum, whiten,
)
from l5.sensor_placement_evaluation import predictions
from l5.workspace import WorkspaceStore
from server import Handler


class NumericalEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = analyze({})

    def test_model_single_fault_contract_and_combined_mass_balance(self):
        model = MODEL.validate(dict(duration=8, step=.5, start=2., fault_duration=2.3, noise=0))
        names = ['pump_degradation', 'valve_restriction', 'tank_leak', 'sensor_bias']
        intensities = {key: .3 for key in names}
        times, templates = signatures(model, names, intensities)
        for i, name in enumerate(names, 1):
            rows, _ = integrate(dict(model, fault=name, severity=.3))
            np.testing.assert_array_equal(templates[i], [[row[key] for key in KEYS] for row in rows])
        rows, physical = integrate(model, faults={'pump_degradation': .3, 'valve_restriction': .4})
        np.testing.assert_array_equal(rows[0]['inlet'], templates[0, 0, 2])
        self.assertAlmostEqual(rows[4]['inlet'], .03*(1-.7*.3))
        self.assertAlmostEqual(rows[4]['transfer'], .03*(1-.85*.4))
        self.assertAlmostEqual(rows[9]['inlet'], .03)
        self.assertLess(max(abs(r['massResidual']) for r in physical), 1e-12)
        np.testing.assert_array_equal(templates[4, times < 2], templates[0, times < 2])

    def test_derivatives_and_stacking_against_analytic_reference(self):
        model = MODEL.validate(dict(duration=8, step=.5, start=2, noise=0, fault_duration=3.25))
        names = ['pump_degradation', 'sensor_bias']
        time, templates = signatures(model, names, {name: .3 for name in names})
        derivative, stability = sensitivities(model, templates[0], names)
        active = (time >= 2) & (time < 5.25)
        reference = np.zeros_like(derivative[1])
        reference[active, 1] = model['sensorBias']
        np.testing.assert_allclose(derivative[1], reference, atol=1e-12)
        np.testing.assert_allclose(derivative[0, :, 2], -model['pumpRate']*.7*active, atol=1e-12)
        self.assertLess(max(stability[0]['relativeL2']), 1e-4)
        stacked = derivative[..., [1, 2]].reshape(2, -1).T
        self.assertEqual(spectrum(stacked)['rank'], 2)
        self.assertEqual(spectrum(derivative[..., [2]].reshape(2, -1).T)['rank'], 1)

    def test_covariance_and_independent_singular_values(self):
        values = np.array([[[0., 0.], [0., 0.]], [[2., 2.], [2., 2.]]])
        cov = np.array([[4., 1.], [1., 1.]])
        result = separations(whiten(values, np.linalg.cholesky(cov)))
        # Inverse = [[1,-1],[-1,4]]/3. At each instant [2,2] C^-1 [2,2]^T = 4.
        self.assertAlmostEqual(result[0, 1], 8**.5)
        np.testing.assert_array_equal(result, result.T)
        res = spectrum(np.array([[3., 0.], [0., 1.], [0., 0.]]))
        self.assertEqual(res['singularValues'], [3., 1.])
        self.assertEqual(res['condition'], 3.)
        self.assertEqual(spectrum(np.zeros((1, 3)))['rank'], 0)
        bad = np.ones((5, 5)).tolist()
        with self.assertRaisesRegex(ValueError, 'positive eigenvalues'):
            normalize({'correlations': bad})
        with self.assertRaisesRegex(ValueError, 'symmetric'):
            bad[0][1] = .4
            normalize({'correlations': bad})
        setup = defaults()
        setup['correlations'][0][1] = setup['correlations'][1][0] = .5
        _, _, covariance = normalize(setup)
        self.assertAlmostEqual(covariance[0, 1], .5 * .004**2)

    def test_exact_constraints_and_independent_profile_optima(self):
        sensors = defaults()['sensors']
        sensors[0].update(mode='required', cost=.1)
        sensors[1].update(mode='excluded')
        sensors[2].update(cost=.2)
        self.assertEqual(list(enumerate_subsets(sensors, .3, 2))[0], ((0,), .1))
        self.assertEqual([row[0] for row in enumerate_subsets(sensors, .3, 2)], [(0,), (0, 2)])
        self.assertEqual([row[0] for row in enumerate_subsets(sensors, .3, 1)], [(0,)])
        self.assertEqual(list(enumerate_subsets(sensors, .05, 3)), [])
        rows = [dict(sensors=[key], cost=cost, nominal={'separation': a},
                     mean={'separation': b}, worst={'separation': c})
                for key, cost, a, b, c in [('A', 2, 9, 5, 1), ('B', 1, 7, 6, 4),
                                           ('C', 3, 6, 5, 2), ('D', 2, 6, 6, 5)]]
        self.assertEqual(rank_subsets(rows, 'separation'), {'nominal': ['A'], 'mean': ['B'], 'worst': ['D']})
        self.assertEqual([row['pareto'] for row in rows], [True, True, False, True])
        result = self.result
        self.assertEqual(len(result['subsets']), 15)
        self.assertEqual(result['winners']['worst'], ['level1', 'level2'])
        self.assertEqual(result['winners']['mean'], ['level1', 'level2', 'transfer'])
        for profile, keys in result['winners'].items():
            chosen = next(row for row in result['subsets'] if row['sensors'] == keys)
            score = chosen[profile]['separation']
            self.assertAlmostEqual(score, max(row[profile]['separation'] for row in result['subsets']), places=10)

    def test_cancellation_and_indistinguishable_hypotheses(self):
        cancellation = self.result['cancellation']
        a, b, combined = cancellation['tank1Rms']
        self.assertLess(combined, min(a, b)/40)
        tank1, tank2, both, all_sensors = cancellation['cases'][0]['metrics']
        self.assertLess(tank1['detectability'], 1)
        self.assertLess(tank1['detectionPower'], .25)
        self.assertGreater(tank2['detectability'], 40)
        self.assertGreater(both['isolability'], 40)
        self.assertGreater(all_sensors['detectability'], both['detectability'])
        self.assertLess(cancellation['cases'][1]['metrics'][1]['isolability'], 2)
        row = next(row for row in self.result['subsets'] if row['sensors'] == ['level1'])
        bias = self.result['hypotheses'].index('sensor_bias')
        self.assertEqual(row['conditions'][0]['distances'][0][bias], 0.)
        self.assertLess(row['conditions'][0]['spectrum']['rank'], len(self.result['parameters']))
        passed, classified, _ = predictions(np.array([[1., 2.]]), np.array([[0., 0.], [1., 2.], [1., 2.]]), 0., 8.)
        self.assertEqual(passed.tolist(), [True])
        self.assertEqual(classified.tolist(), [-1])

    def test_holdout_reproducibility_and_mismatch(self):
        evaluation = self.result['evaluation']
        other = analyze({})['evaluation']
        self.assertNotEqual(evaluation['calibrationSeed'], evaluation['holdoutSeed'])
        self.assertEqual(evaluation['cohorts'], other['cohorts'])
        for row, repeated in zip(evaluation['layouts'], other['layouts']):
            self.assertEqual(row['cohorts'], repeated['cohorts'])
            for cohort in row['cohorts']:
                self.assertTrue(all(sum(counts) == cohort['trialsPerHypothesis'] for counts in cohort['counts']))
        best = next(row for row in evaluation['layouts'] if row['id'] == 'minimax_optimum')
        self.assertGreater(best['cohorts'][0]['classificationAccuracy'], .9)
        self.assertLess(best['cohorts'][2]['classificationAccuracy'], .5)
        self.assertNotEqual(evaluation['cohorts'][0]['model'], evaluation['cohorts'][2]['model'])
        self.assertEqual(best['cohorts'][0]['detectionByFault'], [1.]*5)

    def test_minimax_improves_the_weakest_physical_operating_condition(self):
        result = analyze(dict(budget=4, maxSensors=2,
                              hypotheses=['pump_degradation', 'valve_restriction', 'tank_leak',
                                          'pump_and_valve', 'pump_and_leak'],
                              conditions=[dict(id=key, parameters={}) for key in
                                          ('nominal', 'different_levels', 'valve_opening', 'parameter_shift')]))
        self.assertEqual(result['winners']['mean'], ['level1', 'level2'])
        self.assertEqual(result['winners']['worst'], ['level1', 'inlet'])
        rows = {tuple(row['sensors']): row for row in result['subsets']}
        average, robust = [rows[tuple(result['winners'][key])] for key in ('mean', 'worst')]
        self.assertGreater(average['mean']['separation'], robust['mean']['separation'])
        self.assertGreater(robust['worst']['separation'], 1.4*average['worst']['separation'])


class SensorPlacementHTTP(unittest.TestCase):
    def test_saved_run_report_json_and_catalog_publication(self):
        with TemporaryDirectory() as path:
            store = WorkspaceStore(Path(path))
            workspace = store.create_workspace('Fault evidence')['id']
            other = store.create_workspace('Other')['id']
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            server.workspace_store = store
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            client = build_opener(ProxyHandler({}))
            root = f'http://127.0.0.1:{server.server_port}/api'
            path_for = f'/workspaces/{workspace}/sensor-placement'

            def request(path, body=None):
                req = Request(root+path, data=json.dumps(body).encode() if body is not None else None,
                              headers={'Content-Type': 'application/json'})
                return client.open(req, timeout=15)

            try:
                with request(path_for) as response:
                    self.assertEqual(json.load(response)['runs'], [])
                setup = dict(horizon=8, onset=2, conditions=[dict(id='nominal', parameters={})])
                with request(path_for, dict(name='<Saved & checked>', config=setup)) as response:
                    self.assertEqual(response.status, 201)
                    run = json.load(response)
                run_path = path_for + '/' + run['id']
                reopened = WorkspaceStore(Path(path))
                self.assertEqual(reopened.sensor_placement.get(workspace, run['id']), run)
                with request(run_path + '/analysis.json') as response:
                    self.assertIn('attachment', response.headers['Content-Disposition'])
                    self.assertEqual(json.load(response), run)
                with request(run_path + '/report.html?lang=zh-CN&download=1') as response:
                    report = response.read().decode()
                    self.assertIn('<html lang="zh-CN">', report)
                    self.assertIn('泵与阀故障相消实验', report)
                    self.assertIn('&lt;Saved &amp; checked&gt;', report)
                with request(run_path + '/dataset', dict(condition='nominal', hypothesis='pump_degradation',
                                                          sensors=['inlet'], cohort='holdout_timing')) as response:
                    dataset = json.load(response)
                self.assertEqual(dataset['metadata']['sensorPlacement']['runId'], run['id'])
                self.assertEqual(dataset['metadata']['columns'][0]['unit'], 'm³/s')
                signal_id = dataset['metadata']['columns'][0]['id']
                self.assertIn(signal_id, [s['id'] for s in store.signals.catalog(workspace)])
                expected = np.array(run['analysis']['evaluation']['cohorts'][1]['representative'][1])[:, 2]
                np.testing.assert_allclose(store.load_data(dataset)[1][:, 0], expected, rtol=0, atol=1e-15)
                with self.assertRaises(HTTPError) as error:
                    request(f'/workspaces/{other}/sensor-placement/{run["id"]}')
                self.assertEqual(error.exception.code, 404)
                with self.assertRaises(HTTPError) as error:
                    request(path_for, dict(name='No feasible design', config={'budget': 0}))
                self.assertEqual(error.exception.code, 400)
                self.assertEqual(len(store.sensor_placement.list(workspace)), 1)
                store.delete_workspace(workspace)
                with self.assertRaises(KeyError):
                    store.sensor_placement.get(workspace, run['id'])
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
