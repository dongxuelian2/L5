"""Durable local identification jobs and append-only calibrated twin revisions."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from threading import RLock
from uuid import uuid4

import numpy as np

from .identification import (FIXED, INPUTS, OUTPUTS, PARAMETERS, VERSION, Observations,
                             configuration, fit)
from .models.base import finite


class CalibrationService:
    def __init__(self, store):
        self.store=store
        self.lock=RLock()
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='l5-identification')
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS calibration_runs (
                    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS calibrated_twins (
                    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    revision INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS calibrated_twin_revisions (
                    twin_id TEXT NOT NULL REFERENCES calibrated_twins(id) ON DELETE CASCADE,
                    revision INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(twin_id,revision));
            ''')
            for row in db.execute('SELECT * FROM calibration_runs').fetchall():
                saved=json.loads(row['payload'])
                if saved['status'] in ('queued','running'):
                    saved.update(status='interrupted',error='Identification interrupted by service restart.')
                    db.execute('UPDATE calibration_runs SET payload=? WHERE id=?',(self.encode(saved),row['id']))

    @staticmethod
    def encode(value):
        return json.dumps(value,ensure_ascii=False,allow_nan=False)

    @staticmethod
    def catalog():
        return dict(engineVersion=VERSION,modelId='coupled-tanks',parameters=PARAMETERS,nominal=FIXED,
                    inputs=list(INPUTS),outputs=list(OUTPUTS))

    def observation(self,workspace_id,ref,step):
        if (not isinstance(ref,dict) or set(ref)-{'datasetId','range','mapping','unitsConfirmed',
                'datasetName','sha256','samples','time','model'} or
                ref.get('unitsConfirmed') is not True):
            raise ValueError('Confirm signal units before calibration: levels in m, flows in m³/s, pump in %, valve in fraction.')
        dataset=self.store.dataset(ref.get('datasetId',''))
        if dataset['workspace_id'] != workspace_id:
            raise ValueError('Calibration datasets must belong to this workspace.')
        interval=ref.get('range')
        if (not isinstance(interval,list) or len(interval)!=2 or any(not finite(v) for v in interval) or
                not dataset['metadata']['time']['start'] <= interval[0] < interval[1] <= dataset['metadata']['time']['end']):
            raise ValueError('Choose an observation interval inside the dataset time range.')
        mapping=ref.get('mapping')
        columns={c['name']:c for c in dataset['metadata']['columns']}
        if (not isinstance(mapping,dict) or set(mapping)-set(INPUTS+OUTPUTS) or
                not set(mapping).intersection(OUTPUTS) or
                any(not isinstance(v,str) or v not in columns for v in mapping.values()) or
                len(set(mapping.values())) != len(mapping)):
            raise ValueError('Map unique dataset columns to model inputs and at least one observed output.')
        units=dict(level1={'m'},level2={'m'},inlet={'m³/s','m3/s'},transfer={'m³/s','m3/s'},
                   outlet={'m³/s','m3/s'},pump={'%'},valve={'fraction','1','dimensionless'})
        for role,column in mapping.items():
            unit=columns[column].get('unit','')
            if unit and unit not in units[role]:
                raise ValueError('Mapped signal units are incompatible. Convert units in Transformations first.')
        times,values=self.store.load_data(dataset)
        digest=sha256(times.tobytes()+values.tobytes()).hexdigest()
        if ref.get('sha256',digest)!=digest:
            raise ValueError('Observation source changed. Select the dataset again.')
        mask=(times>=interval[0]) & (times<=interval[1])
        t=times[mask]
        if (not 6<=len(t)<=2000 or np.any(np.diff(t)<=0) or
                t[-1]-t[0]>7200 or np.ceil(np.diff(t)/(.5*step)).sum()>60000):
            raise ValueError('Use 6–2000 strictly increasing observations and at most 60,000 integration substeps.')
        if np.max(np.diff(t)) > 5*np.median(np.diff(t)):
            raise ValueError('Observation interval contains acquisition gaps. Select a continuous run.')
        names=list(columns)
        data={key:values[mask,names.index(column)].copy() for key,column in mapping.items()}
        observed=self.store.observation_mask(dataset)[mask]
        for key,column in mapping.items():
            if not np.all(observed[:,names.index(column)][np.isfinite(data[key])]):
                raise ValueError('Identification requires observed samples. Processed or interpolated values are not measurements.')
            if key in INPUTS:
                low,high=(0,150) if key=='pump' else (.01,1)
                if not np.isfinite(data[key]).all() or np.any((data[key]<low)|(data[key]>high)):
                    raise ValueError('Actuator commands must be complete and inside physical limits.')
            elif np.isfinite(data[key][1:]).sum()<5:
                raise ValueError('Each mapped output needs at least five finite observations after initialization.')
        model=dataset['metadata'].get('model',{})
        # Deliberately omit model config, seed, faults and ground truth.
        reference=dict(datasetId=dataset['id'],datasetName=dataset['name'],range=interval,mapping=mapping,
                       unitsConfirmed=True,sha256=digest,samples=len(t),time=dataset['metadata']['time'],
                       model={k:model[k] for k in ('id','version','simulationId','scenarioId','scenarioVersion') if k in model})
        lineage=dataset['metadata'].get('transformation',{})
        roots=set()
        pending=[s['datasetId'] for s in lineage.get('sources',[]) if 'datasetId' in s]
        while pending:
            identity=pending.pop()
            if identity in roots: continue
            roots.add(identity)
            ancestor=self.store.base_dataset(identity)
            pending.extend(s['datasetId'] for s in ancestor['metadata'].get('transformation',{}).get('sources',[])
                           if 'datasetId' in s)
        return Observations(t,data,reference),dict(id=dataset['id'],hash=digest,roots=roots,
                                                  simulationId=model.get('simulationId'))

    def prepare(self,workspace_id,body):
        self.store.workspace(workspace_id)
        config=configuration(body.get('config'))
        calibration,source=self.observation(workspace_id,body['config'].get('calibration'),config['integrationStep'])
        validation=None
        if body['config'].get('validation') is not None:
            validation,test=self.observation(workspace_id,body['config']['validation'],config['integrationStep'])
            if (source['id']==test['id'] or source['hash']==test['hash'] or
                    source['simulationId'] and source['simulationId']==test['simulationId']):
                a,b=calibration.reference['range'],validation.reference['range']
                if max(a[0],b[0])<=min(a[1],b[1]):
                    raise ValueError('Calibration and validation observations must not overlap, including duplicated datasets.')
            elif (source['roots']|{source['id']}) & (test['roots']|{test['id']}):
                raise ValueError('Derived datasets share source observations. Use independent original runs for validation.')
            if not all(k in validation.values and np.isfinite(validation.values[k][0]) for k in ('level1','level2')):
                raise ValueError('Independent validation requires both initial measured tank levels.')
            if not set(calibration.values).intersection(OUTPUTS) <= set(validation.values).intersection(OUTPUTS):
                raise ValueError('Validation must include every calibrated output.')
        experiment=body.get('experimentId')
        if experiment:
            saved=self.store.experiments.get(experiment)
            if saved['workspace_id'] != workspace_id or saved['config']['datasetId'] != calibration.reference['datasetId']:
                raise ValueError('Linked experiment must use the calibration dataset in this workspace.')
        config.update(calibration=calibration.reference,validation=validation.reference if validation else None)
        return config,calibration,validation

    def create(self,workspace_id,body):
        from .workspace import now
        config,calibration,validation=self.prepare(workspace_id,body)
        name=self.store.name(body.get('name') or 'Coupled-tank identification')
        with self.lock:
            if any(r['status'] in ('queued','running') for r in self.list(workspace_id,all_workspaces=True)):
                raise ValueError('A local identification is already running. Wait for it to finish.')
            run=dict(id=uuid4().hex,workspaceId=workspace_id,name=name,status='queued',createdAt=now(),
                     config=config,experimentId=body.get('experimentId'),progress=dict(stage='queued',evaluations=0),result=None,error=None)
            with self.store.connect() as db:
                db.execute('INSERT INTO calibration_runs VALUES (?,?,?)',(run['id'],workspace_id,self.encode(run)))
            self.executor.submit(self.execute,run['id'],calibration,validation)
        return run

    def update(self,identity,changes):
        with self.lock,self.store.connect() as db:
            row=db.execute('SELECT payload FROM calibration_runs WHERE id=?',(identity,)).fetchone()
            if row is None: return  # Workspace may have been deleted during a run.
            run=json.loads(row['payload']);run.update(changes)
            db.execute('UPDATE calibration_runs SET payload=? WHERE id=?',(self.encode(run),identity))

    def execute(self,identity,calibration,validation):
        from .workspace import now
        try:
            run=self.get(identity)
            self.update(identity,dict(status='running',startedAt=now()))
            result=fit(run['config'],calibration,validation,lambda p:self.update(identity,dict(progress=p)))
            self.update(identity,dict(status='completed',result=result,completedAt=now(),progress=dict(stage='completed',evaluations=result['optimizer']['evaluations'])))
        except Exception as error:
            self.update(identity,dict(status='failed',error=str(error),completedAt=now()))

    def get(self,identity,workspace_id=None):
        with self.store.connect() as db:
            row=db.execute('SELECT payload,workspace_id FROM calibration_runs WHERE id=?',(identity,)).fetchone()
        if row is None or workspace_id is not None and row['workspace_id']!=workspace_id:
            raise KeyError('Calibration run not found.')
        return json.loads(row['payload'])

    def list(self,workspace_id,*,all_workspaces=False):
        self.store.workspace(workspace_id)
        with self.store.connect() as db:
            if all_workspaces:
                rows=db.execute('SELECT payload FROM calibration_runs').fetchall()
            else:
                rows=db.execute('SELECT payload FROM calibration_runs WHERE workspace_id=? ORDER BY rowid DESC LIMIT 200',(workspace_id,)).fetchall()
        return [{k:v for k,v in json.loads(r['payload']).items() if k!='result'} for r in rows]

    def twins(self,workspace_id):
        self.store.workspace(workspace_id)
        with self.store.connect() as db:
            return [json.loads(r['payload']) for r in db.execute('''SELECT v.payload FROM calibrated_twins t
                JOIN calibrated_twin_revisions v ON t.id=v.twin_id AND t.revision=v.revision
                WHERE t.workspace_id=? ORDER BY t.rowid DESC''',(workspace_id,))]

    def revisions(self,workspace_id,identity):
        with self.store.connect() as db:
            rows=db.execute('''SELECT v.payload FROM calibrated_twins t JOIN calibrated_twin_revisions v ON t.id=v.twin_id
                WHERE t.workspace_id=? AND t.id=? ORDER BY v.revision DESC''',(workspace_id,identity)).fetchall()
        if not rows: raise KeyError('Calibrated twin not found.')
        return [json.loads(r['payload']) for r in rows]

    def save_twin(self,workspace_id,body,identity=None):
        from .workspace import now
        self.store.workspace(workspace_id)
        run=self.get(body.get('runId'),workspace_id)
        if run['status']!='completed' or not run['result']['optimizer']['converged']:
            raise ValueError('Save a twin only after numerical convergence.')
        previous=self.revisions(workspace_id,identity)[0] if identity else None
        if previous and body.get('expectedRevision') != previous['revision']:
            raise ValueError('Twin revision changed. Reopen the latest revision.')
        identity=identity or uuid4().hex
        result=run['result']
        twin=dict(id=identity,workspaceId=workspace_id,revision=previous['revision']+1 if previous else 1,
                  name=self.store.name(body.get('name') or (previous['name'] if previous else run['name'])),createdAt=now(),
                  runId=run['id'],engineVersion=VERSION,modelId='coupled-tanks',config=result['fittedConfig'],
                  identifiability=result['identifiability'],uncertainty=result['uncertainty'],warnings=result['warnings'],
                  calibration=run['config']['calibration'],validation=run['config']['validation'],
                  validated=result['validation'] is not None)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current=db.execute('SELECT revision FROM calibrated_twins WHERE id=?',(identity,)).fetchone()
            if previous and (current is None or current['revision']!=previous['revision']):
                raise ValueError('Twin revision changed. Reopen the latest revision.')
            db.execute('INSERT INTO calibrated_twins VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision',
                       (identity,workspace_id,twin['revision']))
            db.execute('INSERT INTO calibrated_twin_revisions VALUES (?,?,?)',(identity,twin['revision'],self.encode(twin)))
        return twin

    def scenario(self,workspace_id,identity,body):
        revisions=self.revisions(workspace_id,identity)
        version=body.get('revision',revisions[0]['revision'])
        if isinstance(version,bool) or not isinstance(version,int):
            raise ValueError('Choose an integer twin revision.')
        twin=next((r for r in revisions if r['revision']==version),None)
        if twin is None: raise KeyError('Calibrated twin revision not found.')
        c=dict(twin['config'])
        # The original physical simulator represents the identifiable product as
        # one effective nominal pump coefficient; no controller dependency.
        c['pumpRate']*=c.pop('pumpEfficiency')
        config={k:v for k,v in c.items() if k in FIXED and k!='pumpEfficiency'}
        return self.store.scenarios.save(workspace_id,dict(modelId='coupled-tanks',name=twin['name'],config=config,
            description=f"Calibrated twin {identity} revision {version}; identification run {twin['runId']}. "
                        f"Identifiability: {twin['identifiability']['status']}; independent validation: {twin['validated']}. "
                        'Pump coefficient includes the fitted efficiency factor.'))
