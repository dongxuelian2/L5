"""Saved input-design experiments and Dataset publication."""
from __future__ import annotations

import csv
from io import StringIO
import json
from threading import Lock
from uuid import uuid4

from .datasets import prepare_csv
from .experiments import encode
from .workspace import now


class DesignExperiments:
    """Input designs precede data collection and have immutable result snapshots."""

    def __init__(self, store):
        self.store = store
        self.optimizer = Lock()
        self.publication = Lock()
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS design_experiments (
                    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    name TEXT NOT NULL, status TEXT NOT NULL, snapshot TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS design_experiments_workspace
                    ON design_experiments(workspace_id, created_at);
            ''')

    def list(self, workspace_id):
        self.store.workspace(workspace_id)
        with self.store.connect() as db:
            return [dict(row) for row in db.execute('''
                SELECT id, name, status, created_at FROM design_experiments
                WHERE workspace_id=? ORDER BY created_at DESC, id''', (workspace_id,))]

    def get(self, workspace_id, identity):
        with self.store.connect() as db:
            result = db.execute('SELECT * FROM design_experiments WHERE workspace_id=? AND id=?',
                                (workspace_id, identity)).fetchone()
        if result is None:
            raise KeyError('Input design experiment not found.')
        fields = dict(result)
        return fields | {'snapshot': json.loads(fields['snapshot'])}

    def create(self, workspace_id, body):
        from .experiment_design import design
        self.store.workspace(workspace_id)
        name = self.store.name(body.get('name'))
        if not self.optimizer.acquire(blocking=False):
            return None
        try:
            result = design(body.get('config'))
            identity, created = uuid4().hex, now()
            self.store.workspace(workspace_id)
            with self.store.connect() as db:
                db.execute('INSERT INTO design_experiments VALUES (?,?,?,?,?,?)',
                           (identity, workspace_id, name, result['status'], encode(result), created))
                db.execute('UPDATE workspaces SET updated_at=? WHERE id=?', (created, workspace_id))
            return dict(id=identity, workspace_id=workspace_id, name=name, created_at=created,
                        status=result['status'], snapshot=result)
        finally:
            self.optimizer.release()

    def publish(self, workspace_id, identity, body):
        from .models.tanks import SIGNALS
        record = self.get(workspace_id, identity)
        strategy, scenario = body.get('designId'), body.get('scenarioId')
        design = next((d for d in record['snapshot']['designs'] if d['id'] == strategy), None)
        if design is None or not isinstance(scenario, str) or scenario not in design['reports']:
            raise ValueError('Select a saved schedule and parameter configuration.')
        report = design['reports'][scenario]
        provenance = dict(experimentId=identity, strategy=strategy, scenario=scenario,
                          modelId=record['snapshot']['config']['modelId'], seed=record['snapshot']['config']['seed'],
                          feasible=design['inputFeasible'] and report['feasible'])
        with self.publication:
            # Repeated publication of the same immutable sample returns the same Dataset.
            with self.store.connect() as db:
                existing = db.execute('''
                    SELECT id FROM datasets WHERE workspace_id=?
                    AND json_extract(metadata,'$.designExperiment.experimentId')=?
                    AND json_extract(metadata,'$.designExperiment.strategy')=?
                    AND json_extract(metadata,'$.designExperiment.scenario')=?
                    ORDER BY created_at LIMIT 1''', (workspace_id, identity, strategy, scenario)).fetchone()
            if existing:
                return self.store.dataset(existing['id']), 200

            columns = report['sampledInputs'] | report['observations']
            output = StringIO()
            writer = csv.writer(output, lineterminator='\n')
            writer.writerow(['time', *columns])
            writer.writerows(zip(report['times'], *columns.values()))
            source = output.getvalue()
            metadata, times, values = prepare_csv(source, dict(timeColumn='time', timeKind='numeric'))
            signals = {s['key']: s for s in SIGNALS}
            for column in metadata['columns']:
                signal = signals[column['name']]
                column.update(unit=signal['unit'], displayName=signal['label'], logicalKey=signal['tag'],
                              tags=['simulation', 'experiment-design'], device='Coupled-Tank Process')
            suffix = f' / {strategy} / {scenario}'
            metadata.update(filename=f'{strategy}-{scenario}-observations.csv', designExperiment=provenance)
            return self.store.save_dataset(workspace_id, record['name'][:160-len(suffix)]+suffix, metadata,
                                           times, values, source), 201


def route(service, method, workspace_id, rest, body):
    if not rest:
        if method == 'GET':
            from .experiment_design import DEFAULT, MEASUREMENTS, PARAMETERS
            return dict(experiments=service.list(workspace_id), defaults=DEFAULT,
                        measurements=MEASUREMENTS, parameters=PARAMETERS), 200
        if method == 'POST':
            created = service.create(workspace_id, body)
            if created is None:
                return {'error': 'Another input design is computing. Try again when it finishes.'}, 409
            return created, 201
    if len(rest) == 1 and method == 'GET':
        return service.get(workspace_id, rest[0]), 200
    if len(rest) == 2 and rest[1] == 'datasets' and method == 'POST':
        return service.publish(workspace_id, rest[0], body)
    return None, 404
