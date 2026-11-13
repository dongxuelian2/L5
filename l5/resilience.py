"""Local scenario, simulation and campaign storage for resilience testing."""
from __future__ import annotations

import csv
from hashlib import sha256
from io import StringIO
import json
import math
from pathlib import Path
import platform
from threading import Lock, Thread
from time import perf_counter
from uuid import uuid4
import zlib

import numpy as np

from .data_quality import summarize
from .workspace import now

MAX_ACTIVE = 4
MAX_CAMPAIGN_STEPS = 1_500_000
ENGINE_SOURCES = ('l5/resilience_simulation.py', 'l5/models/tanks.py', 'l5/resilience_evaluation.py',
                  'l5/analysis.py', 'l5/monitoring.py', 'benchmarks/coverage.py', 'benchmarks/temporal.py',
                  'benchmarks/window_cusum.py', 'benchmarks/dynamic_pca.py', 'benchmarks/adaptive.py')


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':'))


def pack(value):
    return zlib.compress(encode(value).encode('utf-8'))


def unpack(value):
    return json.loads(zlib.decompress(value)) if value is not None else None


class ResilienceService:
    def __init__(self, store):
        self.store = store
        self.lock = Lock()
        self.export_lock = Lock()
        self.working = False
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS resilience_scenarios (
                    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    name TEXT NOT NULL, scenario TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS resilience_runs (
                    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    name TEXT NOT NULL, created_at TEXT NOT NULL, simulation BLOB NOT NULL,
                    dataset_id TEXT REFERENCES datasets(id) ON DELETE SET NULL);
                CREATE TABLE IF NOT EXISTS resilience_campaigns (
                    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    name TEXT NOT NULL, mode TEXT NOT NULL, status TEXT NOT NULL, definition TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, error TEXT);
                CREATE TABLE IF NOT EXISTS resilience_campaign_simulations (
                    campaign_id TEXT NOT NULL REFERENCES resilience_campaigns(id) ON DELETE CASCADE,
                    scenario_key TEXT NOT NULL, simulation BLOB NOT NULL,
                    PRIMARY KEY (campaign_id, scenario_key));
                CREATE TABLE IF NOT EXISTS resilience_cases (
                    id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL REFERENCES resilience_campaigns(id) ON DELETE CASCADE,
                    ordinal INTEGER NOT NULL, scenario_key TEXT NOT NULL, plan TEXT NOT NULL, status TEXT NOT NULL,
                    metrics TEXT, evaluation BLOB, runtime_ms REAL, error TEXT,
                    dataset_id TEXT REFERENCES datasets(id) ON DELETE SET NULL,
                    UNIQUE (campaign_id, ordinal));
            ''')
            interrupted = 'The local service restarted before execution finished.'
            db.execute("UPDATE resilience_cases SET status='interrupted',error=? WHERE status IN ('queued','running')", (interrupted,))
            db.execute("UPDATE resilience_campaigns SET status='interrupted',error=?,updated_at=? WHERE status IN ('queued','running')",
                       (interrupted, now()))

    @staticmethod
    def scenario_view(row):
        return {**dict(row), 'scenario': json.loads(row['scenario'])}

    def scenarios(self, workspace_id):
        self.store.workspace(workspace_id)
        with self.store.connect() as db:
            rows = db.execute('SELECT * FROM resilience_scenarios WHERE workspace_id=? ORDER BY updated_at DESC,id', (workspace_id,))
            return [self.scenario_view(row) for row in rows]

    def save_scenario(self, workspace_id, body):
        from .resilience_simulation import validate_scenario
        self.store.workspace(workspace_id)
        name = self.store.name(body.get('name'))
        scenario = encode(validate_scenario(body.get('scenario')))
        identity, stamp = body.get('id'), now()
        with self.store.connect() as db:
            if identity is None:
                identity = uuid4().hex
                db.execute('INSERT INTO resilience_scenarios VALUES (?,?,?,?,?,?)', (identity, workspace_id, name, scenario, stamp, stamp))
            elif not db.execute('UPDATE resilience_scenarios SET name=?,scenario=?,updated_at=? WHERE workspace_id=? AND id=?',
                                (name, scenario, stamp, workspace_id, identity)).rowcount:
                raise KeyError('Resilience scenario not found.')
            db.execute('UPDATE workspaces SET updated_at=? WHERE id=?', (stamp, workspace_id))
            row = db.execute('SELECT * FROM resilience_scenarios WHERE id=?', (identity,)).fetchone()
        return self.scenario_view(row)

    def simulate(self, workspace_id, body):
        from .resilience_simulation import simulate_scenario
        self.store.workspace(workspace_id)
        simulation = simulate_scenario(body.get('scenario'))
        name = self.store.name(body.get('name') or simulation['scenario']['name'])
        identity, stamp = uuid4().hex, now()
        with self.store.connect() as db:
            db.execute('INSERT INTO resilience_runs (id,workspace_id,name,created_at,simulation) VALUES (?,?,?,?,?)',
                       (identity, workspace_id, name, stamp, pack(simulation)))
            db.execute('UPDATE workspaces SET updated_at=? WHERE id=?', (stamp, workspace_id))
        return dict(id=identity, name=name, created_at=stamp, dataset_id=None, **simulation)

    def runs(self, workspace_id):
        self.store.workspace(workspace_id)
        with self.store.connect() as db:
            return [dict(r) for r in db.execute('''SELECT id,name,created_at,dataset_id FROM resilience_runs
                WHERE workspace_id=? ORDER BY created_at DESC,id''', (workspace_id,))]

    def run(self, workspace_id, identity):
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM resilience_runs WHERE workspace_id=? AND id=?', (workspace_id, identity)).fetchone()
        if row is None:
            raise KeyError('Resilience simulation not found.')
        return dict(id=row['id'], name=row['name'], created_at=row['created_at'], dataset_id=row['dataset_id'], **unpack(row['simulation']))

    def create_campaign(self, workspace_id, body):
        from .experiments import file_hash
        from .resilience_evaluation import BENCHMARK_VERSION, prepare_campaign
        self.store.workspace(workspace_id)
        mode = body.get('mode', 'grid')
        name = self.store.name(body.get('name') or {'benchmark': 'Coupled-tank benchmark', 'search': 'Failure search'}.get(mode, 'Resilience campaign'))
        plans = prepare_campaign(body)
        source_root = Path(__file__).resolve().parents[1]
        engine = dict(python=platform.python_version(), numpy=np.__version__, protocol=1,
                      sourceHashes={path: file_hash(source_root / path) for path in ENGINE_SOURCES})
        definition = encode(dict(request=body, engine=engine, benchmark=BENCHMARK_VERSION if mode == 'benchmark' else None))
        campaign_id, stamp = uuid4().hex, now()
        records, integration_steps = [], 0
        for i, plan in enumerate(plans):
            scenario = plan['scenario']
            period = scenario['sample_interval']
            simulation_steps = math.ceil(scenario['duration'] / period) * math.ceil(period / scenario['integration_step'])
            reference_step = max(.05, min(.25, period))
            reference_steps = 319 * math.ceil(period / reference_step)
            controls = len(scenario['faults']) if plan.get('objective') == 'suppression' else 0
            integration_steps += (simulation_steps + reference_steps) * (1 + controls)
            if integration_steps > MAX_CAMPAIGN_STEPS:
                raise ValueError('Campaign exceeds the integration budget. Reduce cases, duration, or sampling frequency.')
            key = sha256(encode(plan['scenario']).encode('utf-8')).hexdigest()
            records.append((uuid4().hex, campaign_id, i, key, encode(plan), 'queued'))
        with self.lock:
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                active = db.execute("SELECT COUNT(*) FROM resilience_campaigns WHERE status IN ('queued','running')").fetchone()[0]
                if active >= MAX_ACTIVE:
                    raise ValueError(f'At most {MAX_ACTIVE} resilience campaigns may be active.')
                db.execute('INSERT INTO resilience_campaigns VALUES (?,?,?,?,?,?,?,?,NULL)',
                           (campaign_id, workspace_id, name, mode, 'queued', definition, stamp, stamp))
                db.executemany('INSERT INTO resilience_cases (id,campaign_id,ordinal,scenario_key,plan,status) VALUES (?,?,?,?,?,?)', records)
                db.execute('UPDATE workspaces SET updated_at=? WHERE id=?', (stamp, workspace_id))
            if not self.working:
                self.working = True
                Thread(target=self._drain, name='l5-resilience-worker', daemon=True).start()
        return self.campaign(workspace_id, campaign_id)

    @staticmethod
    def campaign_query(predicate):
        return f'''SELECT c.id,c.workspace_id,c.name,c.mode,c.status,c.created_at,c.updated_at,c.error,
            COUNT(t.id) AS total,
            COALESCE(SUM(CASE WHEN t.status IN ('succeeded','failed','interrupted') THEN 1 ELSE 0 END),0) AS completed,
            COALESCE(SUM(CASE WHEN t.status='failed' THEN 1 ELSE 0 END),0) AS failed
            FROM resilience_campaigns c LEFT JOIN resilience_cases t ON t.campaign_id=c.id
            WHERE {predicate} GROUP BY c.id'''

    def campaigns(self, workspace_id):
        self.store.workspace(workspace_id)
        with self.store.connect() as db:
            return [dict(row) for row in db.execute(self.campaign_query('c.workspace_id=?') + ' ORDER BY c.created_at DESC,c.id', (workspace_id,))]

    @staticmethod
    def case_view(row):
        plan = json.loads(row['plan'])
        metrics = json.loads(row['metrics']) if row['metrics'] else None
        if metrics:
            metrics = {k: v for k, v in metrics.items() if k != 'events'}
        return dict(id=row['id'], index=row['ordinal'], status=row['status'], runtime_ms=row['runtime_ms'],
                    error=row['error'], dataset_id=row['dataset_id'], metrics=metrics,
                    **{k: v for k, v in plan.items() if k != 'scenario'})

    def campaign(self, workspace_id, identity):
        with self.store.connect() as db:
            db.execute('BEGIN')
            row = db.execute(self.campaign_query('c.workspace_id=? AND c.id=?'), (workspace_id, identity)).fetchone()
            if row is None:
                raise KeyError('Resilience campaign not found.')
            definition = db.execute('SELECT definition FROM resilience_campaigns WHERE id=?', (identity,)).fetchone()['definition']
            cases = [self.case_view(t) for t in db.execute('''SELECT id,ordinal,plan,status,metrics,runtime_ms,error,dataset_id
                FROM resilience_cases WHERE campaign_id=? ORDER BY ordinal''', (identity,))]
        return dict(row, definition=json.loads(definition), cases=cases)

    def case(self, workspace_id, campaign_id, identity):
        with self.store.connect() as db:
            row = db.execute('''SELECT t.*,s.simulation FROM resilience_cases t
                JOIN resilience_campaigns c ON c.id=t.campaign_id
                LEFT JOIN resilience_campaign_simulations s USING (campaign_id,scenario_key)
                WHERE c.workspace_id=? AND c.id=? AND t.id=?''', (workspace_id, campaign_id, identity)).fetchone()
        if row is None:
            raise KeyError('Resilience case not found.')
        return {**self.case_view(row), 'scenario': json.loads(row['plan'])['scenario'],
                'metrics': json.loads(row['metrics']) if row['metrics'] else None,
                'simulation': unpack(row['simulation']), 'evaluation': unpack(row['evaluation'])}

    def _drain(self):
        while True:
            with self.lock:
                with self.store.connect() as db:
                    campaign = db.execute("SELECT id FROM resilience_campaigns WHERE status='queued' ORDER BY created_at,id LIMIT 1").fetchone()
                if campaign is None:
                    self.working = False
                    return
            campaign_id = campaign['id']
            try:
                self._perform(campaign_id)
            except Exception as error:
                message = str(error)[:4000] or type(error).__name__
                with self.store.connect() as db:
                    db.execute("UPDATE resilience_cases SET status='failed',error=? WHERE campaign_id=? AND status IN ('queued','running')",
                               (message, campaign_id))
                    db.execute("UPDATE resilience_campaigns SET status='failed',error=?,updated_at=? WHERE id=?", (message, now(), campaign_id))

    def _perform(self, campaign_id):
        from .resilience_evaluation import evaluate_case
        from .resilience_simulation import simulate_scenario
        with self.store.connect() as db:
            db.execute("UPDATE resilience_campaigns SET status='running',updated_at=? WHERE id=?", (now(), campaign_id))
            tasks = db.execute('SELECT id,scenario_key,plan FROM resilience_cases WHERE campaign_id=? ORDER BY ordinal', (campaign_id,)).fetchall()
        succeeded = 0
        for task in tasks:
            start = perf_counter()
            status, failure, metrics, evidence = 'failed', None, None, None
            plan = json.loads(task['plan'])
            key = task['scenario_key']
            with self.store.connect() as db:
                if not db.execute("UPDATE resilience_cases SET status='running' WHERE id=?", (task['id'],)).rowcount:
                    return
                previous = db.execute('SELECT simulation FROM resilience_campaign_simulations WHERE campaign_id=? AND scenario_key=?',
                                      (campaign_id, key)).fetchone()
            phase = 'simulation'
            try:
                if previous is None:
                    simulation = simulate_scenario(plan['scenario'])
                    with self.store.connect() as db:
                        db.execute('INSERT INTO resilience_campaign_simulations (campaign_id,scenario_key,simulation) VALUES (?,?,?)',
                                   (campaign_id, key, pack(simulation)))
                else:
                    simulation = unpack(previous['simulation'])
                phase = 'detector evaluation'
                evaluation = evaluate_case(simulation, plan['detector'], objective=plan.get('objective'))
                metrics, evidence = encode(evaluation['metrics']), pack(evaluation)
                status = 'succeeded'
                succeeded += 1
            except Exception as error:
                failure = f'{phase}: {str(error) or type(error).__name__}'[:4000]
            with self.store.connect() as db:
                db.execute('''UPDATE resilience_cases SET status=?,metrics=?,evaluation=?,runtime_ms=?,error=? WHERE id=?''',
                           (status, metrics, evidence, round((perf_counter()-start)*1000, 2), failure, task['id']))
                db.execute('UPDATE resilience_campaigns SET updated_at=? WHERE id=?', (now(), campaign_id))
        status = 'completed' if succeeded == len(tasks) else 'partial' if succeeded else 'failed'
        with self.store.connect() as db:
            db.execute('UPDATE resilience_campaigns SET status=?,updated_at=? WHERE id=?', (status, now(), campaign_id))

    def export(self, workspace_id, body):
        run_id, campaign_id, case_id = (body.get(k) for k in ('run_id', 'campaign_id', 'case_id'))
        if not ((run_id and not campaign_id and not case_id) or (not run_id and campaign_id and case_id)):
            raise ValueError('Select a resilience run or a campaign case to export.')
        with self.export_lock:
            if run_id:
                item = simulation = self.run(workspace_id, run_id)
                reference = dict(runId=run_id)
            else:
                item = self.case(workspace_id, campaign_id, case_id)
                simulation = item['simulation']
                reference = dict(campaignId=campaign_id, caseId=case_id)
            if item['dataset_id']:
                return self.store.dataset(item['dataset_id'])
            if simulation is None:
                raise ValueError('This case has no saved measurements.')
            def link(db, dataset_id):
                if run_id:
                    cursor = db.execute('UPDATE resilience_runs SET dataset_id=? WHERE id=? AND dataset_id IS NULL', (dataset_id, run_id))
                else:
                    cursor = db.execute('UPDATE resilience_cases SET dataset_id=? WHERE id=? AND dataset_id IS NULL', (dataset_id, case_id))
                if not cursor.rowcount:
                    raise ValueError('The resilience source changed while exporting. Reopen it and try again.')
            return self._export_observations(workspace_id, body.get('name') or item['name'], simulation, reference, link)

    def _export_observations(self, workspace_id, name, simulation, reference, link):
        observations = simulation['observations']
        signals = simulation['signals']
        keys = [signal['key'] for signal in signals]
        times = np.array([frame['t'] for frame in observations], dtype=float)
        values = np.array([[frame['values'][key] for key in keys] for frame in observations], dtype=float)
        quality = summarize(times, values, keys)
        columns = [dict(name=key, displayName=signal.get('label', key), unit=signal.get('unit', ''),
                        logicalKey=signal.get('tag', key), tags=['simulation'],
                        **{k: quality['signals'][key][k] for k in ('min', 'max', 'missing')})
                   for key, signal in zip(keys, signals)]
        time = dict(kind='numeric', column='t', sourceUnit='seconds', origin=None, unit='seconds',
                    **{k: quality[k] for k in ('start', 'end', 'typicalInterval', 'irregularCount', 'duplicateCount', 'invalidTimeCount', 'gapCount')})
        metadata = dict(filename='resilience-observations.csv', rowCount=len(times), columns=columns,
                        sourceColumns=['t', *keys], ignoredColumns=[], time=time, quality=quality,
                        missingCount=int(np.isnan(values).sum()), notes=[],
                        resilience=dict(**reference, modelId=simulation['scenario']['model_id'], modelVersion=simulation['model_version'],
                                        timeAxis='acquisition-seconds'))
        csv_buffer = StringIO(newline='')
        writer = csv.writer(csv_buffer, lineterminator='\n')
        writer.writerow(['t', *keys])
        writer.writerows([frame['t'], *(frame['values'][key] for key in keys)] for frame in observations)
        boundary = min(len(times) - 2, max(99, int(len(times) * .2) - 1))
        if boundary >= 0:
            metadata['suggestedRanges'] = dict(baselineRange=[float(times[0]), float(times[boundary])],
                                               analysisRange=[float(times[boundary + 1]), float(times[-1])])
        return self.store.save_dataset(workspace_id, name, metadata, times, values, csv_buffer.getvalue(), on_save=link)
