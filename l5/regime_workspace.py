"""Workspace-owned, immutable regime models and chronological monitoring runs."""
from __future__ import annotations

import json
from math import isfinite, log1p
import re
from time import perf_counter
from uuid import uuid4
import zlib

import numpy as np

from .analysis import signal_contributions
from .experiment_evaluation import evaluate
from .experiments import encode
from .independent import check_range, file_hash, mapping_for, snapshot, window
from .workspace import now


MAX_MODES = 24
MAX_SIGNALS = 128
MAX_DATA_CELLS = 5_000_000
MAX_EVIDENCE_ROWS = 250_000
MODE_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z')
ALGORITHM_LABEL = 'Regime-aware monitoring'


def pack(value):
    return zlib.compress(encode(value).encode('utf-8'), level=3)


def unpack(value):
    return json.loads(zlib.decompress(value))


def identity(value, description):
    if not isinstance(value, str) or not value:
        raise ValueError(f'Select a {description}.')
    return value


def partition_refs(value):
    refs = value if isinstance(value, list) else [value]
    if not 1 <= len(refs) <= 16 or any(not isinstance(ref, dict) for ref in refs):
        raise ValueError('Provide 1–16 dataset ranges for each fit and calibration partition.')
    return refs


def same_source(left, right):
    return bool(set(left['lineage']['identities']).intersection(right['lineage']['identities']))


class PartitionReader:
    def __init__(self, store, workspace_id, signals, reference=None):
        self.store, self.workspace_id, self.signals = store, workspace_id, signals
        self.reference = reference
        self.sources, self.labels, self.lineages = {}, {}, {}
        self.loaded = None
        self.cells = 0

    def lineage(self, dataset):
        dataset_id = dataset['id']
        if dataset_id in self.lineages:
            return self.lineages[dataset_id]
        metadata = dataset['metadata']
        external = metadata.get('external')
        simulation = metadata.get('model', {}).get('simulationId')
        identities = {'dataset:' + dataset_id}
        restricted = bool(external and (external.get('faultNumber') != 0 or external.get('split') != 'training'))
        if external and external.get('sequenceId'):
            identities.add('sequence:' + external['sequenceId'])
        if simulation:
            identities.add('simulation:' + simulation)
        if not metadata.get('transformation'):
            digest = dataset.get('sourceCsvSha256') or file_hash(
                self.store.root / dataset['workspace_id'] / 'datasets' / dataset_id / 'source.csv')
            identities.add('csv:' + digest)
        for source in metadata.get('transformation', {}).get('sources', []):
            ancestor = self.lineage(self.store.base_dataset(source['datasetId']))
            identities.update(ancestor['identities'])
            restricted |= ancestor['restrictedNormalSource']
        result = dict(identities=sorted(identities), restrictedNormalSource=restricted)
        self.lineages[dataset_id] = result
        return result

    def read(self, raw, *, normal=False, modes=1):
        if not isinstance(raw, dict):
            raise ValueError('Specify a dataset and its time range.')
        dataset_id = identity(raw.get('datasetId'), 'dataset')
        if dataset_id not in self.sources:
            dataset = self.store.dataset(dataset_id)
            if dataset['workspace_id'] != self.workspace_id:
                raise ValueError('Regime sources must belong to the same workspace.')
            frozen = snapshot(self.store, dataset)
            self.sources[dataset_id] = {**frozen, 'lineage': self.lineage(frozen)}
        source = self.sources[dataset_id]
        if normal and source['lineage']['restrictedNormalSource']:
            raise ValueError('External normal fit and calibration require fault-free training runs.')
        axis = source['metadata']['time']
        interval = raw.get('range')
        check_range(interval, axis['start'], axis['end'])
        mapping = mapping_for(self.reference or source, source, self.signals, raw.get('signalMapping'))
        self.reference = self.reference or source
        labels = None
        label_id = raw.get('labelSetId')
        if label_id is not None:
            identity(label_id, 'label version')
            if label_id not in self.labels:
                self.labels[label_id] = self.store.experiments.labels(label_id)
            labels = self.labels[label_id]
            if labels['dataset_id'] != dataset_id:
                raise ValueError('The label version must belong to the selected dataset.')
            if normal and not any(i['kind'] == 'normal' and i['start'] <= interval[0] <= interval[1] <= i['end']
                                  for i in labels['intervals']):
                raise ValueError('A labelled training range must lie inside one explicitly normal interval.')
        if self.loaded is None or self.loaded[0] != dataset_id:
            self.loaded = None
            times, values = self.store.load_data(source)
            self.loaded = dataset_id, times, values, self.store.observation_mask(source)
        _, times, values, observed = self.loaded
        mask = window(times, interval)
        count = int(mask.sum())
        self.cells += count * len(mapping)
        if self.cells > MAX_DATA_CELLS or count * modes > MAX_EVIDENCE_ROWS:
            raise ValueError('Select shorter ranges or fewer signals to stay within the regime workspace data budget.')
        names = [column['name'] for column in source['metadata']['columns']]
        columns = [names.index(name) for name in mapping.values()]
        rows = np.flatnonzero(mask)
        data = values[np.ix_(rows, columns)].copy()
        data[~observed[np.ix_(rows, columns)]] = np.nan
        ref = dict(datasetId=dataset_id, range=[float(value) for value in interval], signalMapping=mapping)
        if labels:
            ref['labelSetId'] = labels['id']
        return ref, source, labels, times[rows], data


def check_training_pair(left, right):
    first, first_source, first_mode, first_role = left
    second, second_source, second_mode, second_role = right
    if not same_source(first_source, second_source):
        return
    if first_source['id'] != second_source['id']:
        raise ValueError('Use one dataset identity for partitions from the same source or re-imported copy.')
    a, b = first['range'], second['range']
    if a[0] <= b[1] and b[0] <= a[1]:
        raise ValueError('Fit and calibration ranges from a dataset must be disjoint across all modes.')
    if first_mode == second_mode and first_role != second_role:
        fit, calibration = (a, b) if first_role == 'fit' else (b, a)
        if fit[1] >= calibration[0]:
            raise ValueError('Fit must precede calibration within a mode on the same dataset.')


def detector_options(raw):
    if not isinstance(raw, dict) or set(raw) - {'algorithm', 'alpha', 'variance'}:
        raise ValueError('Detector settings accept algorithm, alpha and variance.')
    return raw


def normalized_score(score, threshold):
    # Monotone log compression around zero for statistics with different units.
    return 0.0 if score is None else log1p(score) - log1p(threshold)


def analysis_projection(record, model, fitted, data):
    decisions, times = record['decisions'], record['times']
    # Scored fallback observations enter the detector metrics irrespective of
    # outcome. Their recognition decision remains separately unconfirmed.
    states = ['alarm' if d['alarm'] else 'abstain' if d['score'] is None else 'normal'
              for d in decisions]
    scores = [normalized_score(d['score'], d['threshold']) for d in decisions]
    mapping = record['evaluation']['signalMapping']

    def mapped_contributions(items):
        return [{**item, 'signal': mapping[item['signal']]} for item in items]

    intervals = [{**item, 'rawPeakScore': item['peakScore'],
                  'peakScore': normalized_score(item['peakScore'], item['threshold']),
                  'signals': [mapping[signal] for signal in item['signals']],
                  'contributions': mapped_contributions(item['contributions'])} for item in record['intervals']]
    peak = max(range(len(times)), key=lambda i: (states[i] != 'abstain', scores[i]))
    peak_detector = fitted.detectors[decisions[peak]['scoringMode']] if states[peak] != 'abstain' else None
    contributions = mapped_contributions(signal_contributions(peak_detector.monitor, data[peak], fitted.signals)) if peak_detector else []
    model_data = model['model']
    fit = sum(mode['fitSamples'] for mode in model_data['modes'].values())
    calibration = sum(mode['calibrationSamples'] for mode in model_data['modes'].values())
    config = dict(algorithm='regime-aware', datasetId=record['datasetId'], analysisRange=record['evaluation']['range'],
                  signals=[mapping[signal] for signal in model_data['signals']], persistence=model_data['config']['persistence'],
                  alpha=model_data['globalDetector']['alpha'], observationPolicy='measured',
                  minCoverage=1, regimeRunId=record['id'], gapThreshold=record['gapThreshold'])
    abstained = states.count('abstain')
    summary = dict(analysisSamples=len(times), flaggedSamples=states.count('alarm'), abstainedSamples=abstained,
                   coverageFraction=(len(times) - abstained) / len(times), peakScore=scores[peak],
                   firstDetection=times[states.index('alarm')] if 'alarm' in states else None,
                   baselineSamples=fit + calibration, fitSamples=fit, calibrationSamples=calibration,
                   imputedValues=dict(baseline=0, analysis=0))
    return dict(id=record['id'], name=record['name'], datasetId=record['datasetId'], workspaceId=record['workspaceId'],
                regimeRunId=record['id'], config=config, algorithmLabel=ALGORITHM_LABEL, times=times, scores=scores,
                states=states, threshold=0, observedFraction=np.isfinite(data).mean(axis=1).tolist(), intervals=intervals,
                relatedSignals=[item['signal'] for item in contributions[:10]],
                signalContributions=contributions, peakTime=times[peak],
                contributionMetric='regime-detector-specific', summary=summary,
                model=dict(version=model_data['version'], modelId=model['id'], score='log1p(score) - log1p(threshold)'),
                createdAt=record['createdAt'], completedAt=record['createdAt'], durationMs=record['durationMs'])


class RegimeService:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS regime_models (
                    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    name TEXT NOT NULL, config TEXT NOT NULL, created_at TEXT NOT NULL, payload BLOB NOT NULL);
                CREATE INDEX IF NOT EXISTS regime_models_workspace ON regime_models(workspace_id,created_at);
                CREATE TABLE IF NOT EXISTS regime_runs (
                    id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
                    model_id TEXT NOT NULL REFERENCES regime_models(id) ON DELETE CASCADE,
                    summary TEXT NOT NULL, payload BLOB NOT NULL, analysis BLOB NOT NULL);
            ''')

    def fit(self, workspace_id, body):
        from .regimes import fit_regimes

        self.store.workspace(workspace_id)
        name = self.store.name(body.get('name') or 'Operating regimes')
        signals, modes = body.get('signals'), body.get('modes')
        if (not isinstance(signals, list) or not 1 <= len(signals) <= MAX_SIGNALS
                or any(not isinstance(s, str) or not s for s in signals) or len(set(signals)) != len(signals)):
            raise ValueError(f'Choose 1–{MAX_SIGNALS} unique detector signals in their original units.')
        if not isinstance(modes, list) or not 2 <= len(modes) <= MAX_MODES:
            raise ValueError(f'Define 2–{MAX_MODES} distinct operating regimes.')
        engine_config = body.get('recognition', {})
        recognition_keys = ('recognitionSignals', 'recognitionAlpha', 'shrinkage', 'minMargin', 'dwell', 'persistence', 'referenceMode')
        if not isinstance(engine_config, dict) or set(engine_config) - set(recognition_keys):
            raise ValueError('Choose supported recognition and persistence settings.')
        default_detector = detector_options(body.get('detector', {}))
        reader = PartitionReader(self.store, workspace_id, signals)
        config_modes, partitions, fit_steps, training, detectors = [], [], [], {}, {}
        for raw in modes:
            mode = raw.get('id') if isinstance(raw, dict) else None
            if not isinstance(mode, str) or not MODE_ID.fullmatch(mode) or mode in training:
                raise ValueError('Regime IDs must be unique and use letters, digits, hyphens or underscores.')
            label = self.store.name(raw.get('label'))
            overrides = detector_options(raw.get('detector', {}))
            detectors[mode] = {**default_detector, **overrides}
            config_mode = dict(id=mode, label=label, detector=detectors[mode])
            arrays = []
            for role in ('fit', 'calibration'):
                config_mode[role], rows = [], []
                for ref in partition_refs(raw.get(role)):
                    clean, source, _, times, values = reader.read(ref, normal=True)
                    steps = np.diff(times)
                    if np.any(steps <= 0):
                        raise ValueError('Fit and calibration require unique timestamps in each partition.')
                    if role == 'fit' and len(steps):
                        fit_steps.append(steps)
                    partition = clean, source, mode, role
                    for previous in partitions:
                        check_training_pair(previous, partition)
                    partitions.append(partition)
                    config_mode[role].append(clean)
                    rows.append(values)
                arrays.append(np.concatenate(rows, axis=0))
            config_modes.append(config_mode)
            training[mode] = tuple(arrays)
        fitted = fit_regimes(training, signals, {**engine_config, **default_detector, 'detectors': detectors}).to_dict()
        gap = body.get('gapThreshold')
        if gap is not None:
            if isinstance(gap, bool) or not isinstance(gap, (int, float)) or not isfinite(gap) or gap <= 0:
                raise ValueError('The acquisition gap threshold must be positive, finite seconds.')
            gap = float(gap)
        elif fit_steps:
            gap = float(5 * np.median(np.concatenate(fit_steps)))
        settings = fitted['config']
        for mode in config_modes:
            mode['detector'] = settings['detectors'][mode['id']]
        config = dict(name=name, signals=signals, modes=config_modes, gapThreshold=gap,
                      detector={key: settings[key] for key in ('algorithm', 'alpha', 'variance')},
                      recognition={key: settings[key] for key in recognition_keys})
        model_id, stamp = uuid4().hex, now()
        payload = dict(model=fitted, sources=reader.sources, labelSets=reader.labels,
                       referenceDatasetId=reader.reference['id'])
        with self.store.connect() as db:
            db.execute('INSERT INTO regime_models VALUES (?,?,?,?,?,?)',
                       (model_id, workspace_id, name, encode(config), stamp, pack(payload)))
            db.execute('UPDATE workspaces SET updated_at=? WHERE id=?', (stamp, workspace_id))
        return self.model(workspace_id, model_id)

    @staticmethod
    def model_row(row):
        return dict(id=row['id'], workspaceId=row['workspace_id'], name=row['name'],
                    createdAt=row['created_at'], config=json.loads(row['config']))

    def models(self, workspace_id):
        self.store.workspace(workspace_id)
        with self.store.connect() as db:
            return [self.model_row(row) for row in db.execute('''SELECT id,workspace_id,name,config,created_at
                FROM regime_models WHERE workspace_id=? ORDER BY created_at DESC,id''', (workspace_id,))]

    def model(self, workspace_id, model_id):
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM regime_models WHERE workspace_id=? AND id=?', (workspace_id, model_id)).fetchone()
        if row is None:
            raise KeyError('Regime model not found in this workspace.')
        data = unpack(row['payload'])
        return {**self.model_row(row), **data, 'comparison': data['model']['comparisons']}

    def execute(self, workspace_id, body):
        from .regimes import FittedRegimes, evaluate_regimes

        started = perf_counter()
        model = self.model(workspace_id, identity(body.get('modelId'), 'regime model'))
        reference = model['sources'][model['referenceDatasetId']]
        reader = PartitionReader(self.store, workspace_id, model['config']['signals'], reference)
        evaluation, source, labels, times, data = reader.read(body.get('evaluation'), modes=len(model['config']['modes']))
        name = self.store.name(body.get('name') or f"{model['name']} · {source['name']}"[:160])
        for mode in model['config']['modes']:
            for ref in mode['fit'] + mode['calibration']:
                trained = model['sources'][ref['datasetId']]
                if same_source(source, trained):
                    if source['id'] != trained['id'] or source['sha256'] != trained['sha256']:
                        raise ValueError('Evaluation cannot reuse a re-imported or changed training source.')
                    if ref['range'][1] >= evaluation['range'][0]:
                        raise ValueError('Evaluation on a training dataset must start after all its fit and calibration ranges.')
        gap = model['config']['gapThreshold']
        fitted = FittedRegimes.from_dict(model['model'])
        result = evaluate_regimes(fitted, times, data, gap_threshold=gap)
        run_id, stamp = uuid4().hex, now()
        protocol = ('chronological-holdout' if any(same_source(source, s) for s in model['sources'].values())
                    else 'distinct-dataset')
        record = dict(**result, id=run_id, analysisId=run_id, name=name, modelId=model['id'], workspaceId=workspace_id,
                      datasetId=source['id'], evaluation=evaluation, source=source, labelSet=labels, protocol=protocol,
                      createdAt=stamp, durationMs=round((perf_counter() - started) * 1000, 2), gapThreshold=gap,
                      series=dict(time=result['times'], values={signal: [float(v) if np.isfinite(v) else None for v in col]
                                  for signal, col in zip(model['config']['signals'], data.T)}))
        analysis = analysis_projection(record, model, fitted, data)
        record['metrics'] = {'regime': evaluate(analysis, labels, gap)}
        for key in ('global', 'single'):
            states = ['alarm' if d[key + 'Alarm'] else 'abstain' if d[key + 'Score'] is None else 'normal'
                      for d in result['decisions']]
            record['metrics'][key] = evaluate(dict(times=result['times'], states=states, durationMs=record['durationMs'],
                                                   relatedSignals=[]), labels, gap)
        with self.store.connect() as db:
            db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?)',
                       (run_id, workspace_id, source['id'], name, encode(analysis['config']), encode(analysis['summary']), stamp))
            db.execute('INSERT INTO regime_runs VALUES (?,?,?,?,?)',
                       (run_id, model['id'], encode(record['summary']), pack(record), pack(analysis)))
            db.execute('UPDATE workspaces SET updated_at=? WHERE id=?', (stamp, workspace_id))
        return {**record, 'model': model}

    def runs(self, workspace_id):
        self.store.workspace(workspace_id)
        with self.store.connect() as db:
            return [dict(id=row['id'], name=row['name'], modelId=row['model_id'], datasetId=row['dataset_id'],
                         createdAt=row['created_at'], summary=json.loads(row['summary']))
                    for row in db.execute('''SELECT j.id,j.name,j.dataset_id,j.created_at,r.model_id,r.summary
                    FROM regime_runs r JOIN jobs j ON j.id=r.id WHERE j.workspace_id=? ORDER BY j.created_at DESC,j.id''',
                                          (workspace_id,))]

    def run(self, run_id, workspace_id=None):
        with self.store.connect() as db:
            row = db.execute('''SELECT r.payload,r.model_id,j.workspace_id FROM regime_runs r
                JOIN jobs j ON j.id=r.id WHERE r.id=?''', (run_id,)).fetchone()
        if row is None or (workspace_id is not None and row['workspace_id'] != workspace_id):
            raise KeyError('Regime monitoring run not found.')
        return {**unpack(row['payload']), 'model': self.model(row['workspace_id'], row['model_id'])}

    def analysis(self, run_id):
        with self.store.connect() as db:
            row = db.execute('SELECT analysis FROM regime_runs WHERE id=?', (run_id,)).fetchone()
        if row is None:
            raise KeyError('Regime monitoring run not found.')
        return unpack(row['analysis'])

    def link_incident(self, workspace_id, run_id, body):
        result = self.analysis(run_id)
        if result['workspaceId'] != workspace_id:
            raise KeyError('Regime monitoring run not found.')
        source = dict(kind='interval', analysisId=run_id, intervalIndex=body.get('intervalIndex'))
        service = self.store.incidents
        service.prepare_link(workspace_id, source)
        if body.get('incidentId'):
            incident = service.row(body['incidentId'])
            if incident['workspace_id'] != workspace_id:
                raise ValueError('Incident belongs to another workspace.')
            return service.add_link(incident['id'], source)
        interval = result['intervals'][source['intervalIndex']]
        return service.create(workspace_id, dict(title=body.get('title') or result['name'], source=source,
                                                 start_time=interval['start'], end_time=interval['end']))
