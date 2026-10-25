"""Run the declared expansion through persisted Workspace Experiments.

The same command can export/resume a saved study. No external files are fetched
implicitly. Use examples.tep.prepare or the opt-in external workflow first.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time

from l5.tep_study import identity, protocol_for
from l5.workspace import WorkspaceStore


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def export(store, study, output):
    output.mkdir(parents=True, exist_ok=True)
    sources = {s['source']['sourceFile']: s['source'] for s in store.tep.sources()['sources'] if s['id'] in ('fault-free-training', 'fault-free-testing', 'faulty-testing')}
    tasks = []
    for task in study['tasks']:
        result = store.result(task['result_id']) if task['result_id'] else None
        tasks.append(dict(id=task['id'], configuration=task['benchmark']['configuration'], batch=task['benchmark']['batch'],
            experimentId=task['experimentId'], runId=task['run_id'], datasetId=task['datasetId'], analysisId=task['result_id'],
            externalRun=task['external']['id'], sourceSequence=task['external']['sequenceId'],
            faultNumber=task['external']['faultNumber'], simulationRun=task['external']['simulationRun'], algorithm=task['algorithm'],
            status=task['status'], error=task['error'], threshold=result['threshold'] if result else None, metrics=task['metrics'],
            scoreSha256=hashlib.sha256(json.dumps(result['scores'], separators=(',', ':')).encode()).hexdigest() if result else None))
    snapshots = {}
    for batch in study['batches']:
        if batch['runId']:
            saved = store.experiments.run(batch['runId'])['snapshot']
            snapshots[batch['runId']] = dict(config=saved['config'], engine=saved['engine'],
                datasetHashes={key: value['sha256'] for key, value in saved['datasets'].items()},
                sourceCsvHashes={key: value['sourceCsvSha256'] for key, value in saved['datasets'].items()})
            snapshots[batch['runId']]['datasetSources'] = {key:dict(id=value['metadata']['external']['id'],
                sequenceId=value['metadata']['external']['sequenceId']) for key,value in saved['datasets'].items()}
    report = {**{k: v for k, v in study.items() if k != 'tasks'}, 'sourceFiles': sources, 'tasks': tasks, 'snapshots': snapshots}
    write_json(output/'results.json', report)
    write_json(output/'summary.json', {k: v for k, v in report.items() if k not in ('tasks', 'snapshots')})
    fields = ['configuration', 'batch', 'externalRun', 'faultNumber', 'simulationRun', 'algorithm', 'status', 'error', 'threshold',
              'fitId', 'modelKey', 'eventCount', 'detected30m', 'detected1h', 'detected4h', 'detectedEventually', 'unobservedEvents',
              'missedEvents', 'firstDelaySeconds', 'TP', 'FP', 'TN', 'FN', 'recall', 'normalSamples', 'normalAlarmSamples',
              'normalAlarmEvents', 'normalAlarmDurationSeconds', 'preInjectionAlarmSamples', 'preInjectionAlarmEvents',
              'preInjectionAlarmDurationSeconds', 'postInjectionAlarmFraction', 'alarmSegments', 'coverage', 'abstainedSamples',
              'experimentId', 'runId', 'datasetId', 'analysisId', 'scoreSha256']
    with (output/'per-run.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for task in tasks:
            row = {k: task[k] for k in fields if k in task}
            metrics = task['metrics']
            if metrics:
                labelled, detection, behavior = metrics['labelled'], metrics['detection'], metrics['behavior']
                windows, normal = detection['windows'], detection['normal']
                row.update(fitId=metrics['training']['fitId'], modelKey=metrics['training']['modelKey'],
                    eventCount=windows['eventual']['totalEvents'], detected30m=windows['1800']['detectedEvents'],
                    detected1h=windows['3600']['detectedEvents'], detected4h=windows['14400']['detectedEvents'],
                    detectedEventually=windows['eventual']['detectedEvents'], unobservedEvents=windows['eventual']['unobservedEvents'],
                    missedEvents=windows['eventual']['totalEvents']-windows['eventual']['detectedEvents'],
                    firstDelaySeconds=labelled['event']['firstDetectionDelay'], **{k: labelled['sample'][k] for k in ('TP', 'FP', 'TN', 'FN', 'recall')},
                    normalSamples=normal['observedSamples'], normalAlarmSamples=normal['alarmSamples'],
                    normalAlarmEvents=normal['alarmEvents'], normalAlarmDurationSeconds=normal['alarmDuration'],
                    preInjectionAlarmSamples=(detection['preInjection'] or {}).get('alarmSamples'),
                    preInjectionAlarmEvents=(detection['preInjection'] or {}).get('alarmEvents'),
                    preInjectionAlarmDurationSeconds=(detection['preInjection'] or {}).get('alarmDuration'),
                    postInjectionAlarmFraction=(detection['postInjection'] or {}).get('alarmFraction'),
                    alarmSegments=behavior['alarmIntervalCount'], coverage=behavior['coverageFraction'], abstainedSamples=behavior['abstainedSamples'])
            writer.writerow(row)
    return report


def run_study(store, workspace_id, protocol_id, study_id=None, output=None):
    study = store.tep_studies.get(workspace_id, study_id) if study_id else store.tep_studies.create(workspace_id, protocol_id)
    if study['protocol']['id'] != protocol_id:
        raise ValueError('Resume study uses a different declared protocol.')
    if output:
        write_json(output/'study.json', dict(workspaceId=workspace_id, studyId=study['id'], protocolId=protocol_id))
    for batch in study['batches']:
        if batch['status'] == 'completed':
            continue
        if batch['runId']:
            # Failures are retained. A rerun requires an explicit Experiment retry,
            # rather than this CLI silently replacing failed published evidence.
            print(f'Retained {batch["status"]}: {batch["experimentId"]}', flush=True)
            continue
        saved = store.experiments.execute(batch['experimentId'], {})
        deadline = time.monotonic()+1800
        while saved['status'] in ('queued', 'running'):
            if time.monotonic() > deadline:
                raise TimeoutError(f'Batch is still active: {saved["id"]}')
            time.sleep(.2)
            saved = store.experiments.run(saved['id'])
        print(f'{batch["name"]}: {saved["status"]}; {saved["completed"]}/{saved["task_count"]} tasks; {saved["duration_ms"]} ms', flush=True)
    study = store.tep_studies.get(workspace_id, study['id'])
    return export(store, study, output) if output else study


def main(default_protocol='rieth-expanded-nine-v1'):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--cache-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--workspace-id')
    parser.add_argument('--study-id', help='Resume/export an existing saved study without replacing recorded failures.')
    args = parser.parse_args()
    os.environ['L5_TEP_CACHE'] = str(args.cache_dir.resolve())
    database = args.data_dir/'workspace.sqlite3'
    if database.is_file():
        with sqlite3.connect(database) as db:
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='experiment_runs'").fetchone()
            if exists and db.execute("SELECT 1 FROM experiment_runs WHERE status IN ('queued','running') LIMIT 1").fetchone():
                raise ValueError('Offline study CLI requires an idle data directory. Stop the service or use another directory.')
    store = WorkspaceStore(args.data_dir)
    workspace_id = args.workspace_id or store.create_workspace('TEP · expanded benchmark and robustness study')['id']
    if args.study_id and not args.workspace_id:
        raise ValueError('--study-id requires its saved --workspace-id.')
    report = run_study(store, workspace_id, default_protocol, args.study_id, args.output_dir)
    print(json.dumps(dict(studyId=report['id'], workspaceId=workspace_id, tasks=len(report['tasks']), status=report['statusCounts'])), flush=True)


if __name__ == '__main__':
    main()
