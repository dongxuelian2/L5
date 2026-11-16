"""Workspace persistence, provenance and exports for coupled-tank recovery studies."""
import csv
from io import StringIO
import json
from uuid import uuid4

from .datasets import prepare_csv
from .reachability import DISTURBANCES, MODEL, Study, defaults, vector

STRATEGIES = ('policy', 'hold', 'drain', 'fill')
COLUMNS = {
    'level1': ('Tank 1 physical level', 'm'),
    'level2': ('Tank 2 physical level', 'm'),
    'pump': ('Pump command', '%'),
    'valve': ('Connection valve opening', 'fraction'),
    'safetyMargin': ('Minimum signed level margin', 'm'),
}


class RecoveryStudies:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS recovery_studies (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                name TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL)''')
            db.execute('CREATE INDEX IF NOT EXISTS recovery_studies_workspace ON recovery_studies(workspace_id, created_at)')

    def index(self, workspace):
        self.store.workspace(workspace)
        with self.store.connect() as db:
            studies = [dict(row) for row in db.execute('''SELECT id, name, created_at FROM recovery_studies
                WHERE workspace_id=? ORDER BY created_at DESC, rowid DESC''', (workspace,))]
        return dict(studies=studies, defaults=defaults(), disturbances=DISTURBANCES,
                    scenarios=[s for s in self.store.scenarios.list(workspace) if s['modelId'] == MODEL],
                    incidents=[dict(id=i['id'], title=i['title']) for i in self.store.incidents.list(workspace)])

    def get(self, workspace, identity):
        self.store.workspace(workspace)
        with self.store.connect() as db:
            row = db.execute('SELECT payload FROM recovery_studies WHERE workspace_id=? AND id=?',
                             (workspace, identity)).fetchone()
        if row is None:
            raise KeyError('Recovery study not found.')
        return json.loads(row['payload'])

    def compute(self, workspace, body):
        self.store.workspace(workspace)
        scenario = incident = None
        if body.get('scenarioId'):
            if body.get('scenarioVersion') is None:
                raise ValueError('Select an exact scenario version.')
            scenario = self.store.scenarios.get(body['scenarioId'], body['scenarioVersion'])
            if scenario['workspaceId'] != workspace or scenario['modelId'] != MODEL:
                raise ValueError('Choose a coupled-tank scenario from this workspace.')
        if body.get('incidentId'):
            if not isinstance(body['incidentId'], str):
                raise ValueError('Choose an incident from this workspace.')
            linked = self.store.incidents.get(body['incidentId'])
            if linked['workspace_id'] != workspace:
                raise ValueError('Choose an incident from this workspace.')
            incident = dict(id=linked['id'], title=linked['title'])
        config = body.get('config', {})
        study = Study(config)
        initial = body.get('initial')
        evaluation = None
        if initial is not None:
            if not isinstance(initial, dict) or not vector(initial.get('heads'), 2):
                raise ValueError('Enter two physical heads between 0 and 10.8 m.')
            scenario_name = initial.get('disturbance', 'nominal')
            if not isinstance(scenario_name, str) or scenario_name not in DISTURBANCES:
                raise ValueError('Choose a modeled replay disturbance.')
            heads, previous = initial['heads'], initial.get('previousAction')
            replays = {strategy: study.replay(heads, previous, strategy, scenario_name) for strategy in STRATEGIES}
            evaluation = dict(initial=dict(heads=list(heads), previousAction=int(previous), disturbance=scenario_name),
                              classification=study.inspect(heads, int(previous)), replays=replays,
                              integrationStep=study.config['integrationStep']*.5)
        return dict(analysis=study.result(), evaluation=evaluation, scenario=scenario, incident=incident)

    def save(self, workspace, body):
        from .workspace import now

        name = self.store.name(body.get('name') or 'Coupled-tank recovery')
        result = self.compute(workspace, body)
        identity, stamp = uuid4().hex, now()
        result.update(id=identity, name=name, workspaceId=workspace, createdAt=stamp)
        with self.store.connect() as db:
            db.execute('INSERT INTO recovery_studies VALUES (?,?,?,?,?)',
                       (identity, workspace, name, stamp, json.dumps(result, ensure_ascii=False, allow_nan=False)))
            db.execute('UPDATE workspaces SET updated_at=? WHERE id=?', (stamp, workspace))
        return result

    def export_dataset(self, workspace, identity, strategy):
        saved = self.get(workspace, identity)
        evaluation = saved['evaluation']
        if evaluation is None or strategy not in STRATEGIES:
            raise ValueError('Select a saved recovery trajectory.')
        replay = evaluation['replays'][strategy]
        stream = StringIO()
        writer = csv.DictWriter(stream, ['t', *COLUMNS], lineterminator='\n')
        writer.writeheader()
        writer.writerows(replay['trajectory'])
        source = stream.getvalue()
        metadata, times, values = prepare_csv(source, dict(timeColumn='t', timeKind='numeric'))
        for column in metadata['columns']:
            column['displayName'], column['unit'] = COLUMNS[column['name']]
            column.update(device=MODEL, tags=['simulation', 'recovery'])
        metadata.update(filename=f'l5-recovery-{identity}-{strategy}.csv',
                        recovery=dict(studyId=identity, strategy=strategy, modelId=MODEL,
                                      modelVersion=saved['analysis']['modelVersion'], status=replay['status'],
                                      disturbance=evaluation['initial']['disturbance'], scope='simulation-only'))
        return self.store.save_dataset(workspace, f"{saved['name'][:140]} · {strategy}", metadata, times, values, source)
