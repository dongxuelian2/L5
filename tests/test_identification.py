"""Numerical recovery, failure modes and durable real-HTTP calibration lifecycle."""
import json
from copy import deepcopy
import time
import unittest
from unittest.mock import patch

import numpy as np

from l5.calibration_examples import observations,csv_observations
from l5.identification import Observations,configuration,fit,predict
from l5.models import resolve
from l5.models.tanks import integrate
from test_incidents import IncidentHTTPFixture


def data(rows):
    return Observations(np.array([r['t'] for r in rows]),
        {k:np.array([r[k] for r in rows]) for k in ('level1','level2','pump','valve')},dict(datasetId='observations'))


def config(extra=None):
    return configuration(dict(parameters={k:dict(initial=v,lower=.01,upper=.08) for k,v in
        dict(pumpRate=.03,connection=.04,outlet=.03).items()},**(extra or {})))


class IdentificationMathTests(unittest.TestCase):
    def test_shared_integrator_matches_simulator_mass_and_positivity(self):
        for changes in [dict(initial1=.01,initial2=3),dict(initial1=4,initial2=3,tankHeight=1),
                        dict(initial1=.001,initial2=.001,pumpRate=0,connection=.2,outlet=.2,area1=.1,area2=.1)]:
            c=resolve('coupled-tanks').validate(dict(duration=10,start=0,noise=0,**changes))
            rows,truth=integrate(c)
            predicted,balance=predict(c,data(rows),.05,with_balance=True)
            np.testing.assert_allclose(predicted[:,:2],[[r['level1'],r['level2']] for r in truth],atol=1e-10)
            self.assertTrue(np.all(predicted[:,:2]>=0))
            self.assertLess(balance,1e-10)

    def test_recovery_noise_validation_and_numerical_convergence(self):
        rows,truth=observations(noise=0)
        validation,_=observations(noise=0,validation=True)
        result=fit(config(),data(rows),data(validation))
        for k,v in truth.items(): self.assertLess(abs(result['parameters'][k]['value']/v-1),.002)
        self.assertTrue(result['optimizer']['converged'])
        self.assertEqual(result['identifiability']['rank'],3)
        self.assertEqual(len(result['validation']['multiStep']),3)
        self.assertTrue(result['validation']['initializationExcluded'])
        self.assertLess(result['validation']['metrics']['level2']['rmse'],result['validation']['originalMetrics']['level2']['rmse']*.01)
        self.assertLess(result['calibration']['numericalStepDifferenceRmse']['level2'],1e-5)
        estimates=[]
        for seed in (19,32,71):
            measured,_=observations(seed=seed)
            fitted=fit(config(),data(measured))
            estimates.append([fitted['parameters'][k]['value'] for k in truth])
            self.assertTrue(fitted['optimizer']['converged'])
            self.assertLess(max(abs(fitted['parameters'][k]['value']/v-1) for k,v in truth.items()),.035)
        self.assertLess(np.max(np.std(estimates,axis=0)/list(truth.values())),.02)

    def test_validation_future_cannot_change_fit_or_earlier_prediction(self):
        rows,_=observations(noise=0)
        test,_=observations(noise=0,validation=True)
        altered=[dict(r,level1=r['level1']+(4 if i>20 else 0),level2=r['level2']-(3 if i>20 else 0)) for i,r in enumerate(test)]
        first=fit(config(),data(rows),data(test))
        second=fit(config(),data(rows),data(altered))
        self.assertEqual(first['parameters'],second['parameters'])
        self.assertEqual(first['optimizer'],second['optimizer'])
        self.assertEqual(first['validation']['predicted'],second['validation']['predicted'])
        changed=data(test)
        changed.values['pump'][100:]=20
        before=predict(first['fittedConfig'],data(test))
        after=predict(first['fittedConfig'],changed)
        np.testing.assert_array_equal(before[:100],after[:100])

    def test_equilibrium_and_pump_product_are_not_unique_and_no_covariance_claim(self):
        rows,_=observations(noise=0,equilibrium=True)
        result=fit(config(),data(rows))
        self.assertLess(result['identifiability']['rank'],3)
        self.assertFalse(result['uncertainty']['available'])
        rows,_=observations(noise=0)
        c=config();c['parameters']['pumpEfficiency']=dict(initial=.8,lower=.3,upper=1.)
        result=fit(c,data(rows))
        self.assertLess(result['identifiability']['rank'],4)
        self.assertIn('pump-product-confounding',result['warnings'])
        self.assertTrue(result['identifiability']['weakCombinations'])
        self.assertFalse(result['uncertainty']['available'])

    def test_mismatch_bounds_budget_and_local_uncertainty(self):
        rows,_=observations(mismatch=True)
        result=fit(config(),data(rows))
        self.assertIn('residual-mismatch',result['warnings'])
        self.assertFalse(result['uncertainty']['available'])
        result=fit(config(dict(maxEvaluations=1)),data(rows))
        self.assertFalse(result['optimizer']['converged'])
        self.assertIn('optimizer-incomplete',result['warnings'])
        rows,_=observations(noise=0)
        result=fit(config(),data(rows))
        self.assertTrue(result['uncertainty']['available'])
        self.assertGreater(result['uncertainty']['standardErrors']['pumpRate'],0)
        self.assertIsNotNone(result['calibration']['parameterEnvelope'])
        c=config();c['parameters']['pumpRate']['upper']=.032
        result=fit(c,data(rows))
        self.assertLessEqual(result['parameters']['pumpRate']['value'],.032)
        self.assertIn('pumpRate',result['identifiability']['activeBounds'])
        self.assertFalse(result['uncertainty']['available'])

    def test_selected_initials_irregular_timestamps_and_optional_flow_output(self):
        rows,_=observations(noise=0)
        selected=data(rows[::2])
        selected.times=selected.times + np.linspace(0,.01,len(selected.times))
        selected.values['inlet']=np.array([r['inlet'] for r in rows[::2]])
        c=config()
        for key in ('initial1','initial2'):
            c['parameters'][key]=dict(initial=1.,lower=.1,upper=2.)
        result=fit(c,selected)
        self.assertEqual(result['identifiability']['rank'],5)
        self.assertLess(abs(result['parameters']['initial1']['value']-1.1),.005)
        self.assertLess(result['calibration']['metrics']['inlet']['rmse'],1e-5)


class CalibrationHTTPTests(IncidentHTTPFixture):
    def import_rows(self,wid,rows,name='Measured tanks'):
        return self.request(f'/workspaces/{wid}/datasets',dict(name=name,csv=csv_observations(rows)),expected=201)

    def reference(self,dataset,start=0,end=200):
        return dict(datasetId=dataset['id'],range=[start,end],unitsConfirmed=True,
                    mapping={k:k for k in ('level1','level2','pump','valve')})

    def finish(self,wid,run):
        for _ in range(300):
            saved=self.request(f"/workspaces/{wid}/calibrations/{run['id']}")
            if saved['status'] not in ('queued','running'): return saved
            time.sleep(.05)
        self.fail('Calibration did not finish.')

    def test_http_save_revisions_restart_export_and_reuse(self):
        wid=self.workspace()
        measured,_=observations(noise=0)
        test,_=observations(noise=0,validation=True)
        d=self.import_rows(wid,measured);v=self.import_rows(wid,test,'Independent validation')
        c=config();c.update(calibration=self.reference(d),validation=self.reference(v))
        run=self.request(f'/workspaces/{wid}/calibrations',dict(name='Physical calibration',config=c),expected=202)
        saved=self.finish(wid,run)
        self.assertEqual(saved['status'],'completed',saved['error'])
        twin=self.request(f'/workspaces/{wid}/twins',dict(runId=run['id'],name='Tank twin'),expected=201)
        self.assertTrue(twin['validated'])
        twin2=self.request(f"/workspaces/{wid}/twins/{twin['id']}",dict(runId=run['id'],expectedRevision=1),method='PATCH')
        self.assertEqual(twin2['revision'],2)
        self.request(f"/workspaces/{wid}/twins/{twin['id']}",dict(runId=run['id'],expectedRevision=1),method='PATCH',expected=400)
        scenario=self.request(f"/workspaces/{wid}/twins/{twin['id']}/scenario",dict(revision=1),expected=201)
        session=self.request(f"/scenarios/{scenario['id']}/run",{},expected=201)
        self.assertEqual(session['config']['pumpRate'],twin['config']['pumpRate'])
        self.assertIn(run['id'],scenario['description'])
        self.stop();self.start()
        self.assertEqual(self.request(f"/workspaces/{wid}/calibrations/{run['id']}")['result'],saved['result'])
        self.assertEqual(len(self.request(f"/workspaces/{wid}/twins/{twin['id']}/revisions")['revisions']),2)
        self.assertEqual(len(self.request(f'/workspaces/{wid}/twins')['twins']),1)
        other=self.workspace('Other')
        self.request(f"/workspaces/{other}/calibrations/{run['id']}",expected=404)
        self.request(f"/workspaces/{other}/twins/{twin['id']}/revisions",expected=404)

    def test_overlap_invalid_observations_and_no_truth_access(self):
        wid=self.workspace()
        rows,_=observations(noise=0)
        d=self.import_rows(wid,rows);duplicate=self.import_rows(wid,rows)
        c=config();c.update(calibration=self.reference(d,0,100),validation=self.reference(duplicate,100,200))
        self.request(f'/workspaces/{wid}/calibrations',dict(config=c),expected=400)

        c['validation']=self.reference(d,101,200)
        # Prove fitting can run with the runtime / truth interface unavailable.
        with patch.object(self.service.workspace_store.runtime,'get',side_effect=AssertionError('No simulator truth')):
            run=self.request(f'/workspaces/{wid}/calibrations',dict(config=c),expected=202)
            result=self.finish(wid,run)
        self.assertEqual(result['status'],'completed',result['error'])
        for broken in [dict(c,nominal={'area1':0}),dict(c,noise={'level1':0}),dict(c,maxEvaluations=True),
                       dict(c,calibration={**c['calibration'],'unitsConfirmed':False}),
                       dict(c,calibration={**c['calibration'],'mapping':dict(level1='level1',level2='level1')})]:
            self.request(f'/workspaces/{wid}/calibrations',dict(config=broken),expected=400)
        repeated=[dict(r,t=0 if i==1 else r['t']) for i,r in enumerate(rows)]
        bad=self.import_rows(wid,repeated)
        c['calibration']=self.reference(bad);c['validation']=None
        self.request(f'/workspaces/{wid}/calibrations',dict(config=c),expected=400)

    def test_units_missing_inputs_processed_samples_lineage_and_replay(self):
        wid=self.workspace()
        store=self.service.workspace_store
        rows,_=observations(noise=0)
        dataset=self.import_rows(wid,rows)
        base=config();base.update(calibration=self.reference(dataset),validation=None)
        prepared,_,_=store.calibration.prepare(wid,dict(config=base))
        # Saved provenance is replayable and revalidated, never trusted as input.
        self.assertEqual(store.calibration.prepare(wid,dict(config=prepared))[0],prepared)
        tampered=deepcopy(prepared);tampered['calibration']['sha256']='bad'
        with self.assertRaisesRegex(ValueError,'source changed'):
            store.calibration.prepare(wid,dict(config=tampered))
        column=next(c for c in dataset['metadata']['columns'] if c['name']=='level1')
        store.signals.update_signal(column['id'],dict(unit='cm'))
        with self.assertRaisesRegex(ValueError,'units are incompatible'):
            store.calibration.prepare(wid,dict(config=base))
        store.signals.update_signal(column['id'],dict(unit='m'))
        missing=[dict(r,pump=float('nan') if i==10 else r['pump']) for i,r in enumerate(rows)]
        broken=self.import_rows(wid,missing)
        with self.assertRaisesRegex(ValueError,'Actuator commands'):
            store.calibration.prepare(wid,dict(config={**base,'calibration':self.reference(broken)}))
        times,values=store.load_data(dataset)
        meta=deepcopy(dataset['metadata']);meta['transformation']=dict(sources=[dict(datasetId=dataset['id'])],clock=dataset['metadata']['clock'])
        observed=np.ones(values.shape,dtype=bool);observed[10,0]=False
        processed=store.save_dataset(wid,'Interpolated levels',meta,times,values,csv_observations(rows),extra_arrays=dict(observed=observed))
        with self.assertRaisesRegex(ValueError,'requires observed samples'):
            store.calibration.prepare(wid,dict(config={**base,'calibration':self.reference(processed)}))
        # Different content defeats the duplicate fingerprint; ancestry still
        # prevents claiming a derived copy as an independent validation run.
        changed=values.copy();changed[:,0]+=.00001
        derived=store.save_dataset(wid,'Derived copy',meta,times,changed,csv_observations(rows))
        nested=deepcopy(meta);nested['transformation']['sources']=[dict(datasetId=derived['id'])]
        nested_values=changed.copy();nested_values[:,1]+=.00001
        grandchild=store.save_dataset(wid,'Nested copy',nested,times,nested_values,csv_observations(rows))
        with self.assertRaisesRegex(ValueError,'share source observations'):
            store.calibration.prepare(wid,dict(config={**base,'validation':self.reference(grandchild)}))

    def test_incomplete_jobs_cannot_be_saved_and_restart_is_explicit(self):
        wid=self.workspace()
        rows,_=observations()
        dataset=self.import_rows(wid,rows)
        c=config(dict(maxEvaluations=1));c.update(calibration=self.reference(dataset),validation=None)
        run=self.request(f'/workspaces/{wid}/calibrations',dict(config=c),expected=202)
        saved=self.finish(wid,run)
        self.assertFalse(saved['result']['optimizer']['converged'])
        self.request(f'/workspaces/{wid}/twins',dict(runId=run['id']),expected=400)
        store=self.service.workspace_store
        store.calibration.update(run['id'],dict(status='running',result=None))
        self.request(f'/workspaces/{wid}/calibrations',dict(config=c),expected=400)
        self.stop();self.start()
        restored=self.request(f"/workspaces/{wid}/calibrations/{run['id']}")
        self.assertEqual(restored['status'],'interrupted')
        self.assertIn('restart',restored['error'])



if __name__=='__main__': unittest.main()
