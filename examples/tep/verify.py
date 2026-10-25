"""Audit the fixed original-data run without tuning on its outcomes."""
import argparse
import json
from pathlib import Path

from l5.tep_import import PROTOCOL, SOURCES
from l5.contracts import TEP_CLASSIC_SCHEMA


def verify(report):
    if report['protocol'] != PROTOCOL or report['status'] != 'completed' or len(report['tasks']) != 72:
        raise ValueError('Expected the unchanged predeclared 72-task protocol and a completed run.')
    expected_files = {'TEP_FaultFree_Training.RData', 'TEP_FaultFree_Testing.RData', 'TEP_Faulty_Testing.RData'}
    if set(report['sourceFiles']) != expected_files or report['runSnapshot']['config']['signals'] != list(TEP_CLASSIC_SCHEMA.keys):
        raise ValueError('Expected all three official originals and the exact 52-feature input order.')
    expected_runs = {f'{s["sourceId"]}-f{s["faultNumber"]:02d}-r{s["simulationRun"]:03d}' for s in PROTOCOL['tests']}
    for filename, source in report['sourceFiles'].items():
        pin = SOURCES['files'][filename]
        if source['md5'] != pin['checksum']['value'] or source['sha256'] != pin['sha256']:
            raise ValueError('Original source identity differs from the checksum-pinned official file.')
    for plan in PROTOCOL['algorithms']:
        tasks = [t for t in report['tasks'] if t['algorithm'] == plan['algorithm']]
        if len(tasks) != 8 or any(t['status'] != 'succeeded' for t in tasks):
            raise ValueError('Each existing method must have eight successful independently scored runs.')
        if {t['externalRun'] for t in tasks} != expected_runs:
            raise ValueError('Each method must retain all predeclared test runs, including weak and missed faults.')
        if len({t['metrics']['training']['modelKey'] for t in tasks}) != 1 or len({t['threshold'] for t in tasks}) != 1:
            raise ValueError('Model configuration and normal-only threshold must be reused across all test runs.')
        if len({t['sourceSequence'] for t in tasks}) != 8:
            raise ValueError('Test sequence boundaries must remain distinct.')
        for task in tasks:
            behavior, labelled = task['metrics']['behavior'], task['metrics']['labelled']
            if behavior['totalSamples'] != 960 or behavior['validSamples']+behavior['abstainedSamples'] != 960:
                raise ValueError('Coverage denominator differs from the complete independent trajectory.')
            sample = labelled['sample']
            if sum(sample[k] for k in ('TP','FP','TN','FN')) != sample['evaluatedSamples']:
                raise ValueError('Confusion counts must retain evaluated rather than unlabelled/abstained samples.')
            for event in labelled['event']['events']:
                delay = event['delay']
                if delay is not None and (delay < 0 or delay % 180):
                    raise ValueError('Detection delay must use the actual 180-second sampling clock.')
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    args = parser.parse_args()
    verify(json.loads(args.report.read_text(encoding='utf-8')))
    print('Verified: 72 independent tasks, nine fixed models, three official source files, explicit metric denominators.')


if __name__ == '__main__':
    main()
