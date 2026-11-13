"""Local, versioned engineering constraint configurations and assessment snapshots."""
from __future__ import annotations

import gzip
import json
from uuid import uuid4

from .workspace import now


SCHEMA_VERSION = 1
EVIDENCE_KINDS = ('safety-observed', 'safety-predicted')


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


class SafetyService:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS safety_configurations (
                    id TEXT NOT NULL, revision INTEGER NOT NULL,
                    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    dataset_id TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
                    name TEXT NOT NULL, constraints TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY (id, revision));
                CREATE INDEX IF NOT EXISTS safety_configurations_owner
                    ON safety_configurations(workspace_id, id, revision);
                CREATE TABLE IF NOT EXISTS safety_assessments (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    dataset_id TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
                    name TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS safety_assessments_owner
                    ON safety_assessments(workspace_id, created_at);
            ''')

    def dataset(self, workspace_id, dataset_id):
        dataset = self.store.dataset(dataset_id)
        if dataset['workspace_id'] != workspace_id:
            raise ValueError('Dataset belongs to a different workspace.')
        return dataset

    @staticmethod
    def signals(dataset):
        return {column['id']: column for column in dataset['metadata']['columns']}

    @staticmethod
    def configuration(row, created_at):
        return dict(id=row['id'], revision=row['revision'], workspaceId=row['workspace_id'],
                    datasetId=row['dataset_id'], name=row['name'], constraints=json.loads(row['constraints']),
                    createdAt=created_at, updatedAt=row['created_at'])

    def configurations(self, workspace_id):
        self.store.workspace(workspace_id)
        with self.store.connect() as db:
            rows = db.execute('''SELECT c.*, history.first_stamp FROM safety_configurations c JOIN
                (SELECT id, MAX(revision) AS latest, MIN(created_at) AS first_stamp
                 FROM safety_configurations WHERE workspace_id=? GROUP BY id) history
                ON c.id=history.id AND c.revision=history.latest
                ORDER BY c.created_at DESC, c.id''', (workspace_id,)).fetchall()
        return [self.configuration(row, row['first_stamp']) for row in rows]

    def get_configuration(self, workspace_id, identity, revision=None):
        if revision is not None and (type(revision) is not int or revision < 1):
            raise ValueError('Choose a valid constraint configuration revision.')
        with self.store.connect() as db:
            row = db.execute('''SELECT c.*, initial.created_at AS first_stamp
                FROM safety_configurations c
                JOIN safety_configurations initial ON c.id=initial.id AND initial.revision=1
                WHERE c.workspace_id=? AND c.id=? AND (? IS NULL OR c.revision=?)
                ORDER BY c.revision DESC LIMIT 1''', (workspace_id, identity, revision, revision)).fetchone()
        if row is None:
            raise KeyError('Constraint configuration not found.')
        return self.configuration(row, row['first_stamp'])

    def save_configuration(self, workspace_id, body, identity=None):
        from .safety_constraints import normalize_constraints

        dataset = self.dataset(workspace_id, body.get('datasetId', ''))
        definitions = normalize_constraints(body.get('constraints'), self.signals(dataset))
        name = self.store.name(body.get('name'))
        revision = 1
        with self.store.connect() as db:
            if identity:
                db.execute('BEGIN IMMEDIATE')
                latest = db.execute('''SELECT dataset_id, revision FROM safety_configurations
                    WHERE workspace_id=? AND id=? ORDER BY revision DESC LIMIT 1''',
                    (workspace_id, identity)).fetchone()
                if latest is None:
                    raise KeyError('Constraint configuration not found.')
                if latest['dataset_id'] != dataset['id']:
                    raise ValueError('A constraint configuration keeps its original dataset.')
                if type(body.get('revision')) is not int or body['revision'] != latest['revision']:
                    raise ValueError('Constraint configuration changed. Reload it before editing.')
                revision = latest['revision'] + 1
            else:
                identity = uuid4().hex
            stamp = now()
            db.execute('INSERT INTO safety_configurations VALUES (?,?,?,?,?,?,?)',
                       (identity, revision, workspace_id, dataset['id'], name, encode(definitions), stamp))
            db.execute('UPDATE workspaces SET updated_at=? WHERE id=?', (stamp, workspace_id))
        return self.get_configuration(workspace_id, identity, revision)

    def evaluate(self, workspace_id, body):
        from .safety_constraints import evaluate_constraints, normalize_constraints

        dataset = self.dataset(workspace_id, body.get('datasetId', ''))
        metadata = dataset['metadata']
        signals = self.signals(dataset)
        configuration_id = body.get('configurationId')
        if configuration_id is None:
            configuration = dict(constraints=normalize_constraints(body.get('constraints'), signals))
        else:
            if not isinstance(configuration_id, str) or body.get('configurationRevision') is None:
                raise ValueError('Choose a saved configuration and its revision.')
            configuration = self.get_configuration(workspace_id, configuration_id, body['configurationRevision'])
            if configuration['datasetId'] != dataset['id']:
                raise ValueError('The constraint configuration belongs to a different dataset.')
            if 'constraints' in body and normalize_constraints(body['constraints'], signals) != configuration['constraints']:
                raise ValueError('Edited constraints must be saved or evaluated independently.')

        name = self.store.name(body.get('name', f"{dataset['name'][:138]} · Safety assessment"))
        times, values = self.store.load_data(dataset)
        observed = self.store.observation_mask(dataset)
        definitions = configuration['constraints']
        used = {term['signalId'] for definition in definitions for term in definition['terms']}
        indexes = {signal_id: index for index, signal_id in enumerate(signals) if signal_id in used}
        historical = evaluate_constraints(
            times, {key: values[:, i] for key, i in indexes.items()}, signals, definitions,
            observed={key: observed[:, i] for key, i in indexes.items()},
            gap_threshold=metadata['quality']['gapThreshold'])
        forecast, options = None, body.get('forecast')
        if options is not None:
            if not isinstance(options, dict):
                raise ValueError('Forecast options must be a JSON object.')
            from .safety_forecast import forecast_constraints
            forecast = forecast_constraints(dataset, times, values, definitions, options, observed=observed)
        model = metadata.get('model')
        source = dict(datasetId=dataset['id'], datasetName=dataset['name'], datasetCreatedAt=dataset['created_at'],
                      clock=metadata['clock'], time=metadata['time'], sourceRows=metadata['rowCount'],
                      invalidTimeCount=metadata['quality']['invalidTimeCount'],
                      observationStart=float(times[0]), observedThrough=float(times[-1]),
                      signals=[signals[key] for key in indexes],
                      model={key: model[key] for key in ('id', 'version', 'name', 'simulationId', 'scenarioId', 'scenarioVersion')
                             if key in model} if model else None)
        if metadata.get('transformation'):
            source['transformation'] = {key: metadata['transformation'][key]
                                        for key in ('definitionId', 'revision', 'executionId', 'createdAt')}
        return dict(schemaVersion=SCHEMA_VERSION, workspaceId=workspace_id, datasetId=dataset['id'],
                    name=name, createdAt=now(), configuration=configuration, source=source,
                    observed=historical, forecast=forecast, forecastOptions=options)

    def assessments(self, workspace_id):
        self.store.workspace(workspace_id)
        with self.store.connect() as db:
            rows = db.execute('''SELECT * FROM safety_assessments
                WHERE workspace_id=? ORDER BY created_at DESC, id''', (workspace_id,)).fetchall()
        return [dict(id=r['id'], workspaceId=workspace_id, datasetId=r['dataset_id'],
                     name=r['name'], createdAt=r['created_at']) for r in rows]

    def assessment_path(self, workspace_id, identity):
        return self.store.root / workspace_id / 'safety-assessments' / f'{identity}.json.gz'

    def save_assessment(self, workspace_id, body):
        assessment = self.evaluate(workspace_id, body)
        identity = assessment['id'] = uuid4().hex
        path = self.assessment_path(workspace_id, identity)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        try:
            with gzip.open(temporary, 'wt', encoding='utf-8', compresslevel=4) as file:
                json.dump(assessment, file, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
            temporary.replace(path)
            with self.store.connect() as db:
                db.execute('INSERT INTO safety_assessments VALUES (?,?,?,?,?)',
                           (identity, workspace_id, assessment['datasetId'], assessment['name'], assessment['createdAt']))
                db.execute('UPDATE workspaces SET updated_at=? WHERE id=?', (assessment['createdAt'], workspace_id))
        except Exception:
            temporary.unlink(missing_ok=True)
            path.unlink(missing_ok=True)
            raise
        return assessment

    def get_assessment(self, workspace_id, identity):
        with self.store.connect() as db:
            row = db.execute('SELECT id FROM safety_assessments WHERE workspace_id=? AND id=?',
                             (workspace_id, identity)).fetchone()
        if row is None:
            raise KeyError('Safety assessment not found.')
        with gzip.open(self.assessment_path(workspace_id, row['id']), 'rt', encoding='utf-8') as file:
            return json.load(file)

    @staticmethod
    def evidence(assessment, kind, constraint_id, index, raw=False):
        if kind not in EVIDENCE_KINDS:
            raise ValueError('Choose observed or predicted constraint evidence.')
        forecast = assessment.get('forecast') or {}
        if type(raw) is not bool or (raw and kind != 'safety-observed'):
            raise ValueError('Raw threshold evidence is available for observations only.')
        if kind == 'safety-observed':
            result = next((r for r in assessment['observed'] if r['constraint']['id'] == constraint_id), None)
        else:
            result = next((r for r in forecast.get('constraints', []) if r['constraintId'] == constraint_id), None)
        intervals = result['rawViolationIntervals' if raw else 'intervals'] if result else []
        if type(index) is not int or not 0 <= index < len(intervals):
            raise ValueError('Choose a saved violation interval.')
        interval = intervals[index]
        if interval.get('state', 'violation') != 'violation':
            raise ValueError('Choose a saved violation interval.')
        definition = next(c for c in assessment['configuration']['constraints'] if c['id'] == constraint_id)
        return dict(assessmentId=assessment['id'], datasetId=assessment['datasetId'], title=assessment['name'],
                    clock=assessment['source']['clock'], safety=dict(kind=kind.removeprefix('safety-'), raw=raw,
                        constraintId=constraint_id, constraintName=definition['name'], unit=result.get('marginUnit', definition['unit']),
                        interval=interval, asOf=forecast.get('observedThrough') if kind == 'safety-predicted' else None,
                        forecastOrigin=forecast.get('requestedAsOf') if kind == 'safety-predicted' else None,
                        timeToViolation=result.get('timeToViolation') if kind == 'safety-predicted' else None))

    def attach(self, workspace_id, identity, body):
        incident = self.store.incidents.row(body.get('incidentId', ''))
        if incident['workspace_id'] != workspace_id:
            raise ValueError('Incident belongs to a different workspace.')
        if body.get('kind') not in ('observed', 'predicted'):
            raise ValueError('Choose observed or predicted constraint evidence.')
        return self.store.incidents.add_link(incident['id'], dict(
            kind='safety-' + body['kind'], assessmentId=identity,
            constraintId=body.get('constraintId'), intervalIndex=body.get('intervalIndex'), raw=body.get('raw', False)))
