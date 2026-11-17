"""Fixed held-out coupled-tank resilience benchmark with a local report."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter

from l5.resilience_evaluation import (BENCHMARK_VERSION, DEVELOPMENT_SEED, SEARCH_SEED,
                                     evaluate_case, prepare_campaign)
from l5.resilience_simulation import simulate_scenario


def paired_evidence(case, simulation, analysis):
    if not case['name'].startswith('short-') or case['detector']['algorithm'] != 'robust-maxz' or case['detector']['signals'] != ['level1']:
        return {}
    start, end = case['scenario']['faults'][0]['onset'], case['scenario']['faults'][0]['recovery']
    rows = [row for row in simulation['truth']['physical'] if start <= row['t'] <= end]
    initial = case['scenario']['initial']
    active_scores = [score for t, score in zip(analysis['times'], analysis['scores']) if start <= t < end]
    return dict(pairedEvidence=dict(peakTank1Deviation=max(abs(row['level1'] - initial['initial1']) for row in rows),
                peakTank2Deviation=max(abs(row['level2'] - initial['initial2']) for row in rows),
                peakActiveScore=max(active_scores)))


def run_benchmark():
    rows = []
    current, simulation = None, None
    for case in prepare_campaign({'mode': 'benchmark'}):
        started = perf_counter()
        try:
            if current != case['name'] or simulation is None:
                current, simulation = case['name'], None
                simulation = simulate_scenario(case['scenario'])
            analysis = evaluate_case(simulation, case['detector'])
            physical = simulation['truth']['physical']
            row = dict(**case, status='completed', metrics=analysis['metrics'],
                       threshold=analysis['analysis']['threshold'],
                       alarms=analysis['analysis']['intervals'],
                       training=analysis['analysis']['training'],
                       maxMassResidual=max(abs(point['massResidual']) for point in physical),
                       **paired_evidence(case, simulation, analysis['analysis']))
        except (ArithmeticError, ValueError) as error:
            row = dict(**case, status='failed', error=str(error),
                       runtimeMs=round((perf_counter()-started)*1000, 2))
        rows.append(row)
    return dict(version=BENCHMARK_VERSION, developmentSeed=DEVELOPMENT_SEED,
                searchSeed=SEARCH_SEED, rows=rows)


def render_markdown(report):
    rows = report['rows']
    completed = sum(row['status'] == 'completed' for row in rows)
    lines = [
        '# Coupled-tank resilience benchmark',
        '',
        f"{completed}/{len(rows)} detector cases completed. Protocol `{report['version']}`.",
        '',
        'Training and calibration use a separate healthy simulation. The test runs use fixed held-out seeds. '
        'Each alarm onset can match at most one active event. Presence records whether any alarm sample '
        'falls within an active event, including an alarm that began earlier.',
        '',
        '| Case | Detector | Presence | Matches | Mean delay (s) | Coverage | Nominal alarms | Nominal alarm share |',
        '|:--|:--|:--|--:|--:|--:|--:|--:|',
    ]
    for row in rows:
        detector = row['detector']
        label = f"{detector['algorithm']} ({', '.join(detector['signals'])})"
        if row['status'] != 'completed':
            lines.append(f"| {row['name']} | {label} | Failed | | | | | |")
            continue
        metrics = row['metrics']
        presence = {True: 'yes', False: 'no', None: '-'}[metrics['presenceDetected']]
        delay = '-' if metrics['meanDelay'] is None else f"{metrics['meanDelay']:.2f}"
        normal = metrics['normal']
        share = '-' if normal['alarmFraction'] is None else f"{normal['alarmFraction']:.2%}"
        lines.append(f"| {row['name']} | {label} | {presence} | "
                     f"{metrics['detectedEvents']}/{metrics['totalEvents']} | {delay} | {metrics['coverage']:.2%} | "
                     f"{normal['alarmEvents']} | {share} |")

    failures = [row for row in rows if row['status'] != 'completed']
    if failures:
        lines.extend(['', '## Execution failures', ''])
        lines.extend(f"- {row['name']}, {row['detector']['algorithm']}: {row['error']}" for row in failures)
    short_cases = [row for row in rows if 'pairedEvidence' in row]
    if len(short_cases) == 3 and all(row['metrics']['presenceDetected'] for row in short_cases[:2]) and not short_cases[-1]['metrics']['presenceDetected']:
        lines.extend(['', '## Paired fault comparison', '',
            'Tank 1 Max-Z detected each short single fault in isolation and missed their simultaneous pair at '
            f"{short_cases[-1]['metrics']['coverage']:.0%} decision coverage. The nominal inlet and inter-tank transfer both start at "
            '0.03 m^3/s. Equal reductions in these flows cancel the initial Tank 1 imbalance when both faults begin. '
            'This finding applies to the benchmark parameters and selected measurements.', '',
            '| Case | Peak Tank 1 deviation (m) | Peak Tank 2 deviation (m) | Peak active score | Threshold |',
            '|:--|--:|--:|--:|--:|'])
        for row in short_cases:
            evidence = row['pairedEvidence']
            lines.append(f"| {row['name']} | {evidence['peakTank1Deviation']:.5f} | {evidence['peakTank2Deviation']:.5f} | "
                         f"{evidence['peakActiveScore']:.3f} | {row['threshold']:.3f} |")
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, help='Optional directory for JSON evidence and a Markdown report.')
    args = parser.parse_args(argv)
    report = run_benchmark()
    markdown = render_markdown(report)
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / 'resilience_report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        (args.output_dir / 'resilience_report.md').write_text(markdown, encoding='utf-8')
    else:
        print(markdown)
    return int(any(row['status'] == 'failed' for row in report['rows']))


if __name__ == '__main__':
    raise SystemExit(main())
