"""Verification of scheduled hydraulics, experiment design and saved results."""
import math
import unittest

import numpy as np

from l5.experiment_design import (D_RIDGE, actuator_box, assess, baselines, design, information, input_margins,
                                  minimum_margin, objective_value, score, sensitivities, simulate, validate_config)
from l5.models.tanks import CoupledTankModel, integrate
from test_incidents import IncidentHTTPFixture


class ScheduledHydraulicsTests(unittest.TestCase):
    def test_exact_switch_and_continuous_state(self):
        c = CoupledTankModel().validate(dict(duration=2., step=.2, integrationStep=.25, start=0., noise=0.))
        switch, command = .537, (75., .6)
        schedule = [(0., 100., 1.), (switch, *command), (1.2, 55., .95)]
        seen = {}
        rows, physical = integrate(c, at=switch, include_at=True, schedule=schedule,
                                   inspect_step=lambda t, h: seen.update({t: h}))
        before_rows, before_physical = integrate(c, at=switch, include_at=True)
        index = next(i for i, r in enumerate(rows) if r['t'] == switch)
        self.assertEqual(rows[:index], before_rows[:index])
        self.assertEqual(physical[index]['level1'], before_physical[index]['level1'])
        self.assertEqual(physical[index]['level2'], before_physical[index]['level2'])
        self.assertEqual((rows[index]['pump'], rows[index]['valve']), command)
        self.assertEqual(seen[switch], [c['initial1'], c['initial2']])
        self.assertEqual(next(r['pump'] for r in rows if r['t'] == 1.2), 55.)
        self.assertNotEqual(rows[-1]['level1'], before_rows[-1]['level1'])
        self.assertLess(max(abs(r['massResidual']) for r in physical), 1e-12)

    def test_dry_and_reverse_flow_stay_nonnegative_and_conservative(self):
        model = CoupledTankModel()
        for initial in ([.001, .001], [0., 2.2], [2.2, 0.]):
            c = model.validate(dict(duration=4.75, step=.65, integrationStep=.25, start=0., area1=.1, area2=.1,
                                    initial1=initial[0], initial2=initial[1], connection=.2, outlet=.2, tankHeight=1.5))
            steps = []
            _, p = integrate(c, schedule=[(0., 0., .01), (.63, 150., 1.), (1.19, 0., 1.)],
                             inspect_step=lambda t, h: steps.append(h))
            self.assertGreaterEqual(min(min(h) for h in steps), 0.)
            self.assertLess(max(abs(r['massResidual']) for r in p), 1e-12)
            self.assertEqual(p[-1]['t'], 4.75)

    def test_between_observation_peak_and_delivery_violation(self):
        c = validate_config(dict(duration=36., controlInterval=12., segments=3, sampleInterval=36.,
                                 levelMax=[1.75, 2.4], tankHeight=1.75, minDelivery=2.,
                                 initialLevels=[1.6, 1.], scenarios=[]))
        u = np.array([[100., 1.], [150., .45], [45., 1.]])
        _, p, extrema = simulate(c, u, c['nominal'], refine=True, monitor=True)
        self.assertTrue(all(row['level1'] < c['tankHeight'] for row in p))
        self.assertGreater(extrema['maxLevel'][0], c['tankHeight'])
        report = score(c, u, c['nominal'], detail=True)
        self.assertLess(report['margins']['overflow'][0], 0)
        self.assertLess(report['margins']['delivery'][0], 0)
        self.assertGreater(report['spilled'], 0.)
        self.assertFalse(report['feasible'])


class InformationDesignTests(unittest.TestCase):
    def test_analytic_sensitivity_scaling_and_structural_absence(self):
        c = validate_config(dict(duration=6., controlInterval=2.5, segments=2, sampleInterval=1.,
                                 nominal={'pumpRate': .02, 'connection': .04, 'outlet': .03},
                                 parameters=['pumpRate', 'connection', 'outlet'], noise={'inlet': .002}, scenarios=[]))
        p = c['nominal'] | {'pumpRate': .04}
        u = np.array([[100., 1.], [120., .8]])
        derivative = sensitivities(c, u, p)
        expected = np.array([1.]*3+[1.2]*4)
        np.testing.assert_allclose(derivative[:, 0, 0], .02*expected, rtol=1e-10)
        np.testing.assert_array_equal(derivative[:, 0, 1:], 0.)
        report = score(c, u, p, detail=True)
        self.assertEqual(report['rank'], 1)
        self.assertEqual(report['structurallyAbsent'], ['connection', 'outlet'])
        self.assertIsNone(report['correlation'])
        self.assertIsNone(report['logDet'])
        self.assertIsNone(report['condition'])
        self.assertLess(report['differenceDisagreement'], 1e-9)
        self.assertAlmostEqual(report['physicalMatrix'][0][0], np.sum((expected/.002)**2), places=4)
        for bound in (1e-4, .2):
            at_bound = sensitivities(c, u, p | {'pumpRate': bound})
            np.testing.assert_allclose(at_bound[:, 0, 0], .02*expected, rtol=1e-9)

    def test_whitening_and_distinct_objectives(self):
        j = np.array([[[1., 0.], [0., 2.]], [[3., 4.], [0., 8.]]])
        fim, sigma, vectors, rank, _ = information(j, [1., 2.])
        np.testing.assert_allclose(fim, [[10., 12.], [12., 33.]])
        np.testing.assert_allclose(vectors.T @ np.diag(sigma**2) @ vectors, fim)
        self.assertEqual(rank, 2)
        self.assertAlmostEqual(objective_value(sigma, 'D'), math.log(np.linalg.det(fim+D_RIDGE*np.eye(2))))
        self.assertAlmostEqual(objective_value(sigma, 'E'), np.linalg.eigvalsh(fim)[0])
        self.assertGreater(objective_value(np.sqrt([100., 1.]), 'D'), objective_value(np.sqrt([5., 4.]), 'D'))
        self.assertLess(objective_value(np.sqrt([100., 1.]), 'E'), objective_value(np.sqrt([5., 4.]), 'E'))
        _, singular, directions, deficient_rank, _ = information(np.zeros((1, 1, 3)), [1.])
        self.assertEqual((deficient_rank, directions.shape, singular.tolist()), (0, (3, 3), [0.]*3))

    def test_central_differences_match_independent_five_point_stencil(self):
        c = validate_config(dict(duration=12., controlInterval=4.1, segments=3, noise={'level1': .004, 'level2': .004}))
        u = np.array([[100., 1.], [150., .62], [70., .9]])
        p = c['nominal']
        numeric = sensitivities(c, u, p, refine=True)
        h = 5e-4
        for j, key in enumerate(c['parameters']):
            samples = []
            for offset in [-2., -1., 1., 2.]:
                r = simulate(c, u, p | {key: p[key]*(1+offset*h)}, refine=True)[0]
                samples.append(np.array([[v['level1'], v['level2']] for v in r]))
            a, b, d, e = samples
            expected = (a-8*b+8*d-e)/(12*h)
            np.testing.assert_allclose(numeric[:, :, j], expected, atol=3e-8, rtol=1e-5)

    def test_baselines_seed_and_fixed_terminal_constraints(self):
        c = validate_config(dict(terminalInput=[75., .75], maxSlew=[5., .042], maxMovement=[48., .46]))
        b = baselines(c, actuator_box(c))
        self.assertEqual(set(b), {'constant', 'step', 'multistep', 'prbs'})
        np.testing.assert_array_equal(b['prbs'], baselines(c, actuator_box(c))['prbs'])
        d = c | {'seed': 41}
        self.assertFalse(np.array_equal(b['prbs'], baselines(d, actuator_box(d))['prbs']))
        for schedule in b.values():
            np.testing.assert_allclose(schedule[0], c['initialInput'])
            np.testing.assert_allclose(schedule[-1], c['terminalInput'])
            self.assertGreaterEqual(minimum_margin(input_margins(c, schedule)[0]), -1e-12)
        impossible = design(c | {'maxMovement': [10., .46]})
        self.assertEqual(impossible['status'], 'infeasible-actuators')
        self.assertEqual(impossible['designs'], [])

    def test_infeasible_state_constraints_are_retained_as_failed_evidence(self):
        result = design(dict(duration=2., segments=1, scenarios=[], minDelivery=5.,
                             terminalLevelTolerance=0., terminalInput=[100., 1.]))
        selected = result['designs'][-1]
        self.assertFalse(selected['feasible'])
        self.assertFalse(result['solvers']['nominal-optimal']['success'])
        self.assertEqual(result['solvers']['nominal-optimal']['auditedStatus'], 'no-feasible-candidate')
        self.assertLess(selected['reports']['nominal']['margins']['delivery'][0], 0)

    def test_repeatable_constrained_optimization_matches_analytic_inlet_reference(self):
        c = dict(duration=10., controlInterval=5., segments=2, scenarios=[], initialInput=[80., .8],
                 maxSlew=[3., 0.], maxMovement=[20., 0.], noise={'inlet': .002},
                 parameters=['pumpRate'], minDelivery=0., objective='E')
        a, b = design(c), design(c)
        d = a['designs'][-1]
        self.assertEqual(d['schedule'], b['designs'][-1]['schedule'])
        self.assertAlmostEqual(d['schedule'][-1]['pump'], 95., places=5)
        self.assertTrue(d['feasible'])
        expected = (.03/.002)**2 * (3*.8**2+3*.95**2)
        self.assertAlmostEqual(d['worstObjective'], expected, places=4)

    def test_robust_optimization_improves_feasible_worst_case_and_reports_mismatch(self):
        result = design({})
        strategies = {d['id']: d for d in result['designs']}
        nominal, robust = strategies['nominal-optimal'], strategies['robust-optimal']
        self.assertTrue(nominal['reports']['nominal']['feasible'])
        self.assertIn('scenario-2', nominal['violatedScenarios'])
        self.assertTrue(robust['feasible'])
        best_conventional = max(d['worstObjective'] for d in result['designs'][:4] if d['feasible'])
        self.assertGreater(robust['worstObjective'], best_conventional+.5)
        self.assertGreater(result['solvers']['robust-optimal']['candidateEvaluations'], 10)
        c = result['config']
        u = np.array([[r['pump'], r['valve']] for r in robust['schedule']])
        mismatch = assess(c, 'held-out', u, {'held-out': {'pumpRate': .038, 'connection': .033, 'outlet': .026}})
        self.assertIn('held-out', mismatch['violatedScenarios'])
        self.assertNotAlmostEqual(mismatch['worstObjective'], robust['worstObjective'], places=2)


class DesignWorkspaceHTTPTests(IncidentHTTPFixture):
    def test_saved_snapshot_reopens_and_publishes_exact_observations(self):
        workspace = self.workspace()
        base = f'/workspaces/{workspace}/experiment-designs'
        self.assertEqual(self.request(base)['defaults']['modelId'], 'coupled-tanks')
        record = self.request(base, dict(name='双水箱试验', config=dict(duration=6., controlInterval=3.,
                              segments=2, scenarios=[], minDelivery=0., objective='E',
                              noise={'level1': .002})), expected=201)
        self.assertEqual(self.request(base)['experiments'][0]['name'], record['name'])
        self.stop()
        self.start()
        identity = record['id']
        self.assertEqual(self.request(f'{base}/{identity}'), record)
        body = dict(designId='nominal-optimal', scenarioId='nominal')
        dataset = self.request(f'{base}/{identity}/datasets', body, expected=201)
        self.assertEqual(self.request(f'{base}/{identity}/datasets', body)['id'], dataset['id'])
        signals = dataset['metadata']['columns']
        self.assertEqual([item['unit'] for item in signals], ['%', 'fraction', 'm'])
        self.assertEqual(signals[-1]['logicalKey'], 'LT-101')
        self.assertEqual(dataset['metadata']['designExperiment']['experimentId'], identity)
        series = self.request(f"/datasets/{dataset['id']}/series?signal=level1&signal=pump")
        saved = record['snapshot']['designs'][-1]['reports']['nominal']
        np.testing.assert_array_equal(series['times'], saved['times'])
        np.testing.assert_array_equal(series['values']['level1'], saved['observations']['level1'])
        np.testing.assert_array_equal(series['values']['pump'], saved['sampledInputs']['pump'])
        other = self.workspace()
        self.request(f'/workspaces/{other}/experiment-designs/{identity}', expected=404)
        self.request(f'{base}/{identity}/datasets', dict(designId='unknown'), expected=400)
