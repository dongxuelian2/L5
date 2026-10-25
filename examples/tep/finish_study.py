"""Export saved study evidence, fault-3 controls and an ordinary Incident report."""
import argparse
import json
import os
from pathlib import Path
import shutil

import numpy as np

from .expanded_run import write_json
from .run import investigate
from l5.experiment_reports import render_experiment_report
from l5.reports import render_report
from l5.tep_study_reports import render_study_report, training_summary
from l5.workspace import WorkspaceStore


def finish(data_dir, cache_dir, output, publish=None):
    os.environ['L5_TEP_CACHE'] = str(cache_dir.resolve())
    store = WorkspaceStore(data_dir)
    verification = {}
    for kind in ('expanded','robustness'):
        ref = json.loads((output/kind/'study.json').read_text(encoding='utf-8'))
        study = store.tep_studies.get(ref['workspaceId'],ref['studyId'])
        summary = training_summary(study)
        write_json(output/kind/'training-summary.json',summary)
        compact = dict(studyId=study['id'],workspaceId=study['workspaceId'],protocolId=study['protocol']['id'],
            protocolHash=study['protocolHash'],statusCounts=study['statusCounts'],tasks=len(study['tasks']),batches=study['batches'],training=summary,
            cells=[{k:c[k] for k in ('configuration','faultNumber','algorithm','plannedRuns','succeeded','failed','unresolvedRuns','sample','event','windows','burden','delay','delayDistribution')} for c in study['cells']])
        controls = []
        for run in (1,2,3):
            control = store.tep_studies.fault3(ref['workspaceId'],ref['studyId'],run)
            write_json(output/kind/f'fault3-run{run}.json',control)
            controls.append({**{k:v for k,v in control.items() if k not in ('raw','configurations')},'configurations':[
                {**{k:v for k,v in pair.items() if k not in ('normal','fault')},**{series:dict(
                    threshold=pair[series]['threshold'],alarmSpans=pair[series]['metrics']['behavior']['alarmSpans'],
                    targetScore=pair[series]['scores'][931],nextScore=pair[series]['scores'][932],
                    metrics=pair[series]['metrics']['detection']) for series in ('normal','fault')}} for pair in control['configurations']]})
        (output/kind/'study.html').write_text(render_study_report(store,study),encoding='utf-8')
        write_json(output/kind/'compact-summary.json',compact)
        write_json(output/kind/'fault3-summary.json',controls)
        audits = []
        for attempt in study['attempts']:
            run = store.experiments.run(attempt['id'])
            audits.append(dict(runId=run['id'],experimentId=run['experiment_id'],status=run['status'],retryOf=run['retry_of'],
                tasks=[dict(id=t['id'],algorithm=t['algorithm'],datasetId=t['config']['datasetId'],status=t['status'],error=t['error'],analysisId=t['result_id']) for t in run['tasks']]))
        write_json(output/kind/'all-attempts.json',audits)
        verification[kind] = dict(studyId=study['id'],workspaceId=study['workspaceId'],tasks=len(study['tasks']),statusCounts=study['statusCounts'],
            fittedModels=len({t['metrics']['training']['fitId'] for t in study['tasks'] if t['metrics']}),
            newFits=sum(not t['metrics']['training']['reused'] for t in study['tasks'] if t['metrics']))
        if publish:
            publish.mkdir(parents=True,exist_ok=True)
            write_json(publish/f'{kind}_summary.json',compact)
            shutil.copyfile(output/kind/'per-run.csv',publish/f'{kind}_per_run.csv')
            if kind == 'robustness':
                write_json(publish/'fault3_summary.json',controls)
    # An actual expanded fault continues through the existing product lifecycle.
    ref = json.loads((output/'expanded'/'study.json').read_text())
    study = store.tep_studies.get(ref['workspaceId'],ref['studyId'])
    first = study['batches'][0]
    receipt_path = output/'incident-receipt.json'
    if receipt_path.exists():
        incident = store.incidents.get(json.loads(receipt_path.read_text())['incidentId'])
    else:
        incident = investigate(store,first['experimentId'],first['runId'])
        write_json(receipt_path,dict(incidentId=incident['id'],experimentId=first['experimentId'],runId=first['runId']))
    (output/'incident.html').write_text(render_report(store,incident['id']),encoding='utf-8')
    (output/'selected-experiment.html').write_text(render_experiment_report(store,first['experimentId'],first['runId']),encoding='utf-8')
    before = dict(incident=incident,counts=study['statusCounts'],tasks=[t['result_id'] for t in study['tasks']])
    reopened = WorkspaceStore(data_dir)
    restored = reopened.tep_studies.get(ref['workspaceId'],ref['studyId'])
    if before != dict(incident=reopened.incidents.get(incident['id']),counts=restored['statusCounts'],tasks=[t['result_id'] for t in restored['tasks']]):
        raise ValueError('Restart changed saved study/Incident evidence.')
    verification['restart'] = dict(restored=True,incidentId=incident['id'],links=len(incident['links']),entries=len(incident['entries']))
    baseline = json.loads((Path(__file__).resolve().parent/'results.json').read_text(encoding='utf-8'))
    report = json.loads((output/'expanded'/'results.json').read_text(encoding='utf-8'))
    selected = {(t['algorithm'],t['externalRun']):t for t in report['tasks']}
    exact_hashes, maximum_threshold_difference = 0,0.
    for old in baseline['tasks']:
        new = selected[(old['algorithm'],old['externalRun'])]
        np.testing.assert_allclose(new['threshold'],old['threshold'],rtol=1e-12,atol=1e-12)
        maximum_threshold_difference = max(maximum_threshold_difference,abs(new['threshold']-old['threshold']))
        if new['metrics']['labelled'] != old['metrics']['labelled']:
            # Label identities belong to different imports; numerical evaluation
            # must still agree with all frozen PR22 sample and event records.
            for key in ('sample','event'):
                if new['metrics']['labelled'][key] != old['metrics']['labelled'][key]:
                    raise ValueError('Expansion changed a published PR22 numerical outcome.')
        exact_hashes += new['scoreSha256'] == old['scoreSha256']
    verification['baseline'] = dict(comparedTasks=72,sampleAndEventMetricsEqual=True,exactScoreHashes=exact_hashes,
        maximumThresholdDifference=maximum_threshold_difference)
    write_json(output/'verification.json',verification)
    return verification


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path,required=True)
    parser.add_argument('--cache-dir',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--publish-dir',type=Path)
    args = parser.parse_args()
    print(json.dumps(finish(args.data_dir,args.cache_dir,args.output_dir,args.publish_dir),indent=2))


if __name__ == '__main__':
    main()
