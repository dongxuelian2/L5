"""New runtime freedoms: real trajectories, causal prefixes and durable experiments."""
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from urllib.request import Request, build_opener, ProxyHandler

import numpy as np

from l5.analysis import ALGORITHMS, run_analysis
from l5.workspace import WorkspaceStore
from server import Handler
from simulation.platform import Config, diagnose, simulate


class RuntimeTests(unittest.TestCase):
    def test_custom_duration_step_and_intervention_parameters(self):
        c = Config(fault='cooling_valve', start=43.7, duration=317.3, step=.5, severity=.83, seed=739)
        rows = simulate(c)
        self.assertEqual(len(rows), 636)
        self.assertEqual(rows[-1]['t'], 317.3)
        self.assertEqual(rows[:187], simulate(c, 'feed_reduce', 93.4, parameters={'feedReduction':.61})[:187])
        weak = simulate(c, 'feed_reduce', 93.4, compact=True, parameters={'feedReduction':.1})
        strong = simulate(c, 'feed_reduce', 93.4, compact=True, parameters={'feedReduction':.61})
        self.assertNotEqual(weak['pressure'], strong['pressure'])
        self.assertGreater(strong['productionLoss'], weak['productionLoss'])
        self.assertEqual(diagnose(rows[:20])['status'], 'insufficient_data')

    def test_prefix_fit_ignores_future_observations_and_source_fault_parameters(self):
        with TemporaryDirectory() as folder:
            store = WorkspaceStore(Path(folder))
            session = store.runtime.create({'config':dict(fault='pump_loss',start=39,severity=.83,duration=317,step=.5,seed=867)})
            identity = session['id']
            body = dict(asOf=93, hypothesis='cooling_valve', at=96.4, horizon=350,
                        mode='observed', actions=['feed_reduce'], parameters={'feedReduction':.22})
            analysis = store.runtime.analysis(identity, body)
            first = store.runtime.intervene(identity, body)['result']
            self.assertNotEqual(analysis['diagnosis']['candidates'][0]['id'], body['hypothesis'])
            for row in session['rows']:
                if row['t'] > 93:
                    for key in row:
                        if key != 't':
                            row[key] = 999999
            session['config']['severity'] = 1.9
            store.runtime.write(store.runtime.folder(identity)/'session.json',session)
            store.runtime.cache.clear()
            self.assertEqual(store.runtime.analysis(identity,body), analysis)
            self.assertEqual(store.runtime.intervene(identity,body)['result'], first)
            with self.assertRaises(ValueError):
                store.runtime.tools(identity, {**body,'calls':[{'tool':'inspect_signal_window','args':{'signal':'pressure','end':94}}]})

    def test_research_algorithms_and_coverage_on_an_unseen_dataset(self):
        rng = np.random.default_rng(837)
        values = rng.normal(size=(700, 4)); values[430:510, 1] += 5
        config = dict(signals=['a','b','c','d'],baselineRange=[0,199],analysisRange=[200,699], alpha=.02)
        for algorithm in ALGORITHMS:
            with self.subTest(algorithm=algorithm):
                result = run_analysis(np.arange(700), values, ['a','b','c','d'], {**config,'algorithm':algorithm})
                self.assertEqual(len(result['scores']),500)
                self.assertTrue(np.isfinite(result['scores']).all())
                self.assertTrue(any(430 <= interval['peakTime'] <= 520 for interval in result['intervals']))
                if algorithm in ('ewma','cusum','window-cusum','adaptive-maxz'):
                    self.assertAlmostEqual(max(c['value'] for c in result['signalContributions']), result['summary']['peakScore'])
                if algorithm == 'dpca-q':
                    self.assertAlmostEqual(sum(c['value'] for c in result['signalContributions']), result['summary']['peakScore'])
        missing = values.copy(); missing[300:350, 0] = np.nan
        result = run_analysis(np.arange(700), missing, ['a','b','c','d'], {**config,'algorithm':'ewma','requiredSignals':['a'],'persistence':3})
        self.assertEqual(result['states'][100:150], ['abstain']*50)
        self.assertEqual(result['summary']['abstainedSamples'],50)
        stressed = run_analysis(np.arange(700), values, ['a','b','c','d'], {**config,'algorithm':'ewma','stress':{'missingFraction':1}})
        self.assertEqual(stressed['summary']['flaggedSamples'],0)
        self.assertEqual(stressed['summary']['abstainedSamples'],500)
        self.assertEqual(stressed['threshold'],result['threshold'])

    def test_http_simulate_investigate_intervene_save_restart_and_reopen(self):
        with TemporaryDirectory() as folder:
            def start():
                service = ThreadingHTTPServer(('127.0.0.1',0),Handler)
                service.workspace_store = WorkspaceStore(Path(folder))
                thread = threading.Thread(target=service.serve_forever,daemon=True);thread.start()
                return service,thread
            def request(path, body=None):
                req = Request(f'http://127.0.0.1:{service.server_port}/api{path}',data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
                with build_opener(ProxyHandler({})).open(req,timeout=30) as response:
                    return json.load(response)
            service,thread = start()
            try:
                workspace = request('/workspaces',{'name':'Runtime acceptance'})
                wid = workspace['id']
                session = request('/simulations',{'workspaceId':wid,'title':'Custom pump experiment','config':dict(fault='pump_loss', start=37.4,severity=.83,duration=317.4,step=.2,seed=9817,noise=1.3,response=.87,delay=8.4,operating=.6)})
                identity = session['id']
                observed = request(f'/simulations/{identity}/analysis',{'asOf':93})
                self.assertEqual(observed['observedThrough'],93)
                self.assertTrue(all(e['t']<=93 for e in observed['alarms']['events']))
                self.assertEqual(len(observed['diagnosis']['candidates']),12)
                tool = request(f'/simulations/{identity}/tools',{'asOf':93,'calls':[{'tool':'sensor_consistency','args':{}},{'tool':'inspect_controller','args':{'controller':'FIC-102'}}]})
                self.assertEqual(tool['result']['trace'][1]['result']['id'],'FIC-102')
                intervention = request(f'/simulations/{identity}/interventions',dict(asOf=93,at=95.6,horizon=340,mode='observed',hypothesis='cooling_valve',actions=['feed_reduce','setpoint'],parameters={'feedReduction':.37,'setpointDrop':3.2}))
                self.assertEqual(intervention['result']['observedThrough'],93)
                self.assertEqual(len(intervention['result']['branches']),2)
                brief = request('/analyze',{'simulationId':identity,'asOf':93,'prompt':'请检查我正在调查的传感器差异'})
                self.assertEqual(brief['incidentId'],identity)
                self.assertEqual(brief['trace'][0]['tool'],'sensor_consistency')
                dataset = request(f'/simulations/{identity}/save',{'workspaceId':wid})
                did = dataset['id']
                self.assertEqual(dataset['metadata']['model']['simulationId'],identity)
                result = request(f'/workspaces/{wid}/analyses',dict(datasetId=did,signals=['flow','pressure','pump'],baselineRange=[0,19.8],analysisRange=[20,317.4],algorithm='ewma',smoothing=.3))
            finally:
                service.shutdown();service.server_close();thread.join()
            service,thread = start()
            try:
                self.assertEqual(request(f'/simulations/{identity}')['rows'],session['rows'])
                self.assertEqual(request(f'/datasets/{did}')['metadata']['model']['simulationId'],identity)
                self.assertEqual(request(f'/analyses/{result["id"]}'),result)
                runs = request(f'/simulations/{identity}/runs')['runs']
                self.assertEqual(len(runs),3)
                self.assertEqual(next(r for r in runs if r['kind']=='intervention')['result'],intervention['result'])
                request(f'/simulations/{identity}/analysis',{'asOf':156.6})
                request(f'/simulations/{identity}/interventions',dict(asOf=156.6,at=160.2,horizon=400,mode='known',hypothesis='pump_loss',actions=['backup_pump'],parameters={'pumpSpeed':127}))
                searched = request(f'/simulations/{identity}/interventions',dict(asOf=156.6,at=160.2,horizon=170.2,mode='known',hypothesis='pump_loss',actions=['backup_pump'],parameters={'pumpSpeed':127},search={'resolution':5}))
                self.assertEqual(searched['result']['search']['evaluated'],3)
            finally:
                service.shutdown();service.server_close();thread.join()


if __name__ == '__main__':
    unittest.main()
