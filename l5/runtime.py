"""Shared model lifecycle, causal windows, durable runs and Dataset export."""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
import json
from pathlib import Path
import re
from threading import RLock
from uuid import uuid4

from .models import resolve
from .models.base import finite

MODEL_ID = 'triplens-synthetic-18-v2'


def catalog():
    """Compatibility endpoint for the established TripLens workbench."""
    return resolve(MODEL_ID).describe()


class SimulationService:
    def __init__(self, store):
        self.store = store
        self.root = store.root / 'simulations'
        self.root.mkdir(exist_ok=True)
        self.cache = OrderedDict()
        self.lock = RLock()

    def folder(self, identity):
        if not isinstance(identity, str) or not re.fullmatch('[a-f0-9]{32}', identity):
            raise KeyError('Simulation not found.')
        return self.root / identity

    @staticmethod
    def write(path: Path, value):
        temporary = path.with_name(f'{path.stem}.{uuid4().hex}.tmp')
        temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        temporary.replace(path)

    def get(self, identity):
        path = self.folder(identity) / 'session.json'
        if not path.exists():
            raise KeyError('Simulation not found.')
        session = json.loads(path.read_text(encoding='utf-8'))
        # Additive projection; reading a legacy session does not rewrite it.
        session.setdefault('modelId', MODEL_ID)
        if any(key not in session for key in ('modelVersion', 'modelDescriptor', 'groundTruth')):
            model = resolve(session['modelId'])
            session.setdefault('modelVersion', model.version)
            session.setdefault('modelDescriptor', model.describe())
            if 'groundTruth' not in session:
                session['groundTruth'] = model.truth(session['config']) if 'ground-truth' in model.describe()['capabilities'] else None
        session.setdefault('scenarioId', None)
        session.setdefault('scenarioVersion', None)
        session.setdefault('status', 'completed')
        return session

    def model(self, session, capability=None):
        model = resolve(session.get('modelId', MODEL_ID))
        if session.get('modelVersion', model.version) != model.version:
            raise ValueError('Saved model version unavailable for new computations; saved results remain readable.')
        if capability and capability not in model.describe()['capabilities']:
            raise ValueError(f'This model does not support {capability}.')
        return model

    def list(self, workspace_id=None):
        referenced = set()
        if workspace_id:
            self.store.workspace(workspace_id)
            referenced = {d['metadata']['model']['simulationId'] for d in self.store.datasets(workspace_id) if d['metadata'].get('model')}
        sessions = []
        for path in self.root.glob('*/session.json'):
            session = self.get(path.parent.name)
            if workspace_id is None or session.get('workspaceId') == workspace_id or session['id'] in referenced:
                sessions.append({k:v for k,v in session.items() if k not in ('rows', 'modelDescriptor')})
        return sorted(sessions, key=lambda s:s['createdAt'], reverse=True)

    def create(self, body):
        scenario = self.store.scenarios.get(body['scenarioId'], body.get('scenarioVersion')) if body.get('scenarioId') else None
        if scenario and ('config' in body or body.get('modelId', scenario['modelId']) != scenario['modelId']):
            raise ValueError('Saved scenarios run their exact version; save parameter edits as a new version first.')
        model = resolve(scenario['modelId'] if scenario else body.get('modelId', MODEL_ID))
        if scenario and scenario['modelVersion'] != model.version:
            raise ValueError('The scenario model version is unavailable for new runs.')
        config = model.validate(scenario['config'] if scenario else body.get('config', {}), randomize=True)
        workspace_id = body.get('workspaceId', scenario['workspaceId'] if scenario else None)
        if scenario and workspace_id != scenario['workspaceId']:
            raise ValueError('Scenario belongs to another Workspace.')
        if workspace_id:
            self.store.workspace(workspace_id)
        from .workspace import now
        descriptor = deepcopy(model.describe())
        if 'simulation' not in descriptor['capabilities']:
            raise ValueError('This model does not support simulation.')
        session = dict(id=uuid4().hex, title=self.store.name(body.get('title') or (scenario['name'] if scenario else f"{descriptor['faults'][config['fault']]} experiment")),
                       modelId=model.id, modelVersion=model.version, modelDescriptor=descriptor, config=config, rows=model.simulate(config),
                       scenarioId=scenario['id'] if scenario else None, scenarioVersion=scenario['version'] if scenario else None,
                       scenarioSnapshot=deepcopy(scenario), groundTruth=model.truth(config) if 'ground-truth' in descriptor['capabilities'] else None, status='completed',
                       createdAt=now(), workspaceId=workspace_id, datasetId=None)
        folder = self.folder(session['id'])
        folder.mkdir()
        self.write(folder / 'session.json', session)
        return session

    def window(self, identity, body):
        session = self.get(identity)
        end = body.get('asOf', session['config']['duration'])
        start = body.get('windowStart', 0)
        if not finite(end) or not finite(start) or not 0 <= start <= end <= session['config']['duration']:
            raise ValueError('Choose a window inside this simulation.')
        rows = [r for r in session['rows'] if start <= r['t'] <= end]
        if len(rows) < 2:
            raise ValueError('This window has fewer than two observations.')
        return session, rows

    def analysis(self, identity, body):
        session, rows = self.window(identity, body)
        model = self.model(session, 'observation')
        key = (identity, rows[0]['t'], rows[-1]['t'])
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                return {**self.cache[key], 'asOf':body.get('asOf', rows[-1]['t'])}
        result = dict(**model.observe(session, rows), asOf=body.get('asOf', rows[-1]['t']),
                      observedThrough=rows[-1]['t'], windowStart=rows[0]['t'], samples=len(rows),
                      modelId=session['modelId'], modelVersion=session['modelVersion'])
        with self.lock:
            self.cache[key] = result
            while len(self.cache) > 128:
                self.cache.popitem(last=False)
        return result

    def record(self, identity, kind, body, result):
        from .workspace import now
        session = self.get(identity)
        record = dict(id=uuid4().hex, kind=kind, request=deepcopy(body), result=result, createdAt=now(),
                      modelId=session['modelId'], modelVersion=session['modelVersion'],
                      scenarioId=session['scenarioId'], scenarioVersion=session['scenarioVersion'])
        folder = self.folder(identity) / 'runs'
        folder.mkdir(exist_ok=True)
        self.write(folder / f"{record['id']}.json", record)
        return record

    def runs(self, identity):
        self.get(identity)
        return sorted([json.loads(p.read_text(encoding='utf-8')) for p in (self.folder(identity)/'runs').glob('*.json')], key=lambda r:r['createdAt'], reverse=True)

    def run(self, identity, run_id):
        self.get(identity)
        if not isinstance(run_id, str) or not re.fullmatch('[a-f0-9]{32}', run_id):
            raise KeyError('Simulation experiment not found.')
        path = self.folder(identity) / 'runs' / f'{run_id}.json'
        if not path.exists():
            raise KeyError('Simulation experiment not found.')
        return json.loads(path.read_text(encoding='utf-8'))

    def tools(self, identity, body):
        session, rows = self.window(identity, body)
        result = self.model(session, 'investigation-tools').tools(session, rows, body)
        return self.record(identity, 'tools', body, result)

    def intervene(self, identity, body):
        session, rows = self.window(identity, body)
        result = self.model(session, 'interventions').intervene(session, rows, body)
        return self.record(identity, 'intervention', body, result)

    def save(self, identity, body):
        with self.lock:
            session = self.get(identity)
            workspace_id = body.get('workspaceId') or session.get('workspaceId')
            self.store.workspace(workspace_id)
            if session.get('datasetId') and session.get('workspaceId') == workspace_id:
                return self.store.dataset(session['datasetId'])
            descriptor = session['modelDescriptor']
            columns = ['t', *[s['key'] for s in descriptor['signals']]]
            text = ','.join(columns) + '\n' + '\n'.join(','.join(str(r[k]) for k in columns) for r in session['rows'])
            dataset = self.store.import_dataset(workspace_id, dict(csv=text, name=body.get('name') or session['title'], filename=f'{identity}.csv'),
                                                model=dict(id=session['modelId'], version=session['modelVersion'], name=descriptor['name'],
                                                    simulationId=identity, scenarioId=session['scenarioId'], scenarioVersion=session['scenarioVersion'],
                                                    scenarioSnapshot=session.get('scenarioSnapshot'), config=session['config'], groundTruth=session['groundTruth'],
                                                    signals=descriptor['signals'], capabilities=descriptor['capabilities']))
            session.update(workspaceId=workspace_id, datasetId=dataset['id'])
            self.write(self.folder(identity) / 'session.json', session)
            return dataset
