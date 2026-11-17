"""Durable sensor diagnostics alongside existing Dataset/Incident services."""
from __future__ import annotations

import json
from uuid import uuid4

from .sensor_health import diagnose
from .sensor_health_tanks import PARAMETERS, ROLES
from .units import canonical
from .workspace import now


class SensorHealthService:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS sensor_diagnostics (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    dataset_id TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
                    name TEXT NOT NULL, summary TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS diagnostics_workspace ON sensor_diagnostics(workspace_id, created_at);
            ''')

    def list(self, workspace_id):
        self.store.workspace(workspace_id)
        with self.store.connect() as db:
            return [{**dict(r), 'summary': json.loads(r['summary'])} for r in db.execute(
                'SELECT * FROM sensor_diagnostics WHERE workspace_id=? ORDER BY created_at DESC,id', (workspace_id,))]

    def get(self, identity):
        with self.store.connect() as db:
            row = db.execute('SELECT workspace_id FROM sensor_diagnostics WHERE id=?', (identity,)).fetchone()
        if row is None:
            raise KeyError('Sensor diagnostic not found.')
        return json.loads((self.store.root / row['workspace_id'] / 'sensor-health' / f'{identity}.json').read_text(encoding='utf-8'))

    def model_defaults(self, dataset_id):
        dataset = self.store.dataset(dataset_id)
        metadata = dataset['metadata'].get('model', {})
        if metadata.get('id') != 'coupled-tanks':
            return None
        # Explicit simulator schema, never guess physical meaning from CSV names.
        return dict(kind='coupled-tanks', mapping={k: k for k in ROLES},
            parameters={k: metadata.get('config', {}).get(k, v) for k, v in PARAMETERS.items()})

    def run(self, workspace_id, body):
        self.store.workspace(workspace_id)
        dataset = self.store.dataset(body.get('datasetId', ''))
        if dataset['workspace_id'] != workspace_id:
            raise ValueError('Dataset belongs to a different workspace.')
        times, values = self.store.load_data(dataset)
        columns = dataset['metadata']['columns']
        config = {k: v for k, v in body.items() if k not in ('datasetId', 'name')}
        result = diagnose(times, values, [s['name'] for s in columns], config, observed=self.store.observation_mask(dataset))
        units = {s['name']: s.get('unit', '') for s in columns}
        for relation in result['config']['relationships']:
            a, b = (units[relation[k]] for k in ('target', 'predictor'))
            if relation['kind'] == 'agreement' and a and b and canonical(a) != canonical(b):
                raise ValueError('Redundant agreement requires matching units; convert signals in Transformations first.')
        if result['config'].get('model'):
            for role, name in result['config']['model']['mapping'].items():
                expected = {'m'} if role in ('level1', 'level2') else {'m³/s'} if role in ('inlet', 'transfer', 'outlet') else {'%'} if role == 'pump' else {'fraction', '1'}
                if units[name] and canonical(units[name]) not in expected:
                    raise ValueError('Convert tank levels to m, flows to m³/s, pump command to %, and opening to fraction before diagnosis.')
        identity, stamp = uuid4().hex, now()
        result.update(id=identity, workspaceId=workspace_id, datasetId=dataset['id'],
            name=self.store.name(body.get('name') or f"Sensor health · {dataset['name']}"), createdAt=stamp,
            signalIdentities=[{k: s[k] for k in ('id', 'name', 'displayName', 'unit') if k in s} for s in columns if s['name'] in config['signals']],
            datasetSnapshot=dict(name=dataset['name'], time=dataset['metadata']['time'], createdAt=dataset['created_at']))
        folder = self.store.root / workspace_id / 'sensor-health'
        folder.mkdir(exist_ok=True)
        path = folder / f'{identity}.json'
        self.store.runtime.write(path, result)
        try:
            with self.store.connect() as db:
                db.execute('INSERT INTO sensor_diagnostics VALUES (?,?,?,?,?,?)',
                    (identity, workspace_id, dataset['id'], result['name'], json.dumps(result['summary']), stamp))
                db.execute('UPDATE workspaces SET updated_at=? WHERE id=?', (stamp, workspace_id))
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return result
