"""Dataset-backed prognostic fits, immutable sessions and numerical exports."""
from __future__ import annotations

import csv
from dataclasses import asdict
from io import StringIO
import json
import math
from uuid import uuid4

import numpy as np

from .datasets import prepare_csv
from .workspace import now


MAINTENANCE_DEFAULTS = dict(preventive_cost=500, corrective_cost=2000, downtime_cost=2,
                            preventive_duration=30, corrective_duration=180, failure_consequence=1500,
                            replacement_cost=1300, replacement_duration=45, scheduled_time=None, discount_rate=0,
                            planning_horizon=None)
SESSION_VERSION = 1


def object_value(value, label):
    if not isinstance(value, dict):
        raise ValueError(f'{label} must be an object.')
    return value


def number(value, label, *, optional=False):
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{label} must be a finite number.')
    return float(value)


def optional_text(value, label, limit):
    if not isinstance(value, str) or len(value.strip()) > limit:
        raise ValueError(f'{label} must be text of at most {limit} characters.')
    return value.strip()


def sequence(value, label):
    if not isinstance(value, (list, tuple)) or len(value) > 1000:
        raise ValueError(f'{label} must be a list of up to 1000 records.')
    return value


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


class PrognosticSessions:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS prognostic_sessions (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    dataset_id TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
                    name TEXT NOT NULL, asset_name TEXT NOT NULL, status TEXT NOT NULL,
                    created_at TEXT NOT NULL, snapshot TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS prognostic_workspace
                    ON prognostic_sessions(workspace_id, created_at DESC);
            ''')

    def validate_measurement_lineage(self, dataset, names):
        """Reject aggregates labeled at the start of a forward-looking bin."""
        pending = [(dataset['id'], name) for name in names]
        visited, datasets = set(), {dataset['id']: dataset}
        while pending:
            dataset_id, name = pending.pop()
            if (dataset_id, name) in visited:
                continue
            visited.add((dataset_id, name))
            if dataset_id not in datasets:
                datasets[dataset_id] = self.store.base_dataset(dataset_id)
            metadata = datasets[dataset_id]['metadata']
            if not (transformation := metadata.get('transformation')):
                continue
            source = next((s for s in transformation['config']['sources'] if s['key'] == name), None)
            if source is None:
                column = next(c for c in metadata['columns'] if c['name'] == name)
                pending.extend((dataset_id, dependency) for dependency in column['dependencies'])
            elif source['resampling'] in ('mean', 'min', 'max'):
                raise ValueError('Use a condition or load signal without forward-bin aggregation. Its timestamp must represent when the measurement was available.')
            else:
                pending.append((source['datasetId'], source['column']))

    def fit(self, workspace_id, body):
        from .prognostics import Asset, ConditionHistory, Indicator, MaintenanceEvent, Observation, forecast, plan_maintenance

        dataset_id = self.store.name(body.get('datasetId'))
        dataset = self.store.dataset(dataset_id)
        if dataset['workspace_id'] != workspace_id:
            raise ValueError('Dataset belongs to a different workspace.')
        metadata = dataset['metadata']
        columns = {c['name']: (index, c) for index, c in enumerate(metadata['columns'])}
        indicator_request = object_value(body.get('indicator'), 'Indicator')
        signal_name = self.store.name(indicator_request.get('signal'))
        load_name = body.get('loadSignal') or None
        if load_name is not None:
            load_name = self.store.name(load_name)
        if signal_name not in columns or (load_name is not None and load_name not in columns):
            raise ValueError('Choose condition and load signals from this Dataset.')
        if signal_name == load_name:
            raise ValueError('Choose a separate signal for operating load.')
        condition_index, condition = columns[signal_name]
        load_index, load = columns[load_name] if load_name is not None else (None, None)

        indicator = Indicator(signal=signal_name,
            definition=optional_text(indicator_request.get('definition'), 'Indicator definition', 4000),
            unit=optional_text(indicator_request.get('unit') or condition.get('unit', ''), 'Indicator unit', 160),
            failure_threshold=number(indicator_request.get('failure_threshold'), 'Failure threshold'),
            direction=indicator_request.get('direction', 'increasing'),
            operating_threshold=number(indicator_request.get('operating_threshold'), 'Operating threshold', optional=True))
        if not indicator.definition or not indicator.unit:
            raise ValueError('Define what the condition signal measures and specify its engineering unit.')
        if condition.get('unit') and indicator.unit != condition['unit']:
            raise ValueError('Use the condition signal unit in the Signal Catalog. Convert values in Data Transformation first if needed.')
        asset_name = self.store.name(body.get('assetName'))
        asset_id = self.store.name(body.get('assetId') or asset_name)
        asset = Asset(id=asset_id, name=asset_name, signals=(signal_name,) if load is None else (signal_name, load_name))

        times, values = self.store.load_data(dataset)
        start = number(body.get('start'), 'Training start', optional=True)
        cutoff = number(body.get('cutoff'), 'Training cutoff', optional=True)
        start = float(times[0]) if start is None else start
        cutoff = float(times[-1]) if cutoff is None else cutoff
        if not times[0] <= start <= cutoff <= times[-1]:
            raise ValueError('The training interval must be ordered and within the Dataset clock range.')
        left, right = times.searchsorted(start, side='left'), times.searchsorted(cutoff, side='right')
        if right - left > 100_000:
            raise ValueError('Choose a training interval with at most 100,000 samples.')
        horizon = number(body.get('horizon'), 'Forecast horizon')
        if not 0 < horizon <= 1e9:
            raise ValueError('Forecast horizon must be between 0 and 1,000,000,000 seconds.')
        probability_horizons = body.get('probabilityHorizons')
        if probability_horizons is not None:
            probability_horizons = [number(t, 'Probability horizon') for t in sequence(probability_horizons, 'Probability horizons')]
            if not 1 <= len(probability_horizons) <= 20 or any(not 0 <= t <= horizon for t in probability_horizons):
                raise ValueError('Choose 1–20 probability horizons within the forecast horizon.')
        method = body.get('method', 'stochastic')
        if method not in ('linear', 'stochastic'):
            raise ValueError('Choose the linear or stochastic prognostic model.')
        seed = body.get('seed', 35)
        if type(seed) is not int or not 0 <= seed < 2**32:
            raise ValueError('Seed must be an integer from 0 through 4294967295.')

        events = []
        for item in sequence(body.get('events', []), 'Maintenance events'):
            item = object_value(item, 'Maintenance event')
            event = MaintenanceEvent(time=number(item.get('time'), 'Maintenance event time'), action=item.get('action', 'restore'))
            events.append(event)
        operating_periods = []
        for period in sequence(body.get('operatingPeriods', []), 'Operating periods'):
            if not isinstance(period, (list, tuple)) or len(period) != 2:
                raise ValueError('Each operating period must have a start and an end.')
            operating_periods.append(tuple(number(t, 'Operating period boundary') for t in period))
        end_status = body.get('endStatus', 'censored')
        failure_time = number(body.get('failureTime'), 'Recorded failure time', optional=True)

        # Preserve missing timestamps and keep only source-observed values.
        selected = values[left:right, [condition_index] if load_index is None else [condition_index, load_index]].copy()
        if metadata.get('transformation'):
            self.validate_measurement_lineage(dataset, asset.signals)
            observed = self.store.observation_mask(dataset)[left:right, [condition_index] if load_index is None else [condition_index, load_index]]
            selected[~observed] = np.nan

        def measurement(value):
            return float(value) if np.isfinite(value) else None

        observations = tuple(Observation(float(t), measurement(row[0]), measurement(row[1]) if load is not None else None)
                             for t, row in zip(times[left:right], selected))
        history = ConditionHistory(asset=asset, indicator=indicator, observations=observations, events=tuple(events),
                                   operating_periods=tuple(operating_periods), end_status=end_status,
                                   failure_time=failure_time, observed_until=float(times[-1]))

        maintenance_request = object_value(body.get('maintenance', {}), 'Maintenance parameters')
        maintenance_config = {key: number(maintenance_request.get(key, value), key, optional=value is None)
                              for key, value in MAINTENANCE_DEFAULTS.items()}
        if any(value is not None and not 0 <= value <= 1e12 for value in maintenance_config.values()):
            raise ValueError('Maintenance costs and durations must be nonnegative and at most one trillion.')
        planning_horizon = maintenance_config['planning_horizon']
        if planning_horizon is not None and not 0 < planning_horizon <= horizon:
            raise ValueError('Planning horizon must be positive and within the forecast horizon.')
        if maintenance_config['scheduled_time'] is not None and maintenance_config['scheduled_time'] > (planning_horizon or horizon):
            raise ValueError('Scheduled intervention must fall within the planning horizon.')

        prediction = forecast(history, method=method, start=start, cutoff=cutoff, horizon=horizon, seed=seed,
                              probability_horizons=probability_horizons)
        maintenance = plan_maintenance(prediction, **maintenance_config)
        config = dict(datasetId=dataset_id, assetId=asset_id, assetName=asset_name, indicator=asdict(indicator),
                      loadSignal=load_name, start=start, cutoff=cutoff, horizon=horizon, method=method, seed=seed,
                      events=[asdict(e) for e in events], operatingPeriods=operating_periods, endStatus=end_status,
                      failureTime=failure_time, maintenance=maintenance_config, probabilityHorizons=probability_horizons)
        benchmark = metadata.get('prognosticBenchmark', {})
        signal_keys = ('id', 'name', 'displayName', 'unit', 'description', 'device', 'logicalKey')
        source = dict(datasetId=dataset_id, datasetName=dataset['name'], clock=metadata['clock'], timeUnit='seconds',
                      signal={k: condition[k] for k in signal_keys}, loadSignal={k: load[k] for k in signal_keys} if load else None,
                      benchmark=benchmark.get('provenance'),
                      transformation={key: metadata['transformation'][key] for key in ('definitionId', 'revision', 'executionId')}
                      if metadata.get('transformation') else None)
        return dict(config=config, forecast=prediction, maintenance=maintenance, source=source)

    def benchmark(self, workspace_id, body):
        from .models.tanks import CoupledTankModel, FIELDS
        from .prognostic_benchmark import benchmark_dataset

        self.store.workspace(workspace_id)
        settings = {key: value for key, value in body.items() if key not in ('scenarioId', 'scenarioVersion')}
        scenario_id, scenario_version = body.get('scenarioId'), body.get('scenarioVersion')
        scenario_source = None
        if scenario_id is not None:
            scenario = self.store.scenarios.get(scenario_id, scenario_version)
            if scenario['workspaceId'] != workspace_id or scenario['modelId'] != CoupledTankModel.id:
                raise ValueError('Choose a coupled-tank scenario from this workspace.')
            if 'tank_config' in settings:
                raise ValueError('Choose saved scenario hydraulics or custom tank settings.')
            hydraulic_keys = {field['key'] for field in FIELDS if field['group'] in ('Model parameters', 'Initial conditions')}
            settings['tank_config'] = {key: value for key, value in scenario['config'].items() if key in hydraulic_keys}
            scenario_source = dict(id=scenario['id'], version=scenario['version'], name=scenario['name'], model_version=scenario['modelVersion'])
        elif scenario_version is not None:
            raise ValueError('Choose a scenario before selecting its version.')
        data = benchmark_dataset(settings)
        if scenario_source is not None:
            data['provenance']['scenario'] = scenario_source
        output = StringIO(newline='')
        writer = csv.DictWriter(output, ['t', *data['signals']], lineterminator='\n')
        writer.writeheader()
        writer.writerows(data['rows'])
        source = output.getvalue()
        metadata, times, values = prepare_csv(source, {'timeColumn': 't', 'timeKind': 'numeric'})
        metadata['filename'] = 'coupled-tank-progressive-pump.csv'
        for column in metadata['columns']:
            column['unit'] = data['signals'][column['name']]
            if column['name'] == data['indicator']['signal']:
                column['description'] = data['indicator']['definition']
        metadata['prognosticBenchmark'] = {key: data[key] for key in ('indicator', 'events', 'operating_periods',
            'load_signal', 'end_status', 'provenance', 'cutoff', 'horizon') if key in data}
        dataset = self.store.save_dataset(workspace_id, 'Coupled-tank pump degradation', metadata, times, values, source)
        cutoff = data.get('cutoff', float(times[-1]))
        defaults = dict(datasetId=dataset['id'], assetId='coupled-tanks-pump', assetName='Coupled-tank inlet pump',
                        indicator=data['indicator'], loadSignal=data.get('load_signal'), start=float(times[0]),
                        cutoff=cutoff, horizon=data.get('horizon', 360.),
                        method='stochastic', seed=35, events=data['events'], operatingPeriods=data.get('operating_periods', []),
                        endStatus=data['end_status'], maintenance=MAINTENANCE_DEFAULTS)
        return dict(dataset=dataset, defaults=defaults)

    def evaluate(self, workspace_id):
        from .prognostic_benchmark import evaluate

        self.store.workspace(workspace_id)
        return evaluate()

    def list(self, workspace_id):
        self.store.workspace(workspace_id)
        with self.store.connect() as db:
            return [dict(row) for row in db.execute('''SELECT id,name,created_at,dataset_id AS datasetId,
                asset_name AS assetName,status FROM prognostic_sessions
                WHERE workspace_id=? ORDER BY created_at DESC,id DESC''', (workspace_id,))]

    def get(self, workspace_id, identity):
        with self.store.connect() as db:
            row = db.execute('SELECT snapshot FROM prognostic_sessions WHERE id=? AND workspace_id=?',
                             (identity, workspace_id)).fetchone()
        if row is None:
            raise KeyError('Prognostic session not found.')
        return json.loads(row['snapshot'])

    def save(self, workspace_id, body):
        name = self.store.name(body.get('name'))
        include_evaluation = body.get('includeEvaluation', False)
        if type(include_evaluation) is not bool:
            raise ValueError('Evaluation selection must be true or false.')
        result = self.fit(workspace_id, body)
        identity, stamp = uuid4().hex, now()
        result.update(id=identity, name=name, created_at=stamp, version=SESSION_VERSION, workspaceId=workspace_id,
                      evaluation=self.evaluate(workspace_id) if include_evaluation else None)
        with self.store.connect() as db:
            db.execute('INSERT INTO prognostic_sessions VALUES (?,?,?,?,?,?,?,?)',
                       (identity, workspace_id, result['config']['datasetId'], name, result['config']['assetName'],
                        result['forecast']['status'], stamp, encode(result)))
            db.execute('UPDATE workspaces SET updated_at=? WHERE id=?', (stamp, workspace_id))
        return result


def export_session(session, format_name):
    if format_name == 'session.json':
        return 'application/json', encode(session)
    output = StringIO(newline='')
    if format_name == 'forecast.csv':
        forecast = session['forecast']
        fields = ['series', 'time_seconds', 'offset_seconds', 'measured', 'fitted', 'load',
                  'median', 'lower', 'upper', 'failure_probability']
        writer = csv.DictWriter(output, fields, lineterminator='\n')
        writer.writeheader()
        writer.writerows(dict(series='history', time_seconds=r['time'], measured=r['value'], fitted=r['fitted'], load=r['load'])
                         for r in forecast['history'])
        writer.writerows(dict(series='trajectory', time_seconds=r['time'], offset_seconds=r['offset'],
                              median=r['median'], lower=r['lower'], upper=r['upper']) for r in forecast['trajectory'])
        writer.writerows(dict(series='first_passage_cdf', time_seconds=forecast['cutoff'] + r['time'], offset_seconds=r['time'],
                              failure_probability=r['probability']) for r in forecast['distribution'])
    else:
        fields = ['series', 'action', 'time_seconds_after_cutoff', 'failure_probability', 'expected_cost',
                  'expected_failure_cost', 'expected_intervention_cost', 'recommended']
        writer = csv.DictWriter(output, fields, lineterminator='\n')
        writer.writeheader()
        maintenance = session['maintenance']
        for section in ('options', 'curve'):
            writer.writerows(dict(series=section, action=r['action'], time_seconds_after_cutoff=r['time'],
                                  failure_probability=r['failure_probability'], expected_cost=r['expected_cost'],
                                  expected_failure_cost=r['expected_failure_cost'], expected_intervention_cost=r['expected_intervention_cost'],
                                  recommended=int(r == maintenance['recommended'])) for r in maintenance[section])
    return 'text/csv', output.getvalue()
