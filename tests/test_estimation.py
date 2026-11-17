"""Independent equations, physical regressions, causality and local HTTP lifecycle."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np

from l5.estimation import (estimate, measurement_update, model_config, observability,
                           score, transition, transition_jacobian)
from l5.estimation_workspace import simulation_observations
from l5.models.tanks import CoupledTankModel, integrate
from l5.workspace import WorkspaceStore
from test_incidents import IncidentHTTPFixture


class EstimationMathTests(unittest.TestCase):
    def test_correlated_measurement_update_matches_information_form(self):
        x = np.array([1.1, .8]); p = np.array([[.4, .12], [.12, .3]])
        r = np.array([[.02, .007], [.007, .03]]); z = np.array([1.5, 1.])
        updated, covariance, innovation, s, nis = measurement_update(x, p, z, [0, 1], r)
        expected_p = np.linalg.inv(np.linalg.inv(p)+np.linalg.inv(r))
        expected_x = expected_p@(np.linalg.solve(p, x)+np.linalg.solve(r, z))
        np.testing.assert_allclose(updated, expected_x, rtol=1e-13)
        np.testing.assert_allclose(covariance, expected_p, atol=1e-15)
        np.testing.assert_allclose(innovation, z-x)
        self.assertAlmostEqual(nis, float((z-x)@np.linalg.inv(p+r)@(z-x)))
        np.testing.assert_allclose(s, p+r)

    def test_masked_scalar_update_matches_hand_calculation(self):
        x = np.array([1., .5]); p = np.array([[.25, .1], [.1, .16]])
        updated, covariance, innovation, s, nis = measurement_update(x, p, [1.2], [0], np.diag([.04, .09]))
        gain = np.array([.25, .1])/.29
        np.testing.assert_allclose(updated, x+gain*.2)
        np.testing.assert_allclose(covariance, p-np.outer(p[:, 0], p[0])/.29)
        self.assertAlmostEqual(nis, .2**2/.29)

    def test_discrete_jacobian_against_independent_analytic_ssprk_chain_rule(self):
        c = model_config()
        def drift(x):
            transfer = .04*np.sign(x[0]-x[1])*np.sqrt(abs(x[0]-x[1]))
            return np.array([.03-transfer, transfer-.03*np.sqrt(x[1])])
        def jacobian(x):
            k = .02/np.sqrt(abs(x[0]-x[1])); d = .015/np.sqrt(x[1])
            return np.array([[-k, k], [k, -k-d]])
        for x in (np.array([1.7, .8]), np.array([.4, 1.2])):
            dt = .1; euler = x+dt*drift(x)
            expected = .5*(x+euler+dt*drift(euler))
            expected_j = .5*(np.eye(2)+(np.eye(2)+dt*jacobian(euler))@(np.eye(2)+dt*jacobian(x)))
            np.testing.assert_allclose(transition(c, x, dt), expected, atol=1e-15)
            for epsilon in (1e-5, 2e-6):
                np.testing.assert_allclose(transition_jacobian(c, x, dt, epsilon), expected_j, rtol=1e-7, atol=1e-9)

    def test_prediction_q_scaling_missing_and_irregular_clock(self):
        observations = [dict(t=t, level1=None) for t in (0., .13, .71, 1.17)]
        result = estimate(observations, model={'valve':0}, config=dict(initialState=[1., .8],
            initialCovariance=[[.2,0],[0,.1]], processCovariance=[[.003,0],[0,.001]], maxStep=.05))
        for row in result['rows']:
            self.assertAlmostEqual(row['estimate'][0], 1+.03*row['t'], places=12)
            self.assertAlmostEqual(row['covariance'][0][0], .2+.003*row['t'], places=10)
            self.assertEqual(row['estimate'], row['openLoop'])
            self.assertIsNone(row['nis'])
            self.assertEqual(row['innovation'], [None, None])
            self.assertEqual(row['direct'], [None, None])
        self.assertEqual(result['predictionOnly'], 4)

    def test_control_hold_splits_between_observations_and_never_backfills(self):
        obs = [dict(t=t) for t in (0., .1, .6, 1.)]
        controls = [dict(t=.25, pumpControl=0), dict(t=.75, pumpControl=150)]
        result = estimate(obs, controls, model={'valve':0}, config={'initialState':[1.,1.]})
        self.assertAlmostEqual(result['rows'][2]['estimate'][0], 1+.03*.25, places=12)
        self.assertAlmostEqual(result['rows'][-1]['estimate'][0], 1+.03*.25+.045*.25, places=12)
        self.assertAlmostEqual(result['rows'][1]['estimate'][0], 1.003, places=12)

    def test_no_future_observation_or_control_leakage_and_no_truth_interface(self):
        a = [dict(t=0.,level2=1.),dict(t=.37,level2=.99),dict(t=1.,level2=.98)]
        b = [*a[:2],dict(t=1.,level2=900.)]
        first = estimate(a, [dict(t=.5,pumpControl=150)])
        second = estimate(b, [dict(t=.5,pumpControl=0)])
        self.assertEqual(first['rows'][:2], second['rows'][:2])
        self.assertEqual(first['rows'][:2], estimate(a[:2])['rows'])
        with self.assertRaises(ValueError):
            estimate([dict(t=0,level1=1,truth=[1,1])])

    def test_covariance_psd_and_finite_dry_equal_reverse_flow_boundaries(self):
        for initial in ([0.,0.],[1.,1.],[0.,1.],[3.,.01]):
            result = estimate([dict(t=t,level2=.01 if i%3 else None) for i,t in enumerate(np.linspace(0,3,31).tolist())],
                              config={'initialState':initial})
            for row in result['rows']:
                p = np.asarray(row['covariance'])
                np.testing.assert_allclose(p,p.T,atol=1e-14)
                self.assertGreaterEqual(np.linalg.eigvalsh(p)[0],-1e-13)
                self.assertTrue(np.isfinite(p).all())
                self.assertTrue(all(v>=0 for v in row['estimate']))
        self.assertIn('nonsmooth-flow', estimate([dict(t=1.)],config={'initialState':[0,0]})['warnings'])

    def test_observability_analytic_matrix_rank_and_nonsmooth_rejection(self):
        expected = np.array([[-.04/1.5,.04/1.5],[.04/1.5,-.04/1.5-.015]])
        for sensor in ('level1','level2'):
            result = observability(sensors=[sensor])
            np.testing.assert_allclose(result['A'], expected)
            h = np.eye(2)[[0 if sensor=='level1' else 1]]
            np.testing.assert_allclose(result['matrix'],np.vstack([h,h@expected]))
            self.assertEqual(result['rank'],2)
            self.assertEqual(observability({'valve':0}, sensors=[sensor])['rank'],1)
            self.assertTrue(observability({'valve':.000001},sensors=[sensor])['poorlyObservable'])
        self.assertEqual(observability({'valve':0})['rank'],2)
        self.assertEqual(observability({'valve':0},point=[1,1],sensors=['level1'])['rank'],1)
        self.assertEqual(observability(sensors=[])['rank'],0)
        self.assertIsNone(observability(point=[1,1])['rank'])
        self.assertIsNone(observability(point=[1,0])['A'])

    def test_partial_observation_reconstruction_and_reproducibility(self):
        source = dict(simulation=dict(duration=240,step=1,noise=0,seed=12,initial1=1.8,initial2=.8),
                      noise=[.01,.01],every=[1,1],dropout=.15,irregular=True)
        obs, controls, truth, _ = simulation_observations(source)
        self.assertEqual((obs,controls,truth),simulation_observations(source)[:3])
        cfg = dict(initialState=[.7,1.5],measurementCovariance=[[.0001,0],[0,.0001]])
        result = estimate(obs,controls,config=cfg,sensors=['level2'])
        self.assertEqual(result,estimate(obs,controls,config=cfg,sensors=['level2']))
        metrics = score(result,truth)
        self.assertLess(metrics['finalAbsoluteError'][0],.025)
        self.assertLess(metrics['methods']['estimate'][0]['rmse'],metrics['methods']['openLoop'][0]['rmse']*.8)
        self.assertTrue(all(row['observed'][0] is None for row in result['rows']))
        self.assertTrue(all(row['direct'][0] is None for row in result['rows']))

    def test_noise_consistency_with_independent_gaussian_prior_ensemble(self):
        # Independent one-update trials, avoiding time-correlated pseudo-replication.
        rng = np.random.default_rng(107)
        p = np.diag([.04,.09]); r = np.diag([.0004,.0009]); nis=[]; nees=[]; covered=[]
        for _ in range(1200):
            truth = rng.multivariate_normal([1.5,1.],p)
            z = truth+rng.multivariate_normal([0,0],r)
            x,cov,_,_,n = measurement_update(np.array([1.5,1.]),p,z,[0,1],r)
            error=x-truth;nis.append(n);nees.append(error@np.linalg.solve(cov,error))
            covered.append(np.abs(error)<=1.96*np.sqrt(np.diag(cov)))
        self.assertLess(abs(np.mean(nis)-2),.16)
        self.assertLess(abs(np.mean(nees)-2),.16)
        self.assertTrue(np.all(np.abs(np.mean(covered,axis=0)-.95)<.025))

    def test_invalid_covariance_times_controls_and_work_budget_rejected(self):
        for cfg in ({'measurementCovariance':[[1,2],[2,1]]},{'processCovariance':[[1,0],[1,1]]},
                    {'measurementCovariance':[[0,0],[0,0]]},{'initialState':[-1,0]}, {'maxStep':0}):
            with self.subTest(cfg=cfg), self.assertRaises(ValueError):
                estimate([dict(t=0)],config=cfg)
        for obs in ([dict(t=1),dict(t=1)],[dict(t=-1)],[dict(t=1,level1=float('nan'))],[dict(t=20000)]):
            with self.assertRaises(ValueError):estimate(obs)
        with self.assertRaises(ValueError):estimate([dict(t=1)],[dict(t=.5,valve=2)])

    def test_simulator_refactor_preserves_independent_mass_balance(self):
        config=CoupledTankModel().validate(dict(duration=20,start=4,initial1=.01,initial2=3,area1=.1,area2=.1))
        _, truth=integrate(config)
        self.assertLess(max(abs(r['massResidual']) for r in truth),1e-10)

    def test_initial_time_retains_only_past_control_holds(self):
        result=estimate([dict(t=2.5)], [dict(t=0.,pumpControl=0),dict(t=3.,pumpControl=150)],
            model={'valve':0},config={'initialTime':2.,'initialState':[1.,1.]})
        self.assertAlmostEqual(result['rows'][0]['estimate'][0],1.,places=12)


class EstimationHTTPTests(IncidentHTTPFixture):
    def test_saved_scenario_estimation_restart_export_and_existing_signal_workflow(self):
        ws=self.request('/workspaces',{'name':'Estimation'},expected=201)['id']
        scenario=self.request(f'/workspaces/{ws}/scenarios',dict(name='Pump loss',modelId='coupled-tanks',
            config=dict(duration=12,start=4,step=.5,fault='pump_degradation',seed=23,pumpRate=.045,area1=.8,initial1=2.)),expected=201)
        request=dict(source=dict(kind='scenario',scenarioId=scenario['id'],noise=[.02,.03],every=[1,3],dropout=.3,irregular=True),
                     sensors=['level2'],compareSensors=True)
        run=self.request(f'/workspaces/{ws}/estimations',request,expected=201)
        self.assertEqual(run['request']['model']['pumpRate'],.03)
        self.assertEqual(run['request']['model']['area1'],1.)
        self.assertEqual(run['result']['config']['initialState'],[1.2,.7])
        self.assertNotIn('fault',run['request']['model'])
        self.assertNotIn('truth',run['inputs'])
        self.assertEqual(len(run['comparisons']),4)
        frozen=run['inputs']
        self.request('/scenarios/'+scenario['id'],dict(config=dict(duration=12,start=4,pumpRate=.09)),method='PATCH')
        self.stop();self.start()
        reopened=self.request('/estimations/'+run['id'])
        self.assertEqual(reopened,run)
        self.assertEqual(reopened['inputs'],frozen)
        exported=self.request('/estimations/'+run['id']+'/dataset',{},expected=201)
        self.assertEqual(exported['metadata']['estimation']['runId'],run['id'])
        series=self.request('/datasets/'+exported['id']+'/series?signal=level1_estimate')
        self.assertEqual(series['values']['level1_estimate'],[r['estimate'][0] for r in run['result']['rows']])
        source=self.request('/datasets/'+exported['id'])
        self.assertEqual(source['metadata']['columns'][0]['unit'],'m')
        self.assertEqual(self.request(f'/workspaces/{ws}/estimations')['runs'][0]['id'],run['id'])
        self.assertTrue(self.request(f'/workspaces/{ws}/signals')['signals'])

    def test_dataset_masked_measurements_control_mapping_no_truth_and_workspace_validation(self):
        ws=self.request('/workspaces',{'name':'CSV estimation'},expected=201)['id']
        dataset=self.request(f'/workspaces/{ws}/datasets',dict(csv='time,lt2,pump\n0,1,100\n0.3,,\n0.7,0.99,0\n1.4,0.98,\n',timeColumn='time'),expected=201)
        body=dict(source=dict(kind='dataset',datasetId=dataset['id'],mapping=dict(level2='lt2',pumpControl='pump')),
                  sensors=['level2'])
        run=self.request(f'/workspaces/{ws}/estimations',body,expected=201)
        self.assertIsNone(run['score'])
        self.assertEqual(run['result']['rows'][1]['dof'],0)
        self.assertEqual(run['inputs']['controls'],[dict(t=0.,pumpControl=100.),dict(t=.7,pumpControl=0.)])
        other=self.request('/workspaces',{'name':'Other'},expected=201)['id']
        self.request(f'/workspaces/{other}/estimations',body,expected=400)
        analysis=self.request(f'/workspaces/{ws}/estimations/observability',dict(model={'valve':0},sensors=['level1']),expected=200)
        self.assertEqual(analysis['rank'],1)

    def test_exported_estimates_cannot_be_assimilated_as_independent_sensors(self):
        with TemporaryDirectory() as tmp:
            store=WorkspaceStore(Path(tmp));ws=store.create_workspace('Derived estimates')['id']
            run=store.estimations.create(ws,dict(source=dict(kind='simulation',simulation={'duration':2,'step':.5})))
            dataset=store.estimations.export(run['id'],{})
            again=store.estimations.create(ws,dict(source=dict(kind='dataset',datasetId=dataset['id'],mapping={'level1':'level1_estimate'})))
            self.assertTrue(all(r['dof']==0 for r in again['result']['rows']))

    def test_export_uses_existing_processed_analysis_and_experiment_workflows(self):
        store=self.service.workspace_store;ws=store.create_workspace('Downstream estimates')['id']
        run=store.estimations.create(ws,dict(source=dict(kind='simulation',simulation=dict(duration=120,step=.5))))
        dataset=store.estimations.export(run['id'],{})
        config=dict(datasetId=dataset['id'],signals=['level1_estimate'],algorithm='robust-maxz',alpha=.05,
                    baselineRange=[0,80],analysisRange=[80.5,120],observationPolicy='processed')
        result=store.analyze(ws,config)
        self.assertEqual(result['config']['observationPolicy'],'processed')
        self.assertGreater(result['summary']['analysisSamples'],0)
        self.assertEqual(store.result(result['id'])['datasetId'],dataset['id'])
        with self.assertRaises(ValueError):
            store.analyze(ws,{**config,'observationPolicy':'measured'})
        from test_experiments import finish
        experiment=store.experiments.save(ws,dict(name='Estimated-state experiment',config={
            **config,'algorithms':[{'algorithm':'robust-maxz'}]}))
        execution=store.experiments.execute(experiment['id'],{})
        finished=finish(store.experiments,execution['id'])
        self.assertEqual(finished['status'],'completed')
        self.assertEqual(finished['tasks'][0]['status'],'succeeded',finished['tasks'][0]['error'])
        self.assertEqual(finished['snapshot']['dataset']['metadata']['estimation']['runId'],run['id'])


if __name__ == '__main__':
    unittest.main()
