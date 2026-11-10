"""Local estimation experiments, frozen inputs and ordinary Dataset exports."""
from __future__ import annotations

import csv
import hashlib
from io import StringIO
import json
import random
from uuid import uuid4

import numpy as np

from .datasets import prepare_csv
from .estimation import MODEL_KEYS, STATES, estimate, model_config, observability, score, settings
from .models.base import finite
from .models.tanks import CoupledTankModel, integrate


def simulation_observations(source):
    """Truth is returned on a separate scoring path, never in inference inputs."""
    raw = source.get('simulation', {})
    if not isinstance(raw, dict):
        raise ValueError('Simulation configuration must be an object.')
    config = CoupledTankModel().validate({'start':min(40., raw.get('duration', 240.)), **raw})
    if config['seed'] is None:
        raise ValueError('Estimation experiments require an explicit reproducible seed.')
    if config['duration']/config['step'] > 6000:
        raise ValueError('Use at most 6,000 simulation samples for estimation.')
    noise = source.get('noise', [.02, .02])
    every = source.get('every', [1, 3])
    dropout = source.get('dropout', .1)
    irregular = source.get('irregular', False)
    if not isinstance(noise, list) or len(noise) != 2 or any(not finite(v) or not 0 <= v <= 1 for v in noise):
        raise ValueError('Specify two sensor noise standard deviations between 0 and 1 m.')
    if not isinstance(every, list) or len(every) != 2 or any(not finite(v) or int(v) != v or not 1 <= v <= 100 for v in every):
        raise ValueError('Specify two integer sensor sampling strides between 1 and 100.')
    if not finite(dropout) or not 0 <= dropout <= 1 or not isinstance(irregular, bool):
        raise ValueError('Dropout must be between 0 and 1; irregular must be boolean.')
    measured, physical = integrate({**config, 'noise': 0.})
    rng = random.Random(config['seed']+173)
    observations, truth = [], []
    for i, (row, actual) in enumerate(zip(measured, physical)):
        values = [row[k]+rng.gauss(0, noise[j]) for j, k in enumerate(STATES)]
        available = [i % every[j] == 0 and rng.random() >= dropout for j in range(2)]
        keep = not irregular or i in (0, len(measured)-1) or rng.random() > .35
        if keep:
            observations.append(dict(t=row['t'], **{k:values[j] if available[j] else None for j, k in enumerate(STATES)}))
            truth.append({k:actual[k] for k in ('t', *STATES)})
    # Commanded valve, not the hidden effective restriction; pump command is
    # likewise distinct from actual inlet flow under pump degradation.
    controls = [dict(t=0., pumpControl=config['pumpControl'], valve=config['valve'])]
    return observations, controls, truth, {**source, 'simulation': config, 'noise':noise, 'every':every,
                                         'dropout':dropout, 'irregular':irregular}


class EstimationService:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS estimation_runs (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                name TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL)''')

    def list(self, workspace_id):
        self.store.workspace(workspace_id)
        with self.store.connect() as db:
            return [dict(r) for r in db.execute('SELECT id,name,created_at FROM estimation_runs WHERE workspace_id=? ORDER BY rowid DESC', (workspace_id,))]

    def get(self, identity):
        with self.store.connect() as db:
            row = db.execute('SELECT payload FROM estimation_runs WHERE id=?', (identity,)).fetchone()
        if row is None:
            raise KeyError('Estimation run not found.')
        return json.loads(row['payload'])

    def dataset_observations(self, workspace_id, source, initial_time):
        dataset = self.store.dataset(source.get('datasetId'))
        if dataset['workspace_id'] != workspace_id:
            raise ValueError('Dataset belongs to another Workspace.')
        mapping = source.get('mapping', {})
        if not isinstance(mapping, dict) or set(mapping)-{*STATES, 'pumpControl', 'valve'}:
            raise ValueError('Map level1, level2, pumpControl and valve to Dataset columns.')
        columns = [c['name'] for c in dataset['metadata']['columns']]
        if any(v not in columns for v in mapping.values() if v is not None):
            raise ValueError('Mapped Dataset column does not exist.')
        selected = [v for v in mapping.values() if v is not None]
        if not selected or len(set(selected)) != len(selected):
            raise ValueError('Map at least one distinct measurement or control column.')
        times, values = self.store.load_data(dataset)
        if len(times) > 6000 or not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
            raise ValueError('Dataset needs at most 6,000 finite strictly increasing timestamps; resolve duplicates before estimation.')
        mask = self.store.observation_mask(dataset)
        observations, controls = [], []
        previous = {}
        for i, t in enumerate(times):
            row, command = dict(t=float(t)), {}
            for key, column in mapping.items():
                if column is None:
                    continue
                j = columns.index(column)
                value = float(values[i, j]) if mask[i, j] and np.isfinite(values[i, j]) else None
                if key in STATES:
                    row[key] = value
                elif value is not None and value != previous.get(key):
                    command[key] = value
            if t >= initial_time:
                observations.append(row)
            if command:
                controls.append(dict(t=float(t), **command))
                previous.update(command)
        return observations, controls, dict(**source, datasetName=dataset['name'],
                    createdAt=dataset['created_at'], time=dataset['metadata']['time'], observationPolicy='measured-only')

    def create(self, workspace_id, body):
        from .workspace import now
        self.store.workspace(workspace_id)
        if not isinstance(body, dict) or set(body)-{'name', 'source', 'model', 'config', 'sensors', 'knownControls', 'compareSensors', 'operatingPoint'}:
            raise ValueError('Unknown estimation request fields.')
        name = self.store.name(body.get('name', 'Tank state estimation'))
        cfg = settings(body.get('config'))
        source = body.get('source', {})
        if not isinstance(source, dict):
            raise ValueError('Choose a simulation, scenario or Dataset source.')
        truth = None
        if source.get('kind') in ('simulation', 'scenario'):
            if source['kind'] == 'scenario':
                scenario = self.store.scenarios.get(source.get('scenarioId'), source.get('version'))
                if scenario['workspaceId'] != workspace_id or scenario['modelId'] != 'coupled-tanks':
                    raise ValueError('Choose a coupled-tank scenario in this Workspace.')
                source = {**source, 'simulation':scenario['config'], 'scenarioSnapshot':scenario}
            observations, controls, truth, source = simulation_observations(source)
        elif source.get('kind') == 'dataset':
            observations, controls, source = self.dataset_observations(workspace_id, source, cfg['initialTime'])
        else:
            raise ValueError('Choose a simulation, scenario or Dataset source.')
        if truth is not None:
            selected = [i for i, row in enumerate(observations) if row['t'] >= cfg['initialTime']]
            observations, truth = [observations[i] for i in selected], [truth[i] for i in selected]
        known = body.get('knownControls', ['pumpControl', 'valve'])
        if not isinstance(known, list) or len(set(known)) != len(known) or any(k not in ('pumpControl', 'valve') for k in known):
            raise ValueError('Select known pumpControl and/or valve commands.')
        controls = [{k:v for k, v in row.items() if k == 't' or k in known} for row in controls]
        controls = [row for row in controls if len(row) > 1]
        # Physical assumptions are always explicit and independent of the
        # simulation's fault, initial conditions and hidden effective inputs.
        model = {k:v for k, v in model_config(body.get('model')).items() if k in MODEL_KEYS}
        result = estimate(observations, controls, model=model, config=cfg, sensors=body.get('sensors'))
        comparison = []
        if not isinstance(body.get('compareSensors', False), bool):
            raise ValueError('compareSensors must be boolean.')
        masks = [[*STATES], ['level1'], ['level2'], []] if body.get('compareSensors') else [result['sensors']]
        for sensors in masks:
            other = result if sensors == result['sensors'] else estimate(observations, controls, model=model, config=cfg, sensors=sensors)
            comparison.append(dict(sensors=sensors, predictionOnly=other['predictionOnly'],
                                   innovationConsistency=other['innovationConsistency'],
                                   score=score(other, truth) if truth is not None else None))
        identity, stamp = uuid4().hex, now()
        frozen = dict(observations=observations, controls=controls)
        fingerprint = hashlib.sha256(json.dumps(frozen, sort_keys=True, allow_nan=False).encode()).hexdigest()
        payload = dict(id=identity, workspaceId=workspace_id, name=name, createdAt=stamp, format='tank-estimation-v1',
                       engineVersion='1.0.0', modelVersion=CoupledTankModel.version,
                       request={**body, 'model':model, 'config':result['config'], 'knownControls':known}, source=source,
                       inputs=frozen, inputSha256=fingerprint, result=result, comparisons=comparison,
                       score=score(result, truth) if truth is not None else None,
                       observability=[observability(model, body.get('operatingPoint'), sensors) for sensors in ([*STATES], ['level1'], ['level2'], [])])
        # Hidden physical state is never persisted amongst the inference inputs.
        with self.store.connect() as db:
            db.execute('INSERT INTO estimation_runs VALUES (?,?,?,?,?)',
                       (identity, workspace_id, name, stamp, json.dumps(payload, allow_nan=False)))
            db.execute('UPDATE workspaces SET updated_at=? WHERE id=?', (stamp, workspace_id))
        return payload

    def export(self, identity, body):
        run = self.get(identity)
        name = self.store.name(body.get('name', run['name'][:140]+' · estimates'))
        output = StringIO()
        writer = csv.writer(output)
        fields = ['estimate', 'prediction', 'openLoop', 'observed', 'lower', 'upper', 'innovation', 'residual']
        names = [f'{state}_{field}' for field in fields for state in STATES]+['P11', 'P12', 'P22', 'NIS', 'measurement_dof']
        writer.writerow(['time', *names])
        for row in run['result']['rows']:
            writer.writerow([row['t'], *(v for field in fields for v in row[field]), row['covariance'][0][0],
                             row['covariance'][0][1], row['covariance'][1][1], row['nis'], row['dof']])
        text = output.getvalue()
        metadata, times, values = prepare_csv(text, dict(timeColumn='time', timeKind='numeric'))
        for column in metadata['columns']:
            column['unit'] = 'm²' if column['name'].startswith('P') else '' if column['name'] in ('NIS', 'measurement_dof') else 'm'
        metadata['estimation'] = dict(runId=identity, engineVersion=run['engineVersion'], modelVersion=run['modelVersion'],
            createdAt=run['createdAt'], source=run['source'], inputSha256=run['inputSha256'],
            request=run['request'], score=run['score'], resultEndpoint=f'/api/estimations/{identity}',
            interpretation='Conditional EKF estimates and Gaussian intervals; not raw sensor observations.')
        # Generated values stay marked processed, preventing accidental reuse as
        # independent measurements by this workspace or measured-only analyses.
        observed = np.zeros(values.shape, dtype=bool)
        return self.store.save_dataset(run['workspaceId'], name, metadata, times, values, text,
                                       extra_arrays=dict(observed=observed))
