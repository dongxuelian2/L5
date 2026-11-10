"""Local immutable control experiments, integrated with normal model Datasets."""
from copy import deepcopy
import json
from threading import RLock
from uuid import uuid4

from .control import compare, validate_protocol
from .models.tanks import CoupledTankModel
from .workspace import now


class ControlService:
    def __init__(self, store):
        self.store=store; self.lock=RLock()
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS control_experiments (
                    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    name TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS control_datasets (
                    control_id TEXT NOT NULL REFERENCES control_experiments(id) ON DELETE CASCADE,
                    controller TEXT NOT NULL, dataset_id TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
                    PRIMARY KEY(control_id,controller));
            ''')

    def list(self, workspace_id):
        self.store.workspace(workspace_id)
        with self.store.connect() as db:
            return [dict(id=r['id'],workspaceId=r['workspace_id'],name=r['name'],createdAt=r['created_at']) for r in db.execute(
                'SELECT id,workspace_id,name,created_at FROM control_experiments WHERE workspace_id=? ORDER BY created_at DESC',(workspace_id,))]

    def get(self, workspace_id, identity):
        self.store.workspace(workspace_id)
        with self.store.connect() as db:
            row=db.execute('SELECT payload FROM control_experiments WHERE id=? AND workspace_id=?',(identity,workspace_id)).fetchone()
            if row is None: raise KeyError('Control experiment not found in this workspace.')
            result=json.loads(row['payload'])
            result['datasets']={r['controller']:r['dataset_id'] for r in db.execute('SELECT * FROM control_datasets WHERE control_id=?',(identity,))}
        return result

    def create(self, workspace_id, body):
        self.store.workspace(workspace_id)
        if set(body)-{'name','scenarioId','scenarioVersion','config','protocol'}:
            raise ValueError('Unknown control experiment parameters.')
        name=self.store.name(body.get('name','Closed-loop comparison'))
        model=CoupledTankModel()
        scenario=self.store.scenarios.get(body['scenarioId'],body.get('scenarioVersion')) if body.get('scenarioId') else None
        if scenario and (scenario['workspaceId']!=workspace_id or scenario['modelId']!=model.id or scenario['modelVersion']!=model.version):
            raise ValueError('Choose a coupled-tank scenario in this workspace with the current model version.')
        if scenario and 'config' in body:
            raise ValueError('Saved scenarios run their exact version; save parameter edits first.')
        config=model.validate(scenario['config'] if scenario else body.get('config',{}),randomize=True)
        protocol=validate_protocol(body.get('protocol',{}),config)
        result=compare(config,protocol)
        result.update(id=uuid4().hex,workspaceId=workspace_id,name=name,createdAt=now(),scenarioSnapshot=deepcopy(scenario),datasets={})
        with self.store.connect() as db:
            db.execute('INSERT INTO control_experiments VALUES (?,?,?,?,?)',(result['id'],workspace_id,name,result['createdAt'],json.dumps(result,ensure_ascii=False,allow_nan=False)))
            db.execute('UPDATE workspaces SET updated_at=? WHERE id=?',(result['createdAt'],workspace_id))
        return result

    def dataset(self, workspace_id, identity, controller):
        with self.lock:
            result=self.get(workspace_id,identity)
            if controller in result['datasets']:
                return self.store.dataset(result['datasets'][controller])
            branch=next((b for b in result['results'] if b['controller']==controller),None)
            if branch is None: raise ValueError('Controller is not part of this saved comparison.')
            model=CoupledTankModel(); descriptor=deepcopy(model.describe())
            # A one-time intervention replay would discard the closed-loop input
            # history. Keep observation/tools, and reopen Control for new policies.
            descriptor['capabilities']=[v for v in descriptor['capabilities'] if v not in ('interventions','forecast')]
            descriptor['actions']=[]
            descriptor['signals'] += [dict(key='reference',tag='SP-102',unit='m',label='Tank 2 reference'),
                                      dict(key='error',tag='ERR-102',unit='m',label='Tank 2 tracking error')]
            scenario=result['scenarioSnapshot']
            session=dict(id=uuid4().hex,title=self.store.name((result['name'][:140]+' · '+controller)),
                         modelId=model.id,modelVersion=model.version,modelDescriptor=descriptor,config=result['config'],rows=branch['rows'],
                         scenarioId=scenario['id'] if scenario else None,scenarioVersion=scenario['version'] if scenario else None,
                         scenarioSnapshot=scenario,groundTruth=model.truth(result['config']),status='completed',createdAt=now(),
                         workspaceId=workspace_id,datasetId=None,
                         control=dict(experimentId=identity,controller=controller,settings=branch['settings'],protocol=result['protocol'],
                                      metrics=branch['metrics'],solver=result['solver'],format=result['format'],noiseFingerprint=result['noiseFingerprint']))
            folder=self.store.runtime.folder(session['id']); folder.mkdir()
            self.store.runtime.write(folder/'session.json',session)
            dataset=self.store.runtime.save(session['id'],dict(workspaceId=workspace_id))
            with self.store.connect() as db:
                db.execute('INSERT INTO control_datasets VALUES (?,?,?)',(identity,controller,dataset['id']))
            return dataset


def csv_result(result):
    """Full-resolution numerical evidence, including separately labelled truth."""
    columns=['controller','t','reference','level1','level2','pump','valve','inlet','transfer','outlet','error',
             'physicalLevel1','physicalLevel2','massResidual','spill']
    lines=[','.join(columns)]
    for branch in result['results']:
        for row,physical in zip(branch['rows'],branch['physical']):
            record={**row,'controller':branch['controller'],'physicalLevel1':physical['level1'],'physicalLevel2':physical['level2'],
                    'massResidual':physical['massResidual'],'spill':physical['spill']}
            lines.append(','.join(str(record[k]) for k in columns))
    return '\n'.join(lines)+'\n'
