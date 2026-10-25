"""Verified, selected external TEP runs imported as ordinary Workspace datasets."""
from __future__ import annotations

import csv
import hashlib
from io import StringIO
import json
import os
from pathlib import Path
import urllib.request

import numpy as np

from benchmarks.rieth_independent import PINNED_SHA256, source_url
from benchmarks.rieth_stream import read_selected
from .contracts import TEP_CLASSIC_SCHEMA
from .datasets import prepare_csv
from .workspace import now

SOURCES = json.loads((Path(__file__).resolve().parents[1] / 'benchmarks/rieth_sources.json').read_text(encoding='utf-8'))
PROFILES = {
    'fault-free-training': ('TEP_FaultFree_Training.RData', 'fault_free_training', 'training', 500, False),
    'fault-free-testing': ('TEP_FaultFree_Testing.RData', 'fault_free_testing', 'testing', 960, False),
    'faulty-training': ('TEP_Faulty_Training.RData', 'faulty_training', 'training', 500, True),
    'faulty-testing': ('TEP_Faulty_Testing.RData', 'faulty_testing', 'testing', 960, True),
}
ADAPTER_VERSION = 'rieth-stream-rdx2-v1'
PROTOCOL = json.loads((Path(__file__).resolve().parents[1] / 'examples/tep/protocol.json').read_text(encoding='utf-8'))


def digest(path, algorithm='sha256'):
    h = hashlib.new(algorithm)
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def verify_source(path, profile):
    filename, _, split, _, faulty = PROFILES[profile]
    pin = SOURCES['files'][filename]
    if not Path(path).is_file() or Path(path).stat().st_size != pin['filesize']:
        raise ValueError(f'{filename}: missing or incomplete official source; expected {pin["filesize"]} bytes.')
    if digest(path, 'md5') != pin['checksum']['value']:
        raise ValueError(f'{filename}: original file checksum differs from Harvard Dataverse V1.')
    sha = digest(path)
    expected = pin.get('sha256') or (PINNED_SHA256['train' if split == 'training' else 'test'] if not faulty else None)
    if expected and sha != expected:
        raise ValueError(f'{filename}: source SHA-256 differs from the pinned reference.')
    return dict(sourceDoi=SOURCES['doi'], sourceVersion=SOURCES['version'], sourceUrl='https://doi.org/10.7910/DVN/6C3JR1',
                sourceFile=filename, sourceObject=PROFILES[profile][1], sourceBytes=pin['filesize'],
                persistentId=pin['persistentId'], md5=pin['checksum']['value'], sha256=sha)


def download_source(directory, profile):
    """Explicit CLI operation only. Runtime requests never download external data."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    filename = PROFILES[profile][0]
    pin = SOURCES['files'][filename]
    path = directory / filename
    if not path.exists():
        partial = path.with_suffix('.RData.partial')
        try:
            req = urllib.request.Request(source_url(pin['persistentId'].rsplit('/', 1)[1]), headers={'User-Agent': 'L5-TEP-research/1.0'})
            with urllib.request.urlopen(req, timeout=120) as response, partial.open('wb') as out:
                count = 0
                for chunk in iter(lambda: response.read(1024*1024), b''):
                    count += len(chunk)
                    if count > pin['filesize']:
                        raise ValueError('Official download exceeds the pinned file size.')
                    out.write(chunk)
            verify_source(partial, profile)
            partial.replace(path)
        finally:
            partial.unlink(missing_ok=True)
    verify_source(path, profile)
    return path


def prepare_runs(source_dir, cache_dir, profile, selections):
    """One bounded extraction, then immutable per-run files for the local UI."""
    if profile not in PROFILES:
        raise ValueError('Choose an official Rieth source profile.')
    selections = tuple(tuple(s) for s in selections)
    if (not 1 <= len(selections) <= 64 or len(set(selections)) != len(selections)
            or any(len(s) != 2 or any(type(v) is not int for v in s) or not 0 <= s[0] <= 20 or not 1 <= s[1] <= 500 for s in selections)):
        raise ValueError('Select 1–64 distinct integer fault (0–20) / run (1–500) pairs.')
    filename, object_name, split, samples, faulty = PROFILES[profile]
    if any((fault != 0) != faulty for fault, _ in selections):
        raise ValueError('Fault identity does not match the selected source file.')
    path = Path(source_dir) / filename
    provenance = verify_source(path, profile)
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    manifest_path = cache / f'{profile}.json'
    previous = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}
    if previous and previous['source']['sha256'] != provenance['sha256']:
        raise ValueError('Prepared cache belongs to a different original source version.')
    entries = {entry['id']: entry for entry in previous.get('runs', [])}
    # Reuse checksum-verified extractions. A changed/corrupt entry is read again
    # from the verified original; repeated study runs do not decompress 0.8 GB.
    pending = []
    for fault, run in selections:
        identity = f'{profile}-f{fault:02d}-r{run:03d}'
        target = cache / f'{identity}.npz'
        if identity not in entries or not target.is_file() or digest(target) != entries[identity]['extractedSha256']:
            pending.append((fault, run))
    runs = read_selected(path, pending, object_name=object_name, samples_per_run=samples) if pending else {}
    for (fault, run), values in runs.items():
        identity = f'{profile}-f{fault:02d}-r{run:03d}'
        target = cache / f'{identity}.npz'
        temporary = target.with_suffix('.partial')
        try:
            with temporary.open('wb') as out:
                np.savez_compressed(out, values=values, samples=np.arange(1, samples+1), columns=np.asarray(TEP_CLASSIC_SCHEMA.keys))
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        onset_sample = (21 if split == 'training' else 161) if faulty else None
        entries[identity] = dict(id=identity, faultNumber=fault, simulationRun=run, split=split, samples=samples,
            features=52, sampleIntervalSeconds=180, firstSample=1, lastSample=samples,
            faultOnsetSample=onset_sample, faultOnsetSeconds=(onset_sample-1)*180 if onset_sample else None,
            sequenceId=f'{provenance["persistentId"]}#fault={fault}&run={run}', extractedSha256=digest(target))
    manifest = dict(adapterVersion=ADAPTER_VERSION, source=provenance, schema=TEP_CLASSIC_SCHEMA.metadata(),
                    timeConvention='t=(sample-1)*180 seconds; first faulty observation is sample 21 (training) or 161 (testing).',
                    preparedAt=now(), runs=sorted(entries.values(), key=lambda r: (r['faultNumber'], r['simulationRun'])))
    temporary = manifest_path.with_suffix('.partial')
    temporary.write_text(json.dumps(manifest, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    temporary.replace(manifest_path)
    return manifest


class TEPImportService:
    def __init__(self, store):
        self.store = store
        self.cache = Path(os.environ.get('L5_TEP_CACHE', store.root / 'external' / 'tep')).resolve()

    def sources(self):
        result = []
        for profile in PROFILES:
            path = self.cache / f'{profile}.json'
            if path.is_file():
                manifest = json.loads(path.read_text(encoding='utf-8'))
                if manifest.get('adapterVersion') != ADAPTER_VERSION or manifest.get('schema') != TEP_CLASSIC_SCHEMA.metadata():
                    raise ValueError(f'{profile}: incompatible prepared TEP cache; run the preparation script again.')
                pin = SOURCES['files'][PROFILES[profile][0]]
                source = manifest.get('source', {})
                if (source.get('sourceFile') != PROFILES[profile][0] or source.get('persistentId') != pin['persistentId']
                        or source.get('md5') != pin['checksum']['value'] or source.get('sourceBytes') != pin['filesize']
                        or (pin.get('sha256') and source.get('sha256') != pin['sha256'])):
                    raise ValueError(f'{profile}: prepared provenance does not match the pinned official source.')
                result.append(dict(id=profile, **manifest))
        return dict(sources=result, preparationCommand='python -m examples.tep.prepare --help')

    def selected(self, profile, ids):
        if not isinstance(ids, list) or not 1 <= len(ids) <= 32 or len(set(ids)) != len(ids):
            raise ValueError('Select 1–32 distinct prepared runs.')
        source = next((s for s in self.sources()['sources'] if s['id'] == profile), None)
        if source is None:
            raise ValueError('This TEP source is not prepared in the configured local cache.')
        result = []
        for identity in ids:
            run = next((r for r in source['runs'] if r['id'] == identity), None)
            if run is None or not isinstance(identity, str) or '/' in identity or '\\' in identity or '..' in identity:
                raise ValueError('Choose run identities from the cached source.')
            _, _, split, samples_per_run, faulty = PROFILES[profile]
            fault, run_id = run['faultNumber'], run['simulationRun']
            onset_sample = (21 if split == 'training' else 161) if faulty else None
            if (isinstance(fault, bool) or not isinstance(fault, int) or not 0 <= fault <= 20 or (fault != 0) != faulty
                    or isinstance(run_id, bool) or not isinstance(run_id, int) or not 1 <= run_id <= 500
                    or identity != f'{profile}-f{fault:02d}-r{run_id:03d}' or run['split'] != split
                    or run['samples'] != samples_per_run or run['features'] != 52 or run['sampleIntervalSeconds'] != 180
                    or run['faultOnsetSample'] != onset_sample or run['faultOnsetSeconds'] != ((onset_sample-1)*180 if onset_sample else None)
                    or run['sequenceId'] != f'{source["source"]["persistentId"]}#fault={fault}&run={run_id}'):
                raise ValueError(f'{identity}: invalid fault/run identity, onset or sampling protocol in prepared cache.')
            path = self.cache / f'{identity}.npz'
            if not path.is_file() or digest(path) != run['extractedSha256']:
                raise ValueError(f'{identity}: prepared data missing or corrupt; prepare it again from the verified source.')
            with np.load(path, allow_pickle=False) as arrays:
                values, samples, columns = arrays['values'], arrays['samples'], arrays['columns'].tolist()
            if columns != list(TEP_CLASSIC_SCHEMA.keys) or values.shape != (run['samples'], 52) or not np.isfinite(values).all() or not np.array_equal(samples, np.arange(1, run['samples']+1)):
                raise ValueError(f'{identity}: invalid selected run schema, measurements or sample indices.')
            result.append((run, values))
        return source, result

    def preview(self, body):
        source, runs = self.selected(body.get('sourceId'), body.get('runIds'))
        return dict(source=source['source'], schema=source['schema'], timeConvention=source['timeConvention'],
                    runs=[dict(**r, missingValues=int((~np.isfinite(v)).sum())) for r, v in runs])

    def import_runs(self, workspace_id, body):
        self.store.workspace(workspace_id)
        source, runs = self.selected(body.get('sourceId'), body.get('runIds'))
        datasets = []
        for run, values in runs:
            out = StringIO(newline='')
            writer = csv.writer(out)
            writer.writerow(('t', *TEP_CLASSIC_SCHEMA.keys))
            writer.writerows(((i*180, *row) for i, row in enumerate(values)))
            source_csv = out.getvalue()
            metadata, times, matrix = prepare_csv(source_csv, dict(timeColumn='t', timeKind='numeric', timeUnit='seconds'))
            metadata.update(filename=source['source']['sourceFile'], external=dict(
                kind='tep-rieth', **source['source'], **run, schema=source['schema'],
                originalColumns=['faultNumber', 'simulationRun', 'sample', *TEP_CLASSIC_SCHEMA.keys],
                timeConvention=source['timeConvention'], adapterVersion=ADAPTER_VERSION,
                importedAt=now(), processing=['Official file size/MD5/SHA-256 verified.', 'Selected independent run; sorted and checked original sample indices.',
                                            'Metadata excluded from 52 detector inputs; no scaling or resampling.']))
            dataset = self.store.save_dataset(workspace_id, f'Rieth {run["split"]} · fault {run["faultNumber"]} · run {run["simulationRun"]}',
                metadata, times, matrix, source_csv, extra_arrays={'original_samples': np.arange(1, len(times)+1)})
            onset = run['faultOnsetSeconds']
            intervals = [dict(kind='normal', start=0, end=float(times[-1]) if onset is None else onset-180)]
            if onset is not None:
                intervals.append(dict(kind='anomaly', start=onset, end=float(times[-1]), onset=onset))
            self.store.experiments.save_labels(dataset['id'], dict(name=f'Rieth fault {run["faultNumber"]} · run {run["simulationRun"]}',
                timeBasis='dataset-seconds', timeSource=source['timeConvention']+' Source: '+source['source']['persistentId'], intervals=intervals),
                source='tep-rieth-published-protocol', provenance=metadata['external'])
            datasets.append(dataset)
        return dict(datasets=datasets)

    def create_case(self, workspace_id):
        """Import the published fixed selection and save the existing Experiment definition."""
        selected = [PROTOCOL['fit'], PROTOCOL['calibration'], *PROTOCOL['tests']]
        imported = {}
        available = self.sources()['sources']
        # Check all cache inputs before creating any datasets.
        for source_id in dict.fromkeys(s['sourceId'] for s in selected):
            ids = [f'{source_id}-f{s["faultNumber"]:02d}-r{s["simulationRun"]:03d}' for s in selected if s['sourceId'] == source_id]
            self.selected(source_id, ids)
        existing = self.store.datasets(workspace_id)
        for source_id in dict.fromkeys(s['sourceId'] for s in selected):
            manifest = next(s for s in available if s['id'] == source_id)
            missing = []
            for selection in (s for s in selected if s['sourceId'] == source_id):
                identity = f'{source_id}-f{selection["faultNumber"]:02d}-r{selection["simulationRun"]:03d}'
                entry = next(r for r in manifest['runs'] if r['id'] == identity)
                dataset = next((d for d in existing if d['metadata'].get('external', {}).get('sequenceId') == entry['sequenceId']
                    and d['metadata']['external'].get('extractedSha256') == entry['extractedSha256']), None)
                if dataset:
                    imported[identity] = dataset
                else:
                    missing.append(identity)
            if missing:
                for dataset in self.import_runs(workspace_id, dict(sourceId=source_id, runIds=missing))['datasets']:
                    imported[dataset['metadata']['external']['id']] = dataset
        def dataset_for(item):
            return imported[f'{item["sourceId"]}-f{item["faultNumber"]:02d}-r{item["simulationRun"]:03d}']
        tests = []
        for item in PROTOCOL['tests']:
            dataset = dataset_for(item)
            tests.append(dict(datasetId=dataset['id'], analysisRange=PROTOCOL['analysisRange'],
                              labelSetId=self.store.experiments.label_sets(dataset['id'])[0]['id']))
        training = {key: dict(datasetId=dataset_for(PROTOCOL[key])['id'], range=PROTOCOL[key]['range']) for key in ('fit', 'calibration')}
        config = {key: PROTOCOL[key] for key in ('alpha', 'minCoverage', 'persistence', 'observationPolicy', 'algorithms', 'analysisRange')}
        config.update(datasetId=tests[0]['datasetId'], signals=list(TEP_CLASSIC_SCHEMA.keys), baselineRange=PROTOCOL['fit']['range'],
                      training=training, testDatasets=tests, requiredSignals=[])
        return self.store.experiments.save(workspace_id, dict(name=PROTOCOL['name'],
            description=PROTOCOL['id']+' · '+PROTOCOL['declaration'], config=config,
            notes='\n'.join(PROTOCOL['limitations'])))
