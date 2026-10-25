"""Reproduce the fixed real-data Workspace experiment and export saved evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time

from l5.experiment_reports import render_experiment_report
from l5.reports import render_report
from l5.tep_import import PROTOCOL
from l5.contracts import TEP_CLASSIC_SCHEMA
from l5.workspace import WorkspaceStore


def require_fixed_protocol(run):
    """Never label an arbitrary saved experiment as the published case study."""
    snapshot = run['snapshot']
    config = snapshot['config']
    if not config.get('training') or not snapshot.get('datasets'):
        raise ValueError('Export requires the saved independent TEP case-study protocol.')
    if config['signals'] != list(TEP_CLASSIC_SCHEMA.keys) or config.get('requiredSignals', []):
        raise ValueError('Saved feature order or observation coverage differs from the published protocol.')
    for key in ('alpha', 'minCoverage', 'persistence', 'observationPolicy', 'algorithms'):
        if config[key] != PROTOCOL[key]:
            raise ValueError(f'The saved {key} differs from the published fixed protocol.')
    def identity(item):
        return f'{item["sourceId"]}-f{item["faultNumber"]:02d}-r{item["simulationRun"]:03d}'
    for key in ('fit', 'calibration'):
        ref = config['training'][key]
        external = snapshot['datasets'][ref['datasetId']]['metadata'].get('external', {})
        if external.get('id') != identity(PROTOCOL[key]) or ref['range'] != PROTOCOL[key]['range']:
            raise ValueError('Saved normal training sources differ from the published protocol.')
    tests = config['testDatasets']
    if len(tests) != len(PROTOCOL['tests']):
        raise ValueError('Saved test selection differs from the published protocol.')
    for plan, expected in zip(tests, PROTOCOL['tests']):
        external = snapshot['datasets'][plan['datasetId']]['metadata'].get('external', {})
        labels = snapshot['testLabels'][plan['datasetId']]
        onset = external.get('faultOnsetSeconds')
        truth = [dict(kind='normal', start=0, end=172620 if onset is None else 28620)]
        if onset is not None:
            truth.append(dict(kind='anomaly', start=28800, end=172620, onset=28800))
        if (external.get('id') != identity(expected) or plan['analysisRange'] != PROTOCOL['analysisRange']
                or not labels or labels['intervals'] != truth):
            raise ValueError('Saved test sources, ranges or truth differ from the published protocol.')


def investigate(store, experiment_id, run_id):
    run = store.experiments.run(run_id)
    dataset = next(d for d in run['snapshot']['datasets'].values()
                   if d['metadata'].get('external', {}).get('id') == 'faulty-testing-f01-r001')
    tasks = [t for t in run['tasks'] if t['config']['datasetId'] == dataset['id'] and t['status'] == 'succeeded']
    if not tasks:
        return None
    incident = store.experiments.link_incident(run_id, dict(taskIds=[t['id'] for t in tasks], title='TEP fault 1 · simulationRun 1 · independent evaluation'))
    source = incident['links'][0]['id']
    store.incidents.save_entry(incident['id'], dict(kind='note', title='Published truth and independent protocol', source_link_id=source,
        observed_at=28800, content='Dataset-provided label: faultNumber=1, first faulty sample=161, normalized onset=28800 s. '
        'Normal fit: FaultFree Training run 1; independent calibration: FaultFree Training run 2. '
        'These labels describe the published simulation protocol; they are not a detector diagnosis.'))
    timing = []
    for task in tasks:
        labelled = task['metrics']['labelled']
        timing.append(f'{task["algorithm"]}: first post-onset delay {labelled["event"]["firstDetectionDelay"]} s; '
                      f'recall {labelled["sample"]["recall"]:.6f}; false alarm rate {labelled["sample"]["falseAlarmRate"]:.6f}.')
    store.incidents.save_entry(incident['id'], dict(kind='evidence', title='Nine-method detection timing', source_link_id=source,
        observed_at=28800, content='\n'.join(timing)))
    reference = next((t for t in tasks if t['algorithm'] == 'pca-q'), tasks[0])
    result = store.result(reference['result_id'])
    times, values = store.load_data(dataset)
    names = [c['name'] for c in dataset['metadata']['columns']]
    before, after = (times < 28800), ((times >= 28800) & (times < 32400))
    evidence = []
    for signal in result['relatedSignals'][:3]:
        column = names.index(signal)
        evidence.append(f'{signal}: pre-onset mean {values[before, column].mean():.6g}; first post-onset hour mean {values[after, column].mean():.6g}. '
                        'Original source numerical units; contribution magnitude is statistical, not a causal attribution.')
    store.incidents.save_entry(incident['id'], dict(kind='evidence', title='Original measurements around published injection', source_link_id=source,
        observed_at=28800, content='\n'.join(evidence)))
    store.incidents.save_entry(incident['id'], dict(kind='hypothesis', title='Candidate explanation: changed process operating condition',
        content='Sustained departures in multiple process measurements are consistent with an operating-condition change. '
                'The dataset supplies faultNumber=1; this generic investigation does not infer a physical root cause or apply TripLens rules.'))
    store.incidents.update(incident['id'], dict(status='resolved',
        description='Predeclared external Rieth fault 1, simulationRun 1, with nine independent detector results and original measurement evidence.',
        conclusion='The saved independent test trajectory is detected by all nine methods under the fixed normal-only protocol. '
                   'Detection times and variable contributions differ by statistic. This supports an observed multivariate deviation; '
                   'fault identity comes from the dataset label and physical cause is not independently established.'))
    return store.incidents.get(incident['id'])


def export(store, experiment_id, output, *, incident_id=None):
    output.mkdir(parents=True, exist_ok=True)
    comparison = store.experiments.comparison(experiment_id, dict(taskIds=[]))
    experiment = comparison['experiment']
    if not experiment['runs']:
        raise ValueError('The selected experiment has no saved executions.')
    run = store.experiments.run(experiment['runs'][0]['id'])
    if run['status'] in ('queued', 'running'):
        raise ValueError('Wait for the fixed experiment to finish before exporting.')
    require_fixed_protocol(run)
    cells = [c for c in comparison['benchmark']['cells'] if c['runId'] == run['id']]
    source_files = {d['metadata']['external']['sourceFile']: {k: d['metadata']['external'][k] for k in ('sourceDoi','sourceFile','sourceObject','persistentId','sourceBytes','sha256','md5')}
                    for d in run['snapshot']['datasets'].values()}
    tasks = []
    for task in run['tasks']:
        dataset = run['snapshot']['datasets'][task['config']['datasetId']]
        result = store.result(task['result_id']) if task['result_id'] else None
        tasks.append(dict(id=task['id'], algorithm=task['algorithm'], status=task['status'], error=task['error'], analysisId=task['result_id'],
            externalRun=dataset['metadata']['external']['id'], sourceSequence=dataset['metadata']['external']['sequenceId'],
            threshold=result['threshold'] if result else None, metrics=task['metrics'],
            scoreSha256=hashlib.sha256(json.dumps(result['scores'], separators=(',', ':')).encode()).hexdigest() if result else None))
    report = dict(protocol=PROTOCOL, workspaceId=experiment['workspace_id'], experimentId=experiment_id, runId=run['id'], status=run['status'],
                  sourceFiles=source_files, runSnapshot=dict(config=run['snapshot']['config'], engine=run['snapshot']['engine'],
                  datasetHashes={identity:d['sha256'] for identity,d in run['snapshot']['datasets'].items()}), cells=cells, tasks=tasks,
                  incidentId=incident_id)
    (output/'results.json').write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False)+'\n', encoding='utf-8')
    lines = ['# Rieth TEP · independent nine-algorithm evaluation', '',
        'Fixed normal fit run 1 and calibration run 2. Eight independent test runs; 52 process inputs; 180 s cadence. Faults 1, 3, 5 were declared before scoring.', '',
        '| Algorithm | Independent normal FP / 1920 | Fault 1 recall / median delay (s) | Fault 3 recall / events hit | Fault 5 recall / median delay (s) |',
        '|---|---:|---:|---:|---:|']
    def val(v):
        return 'undefined' if v is None else f'{v:.6g}'
    for algorithm in [a['algorithm'] for a in PROTOCOL['algorithms']]:
        by_fault = {c['faultNumber']:c for c in cells if c['algorithm'] == algorithm}
        normal, f1, f3, f5 = (by_fault.get(f) for f in (0,1,3,5))
        if not all((normal,f1,f3,f5)):
            lines.append(f'| {algorithm} | missing | missing | missing | missing |')
            continue
        lines.append(f'| {algorithm} | {normal["sample"]["FP"]} | {val(f1["sample"]["recall"])} / {val(f1["delay"]["median"])} | '
                     f'{val(f3["sample"]["recall"])} / {f3["event"]["detectedEvents"]}/{f3["event"]["eligibleEvents"]} | '
                     f'{val(f5["sample"]["recall"])} / {val(f5["delay"]["median"])} |')
    lines += ['', 'Each fault cell contains two runs (1600 post-onset samples); normal testing contains two complete 960-sample runs. '
              'Recall pools TP/FN; delay summarizes detected events only. Missed events have undefined delay. '
              'Full confusion counts, precision/F1/FAR, event counts, per-run metrics, coverage, abstention, durations, errors, hashes and fixed configuration are in results.json.', '',
              *['- '+limitation for limitation in PROTOCOL['limitations']], '']
    (output/'scoreboard.md').write_text('\n'.join(lines), encoding='utf-8')
    (output/'experiment.html').write_text(render_experiment_report(store, experiment_id, run['id']), encoding='utf-8')
    if incident_id:
        (output/'incident.html').write_text(render_report(store, incident_id), encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--cache-dir', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--existing-experiment', help='Export an already completed fixed experiment instead of running another.')
    parser.add_argument('--incident-id', help='Include an existing saved investigation when exporting.')
    parser.add_argument('--investigate', action='store_true', help='Save the predeclared fault 1/run 1 evidence review and report.')
    args = parser.parse_args()
    if args.cache_dir:
        os.environ['L5_TEP_CACHE'] = str(args.cache_dir.resolve())
    database = args.data_dir / 'workspace.sqlite3'
    if database.is_file():
        with sqlite3.connect(database) as db:
            has_runs = db.execute("SELECT 1 FROM sqlite_master WHERE name='experiment_runs'").fetchone()
            if has_runs and db.execute("SELECT 1 FROM experiment_runs WHERE status IN ('queued','running') LIMIT 1").fetchone():
                raise ValueError('This data directory has active tasks. Finish them or choose a separate data directory before using the offline CLI.')
    store = WorkspaceStore(args.data_dir)
    if args.existing_experiment:
        experiment = store.experiments.get(args.existing_experiment)
    else:
        workspace = store.create_workspace('TEP · official independent mode 1 case study')
        experiment = store.tep.create_case(workspace['id'])
        run = store.experiments.execute(experiment['id'], {})
        print(f'Experiment {experiment["id"]}: {run["task_count"]} predeclared tasks', flush=True)
        deadline = time.monotonic()+3600
        while run['status'] in ('queued', 'running'):
            if time.monotonic() >= deadline:
                raise RuntimeError('Experiment exceeded the one-hour local execution bound.')
            time.sleep(.2)
            run = store.experiments.run(run['id'])
        experiment = store.experiments.get(experiment['id'])
    run_id = experiment['runs'][0]['id']
    incident = investigate(store, experiment['id'], run_id) if args.investigate else None
    report = export(store, experiment['id'], args.output_dir, incident_id=incident['id'] if incident else args.incident_id)
    print(f'{report["status"]}: {len(report["tasks"])} tasks; experiment {experiment["id"]}; output {args.output_dir}', flush=True)
    if any(t['status'] != 'succeeded' for t in report['tasks']):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
