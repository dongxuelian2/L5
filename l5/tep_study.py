"""Fixed TEP study orchestration over ordinary Dataset/Experiment records.

No detector implementation lives here. Each batch is a saved Experiment; study
identity and the protocol hash are part of every immutable run snapshot.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from uuid import uuid4

from .contracts import TEP_CLASSIC_SCHEMA
from .detection_metrics import WINDOWS
from .external_benchmark import distribution, summarize
from .experiment_evaluation import ratio

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_FILES = {'rieth-expanded-nine-v1': 'expanded_protocol.json', 'rieth-robustness-nine-v1': 'robustness_protocol.json'}


def protocol_for(identity):
    if identity not in PROTOCOL_FILES:
        raise ValueError('Choose a declared TEP study protocol.')
    return json.loads((ROOT/'examples/tep'/PROTOCOL_FILES[identity]).read_text(encoding='utf-8'))


def protocol_hash(protocol):
    return hashlib.sha256(json.dumps(protocol, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def identity(item):
    return f'{item["sourceId"]}-f{item["faultNumber"]:02d}-r{item["simulationRun"]:03d}'


def validate_benchmark(raw):
    keys = {'studyId', 'protocolId', 'protocolHash', 'configuration', 'batch', 'batches'}
    if not isinstance(raw, dict) or set(raw) != keys or not isinstance(raw.get('studyId'), str) or not re.fullmatch('[a-f0-9]{32}', raw['studyId']):
        raise ValueError('Invalid saved TEP study identity.')
    protocol = protocol_for(raw['protocolId'])
    if raw['protocolHash'] != protocol_hash(protocol) or raw['configuration'] not in protocol['configurations']:
        raise ValueError('TEP study protocol/configuration differs from the declared version.')
    count = (len(protocol['tests'])+27)//28
    if any(type(raw[k]) is not int for k in ('batch', 'batches')) or raw['batches'] != count or not 1 <= raw['batch'] <= count:
        raise ValueError('Invalid TEP batch number or denominator.')
    return deepcopy(raw)


def validate_study_config(store, config):
    """A protocol badge is valid only for the actual sources, truth and settings."""
    meta = config['benchmark']
    protocol = protocol_for(meta['protocolId'])
    for key in ('alpha','minCoverage','persistence','observationPolicy','algorithms','analysisRange'):
        if config[key] != protocol[key]:
            raise ValueError(f'Saved study {key} differs from its fixed protocol.')
    if config['signals'] != list(TEP_CLASSIC_SCHEMA.keys) or config['requiredSignals']:
        raise ValueError('Saved study feature order differs from the fixed protocol.')
    for role, expected in protocol['configurations'][meta['configuration']].items():
        ref = config['training'][role]
        source = store.dataset(ref['datasetId'])['metadata'].get('external', {})
        if source.get('id') != identity(expected) or ref['range'] != expected['range']:
            raise ValueError('Saved study normal training sources differ from the declared configuration.')
    start = (meta['batch']-1)*28
    expected_tests = protocol['tests'][start:start+28]
    if len(config['testDatasets']) != len(expected_tests):
        raise ValueError('Saved study batch is missing declared test trajectories.')
    for plan, expected in zip(config['testDatasets'], expected_tests):
        dataset = store.dataset(plan['datasetId'])
        source = dataset['metadata'].get('external', {})
        if source.get('id') != identity(expected) or plan['analysisRange'] != protocol['analysisRange'] or not plan.get('labelSetId'):
            raise ValueError('Saved study test identities, ranges or labels differ from the declared batch.')
        onset = 28800 if expected['faultNumber'] else None
        truth = [dict(kind='normal',start=0,end=28620 if onset is not None else 172620)]
        if onset is not None:
            truth.append(dict(kind='anomaly',start=28800,end=172620,onset=28800))
        if store.experiments.labels(plan['labelSetId'])['intervals'] != truth:
            raise ValueError('Saved study truth differs from the published injection protocol.')


def aggregate(tasks):
    """Pool disjoint batches only within a labelled study/configuration.

    Failed/not-run tasks remain in planned denominators as unresolved outcomes;
    they are never silently counted as measured misses or discarded.
    """
    copies = []
    for task in tasks:
        meta = task['benchmark']
        config = {k: v for k, v in task['config'].items() if k != 'benchmark'}
        copies.append({**task, 'run_id': meta['configuration'], 'config': config})
    cells = summarize(copies)['cells']
    for cell in cells:
        members = [t for t in tasks if t['id'] in cell['taskIds']]
        scored = [t for t in members if t['status'] == 'succeeded' and t['metrics']]
        positive = cell['faultNumber'] != 0
        unresolved = len(members)-len(scored)
        cell.update(configuration=cell['runId'], plannedRuns=len(members), unresolvedRuns=unresolved,
                    pending=sum(t['status'] in ('not-run', 'queued', 'running') for t in members))
        cell['windows'] = {}
        for key in WINDOWS:
            observed = [t['metrics']['detection']['windows'][key] for t in scored if t['metrics'].get('detection', {}).get('windows')]
            total = sum(v['totalEvents'] for v in observed) + (unresolved if positive else 0)
            hits = sum(v['detectedEvents'] for v in observed)
            cell['windows'][key] = dict(detectedEvents=hits, totalEvents=total, rate=ratio(hits, total),
                unresolvedEvents=unresolved if positive else 0, unobservedEvents=sum(v['unobservedEvents'] for v in observed),
                truncatedEvents=sum(v['truncatedEvents'] for v in observed))
        cell['burden'] = {}
        for phase in ('normal', 'preInjection', 'postInjection'):
            records = [t['metrics']['detection'][phase] for t in scored if t['metrics'].get('detection', {}).get(phase) is not None]
            counts = {k: sum(v[k] for v in records) for k in ('samples', 'observedSamples', 'alarmSamples', 'alarmEvents', 'alarmDuration')}
            cell['burden'][phase] = {**counts, 'alarmFraction': ratio(counts['alarmSamples'], counts['observedSamples'])}
        delays = [v['delay'] for t in scored for v in t['metrics'].get('detection', {}).get('events', [])]
        cell['delayDistribution'] = dict(within30m=sum(v is not None and v <= 1800 for v in delays),
            from30mTo1h=sum(v is not None and 1800 < v <= 3600 for v in delays),
            from1hTo4h=sum(v is not None and 3600 < v <= 14400 for v in delays),
            laterThan4h=sum(v is not None and v > 14400 for v in delays),
            missed=sum(v is None for v in delays), unresolved=unresolved if positive else 0)
    return cells


class TEPStudyService:
    def __init__(self, store):
        self.store = store

    def list(self, workspace_id):
        groups = {}
        for experiment in self.store.experiments.list(workspace_id):
            meta = experiment['config'].get('benchmark')
            if meta:
                record = groups.setdefault(meta['studyId'], dict(id=meta['studyId'], protocolId=meta['protocolId'],
                    protocolHash=meta['protocolHash'], experiments=[], configurations=[]))
                record['experiments'].append(experiment['id'])
                if meta['configuration'] not in record['configurations']:
                    record['configurations'].append(meta['configuration'])
        return list(groups.values())

    def create(self, workspace_id, protocol_id):
        protocol = protocol_for(protocol_id)
        selected = list({identity(s): s for group in protocol['configurations'].values() for s in group.values()}.values()) + protocol['tests']
        by_source = {}
        for item in selected:
            by_source.setdefault(item['sourceId'], set()).add(identity(item))
        # Validate every required cache entry before creating records.
        for source, ids in by_source.items():
            for start in range(0, len(ids), 32):
                self.store.tep.selected(source, sorted(ids)[start:start+32])
        existing = self.store.datasets(workspace_id)
        imported = {}
        sources = {s['id']: s for s in self.store.tep.sources()['sources']}
        for source, ids in by_source.items():
            entries = {r['id']: r for r in sources[source]['runs']}
            missing = []
            for key in sorted(ids):
                dataset = next((d for d in existing if d['metadata'].get('external', {}).get('sequenceId') == entries[key]['sequenceId']
                    and d['metadata']['external'].get('extractedSha256') == entries[key]['extractedSha256']), None)
                if dataset:
                    imported[key] = dataset
                else:
                    missing.append(key)
            for start in range(0, len(missing), 32):
                for dataset in self.store.tep.import_runs(workspace_id, dict(sourceId=source, runIds=missing[start:start+32]))['datasets']:
                    imported[dataset['metadata']['external']['id']] = dataset
        study_id = uuid4().hex
        for configuration, group in protocol['configurations'].items():
            training = {role: dict(datasetId=imported[identity(item)]['id'], range=item['range']) for role, item in group.items()}
            tests = []
            for item in protocol['tests']:
                dataset = imported[identity(item)]
                tests.append(dict(datasetId=dataset['id'], analysisRange=protocol['analysisRange'],
                                  labelSetId=self.store.experiments.label_sets(dataset['id'])[0]['id']))
            for start in range(0, len(tests), 28):
                batch = tests[start:start+28]
                meta = dict(studyId=study_id, protocolId=protocol_id, protocolHash=protocol_hash(protocol),
                            configuration=configuration, batch=start//28+1, batches=(len(tests)+27)//28)
                config = {key: protocol[key] for key in ('alpha', 'minCoverage', 'persistence', 'observationPolicy', 'algorithms', 'analysisRange')}
                config.update(datasetId=batch[0]['datasetId'], training=training, testDatasets=batch,
                              signals=list(TEP_CLASSIC_SCHEMA.keys), requiredSignals=[], baselineRange=group['fit']['range'], benchmark=meta)
                self.store.experiments.save(workspace_id, dict(name=f'{protocol["name"]} · {configuration} · batch {meta["batch"]}/{meta["batches"]}',
                    config=config, description=protocol['declaration'], notes='\n'.join(protocol['limitations'])))
        return self.get(workspace_id, study_id)

    def get(self, workspace_id, study_id):
        experiments = [e for e in self.store.experiments.list(workspace_id) if e['config'].get('benchmark', {}).get('studyId') == study_id]
        if not experiments:
            raise KeyError('Saved TEP study not found in this workspace.')
        experiments.sort(key=lambda e: (e['config']['benchmark']['configuration'], e['config']['benchmark']['batch']))
        protocol_id = experiments[0]['config']['benchmark']['protocolId']
        protocol = protocol_for(protocol_id)
        count = (len(protocol['tests'])+27)//28
        expected = {(c,b) for c in protocol['configurations'] for b in range(1,count+1)}
        identities = [(e['config']['benchmark']['configuration'],e['config']['benchmark']['batch']) for e in experiments]
        if set(identities) != expected or len(identities) != len(expected) or any(e['config']['benchmark']['protocolId'] != protocol_id for e in experiments):
            raise ValueError('Missing, duplicate or mixed-protocol study batches; cannot pool their denominators.')
        tasks, batches, attempts = [], [], []
        for definition in experiments:
            validate_study_config(self.store, definition['config'])
            experiment = self.store.experiments.get(definition['id'])
            meta = definition['config']['benchmark']
            if meta['protocolHash'] != protocol_hash(protocol_for(protocol_id)):
                raise ValueError('Saved study uses a different protocol version; do not pool it with current results.')
            # Latest full execution, with an explicit retry ancestry overlay.
            history = {r['id']: r for r in experiment['runs']}
            chain, cursor = [], experiment['runs'][0]['id'] if experiment['runs'] else None
            while cursor:
                run = self.store.experiments.run(cursor)
                chain.append(run)
                cursor = run['retry_of']
                if cursor and cursor not in history:
                    raise ValueError('Retry ancestry is incomplete.')
            chosen = {}
            for run in reversed(chain):
                if run['snapshot']['config'] != definition['config']:
                    raise ValueError('Study configuration changed after the selected execution; execute the saved definition before pooling.')
                for task in run['tasks']:
                    chosen[(task['algorithm'], task['config']['datasetId'])] = task
            for summary in experiment['runs']:
                attempts.append(dict(experimentId=experiment['id'], **summary))
            snapshots = {d['id']: d for r in chain for d in r['snapshot'].get('datasets', {}).values()}
            for ordinal, plan in enumerate(self.store.experiments.expand(definition['config'])):
                task = chosen.get((plan['algorithm'], plan['datasetId']))
                dataset = snapshots.get(plan['datasetId']) or self.store.dataset(plan['datasetId'])
                external = dataset['metadata']['external']
                record = task or dict(id=f'planned-{experiment["id"]}-{ordinal}', run_id='', algorithm=plan['algorithm'],
                    status='not-run', error=None, metrics=None, config=plan, result_id=None)
                tasks.append({**record, 'benchmark': meta, 'experimentId': experiment['id'], 'datasetId': dataset['id'],
                              'datasetName': dataset['name'], 'external': external})
            batches.append(dict(experimentId=experiment['id'], name=experiment['name'], benchmark=meta,
                                runId=chain[0]['id'] if chain else None, status=chain[0]['status'] if chain else 'not-run'))
        protocol = protocol_for(protocol_id)
        expected_batches = len(protocol['configurations'])*((len(protocol['tests'])+27)//28)
        if len(batches) != expected_batches or len(tasks) != len(protocol['configurations'])*len(protocol['tests'])*len(protocol['algorithms']):
            raise ValueError('Saved study is missing declared batches or tasks; its denominator cannot be pooled.')
        return dict(id=study_id, workspaceId=workspace_id, protocol=protocol, protocolHash=protocol_hash(protocol),
                    batches=batches, attempts=attempts, tasks=tasks, cells=aggregate(tasks),
                    statusCounts={s: sum(t['status'] == s for t in tasks) for s in ('succeeded', 'failed', 'interrupted', 'not-run', 'queued', 'running')})

    def fault3(self, workspace_id, study_id, simulation_run=1):
        from .tep_fault3 import compare_fault3
        return compare_fault3(self.store, self.get(workspace_id, study_id), simulation_run)
