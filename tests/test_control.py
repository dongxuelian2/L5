"""Numerical contracts and end-to-end saved closed-loop experiments."""
from copy import deepcopy
import unittest
from unittest.mock import patch
from urllib.request import build_opener, ProxyHandler

import numpy as np

from l5.control import compare, validate_protocol, PI_DEFAULTS, MPC_DEFAULTS
from l5.controllers import local_dynamics, NOMINAL_KEYS, PIController
from l5.control_solver import solve_qp
from l5.models.tanks import CoupledTankModel, flows, integrate
from l5.control_reports import render_control_report
from test_incidents import IncidentHTTPFixture
from test_experiments import finish


def inputs(changes=None, protocol=None):
    c=CoupledTankModel().validate(dict(duration=80,noise=.002,start=30,seed=197)| (changes or {}))
    return c,validate_protocol(protocol or {},c)


def reproducible(result):
    r=deepcopy(result)
    for b in r['results']:
        for d in b['decisions']: d.pop('durationMs')
        for k in ('meanSolveMs','maxSolveMs'): b['metrics'].pop(k)
    return r


class ControlNumericsTests(unittest.TestCase):
    def test_qp_matches_analytic_optimum_and_active_bounds(self):
        h=np.diag([2.,4.]); g=np.array([-6.,8.]); a=np.array([[1.,0.],[0.,1.],[1.,1.]])
        solution=solve_qp(h,g,a,[0.,-1.,-np.inf],[2.,3.,1.],iterations=5000,tolerance=1e-7)
        self.assertEqual(solution['status'],'solved')
        np.testing.assert_allclose(solution['x'],[2.,-1.],atol=2e-7)
        self.assertLess(solution['stationarityResidual'],1e-7)
        interior=solve_qp(h,g,np.eye(2),[-10,-10],[10,10],tolerance=1e-7)
        np.testing.assert_allclose(interior['x'],[3,-2],atol=1e-7)

    def test_affine_prediction_matches_equilibrium_and_nonlinear_short_step(self):
        c,p=inputs(dict(noise=0,duration=2,start=1))
        nominal={k:c[k] for k in NOMINAL_KEYS}; x=np.array([1.5625,1.]); u=np.array([1.,1.])
        ad,bd,cd=local_dynamics(nominal,x,u,2.)
        np.testing.assert_allclose(ad@x+bd@u+cd,x,atol=1e-12)
        # Independent finite differences of the actual unregularized plant field.
        def derivative(state,command):
            f=flows(c,state,0,commands=dict(pump=command[0]*100,valve=command[1]))[0]
            return np.array([(f[0]-f[1]-f[3]-f[4])/c['area1'],(f[1]-f[2]-f[5])/c['area2']])
        eps=1e-6
        jac=np.column_stack([(derivative(x+np.eye(2)[j]*eps,u)-derivative(x-np.eye(2)[j]*eps,u))/(2*eps) for j in range(2)])
        tiny=1e-5
        at,_,_=local_dynamics(nominal,x,u,tiny)
        np.testing.assert_allclose((at-np.eye(2))/tiny,jac,atol=1e-7)
        changed=u+np.array([.05,-.02])
        rows,physical=integrate({**c,'pumpControl':changed[0]*100,'valve':changed[1]})
        predicted=ad@x+bd@changed+cd
        np.testing.assert_allclose(predicted,[physical[-1]['level1'],physical[-1]['level2']],atol=2e-5)

    def test_seed_reproducibility_and_common_noise_for_every_controller(self):
        c,p=inputs(protocol=dict(reference=[dict(time=0,level=1),dict(time=40.3,level=1.2)]))
        r=compare(c,p); repeated=compare(c,p)
        self.assertEqual(reproducible(r),reproducible(repeated))
        first=r['results'][0]
        for b in r['results'][1:]:
            self.assertEqual([x['t'] for x in b['rows']],[x['t'] for x in first['rows']])
            for key in ('level1','level2'):
                noise=np.array([row[key]-truth[key] for row,truth in zip(b['rows'],b['physical'])])
                expected=np.array([row[key]-truth[key] for row,truth in zip(first['rows'],first['physical'])])
                np.testing.assert_allclose(noise,expected,atol=5e-16)

    def test_feedback_is_chronological_and_uses_only_current_measurements(self):
        c,p=inputs(dict(noise=0,duration=8,start=4))
        observed=[]
        def feedback(row):
            self.assertEqual(set(row),{'t','level1','level2','inlet','transfer','outlet','pump','valve'})
            observed.append(row)
            return dict(pump=0. if row['t']==0 else 120.,valve=.8)
        rows,truth=integrate(c,feedback=feedback,control_interval=1.3)
        self.assertEqual([r['t'] for r in observed],[0,1.3,2.6,3.9,5.2,6.5,7.8])
        self.assertEqual(observed[0]['inlet'],.03)  # prior input measured before actuation
        self.assertEqual(observed[1]['inlet'],0)
        self.assertEqual(observed[2]['inlet'],.036)
        self.assertEqual(rows[0]['pump'],0)
        self.assertLess(max(abs(t['massResidual']) for t in truth),1e-10)

    def test_future_fault_disturbance_and_reference_information_do_not_leak(self):
        for kind in ('pi','mpc'):
            controller={'kind':kind,**({'preview':False} if kind=='mpc' else {})}
            c,p=inputs(dict(duration=60),dict(controllers=[controller],reference=[dict(time=0,level=1)]))
            future=deepcopy(p);future['disturbances']=[dict(start=40,end=55,inletFactor=.2,outletFactor=1.)]
            future['reference'].append(dict(time=45,level=1.4))
            a=compare(c,p)['results'][0]
            b=compare({**c,'fault':'tank_leak','start':40},future)['results'][0]
            self.assertEqual([r for r in a['rows'] if r['t']<40],[r for r in b['rows'] if r['t']<40])
            for da,db in zip(a['decisions'],b['decisions']):
                if da['time']>=40: break
                self.assertEqual({k:v for k,v in da.items() if k!='durationMs'},{k:v for k,v in db.items() if k!='durationMs'})

    def test_conservation_nonnegative_heads_and_hard_actuator_rate_limits(self):
        for changes in [dict(initial1=0,initial2=0,pumpControl=0),dict(initial1=.01,initial2=3),
                        dict(fault='tank_leak',initial1=3.5,initial2=2.8,tankHeight=1.5),dict(fault='valve_restriction')]:
            c,p=inputs(dict(duration=25,start=10,noise=0)|changes,dict(sampleInterval=1.3,
                constraints=dict(pumpRate=2.,valveRate=.02),controllers=[dict(kind='pi',actuateValve=True),dict(kind='mpc',actuateValve=True)]))
            for b in compare(c,p)['results']:
                self.assertTrue(all(min(r['level1'],r['level2'])>=0 for r in b['physical']))
                self.assertLess(b['metrics']['maxMassResidual'],1e-10)
                self.assertEqual(b['metrics']['actuatorViolations'],0)
                self.assertEqual(b['metrics']['rateViolations'],0)

    def test_pi_antiwindup_recovers_from_unreachable_reference_and_rate_saturation(self):
        c,p=inputs(protocol=dict(constraints=dict(pumpMax=110,pumpRate=1)))
        controller=PIController({k:c[k] for k in NOMINAL_KEYS},PI_DEFAULTS,p['constraints'],[1,1])
        for t in range(200):
            _,info=controller.step(dict(t=t,level2=.5),[dict(time=0,level=8)],1)
        self.assertEqual(controller.integral,0.)
        self.assertTrue(info['saturated'])
        command,_=controller.step(dict(t=201,level2=1.5),[dict(time=0,level=1)],1)
        self.assertLess(command[0],1.1)
        self.assertGreaterEqual(command[0],1.09-1e-10) # rate-limited recovery, not windup

    def test_mpc_reoptimizes_first_move_and_handles_iteration_and_numerical_failure(self):
        c,p=inputs(dict(duration=20,start=10),dict(controllers=[dict(kind='mpc')],reference=[dict(time=0,level=1.2)]))
        b=compare(c,p)['results'][0]
        solved=[d for d in b['decisions'] if d['solver']['status']=='solved']
        self.assertTrue(solved)
        for d in solved:
            self.assertEqual(len(d['solver']['prediction']),25)
            self.assertAlmostEqual(d['command']['pump']/100,d['solver']['plan'][0][0],delta=2e-5)
        self.assertNotEqual(b['decisions'][0]['command'],b['decisions'][-1]['command'])
        for fault in ('iterations','numerical'):
            short=deepcopy(p);short['controllers'][0]['maxIterations']=1
            context=patch('l5.controllers.solve_qp',side_effect=np.linalg.LinAlgError('test')) if fault=='numerical' else patch('l5.controllers.solve_qp',wraps=solve_qp)
            with context:
                failed=compare(c,short)['results'][0]
            self.assertEqual(failed['metrics']['solverFailures'],len(failed['decisions']))
            self.assertEqual(failed['metrics']['infeasibleSteps'],0)
            self.assertEqual(failed['metrics']['actuatorViolations'],0)
            self.assertTrue(all(d['solver']['fallback'] for d in failed['decisions']))

    def test_off_clock_reference_metrics_and_unsettled_behavior(self):
        c,p=inputs(dict(duration=10,start=5,noise=0),dict(controllers=[dict(kind='open-loop')],reference=[dict(time=0,level=1),dict(time=3.17,level=1.2)]))
        b=compare(c,p)['results'][0]
        self.assertIn(3.17,[r['t'] for r in b['rows']])
        self.assertAlmostEqual(b['metrics']['iae'],(10-3.17)*.2,places=10)
        self.assertIsNone(b['metrics']['settlingTime'])

    def test_protocol_rejects_invalid_and_excessive_work(self):
        c,_=inputs()
        for raw in [dict(sampleInterval=True),dict(sampleInterval=0),dict(reference=[dict(time=1,level=1)]),
                    dict(reference=[dict(time=0,level=1),dict(time=0,level=2)]),dict(constraints=dict(pumpMax=90)),
                    dict(controllers=[dict(kind='mpc',predictionHorizon=2,controlHorizon=3)]),
                    dict(controllers=[dict(kind='mpc',preview=1)]),dict(controllers=[dict(kind='pid')]),
                    dict(controllers=[dict(kind='pi'),dict(kind='pi')]),dict(unknown=2),
                    dict(disturbances=[dict(start=2,end=1)])]:
            with self.subTest(raw=raw),self.assertRaises(ValueError):validate_protocol(raw,c)

    def test_fixed_and_zero_slew_actuators_remain_feasible_for_mpc(self):
        c,p=inputs(dict(duration=8,start=4,noise=0),dict(controllers=[dict(kind='mpc')],
            constraints=dict(pumpRate=0,valveRate=0),reference=[dict(time=0,level=1.2)]))
        branch=compare(c,p)['results'][0]
        self.assertEqual(branch['metrics']['solverFailures'],0)
        self.assertTrue(all(d['command']==dict(pump=100.,valve=1.) for d in branch['decisions']))

    def test_fixed_controller_benchmark_improves_iae_without_universal_claim(self):
        c,p=inputs(dict(duration=120,noise=0),dict(reference=[dict(time=0,level=1),dict(time=30,level=1.2)]))
        r=compare(c,p);pi,mpc=r['results'][1:]
        self.assertLess(mpc['metrics']['iae'],pi['metrics']['iae']*.7)
        self.assertEqual(mpc['metrics']['solverFailures'],0)
        self.assertGreater(mpc['metrics']['pumpVariation'],pi['metrics']['pumpVariation'])
        # Both controllers retain their fixed defaults; final evaluation cases
        # never select gains. Preview changes this objective and is disclosed.
        self.assertEqual(pi['settings'],PI_DEFAULTS)


class ControlHTTPTests(IncidentHTTPFixture):
    def test_saved_comparison_dataset_incident_report_and_restart(self):
        wid=self.workspace('Control evidence'); base=f'/workspaces/{wid}/control'
        scenario=self.request(f'/workspaces/{wid}/scenarios',dict(modelId='coupled-tanks',name='Leak',config=dict(duration=40,start=20,fault='tank_leak')),expected=201)
        result=self.request(base,dict(name='<Control & evidence>',scenarioId=scenario['id'],scenarioVersion=1,
            protocol=dict(controllers=[dict(kind='pi'),dict(kind='mpc')],reference=[dict(time=0,level=1)])),expected=201)
        self.assertEqual(result['scenarioSnapshot'],scenario)
        self.assertEqual(len(self.request(base)['experiments']),1)
        dataset=self.request(f'{base}/{result["id"]}/dataset',dict(controller='mpc'),expected=201)
        repeated=self.request(f'{base}/{result["id"]}/dataset',dict(controller='mpc'),expected=201)
        self.assertEqual(dataset['id'],repeated['id'])
        self.assertEqual(dataset['metadata']['model']['control']['experimentId'],result['id'])
        session=self.request('/simulations/'+dataset['metadata']['model']['simulationId'])
        self.assertEqual(session['rows'],result['results'][1]['rows'])
        self.assertNotIn('interventions',session['modelDescriptor']['capabilities'])
        self.request('/simulations/'+session['id']+'/interventions',dict(asOf=20,actions=['adjust_pump']),expected=400)
        self.assertEqual(dataset['metadata']['columns'][-1]['name'],'error')
        incident=self.request(f'/workspaces/{wid}/incidents',dict(title='Control test',source=dict(kind='dataset',datasetId=dataset['id'])),expected=201)
        self.assertEqual(incident['links'][0]['reference_id'],dataset['id'])
        experiment=self.request(f'/workspaces/{wid}/experiments',dict(name='Control detection',config=dict(datasetId=dataset['id'],signals=['level1','level2'],baselineRange=[0,19.8],analysisRange=[20,40],algorithms=[dict(algorithm='robust-maxz')])),expected=201)
        execution=self.request('/experiments/'+experiment['id']+'/runs',{},expected=202)
        completed=finish(self.service.workspace_store.experiments,execution['id'])
        self.assertEqual(completed['tasks'][0]['status'],'succeeded')
        report=render_control_report(self.service.workspace_store.control.get(wid,result['id']),locale='en')
        self.assertIn('&lt;Control &amp; evidence&gt;',report)
        self.assertIn('Primal residual',report)
        self.assertIn('<svg',report)
        self.assertNotIn('src="http',report)
        chinese=render_control_report(self.service.workspace_store.control.get(wid,result['id']),locale='zh-CN')
        self.assertIn('闭环控制比较',chinese)
        for suffix,content_type in [('report.html?lang=zh-CN','text/html'),('results.csv?download=1','text/csv')]:
            with build_opener(ProxyHandler({})).open(f'http://127.0.0.1:{self.service.server_port}/api{base}/{result["id"]}/{suffix}') as exported:
                self.assertIn(content_type,exported.headers['Content-Type'])
                payload=exported.read().decode('utf-8')
                self.assertIn('闭环控制比较' if suffix.startswith('report') else 'physicalLevel1',payload)
        self.stop();self.start()
        reopened=self.request(f'{base}/{result["id"]}')
        self.assertEqual(reopened['results'],result['results'])
        self.assertEqual(reopened['datasets']['mpc'],dataset['id'])
        other=self.workspace('Other')
        self.request('/simulations/'+session['id']+'/save',dict(workspaceId=other),expected=400)
        self.request(f'/workspaces/{other}/control/{result["id"]}',expected=404)
        self.request(base,dict(scenarioId=scenario['id'],config={}),expected=400)
