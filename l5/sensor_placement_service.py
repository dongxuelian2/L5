"""Saved sensor-design snapshots and Signal Explorer dataset publishing."""

from __future__ import annotations

import csv
import io
import json
from uuid import uuid4

from .datasets import prepare_csv
from .sensor_placement import CONDITIONS, KEYS, MODEL, MODEL_FIELDS, SENSORS, analyze, defaults
from .workspace import now


class SensorPlacementService:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS sensor_placement_runs (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                name TEXT NOT NULL, created_at TEXT NOT NULL, analysis TEXT NOT NULL
            )''')

    def options(self):
        model = MODEL.describe()
        return dict(models=[dict(id=MODEL.id, version=MODEL.version, name=model['name'])],
                    conditions=list(CONDITIONS), defaults=defaults(), sensors=SENSORS,
                    modelFields=[field for field in model['configFields'] if field['key'] in MODEL_FIELDS])

    def list(self, workspace_id):
        self.store.workspace(workspace_id)
        with self.store.connect() as db:
            return [dict(row) for row in db.execute('''SELECT id, name, created_at FROM sensor_placement_runs
                WHERE workspace_id=? ORDER BY created_at DESC''', (workspace_id,))]

    def get(self, workspace_id, identity):
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM sensor_placement_runs WHERE workspace_id=? AND id=?',
                             (workspace_id, identity)).fetchone()
        if row is None:
            raise KeyError('Sensor placement analysis not found.')
        return {**dict(row), 'analysis': json.loads(row['analysis'])}

    def run(self, workspace_id, body):
        self.store.workspace(workspace_id)
        name = self.store.name(body.get('name'))
        result = analyze(body.get('config', {}))
        identity, stamp = uuid4().hex, now()
        with self.store.connect() as db:
            db.execute('INSERT INTO sensor_placement_runs VALUES (?,?,?,?,?)',
                       (identity, workspace_id, name, stamp, json.dumps(result, allow_nan=False)))
            db.execute('UPDATE workspaces SET updated_at=? WHERE id=?', (stamp, workspace_id))
        return dict(id=identity, workspace_id=workspace_id, name=name, created_at=stamp, analysis=result)

    def dataset(self, workspace_id, identity, body):
        run = self.get(workspace_id, identity)
        analysis = run['analysis']
        condition_id, hypothesis = body.get('condition'), body.get('hypothesis')
        cohort_id = body.get('cohort')
        sensors = body.get('sensors')
        condition = next((c for c in analysis['conditions'] if c['id'] == condition_id), None)
        if condition is None or hypothesis not in analysis['hypotheses']:
            raise ValueError('Select a saved operating condition and hypothesis.')
        if (not isinstance(sensors, list) or not sensors or any(s not in KEYS for s in sensors) or
                len(set(sensors)) != len(sensors)):
            raise ValueError('Select distinct trajectory sensors.')
        index = analysis['hypotheses'].index(hypothesis)
        if cohort_id is None:
            values = condition['templates'][index]
        else:
            cohort = next((c for c in analysis['evaluation']['cohorts'] if c['id'] == cohort_id), None)
            if cohort is None or condition_id != analysis['conditions'][0]['id']:
                raise ValueError('No held-out trajectory matches the selected operating condition.')
            values = cohort['representative'][index]
        source = io.StringIO(newline='')
        writer = csv.writer(source)
        writer.writerow(['time', *sensors])
        selected = [KEYS.index(key) for key in sensors]
        writer.writerows([t, *(row[i] for i in selected)] for t, row in zip(condition['times'], values))
        payload = source.getvalue()
        metadata, times, matrix = prepare_csv(payload, dict(timeColumn='time', timeUnit='seconds'))
        metadata['sensorPlacement'] = dict(runId=identity, condition=condition_id, hypothesis=hypothesis,
                                           cohort=cohort_id, modelId=MODEL.id, modelVersion=analysis['modelVersion'])
        by_key = {sensor['key']: sensor for sensor in SENSORS}
        for column in metadata['columns']:
            sensor = by_key[column['name']]
            column.update(displayName=sensor['label'], unit=sensor['unit'], device=MODEL.id,
                          logicalKey=sensor['tag'], tags=['simulation', 'sensor-placement'])
        label = ' · '.join((run['name'], hypothesis, cohort_id or condition_id))
        return self.store.save_dataset(workspace_id, label[:160], metadata, times, matrix, payload)
