"""Persistent status and numerical observation checkpoints for plant investigations."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
from threading import Event, Lock
from time import monotonic
import traceback

import numpy as np

from .datasets import series_preview
from .industrial_study import run_report, saved_evidence, study
from .plants import SCENARIOS, catalog, operating_plots, run_id, run_key, settings
from .workspace import now


ACTIVE = ('configured', 'running', 'measurements_available', 'analysis_available')


class Cancelled(Exception):
    pass


class PlantRuns:
    def __init__(self, store):
        self.store = store
        self.lock = Lock()
        self.active = {}
        self.study_locks = {}
        self.worker = ThreadPoolExecutor(max_workers=2, thread_name_prefix='plant')
        with store.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS plant_runs (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                updated_at TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL)''')
            db.execute(f"UPDATE plant_runs SET status='interrupted' WHERE status IN ({','.join('?' for _ in ACTIVE)})", ACTIVE)

    def close(self):
        with self.lock:
            for cancel in self.active.values():
                cancel.set()
        self.worker.shutdown(wait=True)

    def row(self, row):
        return dict(json.loads(row['payload']), id=row['id'], updatedAt=row['updated_at'], status=row['status'])

    def list(self, wid):
        self.store.workspace(wid)
        with self.store.connect() as db:
            rows = db.execute('SELECT * FROM plant_runs WHERE workspace_id=? ORDER BY updated_at DESC', (wid,)).fetchall()
        runs = [self.row(row) for row in rows]
        for run in runs:
            run.pop('result', None)
        return dict(plants=catalog(), runs=runs)

    def get(self, wid, identity, *, include_report=True):
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM plant_runs WHERE workspace_id=? AND id=?', (wid, identity)).fetchone()
        if row is None:
            raise KeyError('Plant run not found.')
        run = self.row(row)
        result = run.get('result')
        if include_report and result and result.get('runId') and 'report' not in result:
            experiment = self.store.experiments.run(result['runId'])
            task = next(t for t in experiment['tasks'] if t['result_id'] == result['analysisId'])
            analysis = self.store.result(result['analysisId'])
            dataset = self.store.base_dataset(result['datasets']['evaluation'])
            definitions = [{key: value for key, value in column.items() if key not in ('min', 'max', 'missing')}
                           for column in dataset['metadata']['columns']]
            records = {key: result[key] for key in ('analysisId', 'experimentId', 'runId', 'incidentId')}
            result['report'] = run_report(saved_evidence(self.store, result['runId']), analysis, task, definitions, records)
        return run

    def put(self, wid, identity, status, payload):
        with self.store.connect() as db:
            db.execute('''INSERT INTO plant_runs VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                updated_at=excluded.updated_at,status=excluded.status,payload=excluded.payload''',
                (identity, wid, now(), status, json.dumps(payload, allow_nan=False)))

    def start(self, wid, scenario_id, supplied, stage='investigation'):
        if not isinstance(scenario_id, str) or scenario_id not in SCENARIOS or not isinstance(supplied, dict):
            raise ValueError('Select an executable plant scenario and enter run settings.')
        if stage not in ('measurements', 'investigation'):
            raise ValueError('Choose measurements or the complete investigation.')
        scenario = SCENARIOS[scenario_id]
        config = settings(scenario, supplied)
        identity = run_id(f'{wid}/{run_key(scenario, config)}')
        with self.lock:
            self.store.workspace(wid)
            try:
                existing = self.get(wid, identity)
            except KeyError:
                existing = {}
            if (identity in self.active or existing.get('status') == 'completed'
                    or (stage == 'measurements' and existing.get('status') == 'measurements_ready')):
                return existing
            payload = dict(plantId=scenario.plant.id, modelVersion=scenario.plant.version, scenarioId=scenario_id,
                           title=scenario.title, settings=config, createdAt=existing.get('createdAt', now()),
                           signalDefinitions=[scenario.plant.signals[i-1] for i in scenario.plant.channels],
                           operatingPlots=operating_plots(scenario))
            self.put(wid, identity, 'configured', payload)
            cancel = self.active[identity] = Event()
            self.worker.submit(self.execute, wid, identity, scenario, config, payload, cancel, stage)
        return self.get(wid, identity)

    def cancel(self, wid, identity):
        with self.lock:
            run = self.get(wid, identity, include_report=False)
            if identity in self.active:
                self.active[identity].set()
        return run

    def folder(self, wid, identity):
        return self.store.root / wid / 'plant-runs' / identity

    @contextmanager
    def workspace_removal(self, wid):
        with self.lock:
            if any(run['id'] in self.active for run in self.list(wid)['runs']):
                raise ValueError('Cancel or complete active plant runs before deleting this workspace.')
            yield

    def study_lock(self, key):
        with self.lock:
            return self.study_locks.setdefault(key, Lock())

    def preview(self, wid, identity, *, operating=False):
        run = self.get(wid, identity, include_report=False)
        names = [s['name'] for s in run['signalDefinitions']]
        requested = names
        if operating:
            plots = run.get('operatingPlots')
            if plots is None and run['scenarioId'] in SCENARIOS:
                plots = operating_plots(SCENARIOS[run['scenarioId']])
            if plots:
                requested = list(dict.fromkeys(s['name'] for plot in plots for s in plot['signals']))
        if run.get('evaluationId'):
            return self.store.series(run['evaluationId'], requested)
        path = self.folder(wid, identity) / 'observations.npz'
        try:
            with self.lock:
                with np.load(path, allow_pickle=False) as data:
                    columns = data['signals'].tolist() if 'signals' in data else names
                    available = [name for name in requested if name in columns]
                    if not available:
                        available = names
                    return series_preview(data['times'], data['values'][:, [columns.index(name) for name in available]], available)
        except FileNotFoundError:
            return None

    def execute(self, wid, identity, scenario, config, payload, cancel, stage):
        path = self.folder(wid, identity) / 'observations.npz'
        names = list(dict.fromkeys(s['name'] for s in (
            payload['signalDefinitions'] + [item for plot in payload['operatingPlots'] for item in plot['signals']]
        )))
        positions = {signal['name']: index for index, signal in enumerate(scenario.plant.signals, start=1)}
        channels = [positions[name] for name in names]
        samples = []
        written, last_write = 0, 0.

        def check():
            if cancel.is_set():
                raise Cancelled

        def progress(status, **updates):
            payload.update(updates)
            self.put(wid, identity, status, payload)

        def finish(status, **updates):
            with self.lock:
                progress(status, **updates)
                self.active.pop(identity, None)

        def checkpoint(force=False):
            nonlocal written, last_write
            stamp = monotonic()
            if len(samples) == written or (not force and written and stamp - last_write < .25):
                return
            rows = np.asarray(samples)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name('pending.npz')
            np.savez_compressed(tmp, times=rows[:, 0], values=rows[:, channels], signals=names)
            with self.lock:
                tmp.replace(path)
            written, last_write = len(samples), stamp
            payload.update(sampleCount=written, latestSeconds=float(rows[-1, 0]))

        def observe(row):
            check()
            samples.append(row)
            if not written or monotonic() - last_write >= .25:
                checkpoint()
                progress('measurements_available', role='evaluation')

        try:
            check()
            result = study(self.store, wid, stage, scenario=scenario, config=config,
                           progress=progress, observe=observe, check=check)
            check()
            with self.lock:
                path.unlink(missing_ok=True)
            result.pop('report', None)
            finish('completed' if stage == 'investigation' else 'measurements_ready', role=None, result=result)
        except Cancelled:
            checkpoint(force=True)
            finish('cancelled')
        except Exception as error:
            checkpoint(force=True)
            if not isinstance(error, ValueError):
                traceback.print_exc()
            finish('failed', error=str(error) if isinstance(error, ValueError) else 'See the local server log for the run error.')
        finally:
            with self.lock:
                if self.active.get(identity) is cancel:
                    self.active.pop(identity)
