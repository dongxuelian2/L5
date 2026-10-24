"""Local workspace repository: SQLite metadata, original CSV, NumPy arrays and results."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sqlite3
from uuid import uuid4

import numpy as np

from .analysis import run_analysis
from .datasets import prepare_csv, series_preview


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkspaceStore:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS workspaces (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS datasets (
                    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    name TEXT NOT NULL, metadata TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    dataset_id TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
                    name TEXT NOT NULL, config TEXT NOT NULL, summary TEXT NOT NULL,
                    created_at TEXT NOT NULL);
            ''')
        from .runtime import SimulationService
        self.runtime = SimulationService(self)
        from .incidents import IncidentService
        self.incidents = IncidentService(self)
        from .signals import SignalWorkspace
        self.signals = SignalWorkspace(self)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.root / 'workspace.sqlite3', timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys = ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def name(value: str) -> str:
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 160:
            raise ValueError('Name must contain 1–160 characters.')
        return value.strip()

    def workspace(self, workspace_id: str) -> dict:
        with self.connect() as db:
            row = db.execute('SELECT * FROM workspaces WHERE id=?', (workspace_id,)).fetchone()
        if row is None:
            raise KeyError('Workspace not found.')
        return dict(row)

    def list_workspaces(self) -> list[dict]:
        with self.connect() as db:
            return [dict(r) for r in db.execute('''SELECT w.*,
                (SELECT COUNT(*) FROM datasets WHERE workspace_id=w.id) AS dataset_count,
                (SELECT COUNT(*) FROM jobs WHERE workspace_id=w.id) AS analysis_count
                FROM workspaces w ORDER BY updated_at DESC''')]

    def create_workspace(self, name: str) -> dict:
        identity, stamp = uuid4().hex, now()
        with self.connect() as db:
            db.execute('INSERT INTO workspaces VALUES (?,?,?,?)', (identity, self.name(name), stamp, stamp))
        return self.workspace(identity)

    def rename_workspace(self, identity: str, name: str) -> dict:
        self.workspace(identity)
        with self.connect() as db:
            db.execute('UPDATE workspaces SET name=?,updated_at=? WHERE id=?', (self.name(name), now(), identity))
        return self.workspace(identity)

    def delete_workspace(self, identity: str):
        self.workspace(identity)
        simulations = {s['id'] for s in self.runtime.list(identity)}
        simulations.update(d['metadata']['model']['simulationId'] for d in self.datasets(identity) if d['metadata'].get('model'))
        with self.connect() as db:
            db.execute('DELETE FROM workspaces WHERE id=?', (identity,))
            remaining = [self.dataset_row(r) for r in db.execute('SELECT * FROM datasets')]
        folder = self.root / identity  # identity has been resolved against an existing generated ID.
        if folder.is_dir():
            shutil.rmtree(folder)
        for simulation_id in simulations:
            reference = next((d for d in remaining if d['metadata'].get('model', {}).get('simulationId') == simulation_id), None)
            session = self.runtime.get(simulation_id)
            session.update(workspaceId=reference['workspace_id'] if reference else None,
                           datasetId=reference['id'] if reference else None)
            self.runtime.write(self.runtime.folder(simulation_id) / 'session.json', session)

    def datasets(self, workspace_id: str) -> list[dict]:
        self.workspace(workspace_id)
        with self.connect() as db:
            return [self.dataset_row(r) for r in db.execute('SELECT * FROM datasets WHERE workspace_id=? ORDER BY created_at DESC', (workspace_id,))]

    def dataset_row(self, row) -> dict:
        return self.signals.project({**dict(row), 'metadata': json.loads(row['metadata'])})

    def dataset(self, identity: str) -> dict:
        return self.signals.project(self.base_dataset(identity))

    def base_dataset(self, identity: str) -> dict:
        with self.connect() as db:
            row = db.execute('SELECT * FROM datasets WHERE id=?', (identity,)).fetchone()
        if row is None:
            raise KeyError('Dataset not found.')
        return {**dict(row), 'metadata': json.loads(row['metadata'])}

    def import_dataset(self, workspace_id: str, body: dict, *, model=None) -> dict:
        self.workspace(workspace_id)
        metadata, times, values = prepare_csv(body.get('csv'), body)
        identity, stamp = uuid4().hex, now()
        name = self.name(body.get('name') or body.get('filename') or 'Imported CSV')
        metadata['filename'] = str(body.get('filename', name))
        if model:
            metadata['model'] = model
            config = self.runtime.get(model['simulationId'])['config']
            healthy = times[times < min(config['start'], 20)]
            if len(healthy) and np.any(times > healthy[-1]):
                metadata['suggestedRanges'] = {'baselineRange':[float(times[0]), float(healthy[-1])],
                                               'analysisRange':[float(times[times > healthy[-1]][0]), float(times[-1])]}

        folder = self.root / workspace_id / 'datasets' / identity
        folder.mkdir(parents=True)
        try:
            (folder / 'source.csv').write_text(body['csv'], encoding='utf-8')
            np.savez_compressed(folder / 'series.npz', times=times, values=values)
            with self.connect() as db:
                db.execute('INSERT INTO datasets VALUES (?,?,?,?,?)', (identity, workspace_id, name, json.dumps(metadata), stamp))
                self.signals.register(dict(id=identity, metadata=metadata), db)
                db.execute('UPDATE workspaces SET updated_at=? WHERE id=?', (stamp, workspace_id))
        except Exception:
            shutil.rmtree(folder)
            raise
        return self.dataset(identity)

    def load_data(self, dataset: dict):
        with np.load(self.root / dataset['workspace_id'] / 'datasets' / dataset['id'] / 'series.npz', allow_pickle=False) as data:
            return data['times'], data['values']

    def series(self, identity: str, signals: list[str] | None = None, start: float | None = None, end: float | None = None) -> dict:
        dataset = self.dataset(identity)
        columns = [c['name'] for c in dataset['metadata']['columns']]
        signals = columns[:4] if signals is None else signals
        if not signals or any(s not in columns for s in signals):
            raise ValueError('Select numeric signals from this dataset.')
        times, values = self.load_data(dataset)
        mask = (times >= (start if start is not None else times[0])) & (times <= (end if end is not None else times[-1]))
        if not mask.any():
            raise ValueError('No samples in this time range.')
        return series_preview(times[mask], values[mask][:, [columns.index(s) for s in signals]], signals,
                              gap_threshold=dataset['metadata']['quality']['gapThreshold'])

    def jobs(self, workspace_id: str) -> list[dict]:
        self.workspace(workspace_id)
        with self.connect() as db:
            return [{**dict(r), 'config': json.loads(r['config']), 'summary': json.loads(r['summary'])} for r in
                    db.execute('SELECT * FROM jobs WHERE workspace_id=? ORDER BY created_at DESC', (workspace_id,))]

    def sample(self, identity, at, signals=None):
        """Nearest full-resolution observation for a shared incident cursor."""
        if not np.isfinite(at):
            raise ValueError('请选择有限的观察时间。')
        dataset = self.dataset(identity)
        names = [c['name'] for c in dataset['metadata']['columns']]
        signals = names[:4] if signals is None else signals
        if not signals or any(s not in names for s in signals):
            raise ValueError('请选择此数据集的数值变量。')
        times, values = self.load_data(dataset)
        right = min(len(times)-1, int(np.searchsorted(times, at)))
        index = right-1 if right and abs(times[right-1]-at) <= abs(times[right]-at) else right
        def value(row, column):
            v = values[row, names.index(column)]
            return float(v) if np.isfinite(v) else None
        return dict(time=float(times[index]), previousTime=float(times[index-1]) if index else None,
                    nextTime=float(times[index+1]) if index+1 < len(times) else None,
                    values={s: value(index, s) for s in signals},
                    previous={s: value(index-1, s) if index else None for s in signals})

    def analyze(self, workspace_id: str, body: dict) -> dict:
        self.workspace(workspace_id)
        dataset = self.dataset(body.get('datasetId', ''))
        if dataset['workspace_id'] != workspace_id:
            raise ValueError('Dataset belongs to a different workspace.')
        times, values = self.load_data(dataset)
        result = run_analysis(times, values, [c['name'] for c in dataset['metadata']['columns']], body)
        identity, stamp = uuid4().hex, now()
        name = self.name(body.get('name') or f"{result['algorithmLabel']} · {dataset['name']}")
        result.update({'id': identity, 'workspaceId': workspace_id, 'datasetId': dataset['id'], 'name': name, 'createdAt': stamp})
        folder = self.root / workspace_id / 'results'
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f'{identity}.json'
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        temporary.replace(path)
        try:
            with self.connect() as db:
                db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?)',
                           (identity, workspace_id, dataset['id'], name, json.dumps(result['config']), json.dumps(result['summary']), stamp))
                db.execute('UPDATE workspaces SET updated_at=? WHERE id=?', (stamp, workspace_id))
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return result

    def result(self, identity: str) -> dict:
        with self.connect() as db:
            row = db.execute('SELECT workspace_id FROM jobs WHERE id=?', (identity,)).fetchone()
        if row is None:
            raise KeyError('Analysis not found.')
        return json.loads((self.root / row['workspace_id'] / 'results' / f'{identity}.json').read_text(encoding='utf-8'))
