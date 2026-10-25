"""Saved transformation definitions and immutable, ordinary Workspace datasets."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import keyword
import re
from uuid import uuid4

import numpy as np

from .data_quality import summarize
from .datasets import series_preview
from .expressions import FUNCTIONS, Quantity, evaluate, parse
from .resampling import DUPLICATES, METHODS, MISSING_METHODS, PROVENANCE, deduplicate, fill_missing, resample
from .signals import finite
from .units import canonical, conversion, convert


def signal_key(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', value) or keyword.iskeyword(value) or value in FUNCTIONS:
        raise ValueError('Signal keys must start with a letter, contain letters, digits or underscores (up to 64), and not be reserved names.')
    return value


def quality_summary(values):
    valid = values[np.isfinite(values)]
    return dict(samples=len(values), validCount=len(valid), missingCount=len(values) - len(valid),
                missingFraction=1 - len(valid) / len(values) if len(values) else 0,
                min=float(valid.min()) if len(valid) else None, max=float(valid.max()) if len(valid) else None)


class TransformationService:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS transformations (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                name TEXT NOT NULL, config TEXT NOT NULL, revision INTEGER NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''')

    @staticmethod
    def row(row):
        return {**dict(row), 'config': json.loads(row['config'])}

    def list(self, workspace_id):
        self.store.workspace(workspace_id)
        with self.store.connect() as db:
            return [self.row(r) for r in db.execute('SELECT * FROM transformations WHERE workspace_id=? ORDER BY updated_at DESC', (workspace_id,))]

    def get(self, identity):
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM transformations WHERE id=?', (identity,)).fetchone()
        if row is None:
            raise KeyError('Transformation not found.')
        return self.row(row)

    def normalize(self, workspace_id, config):
        if not isinstance(config, dict) or config.get('version', 1) != 1:
            raise ValueError('Choose a version 1 transformation definition.')
        sources, derived = config.get('sources'), config.get('derived', [])
        if not isinstance(sources, list) or not sources or len(sources) > 100:
            raise ValueError('Choose 1–100 source signals.')
        if not isinstance(derived, list) or len(derived) > 100:
            raise ValueError('Use up to 100 ordered derived signals.')
        if any(not isinstance(s, dict) for s in sources + derived):
            raise ValueError('Each signal definition must be an object.')
        selected = self.store.signals.selection(workspace_id, [s.get('signalId') for s in sources])
        catalog = {s['id']: s for s in selected}
        keys, normalized, axes = set(), [], set()
        for source in sources:
            signal = catalog[source['signalId']]
            key = signal_key(source.get('key'))
            if key in keys:
                raise ValueError('Every source and derived signal needs a unique key.')
            keys.add(key)
            method = source.get('resampling', 'linear')
            duplicate = source.get('duplicatePolicy', 'error')
            if method not in METHODS or duplicate not in DUPLICATES:
                raise ValueError('Choose a supported resampling method and duplicate policy.')
            gap = finite(source.get('maxGapSeconds', 5 * (signal['time'].get('typicalInterval') or 1)))
            if gap <= 0:
                raise ValueError('Maximum gap must be a positive number of seconds.')
            missing = source.get('missing', {'method': 'keep'})
            if not isinstance(missing, dict) or missing.get('method') not in MISSING_METHODS:
                raise ValueError('Choose a supported missing-value policy.')
            missing = dict(method=missing['method'])
            if missing['method'] == 'fixed':
                missing['value'] = finite(source['missing'].get('value'))
            if missing['method'] == 'statistic':
                statistic = source['missing'].get('statistic', 'median')
                if statistic not in ('mean', 'median', 'min', 'max'):
                    raise ValueError('Choose mean, median, min or max for statistical filling.')
                missing['statistic'] = statistic
            source_unit = source.get('sourceUnit', signal.get('unit', ''))
            target_unit = source.get('unit', source_unit)
            rotational = source.get('rotational', False)
            if not isinstance(rotational, bool):
                raise ValueError('Rotational-speed meaning must be explicitly true or false.')
            relation = conversion(source_unit, target_unit, rotational=rotational)
            # Definitions retain explicit resolved clocks and source unit semantics when reopened.
            clock = source.get('clock', signal['clock'])
            if not isinstance(clock, dict) or not isinstance(clock.get('axisId'), str) or not clock['axisId']:
                raise ValueError('Source clock needs an explicit axis identity.')
            clock = {**clock, 'offset': finite(clock.get('offset'))}
            axes.add(clock['axisId'])
            display = self.store.name(source.get('displayName') or signal.get('displayName') or key)
            normalized.append(dict(signalId=signal['id'], datasetId=signal['datasetId'], column=signal['name'],
                key=key, displayName=display, sourceUnit=source_unit, unit=target_unit, rotational=rotational,
                conversion=relation, resampling=method, maxGapSeconds=gap, duplicatePolicy=duplicate,
                missing=missing, clock=clock))
        if len(axes) != 1:
            raise ValueError('Sources use unrelated clocks. Save an explicit time reference in Signal catalog before aligning them.')
        grid = config.get('grid', {})
        if not isinstance(grid, dict):
            raise ValueError('Enter a target time grid.')
        mode = grid.get('mode', 'intersection')
        interval = finite(grid.get('intervalSeconds', 1))
        if mode not in ('intersection', 'union', 'custom') or interval <= 0:
            raise ValueError('Choose intersection, union or custom coverage and a positive sampling interval.')
        grid = dict(mode=mode, intervalSeconds=interval, axisId=next(iter(axes)))
        if mode == 'custom':
            for key in ('start', 'end'):
                grid[key] = finite(config['grid'].get(key))
            if grid['start'] > grid['end']:
                raise ValueError('Grid start must precede its end.')
        outputs = []
        for output in derived:
            key = signal_key(output.get('key'))
            if key in keys:
                raise ValueError('Every source and derived signal needs a unique key.')
            parse(output.get('expression'), keys)
            unit = output.get('unit', '')
            canonical(unit)
            description = output.get('description', '')
            if not isinstance(description, str) or len(description) > 4000:
                raise ValueError('Derived description must be text of up to 4000 characters.')
            outputs.append(dict(key=key, displayName=self.store.name(output.get('displayName') or key),
                                expression=output['expression'], unit=unit, description=description))
            keys.add(key)
        return dict(version=1, grid=grid, sources=normalized, derived=outputs)

    def save(self, workspace_id, body, identity=None):
        self.store.workspace(workspace_id)
        previous = self.get(identity) if identity else None
        if previous and previous['workspace_id'] != workspace_id:
            raise ValueError('Transformation belongs to another workspace.')
        config = self.normalize(workspace_id, body.get('config'))
        # Validate expressions with actual units and data before persisting a usable definition.
        self.compute(workspace_id, config)
        name = self.store.name(body.get('name'))
        from .workspace import now
        stamp = now()
        identity = identity or uuid4().hex
        with self.store.connect() as db:
            db.execute('''INSERT INTO transformations VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name,config=excluded.config,
                revision=transformations.revision+1,updated_at=excluded.updated_at''',
                (identity, workspace_id, name, json.dumps(config, allow_nan=False), 1, stamp, stamp))
            db.execute('UPDATE workspaces SET updated_at=? WHERE id=?', (stamp, workspace_id))
        return self.get(identity)

    def compute(self, workspace_id, config):
        config = self.normalize(workspace_id, config)
        loaded, prepared, snapshots = {}, [], []
        for source in config['sources']:
            identity = source['datasetId']
            if identity not in loaded:
                dataset = self.store.dataset(identity)
                times, values = self.store.load_data(dataset)
                observed = self.store.observation_mask(dataset)
                path = self.store.root / workspace_id / 'datasets' / identity / 'series.npz'
                loaded[identity] = dataset, times, values, observed
                snapshots.append(dict(datasetId=identity, datasetName=dataset['name'], createdAt=dataset['created_at'],
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest(), simulationId=dataset['metadata'].get('model', {}).get('simulationId'),
                    sourceSimulations=dataset['metadata'].get('transformation', {}).get('sourceSimulations', []),
                    model=dataset['metadata'].get('model'),
                    sourceModels=dataset['metadata'].get('transformation', {}).get('sourceModels', [])))
            dataset, times, values, observed = loaded[identity]
            column = next(i for i, c in enumerate(dataset['metadata']['columns']) if c['name'] == source['column'])
            converted = convert(values[:, column], source['sourceUnit'], source['unit'], rotational=source['rotational'])
            native = times
            mean_times = native[:-1][np.diff(native) == 0] if source['duplicatePolicy'] == 'mean' else np.array([])
            native, converted, mask, duplicates = deduplicate(native, converted, observed[:, column], source['duplicatePolicy'])
            prepared.append((source, native, converted, mask, duplicates, dataset['metadata']['quality'], mean_times))
        starts = [p[1][0] + p[0]['clock']['offset'] for p in prepared]
        ends = [p[1][-1] + p[0]['clock']['offset'] for p in prepared]
        policy = config['grid']
        start = policy.get('start', max(starts) if policy['mode'] == 'intersection' else min(starts))
        end = policy.get('end', min(ends) if policy['mode'] == 'intersection' else max(ends))
        if end < start:
            raise ValueError('Sources have no common coverage. Choose union or a custom interval to preserve missing values.')
        interval = policy['intervalSeconds']
        # Subtract clock origins before adding sample seconds. Forming a Unix-sized
        # timestamp for every sample would round millisecond/subsecond observations.
        local_ends = [p[1][-1] + (p[0]['clock']['offset'] - start) for p in prepared]
        duration = end - start if policy['mode'] == 'custom' else min(local_ends) if policy['mode'] == 'intersection' else max(local_ends)
        tolerance = min(interval * .25, max(1e-12, abs(float(np.spacing(max(1., abs(start))))) * 2))
        ratio = duration / interval
        if not np.isfinite(ratio) or ratio > 999999 or (int(ratio) + 1) * (len(prepared) + len(config['derived'])) > 10000000:
            raise ValueError('Target grid exceeds 1,000,000 rows or 10,000,000 values. Choose a larger interval or shorter window.')
        count = int(np.floor(ratio + tolerance / interval)) + 1
        times = np.arange(count, dtype=float) * interval
        quantities, columns, provenance, masks, summaries = {}, [], [], [], []
        for source, native, values, observed, duplicates, source_quality, mean_times in prepared:
            local = native + (source['clock']['offset'] - start)
            result, codes, measured = resample(local, values, observed, times, method=source['resampling'],
                interval=interval, max_gap=source['maxGapSeconds'], tolerance=tolerance)
            if len(mean_times):
                duplicate_local = mean_times + (source['clock']['offset'] - start)
                indexes = np.minimum(np.searchsorted(times, duplicate_local), len(times) - 1)
                indexes = indexes[np.isclose(times[indexes], duplicate_local, atol=tolerance, rtol=0)]
                codes[indexes[codes[indexes] == 1]] = 4
            before = quality_summary(result)
            eligible = (local >= times[0]) & (local <= times[-1]) & observed
            result, codes, measured, effective_missing = fill_missing(times, result, codes, measured,
                policy=source['missing'], max_gap=source['maxGapSeconds'], coverage=(local[0], local[-1]),
                statistic_values=values[eligible], anchor_times=local, anchor_values=values, anchor_observed=observed)
            finite_result = np.isfinite(result)
            if np.any((codes != 0) & ~finite_result):
                raise ValueError('Resampling produced nonfinite values; check signal magnitudes.')
            quantities[source['key']] = Quantity(result, source['unit'], measured, rotational=source['rotational'])
            columns.append(dict(name=source['key'], displayName=source['displayName'], unit=source['unit'],
                dataType='float64', sourceSignalIds=[source['signalId']], description='Transformed source signal'))
            provenance.append(codes)
            masks.append(measured)
            summaries.append(dict(key=source['key'], sourceSignalId=source['signalId'], sourceCoverage=[float(native[0] + source['clock']['offset']), float(native[-1] + source['clock']['offset'])],
                sourceQuality={k: source_quality[k] for k in ('totalCount', 'invalidTimeCount', 'gapCount', 'irregularCount', 'duplicateCount')},
                sourceSignalQuality={k: source_quality['signals'][source['column']][k] for k in ('finiteCount', 'validCount', 'missingFraction', 'min', 'max', 'invalidTimeMeasurements')},
                duplicatesResolved=duplicates, duplicatePolicy=source['duplicatePolicy'], missingPolicy=effective_missing,
                conversion=source['conversion'], before=before, after=quality_summary(result),
                provenance={label: int(np.sum(codes == code)) for code, label in PROVENANCE.items()},
                observedCount=int(measured.sum())))
        source_ids = {s['key']: [s['signalId']] for s in config['sources']}
        for output in config['derived']:
            quantity, dependencies, inferred = evaluate(output['expression'], quantities, times, output['unit'])
            quantities[output['key']] = quantity
            source_ids[output['key']] = list(dict.fromkeys(s for key in dependencies for s in source_ids[key]))
            columns.append(dict(name=output['key'], displayName=output['displayName'], unit=quantity.unit,
                dataType='float64', expression=output['expression'], sourceSignalIds=source_ids[output['key']],
                dependencies=dependencies, inferredUnit=inferred, description=output['description']))
            codes = np.where(np.isfinite(quantity.values), 7, 0).astype(np.uint8)
            provenance.append(codes)
            masks.append(quantity.observed)
            summaries.append(dict(key=output['key'], dependencies=dependencies, inputUnits={k: quantities[k].unit for k in dependencies},
                inferredUnit=inferred, outputUnit=quantity.unit, before=quality_summary(quantity.values), after=quality_summary(quantity.values),
                provenance={label: int(np.sum(codes == code)) for code, label in PROVENANCE.items()}, observedCount=int(quantity.observed.sum())))
        values = np.column_stack([quantities[c['name']].values for c in columns])
        names = [c['name'] for c in columns]
        quality = summarize(times, values, names)
        for column in columns:
            q = quality['signals'][column['name']]
            column.update(missing=q['missing'], min=q['min'], max=q['max'])
        absolute = policy['axisId'] == 'utc'
        origin = datetime.fromtimestamp(start, timezone.utc).isoformat() if absolute else None
        time = dict(kind='datetime' if absolute else 'numeric', origin=origin, column='time', unit='seconds',
                    start=0., end=float(times[-1]), sampleInterval=interval,
                    **{k: quality[k] for k in ('typicalInterval', 'irregularCount', 'duplicateCount', 'invalidTimeCount', 'gapCount')})
        simulations = list(dict.fromkeys(sid for s in snapshots for sid in ([s['simulationId']] if s['simulationId'] else s['sourceSimulations'])))
        source_models = {m['simulationId']: m for s in snapshots for m in ([s['model']] if s.get('model') else s.get('sourceModels', []))}
        lineage = dict(config=config, sources=snapshots, sourceSimulations=simulations, sourceModels=list(source_models.values()),
            clock=dict(axisId=policy['axisId'], offset=float(start)),
            grid=dict(start=float(start), requestedEnd=float(end), end=float(start + times[-1]), intervalSeconds=interval, samples=count),
            quality=summaries, provenanceCodes=PROVENANCE)
        metadata = dict(rowCount=count, columns=columns, sourceColumns=['time'] + names, ignoredColumns=[],
            missingCount=int(np.sum(~np.isfinite(values))), quality=quality, time=time, transformation=lineage,
            notes=['Generated by a saved transformation. Source datasets are unchanged.',
                   'Interpolation, holds and fills retain provenance. Analysis defaults to original observations; processed values require an explicit policy.'])
        if count > 1:
            boundary = min(count - 2, max(99, int(count * .2) - 1))
            metadata['suggestedRanges'] = dict(baselineRange=[0., float(times[boundary])], analysisRange=[float(times[boundary + 1]), float(times[-1])])
        return metadata, times, values, np.column_stack(provenance), np.column_stack(masks)

    def preview(self, workspace_id, config):
        metadata, times, values, codes, masks = self.compute(workspace_id, config)
        names = [c['name'] for c in metadata['columns']]
        sample = [dict(time=float(times[i]), values={key: float(values[i, j]) if np.isfinite(values[i, j]) else None for j, key in enumerate(names)},
                       provenance={key: PROVENANCE[int(codes[i, j])] for j, key in enumerate(names)},
                       observed={key: bool(masks[i, j]) for j, key in enumerate(names)}) for i in range(min(8, len(times)))]
        return dict(metadata=metadata, series=series_preview(times, values, names), samples=sample)

    def execute(self, identity, body):
        definition = self.get(identity)
        metadata, times, values, codes, masks = self.compute(definition['workspace_id'], definition['config'])
        from .workspace import now
        metadata['transformation'].update(definitionId=identity, definitionName=definition['name'],
            revision=definition['revision'], executionId=uuid4().hex, createdAt=now())
        name = body.get('name') or f"{definition['name']} · v{definition['revision']}"
        # CSV is a portable output artifact; the full precision NPZ is the analysis source.
        import csv
        from io import StringIO
        text = StringIO()
        writer = csv.writer(text)
        writer.writerow(metadata['sourceColumns'])
        writer.writerows([float(t)] + [float(v) if np.isfinite(v) else '' for v in row] for t, row in zip(times, values))
        return self.store.save_dataset(definition['workspace_id'], name, metadata, times, values, text.getvalue(),
                                       extra_arrays=dict(provenance=codes, observed=masks))
