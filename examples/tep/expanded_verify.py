"""Audit complete study coverage, frozen training, batches and timing denominators."""
import argparse
from collections import Counter
import json
from pathlib import Path

from l5.tep_import import SOURCES
from l5.tep_study import identity, protocol_for, protocol_hash


def verify(report, require_success=True):
    protocol = protocol_for(report['protocol']['id'])
    if report['protocol'] != protocol or report['protocolHash'] != protocol_hash(protocol):
        raise ValueError('Report differs from the predeclared protocol.')
    expected = {(configuration,plan['algorithm'],identity(test)) for configuration in protocol['configurations']
                for plan in protocol['algorithms'] for test in protocol['tests']}
    actual = Counter((t['configuration'],t['algorithm'],t['externalRun']) for t in report['tasks'])
    if set(actual) != expected or any(v != 1 for v in actual.values()):
        raise ValueError('Missing or duplicate predeclared tasks in the study denominator.')
    for filename in ('TEP_FaultFree_Training.RData','TEP_FaultFree_Testing.RData','TEP_Faulty_Testing.RData'):
        pin, source = SOURCES['files'][filename], report['sourceFiles'].get(filename,{})
        if source.get('sha256') != pin['sha256'] or source.get('md5') != pin['checksum']['value'] or source.get('sourceBytes') != pin['filesize']:
            raise ValueError('Study must retain all three checksum-pinned official source files.')
    for configuration in protocol['configurations']:
        for plan in protocol['algorithms']:
            tasks = [t for t in report['tasks'] if t['configuration'] == configuration and t['algorithm'] == plan['algorithm']]
            successful = [t for t in tasks if t['status'] == 'succeeded']
            if require_success and len(successful) != len(tasks):
                raise ValueError('The official acceptance run requires every declared task to succeed; failures remain in the report.')
            for task in tasks:
                if task['status'] != 'succeeded' and task['status'] in ('failed','interrupted') and not task['error']:
                    raise ValueError('Failure records require an explicit error.')
            if successful and (len({t['threshold'] for t in successful}) != 1 or len({t['metrics']['training']['modelKey'] for t in successful}) != 1
                or len({t['metrics']['training']['fitId'] for t in successful}) != 1):
                raise ValueError('Each normal configuration must reuse one fitted model/threshold across every test batch.')
            for task in successful:
                metrics, fault = task['metrics'], task['faultNumber'] != 0
                behavior, sample, detection = metrics['behavior'], metrics['labelled']['sample'], metrics['detection']
                if behavior['totalSamples'] != 960 or behavior['validSamples']+behavior['abstainedSamples'] != 960:
                    raise ValueError('Independent trajectory or observation denominator changed.')
                if sum(sample[k] for k in ('TP','FP','TN','FN')) != sample['evaluatedSamples']:
                    raise ValueError('Confusion denominator is inconsistent.')
                if detection['normal']['samples'] != (160 if fault else 960):
                    raise ValueError('Normal/pre-injection boundary must precede t=28800 s.')
                if fault and (detection['postInjection']['samples'] != 800 or detection['preInjection']['samples'] != 160):
                    raise ValueError('Fault injection must occur at sample 161 / 28800 s.')
                counts = []
                for key in ('1800','3600','14400','eventual'):
                    window = detection['windows'][key]
                    if window['totalEvents'] != int(fault):
                        raise ValueError('Missed/unobserved events disappeared from an early detection denominator.')
                    counts.append(window['detectedEvents'])
                if counts != sorted(counts):
                    raise ValueError('Early/eventual detection must be monotone in the horizon.')
                for event in detection['events']:
                    if event['onset'] != 28800 or (event['delay'] is not None and (event['delay'] < 0 or event['delay'] % 180)):
                        raise ValueError('Event delays must use actual elapsed seconds and the original injection time.')
    for configuration in protocol['configurations']:
        cells = [c for c in report['cells'] if c['configuration'] == configuration]
        if len(cells) != 21*9:
            raise ValueError('Every fault × algorithm cell must be present.')
        for cell in cells:
            expected_runs = 3 if cell['faultNumber'] else 5
            if cell['plannedRuns'] != expected_runs or cell['windows']['eventual']['totalEvents'] != (expected_runs if cell['faultNumber'] else 0):
                raise ValueError('Multi-batch pooled denominators do not match the declared run count.')
    # Normal fit/calibration identities are audited in each frozen batch snapshot.
    for snapshot in report['snapshots'].values():
        config = snapshot['config']
        meta = config['benchmark']
        if len(config['testDatasets'])*9 > 256 or meta['protocolHash'] != report['protocolHash']:
            raise ValueError('Batch budget or protocol isolation was lost.')
        for role, expected_source in protocol['configurations'][meta['configuration']].items():
            ref = config['training'][role]
            if ref['range'] != expected_source['range'] or ref['datasetId'] not in snapshot['datasetHashes']:
                raise ValueError('Frozen training range or input hash is missing.')
            if snapshot['datasetSources'][ref['datasetId']]['id'] != identity(expected_source):
                raise ValueError('Frozen fit/calibration source identity differs from the declared normal run.')
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reports', type=Path, nargs='+')
    args = parser.parse_args()
    for path in args.reports:
        report = json.loads(path.read_text(encoding='utf-8'))
        verify(report)
        print(f'Verified {report["protocol"]["id"]}: {len(report["tasks"])} tasks; all fault/run/algorithm and early-event denominators retained.')


if __name__ == '__main__':
    main()
