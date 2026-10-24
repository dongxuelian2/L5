"""Persistent signal semantics, explicit clocks and multi-source exploration."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from uuid import uuid4, uuid5, NAMESPACE_URL

import numpy as np

from .data_quality import summarize
from .datasets import series_preview


def finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value):
        raise ValueError('Enter a finite time in seconds.')
    return float(value)


def utc_seconds(value):
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError('UTC origin must include a timezone, for example 2026-10-24T08:00:00+08:00.')
        return stamp.timestamp()
    except (TypeError, AttributeError, OverflowError) as error:
        raise ValueError('Enter an ISO date/time with timezone.') from error


class SignalWorkspace:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS signals (
                    id TEXT PRIMARY KEY,
                    dataset_id TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
                    column_name TEXT NOT NULL, metadata TEXT NOT NULL,
                    UNIQUE(dataset_id, column_name));
                CREATE TABLE IF NOT EXISTS dataset_time_references (
                    dataset_id TEXT PRIMARY KEY REFERENCES datasets(id) ON DELETE CASCADE,
                    config TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS explorer_views (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    name TEXT NOT NULL, config TEXT NOT NULL, updated_at TEXT NOT NULL);
            ''')
            for row in db.execute('SELECT * FROM datasets').fetchall():
                dataset = {**dict(row), 'metadata': json.loads(row['metadata'])}
                metadata = dataset['metadata']
                if 'quality' not in metadata:
                    times, values = store.load_data(dataset)
                    metadata['quality'] = summarize(times, values, [c['name'] for c in metadata['columns']])
                    for key in ('typicalInterval', 'irregularCount', 'duplicateCount', 'invalidTimeCount', 'gapCount'):
                        metadata['time'][key] = metadata['quality'][key]
                    db.execute('UPDATE datasets SET metadata=? WHERE id=?', (json.dumps(metadata), dataset['id']))
                self.register(dataset, db)

    def register(self, dataset, db):
        model = dataset['metadata'].get('model')
        if model:
            from simulation.platform import META
        for column in dataset['metadata']['columns']:
            name = column['name']
            defaults = dict(displayName=name, unit='', description='', category='', device='', tags=[], logicalKey='')
            if model and name in META:
                signal = META[name]
                defaults.update(displayName=signal.get('label', name), unit=signal.get('unit', ''),
                                device='TripLens process', tags=['simulation'])
            identity = uuid5(NAMESPACE_URL, f'l5:dataset:{dataset["id"]}:signal:{name}').hex
            db.execute('INSERT OR IGNORE INTO signals VALUES (?,?,?,?)', (identity, dataset['id'], name, json.dumps(defaults)))

    def project(self, dataset):
        with self.store.connect() as db:
            rows = db.execute('SELECT * FROM signals WHERE dataset_id=?', (dataset['id'],)).fetchall()
        by_name = {r['column_name']: dict(id=r['id'], **json.loads(r['metadata'])) for r in rows}
        dataset['metadata']['columns'] = [{**c, **by_name.get(c['name'], {})} for c in dataset['metadata']['columns']]
        dataset['metadata']['clock'] = self.clock(dataset['id'])
        return dataset

    def catalog(self, workspace_id):
        signals = []
        for dataset in self.store.datasets(workspace_id):
            metadata = dataset['metadata']
            for column in metadata['columns']:
                signals.append(dict(**column, datasetId=dataset['id'], workspaceId=workspace_id,
                    datasetName=dataset['name'], source='TripLens simulation' if metadata.get('model') else 'CSV',
                    simulationId=metadata.get('model', {}).get('simulationId'),
                    time=metadata['time'], clock=metadata['clock'], quality=metadata['quality']['signals'][column['name']]))
        return signals

    def update_signal(self, identity, body):
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM signals WHERE id=?', (identity,)).fetchone()
            if row is None:
                raise KeyError('Signal not found.')
            metadata = json.loads(row['metadata'])
            if set(body) - metadata.keys():
                raise ValueError('Only signal display metadata can be edited; the source column and ID are stable.')
            for key, value in body.items():
                if key == 'tags':
                    if not isinstance(value, list) or len(value) > 40 or any(not isinstance(t, str) or not t.strip() or len(t) > 80 for t in value):
                        raise ValueError('Tags must be a list of up to 40 nonempty labels (80 characters each).')
                    metadata[key] = list(dict.fromkeys(t.strip() for t in value))
                else:
                    if not isinstance(value, str) or len(value) > (4000 if key == 'description' else 160):
                        raise ValueError('Signal text is too long or invalid.')
                    if key == 'displayName' and not value.strip():
                        raise ValueError('Display name is required.')
                    metadata[key] = value.strip()
            db.execute('UPDATE signals SET metadata=? WHERE id=?', (json.dumps(metadata), identity))
        return dict(id=identity, name=row['column_name'], datasetId=row['dataset_id'], **metadata)

    def reference(self, identity):
        self.store.base_dataset(identity)
        with self.store.connect() as db:
            row = db.execute('SELECT config FROM dataset_time_references WHERE dataset_id=?', (identity,)).fetchone()
        return json.loads(row['config']) if row else dict(mode='independent', offsetSeconds=0)

    def clock(self, identity, seen=()):
        if identity in seen:
            raise ValueError('Time references cannot form a cycle.')
        dataset = self.store.base_dataset(identity)
        metadata = dataset['metadata']
        origin = metadata['time'].get('origin')
        key = 'dataset:' + identity
        config = self.reference(identity)
        if origin:
            return dict(key=key, axisId='utc', offset=utc_seconds(origin), label='UTC absolute time', reference=dict(mode='native'))
        if config['mode'] == 'utc':
            return dict(key=key, axisId='utc', offset=utc_seconds(config['utcOrigin']) + config['offsetSeconds'],
                        label='UTC absolute time', reference=config)
        if config['mode'] == 'reference':
            target = config['referenceDatasetId']
            if target in (*seen, identity):
                raise ValueError('Time references cannot form a cycle.')
            parent = self.clock(target, (*seen, identity))
            return dict(key=key, axisId=parent['axisId'], offset=parent['offset'] + config['offsetSeconds'],
                        label=parent['label'], reference=config)
        simulation = metadata.get('model', {}).get('simulationId')
        return dict(key=key, axisId='simulation:' + simulation if simulation else key, offset=0,
                    label=dataset['name'], reference=config)

    def set_reference(self, identity, body):
        dataset = self.store.base_dataset(identity)
        if dataset['metadata']['time'].get('origin'):
            raise ValueError('This dataset already has an absolute source clock. Its original timestamps are preserved.')
        mode = body.get('mode')
        if mode not in ('independent', 'reference', 'utc'):
            raise ValueError('Choose an independent clock, another dataset, or a UTC origin.')
        config = dict(mode=mode, offsetSeconds=finite(body.get('offsetSeconds', 0)) if mode != 'independent' else 0)
        if mode == 'reference':
            target = self.store.base_dataset(body.get('referenceDatasetId', ''))
            if target['workspace_id'] != dataset['workspace_id']:
                raise ValueError('Time reference must belong to the same workspace.')
            # Validate the entire proposed chain before writing it.
            self.clock(target['id'], (identity,))
            config['referenceDatasetId'] = target['id']
        elif mode == 'utc':
            seconds = utc_seconds(body.get('utcOrigin'))
            config['utcOrigin'] = datetime.fromtimestamp(seconds, timezone.utc).isoformat()
        with self.store.connect() as db:
            db.execute('INSERT INTO dataset_time_references VALUES (?,?) ON CONFLICT(dataset_id) DO UPDATE SET config=excluded.config',
                       (identity, json.dumps(config)))
        return self.clock(identity)

    def selection(self, workspace_id, identities):
        if not isinstance(identities, list) or any(not isinstance(s, str) for s in identities):
            raise ValueError('Choose signal IDs from this workspace.')
        catalog = {s['id']: s for s in self.catalog(workspace_id)}
        if any(s not in catalog for s in identities):
            raise ValueError('Selected signal does not belong to this workspace.')
        return [catalog[s] for s in dict.fromkeys(identities)]

    def exploration_axes(self, selected, windows):
        if not isinstance(windows, dict):
            raise ValueError('Observation windows must be keyed by clock identity.')
        axes = {}
        for signal in selected:
            clock, time = signal['clock'], signal['time']
            first, last = time['start'] + clock['offset'], time['end'] + clock['offset']
            axis = axes.setdefault(clock['axisId'], dict(id=clock['axisId'], label=clock['label'],
                origin='1970-01-01T00:00:00Z' if clock['axisId'] == 'utc' else None, start=first, end=last))
            axis['start'], axis['end'] = min(axis['start'], first), max(axis['end'], last)
        for axis in axes.values():
            window = windows.get(axis['id'], {})
            if not isinstance(window, dict):
                raise ValueError('Enter a valid observation window.')
            start, end = finite(window.get('start', axis['start'])), finite(window.get('end', axis['end']))
            if start > end:
                raise ValueError('Observation window start must precede its end.')
            at = finite(window.get('at', start))
            if not start <= at <= end:
                raise ValueError('Observation cursor must be inside its window.')
            axis['window'] = dict(start=start, end=end, at=at)
        return axes

    def explore(self, workspace_id, body):
        selected = self.selection(workspace_id, body.get('signalIds', []))
        axes = self.exploration_axes(selected, body.get('windows', {}))
        series, loaded = [], {}
        for signal in selected:
            identity, name, clock = signal['datasetId'], signal['name'], signal['clock']
            if identity not in loaded:
                dataset = self.store.dataset(identity)
                times, values = self.store.load_data(dataset)
                loaded[identity] = dataset, times, values
            dataset, times, values = loaded[identity]
            window = axes[clock['axisId']]['window']
            mask = (times >= window['start'] - clock['offset']) & (times <= window['end'] - clock['offset'])
            index = next(i for i, c in enumerate(dataset['metadata']['columns']) if c['name'] == name)
            preview = series_preview(times[mask], values[mask, index:index+1], [name],
                                     gap_threshold=dataset['metadata']['quality']['gapThreshold'])
            series.append(dict(signal=signal, nativeTimes=preview['times'], times=[t + clock['offset'] for t in preview['times']],
                values=preview['values'][name], segmentIds=preview['segmentIds'][name],
                sourceRows=preview['sourceRows'], displayRows=preview['displayRows']))
        return dict(axes=list(axes.values()), series=series)

    def cursor(self, workspace_id, body):
        at, axis_id = finite(body.get('at')), body.get('axisId')
        samples = []
        loaded = {}
        for signal in self.selection(workspace_id, body.get('signalIds', [])):
            clock = signal['clock']
            if clock['axisId'] != axis_id:
                continue
            identity = signal['datasetId']
            if identity not in loaded:
                dataset = self.store.dataset(identity)
                loaded[identity] = dataset, *self.store.load_data(dataset)
            dataset, times, values = loaded[identity]
            local = at - clock['offset']
            status = 'outside' if local < times[0] or local > times[-1] else 'gap' if any(
                gap['start'] < local < gap['end'] for gap in dataset['metadata']['quality']['gaps']) else 'measured'
            right = min(len(times)-1, int(np.searchsorted(times, local)))
            index = right-1 if right and abs(times[right-1]-local) <= abs(times[right]-local) else right
            index = int(np.searchsorted(times, times[index], side='left'))
            column = next(i for i, c in enumerate(dataset['metadata']['columns']) if c['name'] == signal['name'])
            value = values[index, column]
            if status == 'measured' and not np.isfinite(value):
                status = 'missing'
            samples.append(dict(signalId=signal['id'], status=status, value=float(value) if status == 'measured' else None,
                time=float(times[index] + clock['offset']), nativeTime=float(times[index]), sourceIndex=index,
                deltaSeconds=float(times[index] - local), duplicateCount=int(np.searchsorted(times, times[index], side='right') - np.searchsorted(times, times[index], side='left'))))
        return dict(axisId=axis_id, at=at, samples=samples)

    @staticmethod
    def view_row(row):
        return dict(id=row['id'], workspaceId=row['workspace_id'], name=row['name'],
                    updatedAt=row['updated_at'], **json.loads(row['config']))

    def views(self, workspace_id):
        self.store.workspace(workspace_id)
        with self.store.connect() as db:
            return [self.view_row(r) for r in db.execute('SELECT * FROM explorer_views WHERE workspace_id=? ORDER BY updated_at DESC', (workspace_id,))]

    def save_view(self, workspace_id, body, identity=None):
        selected = self.selection(workspace_id, body.get('signalIds', []))
        # Window validation shares the same rules as actual browsing.
        axes = self.exploration_axes(selected, body.get('windows', {}))
        mode = body.get('displayMode', 'separate')
        if mode not in ('separate', 'overlay'):
            raise ValueError('Choose separate curves or compatible overlays.')
        config = dict(signalIds=[s['id'] for s in selected], windows={a['id']: a['window'] for a in axes.values()}, displayMode=mode)
        from .workspace import now
        with self.store.connect() as db:
            if identity and not db.execute('SELECT 1 FROM explorer_views WHERE id=? AND workspace_id=?', (identity, workspace_id)).fetchone():
                raise KeyError('Explorer view not found.')
            identity = identity or uuid4().hex
            db.execute('INSERT INTO explorer_views VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,config=excluded.config,updated_at=excluded.updated_at',
                       (identity, workspace_id, self.store.name(body.get('name')), json.dumps(config), now()))
            row = db.execute('SELECT * FROM explorer_views WHERE id=?', (identity,)).fetchone()
        return self.view_row(row)
