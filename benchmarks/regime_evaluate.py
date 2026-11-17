"""Fixed, normal-only training protocol for causal regime-aware monitoring."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
from statistics import median

import numpy as np

from l5.contracts import TEP_MULTIMODE_SCHEMA
from l5.regimes import evaluate_regimes, fit_regimes

from .multimode_normal import (
    CAL_END, FIT_END, MODE_IDS, TOTAL_COLUMNS, download_mode_data, read_mode_data,
)

METHODS = ('robust-maxz', 'pca-q', 'pca-t2')
APPROACHES = {
    'global': ('globalAlarm', 'globalScore'),
    'single': ('singleAlarm', 'singleScore'),
    'regimeAware': ('alarm', 'score'),
}
SETTINGS = dict(alpha=.01, recognitionAlpha=.01, variance=.90, shrinkage=.15,
                minMargin=2., dwell=4, persistence=3)
SEEDS = (1221, 1222, 1223, 1224, 1225, 1226)
FIT_SEED, CALIBRATION_SEED = 1201, 1202
NEAR_TRANSITION_SAMPLES = 12
FAULT_EARLY_SAMPLES = 12
SYNTHETIC_SIGNALS = ('load', 'setpoint', 'flow', 'temperature', 'pressure')
CENTERS = {
    'A': np.array([0., 0., 3., 0., 0.]),
    'B': np.array([4., 1.8, 6., 1.6, -1.4]),
    'C': np.array([5.1, 1.8, 5.5, 1.6, -1.4]),
}
OFF_CATALOG_CENTERS = {
    'unknown': np.array([-5., 4., 4., 2., 0.]),
    'ambiguous': (CENTERS['B'] + CENTERS['C']) / 2,
}


@dataclass(frozen=True)
class Transition:
    source: str
    destination: str
    onset: int
    settled: int
    deadline: int


@dataclass(frozen=True)
class Fault:
    name: str
    onset: int
    end: int


@dataclass(frozen=True)
class Trial:
    name: str
    values: np.ndarray
    mode: np.ndarray
    transitions: tuple[Transition, ...] = ()
    faults: tuple[Fault, ...] = ()


def _noise(rng: np.random.Generator, count: int) -> np.ndarray:
    innovations = rng.normal(size=(count, len(SYNTHETIC_SIGNALS)))
    innovations[:, 3] = .35 * innovations[:, 2] + np.sqrt(1 - .35**2) * innovations[:, 3]
    noise = innovations.copy()
    for row in range(1, count):
        noise[row] = .45 * noise[row - 1] + np.sqrt(1 - .45**2) * innovations[row]
    return noise * np.array([.42, .26, .30, .20, .18])


def synthetic_partitions() -> dict[str, tuple[np.ndarray, np.ndarray]]:
    fit, calibration = np.random.default_rng(FIT_SEED), np.random.default_rng(CALIBRATION_SEED)
    return {mode: (center + _noise(fit, 600), center + _noise(calibration, 300))
            for mode, center in CENTERS.items()}


def synthetic_trials(seed: int) -> list[Trial]:
    rng = np.random.default_rng(seed)

    def trial(name, phases, *, faults=(), transient=None):
        labels = []
        means = []
        transitions = []
        for mode, count in phases:
            if isinstance(mode, tuple):
                source, destination = mode
                weights = np.arange(1, count + 1)[:, None] / (count + 1)
                means.extend((1 - weights) * CENTERS[source] + weights * CENTERS[destination])
                transitions.append(Transition(source, destination, len(labels), len(labels) + count,
                                              len(labels) + count + 30))
                labels.extend(['transition'] * count)
            else:
                center = CENTERS[mode] if mode in CENTERS else OFF_CATALOG_CENTERS[mode]
                means.extend([center] * count)
                labels.extend([mode] * count)
        values = np.asarray(means) + _noise(rng, len(labels))
        if transient is not None:
            start, end = transient
            values[start:end] += CENTERS['B'] - CENTERS['A']
        for event, shift in faults:
            values[event.onset:event.end] += shift
        return Trial(f'{name}-{seed}', values, np.asarray(labels), tuple(transitions),
                     tuple(event for event, _ in faults))

    return [
        trial('healthy-transitions', [('A', 100), (('A', 'B'), 8), ('B', 80),
                                      (('B', 'C'), 8), ('C', 100)], transient=(35, 37)),
        trial('steady-faults', [('A', 100), (('A', 'B'), 8), ('B', 120)], faults=(
            (Fault('pressure-bias', 40, 61), [0, 0, 0, 0, 1.5]),
            (Fault('weak-temperature-bias', 145, 169), [0, 0, 0, .32, 0]),
            (Fault('flow-bias', 189, 212), [0, 0, 1.55, 0, 0]),
        )),
        trial('fault-across-transition', [('A', 100), (('A', 'B'), 8), ('B', 100)], faults=(
            (Fault('pressure-bias-near-transition', 97, 130), [0, 0, 0, 0, 1.5]),
        )),
        trial('uncertain-regimes', [('B', 75), ('ambiguous', 80), ('B', 75),
                                    ('unknown', 75), ('A', 75)]),
    ]


def _burden(scored: np.ndarray, alarm: np.ndarray, starts: np.ndarray, mask: np.ndarray) -> dict:
    return dict(samples=int(mask.sum()), scoredSamples=int((scored & mask).sum()),
                alarmSamples=int((alarm & mask).sum()), alarmStarts=int((starts & mask).sum()))


def _trial_metrics(trial: Trial, result: dict) -> dict:
    decisions = result['decisions']
    size = len(decisions)
    if size != len(trial.mode):
        raise ValueError('Evaluation decisions must preserve every trial sample.')
    recognized = np.array([row['mode'] or 'unconfirmed' for row in decisions])
    recognition = np.array([row['recognition'] for row in decisions])
    known = ~np.isin(trial.mode, ('transition', 'ambiguous', 'unknown'))
    fault = np.zeros(size, dtype=bool)
    for event in trial.faults:
        fault[event.onset:event.end] = True
    near_transition = np.zeros(size, dtype=bool)
    for event in trial.transitions:
        near_transition[event.onset:event.settled + NEAR_TRANSITION_SAMPLES] = True

    confusion = {label: dict(Counter(recognized[(trial.mode == label) & ~fault].tolist()))
                 for label in sorted(set(trial.mode[known]))}
    open_set = {}
    for phase in ('unknown', 'ambiguous'):
        mask = trial.mode == phase
        open_set[phase] = dict(samples=int(mask.sum()), confirmed=int((mask & (recognized != 'unconfirmed')).sum()),
                               evidence=dict(Counter(recognition[mask].tolist())))

    transition_events = result['transitions']
    matched = set()
    transitions = []
    for expected in trial.transitions:
        match = next(((idx, event) for idx, event in enumerate(transition_events)
                      if idx not in matched and event['outcome'] == 'confirmed'
                      and event['fromMode'] == expected.source and event['toMode'] == expected.destination
                      and expected.onset <= event['confirmedTime'] < expected.deadline), None)
        candidate = confirmation = None
        if match:
            idx, event = match
            matched.add(idx)
            candidate, confirmation = event['candidateTime'], event['confirmedTime']
        transitions.append(dict(trial=trial.name, source=expected.source, destination=expected.destination,
                                onset=expected.onset, settled=expected.settled, deadline=expected.deadline,
                                candidate=candidate, confirmed=confirmation,
                                delay=None if confirmation is None else confirmation - expected.onset,
                                delayAfterSettling=None if confirmation is None else confirmation - expected.settled))

    monitoring = {}
    for approach, (alarm_field, score_field) in APPROACHES.items():
        alarm = np.array([row[alarm_field] for row in decisions], dtype=bool)
        scored = np.array([row[score_field] is not None for row in decisions], dtype=bool)
        starts = alarm & ~np.r_[False, alarm[:-1]]
        faults = []
        for event in trial.faults:
            new = np.flatnonzero(starts[event.onset:event.end])
            delay = int(new[0]) if len(new) else None
            faults.append(dict(trial=trial.name, fault=event.name, onset=event.onset, end=event.end,
                               crossesTransition=any(event.onset < transition.settled and
                                                     event.end > transition.onset for transition in trial.transitions),
                               scoredSamples=int(scored[event.onset:event.end].sum()),
                               delay=delay, firstAlarm=None if delay is None else event.onset + delay,
                               activeBeforeOnset=bool(event.onset and alarm[event.onset - 1])))
        monitoring[approach] = dict(
            allHealthy=_burden(scored, alarm, starts, ~fault),
            knownHealthy=_burden(scored, alarm, starts, known & ~fault),
            nearTransition=_burden(scored, alarm, starts, near_transition & ~fault),
            unknownHealthy=_burden(scored, alarm, starts, trial.mode == 'unknown'),
            ambiguousHealthy=_burden(scored, alarm, starts, trial.mode == 'ambiguous'),
            faults=faults,
        )
    return dict(confusion=confusion, openSet=open_set, transitions=transitions,
                transitionOutcomes=dict(Counter(row['outcome'] for row in transition_events)),
                unmatchedConfirmed=[dict(trial=trial.name, source=row['fromMode'], destination=row['toMode'],
                                         candidate=row['candidateTime'], confirmed=row['confirmedTime'])
                                    for idx, row in enumerate(transition_events)
                                    if row['outcome'] == 'confirmed' and idx not in matched],
                monitoring=monitoring)


def _fraction(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _sum_fields(records: list[dict], fields: tuple[str, ...]) -> dict:
    return {field: sum(record[field] for record in records) for field in fields}


def _counts(records) -> dict:
    counts = Counter()
    for record in records:
        counts.update(record)
    return dict(sorted(counts.items()))


def _fault_metrics(faults: list[dict]) -> dict:
    delays = [event['delay'] for event in faults if event['delay'] is not None]
    return dict(events=len(faults), detected=len(delays), missed=len(faults) - len(delays),
                detectionFraction=_fraction(len(delays), len(faults)),
                detectedWithin12Samples=sum(delay < FAULT_EARLY_SAMPLES for delay in delays),
                medianDetectedDelay=median(delays) if delays else None)


def _summary(records: list[dict]) -> dict:
    labels = sorted({mode for row in records for mode in row['confusion']})
    confusion = {mode: _counts(row['confusion'].get(mode, {}) for row in records) for mode in labels}
    known = sum(sum(row.values()) for row in confusion.values())
    correct = sum(row.get(mode, 0) for mode, row in confusion.items())
    unconfirmed = sum(row.get('unconfirmed', 0) for row in confusion.values())
    open_set = {}
    for phase in ('unknown', 'ambiguous'):
        values = [row['openSet'][phase] for row in records]
        counts = _sum_fields(values, ('samples', 'confirmed'))
        open_set[phase] = dict(**counts, rejectionFraction=_fraction(counts['samples'] - counts['confirmed'],
                                                                     counts['samples']),
                               evidence=_counts(value['evidence'] for value in values))

    transitions = [event for row in records for event in row['transitions']]
    transition_delays = [event['delay'] for event in transitions if event['delay'] is not None]
    monitoring = {}
    for approach in APPROACHES:
        rows = [row['monitoring'][approach] for row in records]
        workload = {}
        for group in ('allHealthy', 'knownHealthy', 'nearTransition', 'unknownHealthy', 'ambiguousHealthy'):
            counts = _sum_fields([row[group] for row in rows], ('samples', 'scoredSamples', 'alarmSamples', 'alarmStarts'))
            workload[group] = dict(**counts, alarmFraction=_fraction(counts['alarmSamples'], counts['samples']),
                                   coverage=_fraction(counts['scoredSamples'], counts['samples']))
        faults = [event for row in rows for event in row['faults']]
        monitoring[approach] = dict(**workload, faults=dict(
            **_fault_metrics(faults),
            withinMode=_fault_metrics([event for event in faults if not event['crossesTransition']]),
            crossesTransition=_fault_metrics([event for event in faults if event['crossesTransition']]),
            cases=faults))
    return dict(
        trials=len(records),
        recognition=dict(knownHealthySamples=known, correct=correct, wrong=known - correct - unconfirmed,
                         unconfirmed=unconfirmed, accuracy=_fraction(correct, known), confusion=confusion,
                         openSet=open_set),
        transitions=dict(expected=len(transitions), matched=len(transition_delays),
                         missed=len(transitions) - len(transition_delays),
                         medianDelay=median(transition_delays) if transition_delays else None,
                         outcomes=_counts(row['transitionOutcomes'] for row in records), cases=transitions,
                         unmatchedConfirmed=[event for row in records for event in row['unmatchedConfirmed']]),
        monitoring=monitoring,
    )


def _evaluate(model, trial: Trial) -> dict:
    # Truth and event windows enter metrics only after a complete causal replay.
    result = evaluate_regimes(model, np.arange(len(trial.values), dtype=float), trial.values)
    return _trial_metrics(trial, result)


def _fit(partitions, signals, algorithm, recognition_signals):
    return fit_regimes(partitions, signals, dict(**SETTINGS, algorithm=algorithm,
                       referenceMode=next(iter(partitions)), recognitionSignals=list(recognition_signals)))


def _comparison(methods: dict) -> dict:
    reference = methods[METHODS[0]]
    shared = {key: reference[key] for key in ('trials', 'recognition', 'transitions')}
    for result in methods.values():
        if any(result[key] != value for key, value in shared.items()):
            raise ValueError('Recognition and transitions must be independent of the monitoring algorithm.')
    return dict(**shared, monitoringByMethod={method: result['monitoring'] for method, result in methods.items()})


def run_synthetic() -> dict:
    partitions = synthetic_partitions()
    trials = [trial for seed in SEEDS for trial in synthetic_trials(seed)]
    results = {}
    for method in METHODS:
        model = _fit(partitions, SYNTHETIC_SIGNALS, method, SYNTHETIC_SIGNALS[:2])
        results[method] = _summary([_evaluate(model, trial) for trial in trials])
    return _comparison(results)


def run_thufdd(data: dict[int, np.ndarray]) -> dict:
    partitions = {str(mode): (data[mode][:FIT_END], data[mode][FIT_END:CAL_END]) for mode in MODE_IDS}
    tails = {str(mode): data[mode][CAL_END:] for mode in MODE_IDS}
    signals = TEP_MULTIMODE_SCHEMA.keys
    isolated = [Trial(f'mode-{mode}-normal-tail', values, np.repeat(mode, len(values)))
                for mode, values in tails.items()]
    boundaries = np.cumsum([len(trial.values) for trial in isolated])
    joins = tuple(Transition(str(source), str(destination), int(boundary), int(boundary), int(boundary) + 30)
                  for source, destination, boundary in zip(MODE_IDS, MODE_IDS[1:], boundaries[:-1]))
    stitched = Trial('stitched-healthy-tails-1-to-6', np.concatenate([trial.values for trial in isolated]),
                     np.concatenate([trial.mode for trial in isolated]), joins)
    by_trial = {name: {} for name in ('isolatedKnownTails', 'stitchedKnownTails', 'withheldModeTails')}
    rejection_by_mode = None
    for method in METHODS:
        model = _fit(partitions, signals, method, signals)
        withheld = {}
        for mode, values in tails.items():
            retained = {label: partitions[label] for label in partitions if label != mode}
            smaller_model = _fit(retained, signals, method, signals)
            unknown = Trial(f'mode-{mode}-withheld-tail', values, np.repeat('unknown', len(values)))
            withheld[mode] = _evaluate(smaller_model, unknown)
        by_trial['isolatedKnownTails'][method] = _summary([_evaluate(model, trial) for trial in isolated])
        by_trial['stitchedKnownTails'][method] = _summary([_evaluate(model, stitched)])
        by_trial['withheldModeTails'][method] = _summary(list(withheld.values()))
        rejection = {mode: row['openSet']['unknown'] for mode, row in withheld.items()}
        if rejection_by_mode is not None and rejection_by_mode != rejection:
            raise ValueError('Withheld-mode rejection must be independent of the monitoring algorithm.')
        rejection_by_mode = rejection
    return dict(**{name: _comparison(methods) for name, methods in by_trial.items()},
                rejectionByWithheldMode=rejection_by_mode)


def run(data_dir: Path | None = None, *, allow_network: bool = False) -> dict:
    result = dict(version=1, protocol=dict(
        settings=SETTINGS, methods=METHODS, nearTransitionSamplesAfterSettling=NEAR_TRANSITION_SAMPLES,
        earlyFaultWindowSamples=FAULT_EARLY_SAMPLES,
        transitionConfirmationWindowSamplesAfterSettling=30,
        singleReference='First configured mode in fixed source order. Withheld modes are absent from every fit and calibration.',
        synthetic=dict(fitSeed=FIT_SEED, calibrationSeed=CALIBRATION_SEED, evaluationSeeds=SEEDS,
                       fitSamplesPerMode=600, calibrationSamplesPerMode=300, signals=SYNTHETIC_SIGNALS,
                       recognitionSignals=SYNTHETIC_SIGNALS[:2]),
    ))
    result['synthetic'] = run_synthetic()
    if data_dir is not None:
        sources = download_mode_data(data_dir, allow_network=allow_network)
        data = read_mode_data(data_dir)
        result['thufdd'] = dict(
            signalSchema=TEP_MULTIMODE_SCHEMA.metadata(), rawColumns=TOTAL_COLUMNS,
            sourceColumnIndices=list(range(53)), fitRows=[0, FIT_END], calibrationRows=[FIT_END, CAL_END],
            evaluationStartsAtRow=CAL_END, rowCounts={str(mode): len(values) for mode, values in data.items()},
            partitionBasis='Chronological within a single normal trajectory per mode. Stitched joins are constructed.',
            originalSources=sources, **run_thufdd(data),
        )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--thufdd-dir', type=Path, help='Directory for the six pinned original MATLAB files')
    parser.add_argument('--download', action='store_true', help='Allow missing THUFDD files to be fetched')
    parser.add_argument('--output', type=Path, required=True, help='Write JSON metrics and per-event outcomes')
    args = parser.parse_args(argv)
    if args.download and args.thufdd_dir is None:
        parser.error('--download requires --thufdd-dir')
    try:
        report = run(args.thufdd_dir, allow_network=args.download)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + '\n',
                               encoding='utf-8', newline='\n')
    except (OSError, RuntimeError, ValueError) as error:
        parser.error(str(error))
    print(f'Regime monitoring evaluation written to {args.output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
