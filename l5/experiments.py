"""SQLite experiments, immutable run snapshots and a bounded local batch worker."""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import platform
from pathlib import Path
from threading import Lock, Thread
from time import perf_counter
from uuid import uuid4

import numpy as np

from .analysis import ALGORITHMS
from .experiment_evaluation import RULES, evaluate, validate_intervals
from .incident_timeline import compare_intervals, observed_spans
from .incidents import text
from .workspace import now

MAX_TASKS = 64
MAX_EXTERNAL_TASKS = 256
MAX_ACTIVE_RUNS = 4
PARAMETERS = {
    'robust-maxz': (), 'pca-q': ('variance',), 'pca-t2': ('variance',),
    'ewma': ('smoothing',), 'cusum': ('reference',), 'window-cusum': ('reference', 'window'),
    'dpca-q': ('variance', 'lags'), 'dpca-t2': ('variance', 'lags'),
    'adaptive-maxz': ('rate', 'guard', 'maxShift'),
}
DEFAULTS = dict(alpha=.01, variance=.9, smoothing=.25, reference=.5, window=12, lags=2,
                rate=.02, guard=2.5, maxShift=1.5, fitFraction=.7, minCoverage=.9, persistence=1)


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def numeric(key, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{key} must be a finite number.')
    ranges = dict(alpha=(0, .5, False, False), variance=(.5, 1, True, False), smoothing=(0, 1, False, True),
                  rate=(0, 1, False, False), fitFraction=(.5, .9, True, True), minCoverage=(0, 1, False, True),
                  lags=(1, 8, True, True), window=(2, 100000, True, True), persistence=(1, 100000, True, True))
    low, high, closed_low, closed_high = ranges.get(key, (0, 1e6, False, True))
    if (value < low if closed_low else value <= low) or (value > high if closed_high else value >= high):
        raise ValueError(f'{key} is outside its allowed range ({low}, {high}).')
    if key in ('lags', 'window', 'persistence') and not isinstance(value, int):
        raise ValueError(f'{key} must be an integer.')
    return value


def file_hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


class ExperimentService:
    def __init__(self, store):
        self.store, self.lock, self.working = store, Lock(), False
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS experiment_labels (
                    id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
                    version INTEGER NOT NULL, name TEXT NOT NULL, source TEXT NOT NULL,
                    payload TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(dataset_id,version));
                CREATE TABLE IF NOT EXISTS experiments (
                    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    name TEXT NOT NULL, description TEXT NOT NULL, config TEXT NOT NULL, revision INTEGER NOT NULL,
                    notes TEXT NOT NULL, conclusion TEXT NOT NULL, conclusion_run_ids TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS experiments_workspace ON experiments(workspace_id,updated_at);
                CREATE TABLE IF NOT EXISTS experiment_records (
                    id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
                    revision INTEGER NOT NULL, notes TEXT NOT NULL, conclusion TEXT NOT NULL,
                    run_ids TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS experiment_runs (
                    id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
                    snapshot TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
                    started_at TEXT, completed_at TEXT, duration_ms REAL, retry_of TEXT);
                CREATE TABLE IF NOT EXISTS experiment_tasks (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES experiment_runs(id) ON DELETE CASCADE,
                    ordinal INTEGER NOT NULL, algorithm TEXT NOT NULL, config TEXT NOT NULL, status TEXT NOT NULL,
                    result_id TEXT REFERENCES jobs(id) ON DELETE SET NULL, duration_ms REAL,
                    error TEXT, metrics TEXT, started_at TEXT, completed_at TEXT);
                CREATE INDEX IF NOT EXISTS experiment_tasks_run ON experiment_tasks(run_id,ordinal);
            ''')
            # A process restart never pretends a pending computation completed.
            stamp = now()
            db.execute("UPDATE experiment_tasks SET status='interrupted',error=?,completed_at=? WHERE status IN ('queued','running')",
                       ('Local service stopped before this task completed. Retry unfinished tasks in a new run.', stamp))
            db.execute("UPDATE experiment_runs SET status='interrupted',completed_at=? WHERE status IN ('queued','running')", (stamp,))

    def list(self, workspace_id):
        self.store.workspace(workspace_id)
        with self.store.connect() as db:
            rows = db.execute('''SELECT e.*,
                (SELECT COUNT(*) FROM experiment_runs WHERE experiment_id=e.id) AS run_count,
                (SELECT MAX(created_at) FROM experiment_runs WHERE experiment_id=e.id) AS last_run_at,
                (SELECT COUNT(*) FROM experiment_tasks t JOIN experiment_runs r ON r.id=t.run_id
                 WHERE r.experiment_id=e.id) AS historical_task_count
                FROM experiments e WHERE workspace_id=? ORDER BY updated_at DESC,id''', (workspace_id,)).fetchall()
        return [self.definition_row(row) for row in rows]

    @staticmethod
    def definition_row(row):
        result = dict(row)
        for key in ('config', 'conclusion_run_ids'):
            result[key] = json.loads(result[key])
        return result

    def get(self, identity):
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM experiments WHERE id=?', (identity,)).fetchone()
        if row is None:
            raise KeyError('Experiment not found.')
        with self.store.connect() as db:
            records = [{**dict(record), 'run_ids': json.loads(record['run_ids'])} for record in db.execute(
                'SELECT * FROM experiment_records WHERE experiment_id=? ORDER BY created_at DESC,id', (identity,))]
        return {**self.definition_row(row), 'runs': self.runs(identity), 'records': records}

    def validate(self, workspace_id, raw):
        if not isinstance(raw, dict):
            raise ValueError('Experiment config must be an object.')
        dataset = self.store.dataset(raw.get('datasetId', ''))
        if dataset['workspace_id'] != workspace_id:
            raise ValueError('Experiment dataset belongs to a different workspace.')
        independent = raw.get('training') is not None
        training, training_datasets = (None, None)
        if independent:
            from .independent import validate_training, validate_test
            training, training_datasets = validate_training(self.store, workspace_id, raw)
        columns = [s['name'] for s in (training_datasets['fit'] if independent else dataset)['metadata']['columns']]
        signals = raw.get('signals')
        if not isinstance(signals, list) or not signals or any(not isinstance(s, str) or s not in columns for s in signals) or len(signals) != len(set(signals)):
            raise ValueError('Choose unique numeric signals from the experiment dataset.')
        config = dict(datasetId=dataset['id'], signals=signals)
        axis = dataset['metadata']['time']
        for key in ('baselineRange', 'analysisRange'):
            if independent and key == 'baselineRange':
                config[key] = training['fit']['range']
                continue
            interval = raw.get(key)
            if not isinstance(interval, list) or len(interval) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in interval):
                raise ValueError(f'{key} needs two finite times in dataset seconds.')
            if not axis['start'] <= interval[0] <= interval[1] <= axis['end']:
                raise ValueError(f'{key} must be inside the dataset time range.')
            config[key] = interval
        if not independent and config['baselineRange'][1] >= config['analysisRange'][0]:
            raise ValueError('Baseline must finish before the analysis window starts.')
        for key in ('alpha', 'fitFraction', 'minCoverage', 'persistence'):
            config[key] = numeric(key, raw.get(key, DEFAULTS[key]))
        config['observationPolicy'] = raw.get('observationPolicy', 'measured')
        if config['observationPolicy'] not in ('measured', 'processed'):
            raise ValueError('Select measured or processed observation policy.')
        required = raw.get('requiredSignals', [])
        if not isinstance(required, list) or any(s not in signals for s in required):
            raise ValueError('Required observed signals must be selected input signals.')
        config['requiredSignals'] = list(dict.fromkeys(required))
        if raw.get('labelSetId'):
            labels = self.labels(raw['labelSetId'])
            if labels['dataset_id'] != dataset['id']:
                raise ValueError('Labels belong to a different dataset.')
            config['labelSetId'] = labels['id']
        if independent:
            config['training'], config['testDatasets'] = training, []
            tests = raw.get('testDatasets', [dict(datasetId=dataset['id'], analysisRange=config['analysisRange'], labelSetId=config.get('labelSetId'))])
            if not isinstance(tests, list) or not 1 <= len(tests) <= 32 or any(not isinstance(t, dict) for t in tests):
                raise ValueError('Choose 1–32 independent test datasets.')
            seen_tests = set()
            for item in tests:
                test, mapping = validate_test(self.store, workspace_id, {**raw, **item}, training, training_datasets)
                sequence = test['metadata'].get('external', {}).get('sequenceId', test['id'])
                if sequence in seen_tests:
                    raise ValueError('Each independent test run may occur only once, including re-imported copies.')
                seen_tests.add(sequence)
                plan = dict(datasetId=test['id'], analysisRange=item['analysisRange'], signalMapping=mapping)
                if item.get('labelSetId'):
                    labels = self.labels(item['labelSetId'])
                    if labels['dataset_id'] != test['id']:
                        raise ValueError('Each test label version must belong to that test dataset.')
                    plan['labelSetId'] = labels['id']
                config['testDatasets'].append(plan)
            if config['testDatasets'][0]['datasetId'] != dataset['id']:
                raise ValueError('The experiment dataset must be the first declared test dataset.')
        algorithms = raw.get('algorithms')
        if not isinstance(algorithms, list) or not 1 <= len(algorithms) <= len(ALGORITHMS):
            raise ValueError('Choose one or more of the nine available algorithms.')
        config['algorithms'], seen = [], set()
        for item in algorithms:
            if not isinstance(item, dict) or item.get('algorithm') not in ALGORITHMS:
                raise ValueError('Unknown detection algorithm.')
            algorithm = item['algorithm']
            if algorithm in seen:
                raise ValueError('Use one entry per algorithm, with candidate values for a parameter study.')
            seen.add(algorithm)
            allowed = ('alpha', *PARAMETERS[algorithm])
            params, study = item.get('parameters', {}), item.get('study', {})
            if not isinstance(params, dict) or not isinstance(study, dict) or set(params) - set(allowed) or set(study) - set(allowed):
                raise ValueError(f'Only applicable parameters are allowed for {algorithm}: {", ".join(allowed)}.')
            params = {key: numeric(key, value) for key, value in params.items()}
            clean_study = {}
            for key, candidates in study.items():
                if not isinstance(candidates, list) or not 1 <= len(candidates) <= 8:
                    raise ValueError('Each study parameter needs 1–8 candidate values.')
                clean_study[key] = list(dict.fromkeys(numeric(key, value) for value in candidates))
            config['algorithms'].append(dict(algorithm=algorithm, parameters=params, study=clean_study))
        tasks = self.expand(config)
        return config, tasks

    @staticmethod
    def expand(config):
        common = {key: value for key, value in config.items() if key not in ('algorithms', 'labelSetId', 'testDatasets')}
        tests = config.get('testDatasets', [{}])
        limit = MAX_EXTERNAL_TASKS if config.get('training') else MAX_TASKS
        tasks = []
        for item in config['algorithms']:
            keys = list(item['study'])
            count = math.prod(len(item['study'][key]) for key in keys)
            if len(tasks) + count*len(tests) > limit:
                raise ValueError(f'An experiment is limited to {limit} tasks. Reduce study candidates or test runs.')
            for values in itertools.product(*(item['study'][key] for key in keys)):
                algorithm = item['algorithm']
                defaults = {key: DEFAULTS[key] for key in PARAMETERS[algorithm]}
                for test in tests:
                    tasks.append({**common, **test, 'algorithm': algorithm, **defaults, **item['parameters'], **dict(zip(keys, values))})
        return tasks

    def preview(self, workspace_id, raw):
        config, tasks = self.validate(workspace_id, raw)
        return dict(config=config, taskCount=len(tasks), maxTasks=MAX_EXTERNAL_TASKS if config.get('training') else MAX_TASKS, tasks=tasks)

    def save(self, workspace_id, body, identity=None):
        self.store.workspace(workspace_id)
        previous = self.get(identity) if identity else {}
        if previous and previous['workspace_id'] != workspace_id:
            raise ValueError('Experiment belongs to another workspace.')
        config, _ = self.validate(workspace_id, body.get('config', previous.get('config')))
        name = self.store.name(body.get('name', previous.get('name')))
        description = text(body.get('description', previous.get('description', '')), 'Description')
        notes = text(body.get('notes', previous.get('notes', '')), 'Notes')
        conclusion = text(body.get('conclusion', previous.get('conclusion', '')), 'Conclusion')
        references = body.get('conclusion_run_ids', previous.get('conclusion_run_ids', []))
        if not isinstance(references, list) or any(not isinstance(r, str) for r in references):
            raise ValueError('Conclusion references must be experiment run IDs.')
        existing_ids = {run['id'] for run in previous.get('runs', [])}
        if any(r not in existing_ids for r in references):
            raise ValueError('Conclusions must reference saved runs of this experiment.')
        stamp = now()
        with self.store.connect() as db:
            if previous:
                # Reject concurrent stale edits if the caller supplies its revision.
                revision = body.get('revision', previous['revision'])
                changed = db.execute('''UPDATE experiments SET name=?,description=?,config=?,revision=revision+1,
                    notes=?,conclusion=?,conclusion_run_ids=?,updated_at=? WHERE id=? AND revision=?''',
                    (name, description, encode(config), notes, conclusion, encode(references), stamp, identity, revision)).rowcount
                if not changed:
                    raise ValueError('Experiment changed since it was opened. Reopen it before saving.')
            else:
                identity = uuid4().hex
                db.execute('INSERT INTO experiments VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                           (identity, workspace_id, name, description, encode(config), 1, notes, conclusion, encode(references), stamp, stamp))
            if (notes, conclusion, references) != (previous.get('notes', ''), previous.get('conclusion', ''), previous.get('conclusion_run_ids', [])):
                db.execute('INSERT INTO experiment_records VALUES (?,?,?,?,?,?,?)',
                           (uuid4().hex, identity, previous.get('revision', 0)+1, notes, conclusion, encode(references), stamp))
            db.execute('UPDATE workspaces SET updated_at=? WHERE id=?', (stamp, workspace_id))
        return self.get(identity)

    def copy(self, identity):
        previous = self.get(identity)
        return self.save(previous['workspace_id'], dict(name=(previous['name'][:150] + ' · copy'),
            description=previous['description'], config=previous['config'], notes=previous['notes']))

    def labels(self, identity):
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM experiment_labels WHERE id=?', (identity,)).fetchone()
        if row is None:
            raise KeyError('Label version not found.')
        result = dict(row)
        return {**{key: value for key, value in result.items() if key != 'payload'}, **json.loads(row['payload'])}

    def label_sets(self, dataset_id):
        self.store.dataset(dataset_id)
        with self.store.connect() as db:
            ids = [row['id'] for row in db.execute('SELECT id FROM experiment_labels WHERE dataset_id=? ORDER BY version DESC', (dataset_id,))]
        return [self.labels(identity) for identity in ids]

    def save_labels(self, dataset_id, body, *, source='manual', provenance=None):
        dataset = self.store.dataset(dataset_id)
        axis = dataset['metadata']['time']
        if body.get('timeBasis') != 'dataset-seconds':
            raise ValueError('Labels must explicitly declare timeBasis: dataset-seconds.')
        time_source = text(body.get('timeSource', ''), 'Label time source', 2000)
        if not time_source:
            raise ValueError('Record where the label times came from.')
        intervals = validate_intervals(body.get('intervals'), [axis['start'], axis['end']])
        identity, stamp = uuid4().hex, now()
        payload = dict(intervals=intervals, timeBasis='dataset-seconds', timeSource=time_source,
                       clock=self.store.signals.clock(dataset_id), provenance=provenance, rules=RULES)
        with self.store.connect() as db:
            # Serialise version allocation across concurrent HTTP requests.
            db.execute('BEGIN IMMEDIATE')
            version = db.execute('SELECT COALESCE(MAX(version),0)+1 FROM experiment_labels WHERE dataset_id=?', (dataset_id,)).fetchone()[0]
            db.execute('INSERT INTO experiment_labels VALUES (?,?,?,?,?,?,?)',
                       (identity, dataset_id, version, self.store.name(body.get('name') or 'Truth labels'), source, encode(payload), stamp))
        return self.labels(identity)

    def triplens_labels(self, dataset_id, body):
        """Legacy entry point, accepting the same persisted simulation truth."""
        return self.simulation_labels(dataset_id, body)

    def simulation_labels(self, dataset_id, body):
        dataset = self.store.dataset(dataset_id)
        metadata = dataset['metadata']
        simulations = metadata.get('transformation', {}).get('sourceSimulations', [])
        if metadata.get('model'):
            simulations = [metadata['model']['simulationId']]
        simulation_id = body.get('simulationId')
        if not simulation_id and len(simulations) == 1:
            simulation_id = simulations[0]
        if simulation_id not in simulations:
            raise ValueError('Choose one known source simulation for this dataset.')
        session = self.store.runtime.get(simulation_id)
        source_clock = self.store.signals.clock(session['datasetId'])
        clock = self.store.signals.clock(dataset_id)
        if source_clock['axisId'] != clock['axisId']:
            raise ValueError('Simulation truth needs an explicit compatible dataset clock.')
        source_models = [metadata['model']] if metadata.get('model') else metadata.get('transformation', {}).get('sourceModels', [])
        source_model = next((m for m in source_models if m['simulationId'] == simulation_id), {})
        truth = source_model.get('groundTruth')
        truth = truth or session['groundTruth']
        if truth is None:
            raise ValueError('This model does not provide saved ground-truth labels.')
        offset = source_clock['offset'] - clock['offset']
        onset = session['config']['start'] + offset
        times, _ = self.store.load_data(dataset)
        first, last = float(times[0]), float(times[-1])
        intervals = []
        coverage = truth['coverage']
        covered = (times >= coverage[0]+offset) & (times <= coverage[1]+offset)
        faults = truth['intervals']
        normal_end = min(i['start'] for i in faults)+offset if faults else float('inf')
        normal = times[covered & (times < normal_end)]
        if len(normal):
            intervals.append(dict(kind='normal', start=float(normal[0]), end=float(normal[-1])))
        for fault in faults:
            start, end = fault['start']+offset, fault['end']+offset
            selected = times[covered & (times >= start) & ((times < end) if fault.get('endExclusive') else (times <= end))]
            if len(selected):
                # Keep a non-grid onset for event-delay calculation. Closed
                # evaluation intervals stop on the last actually labelled sample.
                intervals.append(dict(kind='anomaly', start=max(first,start), end=float(selected[-1]), onset=start))
        if not intervals:
            raise ValueError('No known simulation labels overlap this dataset. Post-fault recovery remains unknown.')
        name = session['modelDescriptor']['name']
        legacy = session['modelId'] == 'triplens-synthetic-18-v2'
        return self.save_labels(dataset_id, dict(name=body.get('name') or f'{name} known simulation truth',
            timeBasis='dataset-seconds', timeSource=f'Saved {name} simulation {simulation_id}; configured fault intervals, not detector predictions. Finite-fault recovery is unknown.', intervals=intervals),
            source='triplens-simulation' if legacy else 'model-simulation', provenance=dict(simulationId=simulation_id,
                modelId=session['modelId'], modelVersion=session['modelVersion'], scenarioId=session['scenarioId'], scenarioVersion=session['scenarioVersion'],
                config=session['config'], groundTruth=truth, nativeOnset=onset, sourceClock=source_clock))

    def runs(self, identity):
        with self.store.connect() as db:
            return [dict(row) for row in db.execute('''SELECT r.id,r.experiment_id,r.status,r.created_at,r.started_at,
                r.completed_at,r.duration_ms,r.retry_of,COUNT(t.id) AS task_count,
                SUM(CASE WHEN t.status='succeeded' THEN 1 ELSE 0 END) AS succeeded,
                SUM(CASE WHEN t.status='failed' THEN 1 ELSE 0 END) AS failed,
                SUM(CASE WHEN t.status IN ('succeeded','failed','interrupted') THEN 1 ELSE 0 END) AS completed
                FROM experiment_runs r LEFT JOIN experiment_tasks t ON t.run_id=r.id
                WHERE r.experiment_id=? GROUP BY r.id ORDER BY r.created_at DESC,r.id''', (identity,))]

    def run(self, identity):
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM experiment_runs WHERE id=?', (identity,)).fetchone()
            if row is None:
                raise KeyError('Experiment run not found.')
            tasks = [dict(task) for task in db.execute('SELECT * FROM experiment_tasks WHERE run_id=? ORDER BY ordinal', (identity,))]
        for task in tasks:
            for key in ('config', 'metrics'):
                task[key] = json.loads(task[key]) if task[key] else None
        return {**dict(row), 'snapshot': json.loads(row['snapshot']), 'tasks': tasks,
                'task_count': len(tasks), 'completed': sum(t['status'] in ('succeeded', 'failed', 'interrupted') for t in tasks)}

    def execute(self, identity, body):
        experiment = self.get(identity)
        retry_id = body.get('retryRunId')
        if retry_id:
            previous = self.run(retry_id)
            if previous['experiment_id'] != identity or previous['status'] in ('queued', 'running'):
                raise ValueError('Choose a finished run of this experiment to retry.')
            snapshot = previous['snapshot']
            tasks = [task['config'] for task in previous['tasks'] if task['status'] != 'succeeded']
            if not tasks:
                raise ValueError('This run has no unfinished tasks.')
        else:
            config, tasks = self.validate(experiment['workspace_id'], experiment['config'])
            dataset = self.store.dataset(config['datasetId'])
            folder = self.store.root / dataset['workspace_id'] / 'datasets' / dataset['id']
            snapshot = dict(schemaVersion=1, experiment={k: experiment[k] for k in ('id', 'name', 'description', 'revision', 'notes', 'conclusion', 'conclusion_run_ids')},
                config=config, dataset={**dataset, 'sha256': file_hash(folder / 'series.npz'), 'sourceCsvSha256': file_hash(folder / 'source.csv')},
                labels=self.labels(config['labelSetId']) if config.get('labelSetId') else None,
                engine=dict(python=platform.python_version(), numpy=np.__version__, analysis='l5.analysis.run_analysis',
                    sourceHashes={name: file_hash(Path(__file__).resolve().parents[1] / name) for name in (
                        'l5/analysis.py', 'l5/monitoring.py', 'benchmarks/coverage.py', 'benchmarks/temporal.py',
                        'benchmarks/window_cusum.py', 'benchmarks/dynamic_pca.py', 'benchmarks/adaptive.py')}), rules=RULES)
            snapshot['researchRecordId'] = experiment['records'][0]['id'] if experiment['records'] else None
            if config.get('training'):
                from .independent import snapshot as dataset_snapshot
                ids = dict.fromkeys([ref['datasetId'] for ref in config['training'].values()] + [test['datasetId'] for test in config['testDatasets']])
                snapshot['datasets'] = {identity: dataset_snapshot(self.store, self.store.dataset(identity)) for identity in ids}
                snapshot['testLabels'] = {test['datasetId']: self.labels(test['labelSetId']) if test.get('labelSetId') else None for test in config['testDatasets']}
                snapshot['schemaVersion'] = 2
                snapshot['engine']['analysis'] = 'l5.independent.fit_detector / score_detector -> l5.analysis.score_analysis'
                snapshot['engine']['sourceHashes'].update({name: file_hash(Path(__file__).resolve().parents[1] / name) for name in (
                    'l5/independent.py', 'l5/tep_import.py', 'l5/datasets.py', 'benchmarks/rieth_stream.py',
                    'benchmarks/rieth_sources.json', 'examples/tep/protocol.json')})
        run_id, stamp = uuid4().hex, now()
        with self.lock:
            with self.store.connect() as db:
                active = db.execute("SELECT COUNT(*) FROM experiment_runs WHERE status IN ('queued','running')").fetchone()[0]
                if active >= MAX_ACTIVE_RUNS:
                    raise ValueError(f'At most {MAX_ACTIVE_RUNS} local runs may be active. Wait for a batch to finish.')
                db.execute('INSERT INTO experiment_runs VALUES (?,?,?,?,?,?,?,?,?)',
                           (run_id, identity, encode(snapshot), 'queued', stamp, None, None, None, retry_id))
                for ordinal, config in enumerate(tasks):
                    db.execute('''INSERT INTO experiment_tasks (id,run_id,ordinal,algorithm,config,status)
                        VALUES (?,?,?,?,?,?)''', (uuid4().hex, run_id, ordinal, config['algorithm'], encode(config), 'queued'))
            if not self.working:
                self.working = True
                Thread(target=self._drain, name='l5-experiment-worker', daemon=True).start()
        return self.run(run_id)

    def _drain(self):
        while True:
            with self.lock:
                with self.store.connect() as db:
                    row = db.execute("SELECT id FROM experiment_runs WHERE status='queued' ORDER BY created_at,id LIMIT 1").fetchone()
                if row is None:
                    self.working = False
                    return
            run_id, started = row['id'], perf_counter()
            try:
                self._perform(run_id)
            except Exception as error:
                # Keep earlier successful tasks and expose the remaining error.
                with self.store.connect() as db:
                    db.execute("UPDATE experiment_tasks SET status='failed',error=?,completed_at=? WHERE run_id=? AND status IN ('queued','running')",
                               (str(error)[:4000], now(), run_id))
                    db.execute("UPDATE experiment_runs SET status='failed',completed_at=?,duration_ms=? WHERE id=?",
                               (now(), (perf_counter()-started)*1000, run_id))

    def _perform(self, run_id):
        run = self.run(run_id)
        snapshot = run['snapshot']
        dataset = snapshot['dataset']
        for source in snapshot.get('datasets', {dataset['id']: dataset}).values():
            path = self.store.root / source['workspace_id'] / 'datasets' / source['id'] / 'series.npz'
            if file_hash(path) != source['sha256']:
                raise ValueError('Dataset content changed since this run was snapshotted; no tasks were executed.')
        started = perf_counter()
        with self.store.connect() as db:
            db.execute("UPDATE experiment_runs SET status='running',started_at=? WHERE id=?", (now(), run_id))
        fitted_models = {}
        for task in run['tasks']:
            task_start, result_id = perf_counter(), None
            with self.store.connect() as db:
                db.execute("UPDATE experiment_tasks SET status='running',started_at=? WHERE id=?", (now(), task['id']))
            try:
                fitted = None
                if task['config'].get('training'):
                    from .independent import fit_detector, training_key
                    key = training_key(task['config'])
                    if key not in fitted_models:
                        fitted_models[key] = fit_detector(self.store, dataset['workspace_id'], task['config'])
                    fitted = fitted_models[key]
                result = self.store.analyze(dataset['workspace_id'], {**task['config'], 'name': f"{snapshot['experiment']['name'][:110]} · {ALGORITHMS[task['algorithm']]}"},
                    experiment=dict(experimentId=run['experiment_id'], runId=run_id, taskId=task['id']), fitted=fitted)
                result_id = result['id']
                target = snapshot.get('datasets', {}).get(task['config']['datasetId'], dataset)
                labels = snapshot.get('testLabels', {}).get(target['id'], snapshot['labels'])
                metrics = evaluate(result, labels, target['metadata'].get('quality', {}).get('gapThreshold'))
                if fitted:
                    metrics['training'] = dict(modelKey=fitted.key, fitDurationMs=fitted.duration_ms)
                status, error = 'succeeded', None
            except Exception as failure:
                status, error, metrics = 'failed', str(failure)[:4000], None
            with self.store.connect() as db:
                db.execute('''UPDATE experiment_tasks SET status=?,result_id=?,duration_ms=?,error=?,metrics=?,completed_at=? WHERE id=?''',
                    (status, result_id, round((perf_counter()-task_start)*1000, 2), error, encode(metrics) if metrics else None, now(), task['id']))
        final = self.run(run_id)
        successes = sum(t['status'] == 'succeeded' for t in final['tasks'])
        status = 'completed' if successes == len(final['tasks']) else 'partial' if successes else 'failed'
        with self.store.connect() as db:
            db.execute('UPDATE experiment_runs SET status=?,completed_at=?,duration_ms=? WHERE id=?',
                       (status, now(), round((perf_counter()-started)*1000, 2), run_id))

    def comparison(self, identity, body):
        experiment = self.get(identity)
        tasks, runs = [], {}
        for item in experiment['runs']:
            run = self.run(item['id'])
            runs[run['id']] = run
            for task in run['tasks']:
                target = run['snapshot'].get('datasets', {}).get(task['config']['datasetId'], run['snapshot']['dataset'])
                tasks.append({**task, 'runCreatedAt': run['created_at'], 'datasetId': target['id'],
                    'datasetName': target['name'], 'external': target['metadata'].get('external'),
                    'experimentRevision': run['snapshot']['experiment']['revision']})
        selected = body.get('taskIds', [])
        if not isinstance(selected, list) or len(selected) > 12 or any(not isinstance(t, str) for t in selected):
            raise ValueError('Select at most 12 saved tasks for detailed comparison.')
        if any(t not in {task['id'] for task in tasks} for t in selected):
            raise ValueError('Comparison tasks must belong to this experiment.')
        analyses = []
        for task in tasks:
            if task['id'] not in selected or task['status'] != 'succeeded':
                continue
            run = runs[task['run_id']]
            dataset = run['snapshot'].get('datasets', {}).get(task['config']['datasetId'], run['snapshot']['dataset'])
            result = self.store.result(task['result_id'])
            clock = dataset['metadata']['clock']
            offset = clock['offset']
            intervals = [{**span, 'start': span['start']+offset, 'end': span['end']+offset} for span in task['metrics']['behavior']['alarmSpans']]
            analyses.append(dict(id=task['id'], task=task, result=result, dataset=dataset, axisId=clock['axisId'], offset=offset,
                intervals=intervals, observedSpans=observed_spans(result, offset, dataset['metadata'].get('quality', {}).get('gapThreshold'))))
        groups = []
        for axis_id in dict.fromkeys(a['axisId'] for a in analyses):
            members = [a for a in analyses if a['axisId'] == axis_id]
            reference = members[0]
            matching_windows = all([v+member['offset'] for v in member['result']['config']['analysisRange']] ==
                                   [v+reference['offset'] for v in reference['result']['config']['analysisRange']] for member in members)
            matching_coverage = all(member['observedSpans'] == reference['observedSpans'] for member in members)
            def inputs(member):
                config, dataset = member['result']['config'], member['dataset']
                return (dataset['sha256'], config['signals'], [t+member['offset'] for t in config['baselineRange']],
                        config.get('observationPolicy', 'measured'), config['minCoverage'], config['requiredSignals'], config['fitFraction'],
                        member['result'].get('training', {}).get('sources'))
            matching_inputs = all(inputs(member) == inputs(reference) for member in members)
            label_ids = [runs[member['task']['run_id']]['snapshot'].get('testLabels', {}).get(member['dataset']['id'], runs[member['task']['run_id']]['snapshot']['labels']) for member in members]
            matching_labels = len({label['id'] if label else None for label in label_ids}) == 1
            agreement = []
            for left, right in itertools.combinations(members, 2):
                # Exact shared timestamps only; never interpolate detector states.
                lt = np.asarray(left['result']['times']) + left['offset']
                rt = np.asarray(right['result']['times']) + right['offset']
                if len(np.unique(lt)) != len(lt) or len(np.unique(rt)) != len(rt):
                    agreement.append(dict(left=left['id'], right=right['id'], jointSamples=0, agreement=None, alarmJaccard=None,
                                          reason='Duplicate timestamps make sample pairing ambiguous; no sample agreement computed.'))
                    continue
                _, li, ri = np.intersect1d(lt, rt, return_indices=True)
                ls, rs = np.asarray(left['result']['states'])[li], np.asarray(right['result']['states'])[ri]
                valid = (ls != 'abstain') & (rs != 'abstain')
                la, ra = ls[valid] == 'alarm', rs[valid] == 'alarm'
                union = int((la | ra).sum())
                agreement.append(dict(left=left['id'], right=right['id'], jointSamples=int(valid.sum()),
                    agreement=float((la == ra).mean()) if valid.any() else None,
                    alarmJaccard=float((la & ra).sum()/union) if union else None))
            groups.append(dict(axisId=axis_id, taskIds=[m['id'] for m in members], matchingWindows=matching_windows,
                matchingCoverage=matching_coverage, matchingInputs=matching_inputs, matchingLabelSets=matching_labels,
                agreement=agreement, **compare_intervals(members)))
        from .external_benchmark import summarize
        return dict(experiment=experiment, tasks=tasks, analyses=analyses, groups=groups, rules=RULES, benchmark=summarize(tasks))

    def link_incident(self, identity, body):
        run = self.run(identity)
        experiment = self.get(run['experiment_id'])
        task_ids = body.get('taskIds')
        if not isinstance(task_ids, list) or not task_ids or len(task_ids) > MAX_TASKS or any(not isinstance(t, str) for t in task_ids):
            raise ValueError('Select completed tasks to associate with an incident.')
        tasks = {task['id']: task for task in run['tasks']}
        prepared, sources, ranges = [], [], []
        intervals = body.get('intervals', {})
        if not isinstance(intervals, dict) or set(intervals) - set(task_ids):
            raise ValueError('Interval selections must refer to selected tasks.')
        for task_id in dict.fromkeys(task_ids):
            task = tasks.get(task_id)
            if not task or task['status'] != 'succeeded':
                raise ValueError('Incident sources must be successful tasks from this run.')
            source = dict(kind='analysis', analysisId=task['result_id'])
            if task_id in intervals:
                source.update(kind='interval', intervalIndex=intervals[task_id])
            prepared.append(self.store.incidents.prepare_link(experiment['workspace_id'], source))
            sources.append(source)
            if source['kind'] == 'interval':
                interval = self.store.result(task['result_id'])['intervals'][source['intervalIndex']]
                ranges.append([interval['start'], interval['end']])
            else:
                ranges.append(task['config']['analysisRange'])
        incident_id = body.get('incidentId')
        if incident_id:
            incident = self.store.incidents.get(incident_id)
            if incident['workspace_id'] != experiment['workspace_id']:
                raise ValueError('Incident belongs to another workspace.')
        else:
            incident = self.store.incidents.create(experiment['workspace_id'], dict(
                title=body.get('title') or experiment['name'], source=sources[0],
                start_time=min(window[0] for window in ranges), end_time=max(window[1] for window in ranges)))
            incident_id = incident['id']
        with self.store.connect() as db:
            for source in prepared:
                self.store.incidents.insert_link(db, incident_id, source)
            self.store.incidents.touch(db, incident_id, experiment['workspace_id'])
        return self.store.incidents.get(incident_id)
