"""Physical invariants and the same saved research lifecycle for both models."""
import hashlib
import json
from pathlib import Path
import unittest

import numpy as np
from l5.analysis import ALGORITHMS

from l5.models import MODELS, catalog, resolve
from l5.models.tanks import integrate
from l5.reports import render_report
from l5.experiment_reports import render_experiment_report
from l5.workspace import WorkspaceStore
from test_incidents import IncidentHTTPFixture
from test_experiments import finish


class TankPhysicsTests(unittest.TestCase):
    def setUp(self):
        self.model=resolve('coupled-tanks')

    def test_equilibrium_mass_conservation_and_positive_dry_reverse_overflow_cases(self):
        config=self.model.validate(dict(noise=0,duration=120))
        _,physical=integrate(config)
        self.assertTrue(all(p['level1']==1.5625 and p['level2']==1 for p in physical))
        for changes in [dict(initial1=0,initial2=0,pumpRate=0),dict(initial1=.01,initial2=3),
                        dict(initial1=4,initial2=3,tankHeight=1),dict(fault='tank_leak',severity=1),
                        dict(area1=.1,area2=.1,initial1=.001,initial2=.001,connection=.2,outlet=.2,integrationStep=.25)]:
            with self.subTest(changes=changes):
                _,physical=integrate(self.model.validate({**config,**changes}))
                self.assertLess(max(abs(p['massResidual']) for p in physical),1e-9)
                self.assertTrue(all(p['level1']>=0 and p['level2']>=0 for p in physical))

    def test_step_convergence_seed_and_measurement_separation(self):
        config=self.model.validate(dict(fault='tank_leak',duration=120,noise=.004,seed=47))
        rows,physical=integrate(config)
        self.assertEqual(rows,integrate(config)[0])
        changed,other_physical=integrate({**config,'seed':48})
        self.assertNotEqual(rows,changed)
        self.assertEqual(physical,other_physical)
        fine=integrate({**config,'integrationStep':.025})[1]
        coarser=integrate({**config,'integrationStep':.1,'step':.4})[1]
        self.assertLess(max(abs(a['level2']-b['level2']) for a,b in zip(physical,fine)),2e-6)
        self.assertLess(max(abs(a['level2']-b['level2']) for a,b in zip(physical[::2],coarser)),1e-5)

    def test_fault_response_directions_and_bias_does_not_change_physics(self):
        config=self.model.validate(dict(noise=0,duration=180))
        healthy,physical=integrate(config)
        pump=integrate({**config,'fault':'pump_degradation'})[0]
        valve=integrate({**config,'fault':'valve_restriction'})[0]
        leak=integrate({**config,'fault':'tank_leak'})[0]
        biased,biased_physical=integrate({**config,'fault':'sensor_bias'})
        self.assertLess(pump[-1]['level2'],healthy[-1]['level2'])
        self.assertGreater(valve[-1]['level1'],healthy[-1]['level1'])
        self.assertLess(valve[-1]['level2'],healthy[-1]['level2'])
        self.assertLess(leak[-1]['level1'],healthy[-1]['level1'])
        self.assertEqual(physical,biased_physical)
        self.assertAlmostEqual(biased[-1]['level2']-healthy[-1]['level2'],config['sensorBias']*config['severity'])

    def test_interventions_have_causal_prefix_real_parameter_response_and_metrics(self):
        config=self.model.validate(dict(fault='pump_degradation',duration=180,noise=0))
        rows=self.model.simulate(config)
        body=dict(at=83.17,horizon=180,actions=['adjust_pump','backup_pump','stop_supply'],parameters={'pumpControl':105})
        result=self.model.intervene({'config':config},rows[:401],body)
        base=result['baseline']
        for branch in result['branches']:
            cutoff=next(i for i,t in enumerate(branch['times']) if t>=83.17)
            self.assertEqual(branch['times'][cutoff],83.17)
            for key in base['values']:
                self.assertEqual(base['values'][key][:cutoff+1],branch['values'][key][:cutoff+1])
        self.assertLess(result['branches'][1]['metrics']['levelDeviation'],base['metrics']['levelDeviation'])
        stronger=self.model.intervene({'config':config},rows[:401],{**body,'parameters':{'pumpControl':150}})
        self.assertNotEqual(result['branches'][0]['values'],stronger['branches'][0]['values'])
        self.assertNotEqual(base['values'],result['branches'][2]['values'])
        with self.assertRaises(ValueError):
            self.model.intervene({'config':config},rows[:401],{**body,'mode':'observed'})

    def test_model_descriptors_are_independent_and_validation_is_bounded(self):
        models=catalog()
        self.assertEqual([len(m['signals']) for m in models],[18,7])
        self.assertNotIn('diagnosis',models[1]['capabilities'])
        for config in [dict(seed=True),dict(integrationStep=.0001),dict(area1=0),dict(unknown=1),dict(duration=100000,step=.02),dict(fault='cooling_valve')]:
            with self.subTest(config=config),self.assertRaises(ValueError):
                self.model.validate(config)
        with self.assertRaises(ValueError):
            resolve('unregistered')


class ModelWorkspaceHTTPTests(IncidentHTTPFixture):
    def test_unadvertised_optional_operations_need_no_model_implementation(self):
        tank=resolve('coupled-tanks')
        class ObservationOnly:
            id='observation-only-tank-test'
            version='1.0.0'
            validate=staticmethod(tank.validate)
            simulate=staticmethod(tank.simulate)
            observe=staticmethod(tank.observe)
            def describe(self):
                return {**tank.describe(),'modelId':self.id,'capabilities':['simulation','observation'],'tools':[], 'actions':[]}
        model=ObservationOnly();MODELS[model.id]=model
        try:
            wid=self.workspace('Optional capabilities')
            session=self.request('/simulations',dict(workspaceId=wid,modelId=model.id,config=dict(duration=10,start=5)),expected=201)
            self.assertIsNone(session['groundTruth'])
            sid=session['id']
            self.request(f'/simulations/{sid}/analysis',dict(asOf=8))
            self.request(f'/simulations/{sid}/tools',dict(asOf=8,calls=[dict(tool='flow_balance')]),expected=400)
            self.request(f'/simulations/{sid}/interventions',dict(asOf=8),expected=400)
            dataset=self.request(f'/simulations/{sid}/save',{})
            self.request(f"/datasets/{dataset['id']}/labels/simulation",{},expected=400)
        finally:
            del MODELS[model.id]

    def test_scenario_versions_copy_repeat_and_restart_preserve_original_run(self):
        wid=self.workspace('Model scenarios')
        self.assertEqual(len(self.request('/models')['models']),2)
        scenario=self.request(f'/workspaces/{wid}/scenarios',dict(modelId='coupled-tanks',name='Pump fault',config=dict(fault='pump_degradation',duration=120)),expected=201)
        path=f"/scenarios/{scenario['id']}"
        first=self.request(path+'/run',dict(scenarioVersion=1),expected=201)
        second=self.request(path+'/run',dict(scenarioVersion=1),expected=201)
        self.assertEqual(first['rows'],second['rows'])
        folder=self.folder/'simulations'/first['id']/'session.json'
        digest=hashlib.sha256(folder.read_bytes()).hexdigest()
        updated=self.request(path,dict(name='Stronger fault',config={**scenario['config'],'severity':.9},expectedVersion=1),method='PATCH')
        self.assertEqual(updated['version'],2)
        self.request(path,dict(expectedVersion=1),method='PATCH',expected=400)
        self.request(path+'/run',dict(config=dict(severity=1)),expected=400)
        self.request(path+'/run',dict(workspaceId=self.workspace('Other')),expected=400)
        copied=self.request(path+'/copy',dict(version=1),expected=201)
        self.assertNotEqual(copied['id'],scenario['id'])
        self.assertEqual(copied['config'],scenario['config'])
        third=self.request(path+'/run',dict(scenarioVersion=2),expected=201)
        self.assertNotEqual(first['rows'],third['rows'])
        self.stop();self.start()
        self.assertEqual(hashlib.sha256(folder.read_bytes()).hexdigest(),digest)
        recovered=self.request('/simulations/'+first['id'])
        self.assertEqual(recovered['scenarioSnapshot'],scenario)
        self.assertEqual(recovered['rows'],first['rows'])
        self.assertEqual(len(self.request(path+'/versions')['versions']),2)
        self.assertEqual(self.request(path+'?version=1'),scenario)

    def test_two_models_share_datasets_experiments_incidents_reports_and_restart(self):
        wid=self.workspace('Two models')
        records=[]
        for model,config,signals in [('triplens-synthetic-18-v2',dict(fault='pump_loss',start=40.37,duration=150,step=.2),['flow','pressure','pump']),
                                     ('coupled-tanks',dict(fault='pump_degradation',start=40.37,duration=150),['level1','level2','outlet'])]:
            scenario=self.request(f'/workspaces/{wid}/scenarios',dict(modelId=model,name=model,config=config),expected=201)
            session=self.request(f"/scenarios/{scenario['id']}/run",{},expected=201)
            sid=session['id'];prefix=f'/simulations/{sid}'
            observation=self.request(prefix+'/analysis',dict(asOf=80))
            self.assertEqual(observation['modelId'],model)
            calls=[dict(tool='sensor_consistency',args={})] if model.startswith('triplens') else [dict(tool='flow_balance',args={}),dict(tool='sensor_check',args={})]
            tool=self.request(prefix+'/tools',dict(asOf=80,calls=calls))
            body=dict(asOf=80,at=83.17,horizon=150,mode='known',hypothesis=config['fault'],actions=['backup_pump','feed_reduce'] if model.startswith('triplens') else ['backup_pump','adjust_pump'])
            intervention=self.request(prefix+'/interventions',body)
            dataset=self.request(prefix+'/save',dict(workspaceId=wid))
            metadata=dataset['metadata']
            self.assertEqual(metadata['model']['scenarioId'],scenario['id'])
            self.assertEqual(metadata['model']['groundTruth'],session['groundTruth'])
            self.assertEqual(len(metadata['columns']),18 if model.startswith('triplens') else 7)
            if model=='coupled-tanks':
                self.assertEqual(next(c for c in metadata['columns'] if c['name']=='level2')['unit'],'m')
                self.request('/analyze',dict(simulationId=sid,asOf=80,prompt='diagnose'),expected=400)
            labels=self.request(f"/datasets/{dataset['id']}/labels/simulation",{},expected=201)
            self.assertAlmostEqual(next(i for i in labels['intervals'] if i['kind']=='anomaly')['start'],40.37)
            service=self.service.workspace_store.experiments
            experiment=self.request(f'/workspaces/{wid}/experiments',dict(name=model+' detection',config=dict(datasetId=dataset['id'],signals=signals,
                baselineRange=[0,19.8],analysisRange=[20,150],labelSetId=labels['id'],algorithms=[dict(algorithm=a) for a in ALGORITHMS])),expected=201)
            run=self.request(f"/experiments/{experiment['id']}/runs",{},expected=202)
            research=finish(service,run['id'])
            self.assertEqual(research['status'],'completed')
            self.assertTrue(all(t['status']=='succeeded' and t['metrics']['labelled'] for t in research['tasks']))
            incident=self.request(f'/workspaces/{wid}/incidents',dict(title=model+' investigation',source=dict(kind='simulation',simulationId=sid,windowStart=0,asOf=80)),expected=201)
            for record in (tool,intervention):
                self.request(f"/incidents/{incident['id']}/links",dict(kind='run',simulationId=sid,runId=record['id']),expected=201)
            self.request(f"/incidents/{incident['id']}/links",dict(kind='analysis',analysisId=research['tasks'][0]['result_id']),expected=201)
            report=render_report(self.service.workspace_store,incident['id'])
            self.assertIn(model,report);self.assertIn(scenario['id'],report);self.assertIn('<svg',report)
            if model=='coupled-tanks':
                self.assertIn('Delivered water',report);self.assertNotIn('物理峰值压力 kPa',report)
            experiment_report=render_experiment_report(self.service.workspace_store,experiment['id'])
            self.assertIn(model,experiment_report);self.assertIn(scenario['id'],experiment_report)
            records.append((sid,tool,intervention,dataset,experiment,research,incident))
        self.stop();self.start()
        index=self.request(f'/workspaces/{wid}/model-research')
        self.assertEqual(len(index['rows']),18)
        self.assertEqual({m['id'] for row in index['rows'] for m in row['models']},{'coupled-tanks','triplens-synthetic-18-v2'})
        self.assertTrue(all(row['metrics']['labelled'] and row['labelVersion']==1 for row in index['rows']))
        for sid,tool,intervention,dataset,experiment,research,incident in records:
            self.assertEqual(len(self.request(f'/simulations/{sid}/runs')['runs']),2)
            self.assertEqual(self.request(f"/simulations/{sid}/runs/{intervention['id']}"),intervention)
            self.assertEqual(self.request(f"/datasets/{dataset['id']}")['metadata'],dataset['metadata'])
            self.assertEqual(self.request(f"/experiment-runs/{research['id']}"),research)
            self.assertEqual(len(self.request(f"/incidents/{incident['id']}")['links']),4)

    def test_finite_fault_labels_derived_model_provenance_and_legacy_files_are_unchanged(self):
        wid=self.workspace('Truth and legacy')
        session=self.request('/simulations',dict(workspaceId=wid,modelId='coupled-tanks',config=dict(fault='sensor_bias',start=40.37,fault_duration=11.13,duration=120)),expected=201)
        dataset=self.request(f"/simulations/{session['id']}/save",{})
        labels=self.request(f"/datasets/{dataset['id']}/labels/simulation",{},expected=201)
        self.assertLess(max(i['end'] for i in labels['intervals']),51.5)
        signal=next(s for s in self.request(f'/workspaces/{wid}/signals')['signals'] if s['datasetId']==dataset['id'] and s['name']=='level2')
        definition=self.request(f'/workspaces/{wid}/transformations',dict(name='Tank crop',config=dict(version=1,sources=[dict(signalId=signal['id'],key='level',resampling='nearest',maxGapSeconds=1,missing={'method':'keep'},duplicatePolicy='mean')],derived=[],grid=dict(mode='custom',start=10,end=100,intervalSeconds=.2,axisId=signal['clock']['axisId']))),expected=201)
        derived=self.request(f"/transformations/{definition['id']}/execute",{},expected=201)
        self.assertEqual(derived['metadata']['transformation']['sourceModels'][0]['id'],'coupled-tanks')
        mapped=self.request(f"/datasets/{derived['id']}/labels/simulation",{},expected=201)
        self.assertAlmostEqual(next(i for i in mapped['intervals'] if i['kind']=='anomaly')['onset'],30.37)
        legacy=self.request('/simulations',dict(workspaceId=wid,config=dict(duration=120,step=.2)),expected=201)
        path=self.folder/'simulations'/legacy['id']/'session.json'
        old={k:v for k,v in legacy.items() if k not in ('modelVersion','modelDescriptor','scenarioId','scenarioVersion','scenarioSnapshot','groundTruth','status')}
        old['config'].pop('fault_duration',None)
        path.write_text(json.dumps(old),encoding='utf-8')
        before=path.read_bytes()
        self.stop();self.start()
        restored=self.request('/simulations/'+legacy['id'])
        self.assertEqual(restored['modelVersion'],'2.0.0');self.assertEqual(restored['rows'],old['rows'])
        self.request(f"/simulations/{legacy['id']}/analysis",dict(asOf=80))
        self.request(f"/simulations/{legacy['id']}/tools",dict(asOf=80,calls=[dict(tool='sensor_consistency',args={})]))
        self.assertEqual(path.read_bytes(),before)
        # Persisted descriptors and rows can be read if an implementation is no
        # longer registered. New computation must fail rather than remap it.
        retired={**restored,'modelId':'retired-model','modelVersion':'retired-version'}
        path.write_text(json.dumps(retired),encoding='utf-8')
        self.assertEqual(self.request('/simulations/'+legacy['id'])['rows'],old['rows'])
        self.request(f"/simulations/{legacy['id']}/analysis",dict(asOf=80),expected=400)


if __name__=='__main__':
    unittest.main()
