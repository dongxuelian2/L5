"""Versioned definitions, separate from immutable simulation trajectories."""
import json
from uuid import uuid4
from .models import resolve


class ScenarioService:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS model_scenarios (
                    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    model_id TEXT NOT NULL, current_version INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS model_scenario_versions (
                    scenario_id TEXT NOT NULL REFERENCES model_scenarios(id) ON DELETE CASCADE,
                    version INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(scenario_id,version));
            ''')

    def get(self, identity, version=None):
        if not isinstance(identity, str):
            raise ValueError('Scenario ID must be text.')
        with self.store.connect() as db:
            scenario = db.execute('SELECT * FROM model_scenarios WHERE id=?',(identity,)).fetchone()
            if scenario is None:
                raise KeyError('Scenario not found.')
            if version is not None and (isinstance(version,bool) or not isinstance(version,int) or version < 1):
                raise ValueError('Choose a positive integer scenario version.')
            row = db.execute('SELECT payload FROM model_scenario_versions WHERE scenario_id=? AND version=?',
                (identity,scenario['current_version'] if version is None else version)).fetchone()
        if row is None:
            raise KeyError('Scenario version not found.')
        return json.loads(row['payload'])

    def versions(self, identity):
        self.get(identity)
        with self.store.connect() as db:
            return [json.loads(r['payload']) for r in db.execute(
                'SELECT payload FROM model_scenario_versions WHERE scenario_id=? ORDER BY version DESC',(identity,))]

    def list(self, workspace_id):
        self.store.workspace(workspace_id)
        with self.store.connect() as db:
            return [json.loads(r['payload']) for r in db.execute('''SELECT v.payload FROM model_scenarios s
                JOIN model_scenario_versions v ON v.scenario_id=s.id AND v.version=s.current_version
                WHERE s.workspace_id=? ORDER BY s.rowid DESC''',(workspace_id,))]

    def save(self, workspace_id, body, identity=None):
        from .workspace import now
        self.store.workspace(workspace_id)
        previous = self.get(identity) if identity else None
        expected = body.get('expectedVersion')
        if expected is not None and (isinstance(expected,bool) or not isinstance(expected,int) or expected < 1):
            raise ValueError('expectedVersion must be a positive integer.')
        if previous and previous['workspaceId'] != workspace_id:
            raise ValueError('Scenario belongs to another Workspace.')
        model = resolve(body.get('modelId', previous['modelId'] if previous else None))
        if previous and (model.id != previous['modelId'] or model.version != previous['modelVersion']):
            raise ValueError('A scenario retains its model and version; create a new scenario for another model.')
        description = body.get('description',previous['description'] if previous else '')
        if not isinstance(description,str) or len(description) > 10000:
            raise ValueError('Scenario description must be text of at most 10,000 characters.')
        config = model.validate(body.get('config',previous['config'] if previous else {}))
        stamp = now(); identity = identity or uuid4().hex
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT current_version FROM model_scenarios WHERE id=?',(identity,)).fetchone()
            current = row['current_version'] if row else 0
            if previous and (current != previous['version'] or body.get('expectedVersion',current) != current):
                raise ValueError('Scenario changed; reopen the latest version before saving.')
            version = current+1
            snapshot = dict(id=identity,workspaceId=workspace_id,modelId=model.id,modelVersion=model.version,
                version=version,name=self.store.name(body.get('name',previous['name'] if previous else 'New scenario')),
                description=description,config=config,createdAt=previous['createdAt'] if previous else stamp,updatedAt=stamp)
            db.execute('INSERT INTO model_scenarios VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET current_version=excluded.current_version',
                (identity,workspace_id,model.id,version))
            db.execute('INSERT INTO model_scenario_versions VALUES (?,?,?)',
                (identity,version,json.dumps(snapshot,ensure_ascii=False,allow_nan=False)))
            db.execute('UPDATE workspaces SET updated_at=? WHERE id=?',(stamp,workspace_id))
        return snapshot

    def copy(self, identity, body):
        previous = self.get(identity,body.get('version'))
        return self.save(previous['workspaceId'],dict(modelId=previous['modelId'],config=previous['config'],
            name=body.get('name',previous['name'][:150]+' · copy'),description=previous['description']))
