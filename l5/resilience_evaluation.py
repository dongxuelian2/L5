"""Held-out detector evaluation, bounded campaign grids and numerical search."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from itertools import product
import math
from random import Random
from time import perf_counter

import numpy as np

from .analysis import ALGORITHMS, run_analysis
from .detection_metrics import detection_metrics
from .experiment_evaluation import ratio, spans
from .experiments import DEFAULTS, PARAMETERS, numeric
from .resilience_simulation import FAULT_FIELDS as FAULT_PARAMETERS, PROFILE_FIELDS, simulate_scenario, validate_scenario


MAX_CASES = 64
MAX_SEARCH_CASES = 32
MAX_SUPPRESSION_EVENTS = 6
BENCHMARK_VERSION = 'coupled-tank-resilience-v1'
DEVELOPMENT_SEED = 42017
SEARCH_SEED = 62043
BENCHMARK_SEED = 92351
TRAINING_SEED = 14071
OBJECTIVES = ('missed', 'delay', 'false_alarms', 'suppression', 'coverage')
DEFAULT_DETECTOR = dict(algorithm='robust-maxz', signals=['level1', 'level2'],
                        persistence=3, alpha=.01, minCoverage=.9, requiredSignals=[],
                        training=dict(seed=TRAINING_SEED, noise=.002, initial={}, parameters={}))
BENCHMARK_DETECTORS = [DEFAULT_DETECTOR, {**DEFAULT_DETECTOR, 'algorithm': 'ewma'},
                       {**DEFAULT_DETECTOR, 'algorithm': 'pca-q'},
                       {**DEFAULT_DETECTOR, 'signals': ['level1']}]
SCENARIO_AXES = {'duration', 'seed', 'faults', 'measurement.noise', 'measurement.physical_noise',
                 'measurement.missing_fraction', 'initial.initial1', 'initial.initial2'}
FAULT_AXES = {'onset', 'recovery', 'severity', 'type', 'target', 'profile', 'duration'}


def campaign_catalog():
    return dict(algorithms=dict(ALGORITHMS), default_detectors=deepcopy([DEFAULT_DETECTOR]),
                benchmark_detectors=deepcopy(BENCHMARK_DETECTORS), objectives=list(OBJECTIVES),
                max_cases=MAX_CASES, max_search_cases=MAX_SEARCH_CASES,
                benchmark_version=BENCHMARK_VERSION)


def _seed(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 2147483647:
        raise ValueError(f'{label} must be an integer in [0, 2147483647].')
    return value


def _detector(raw, available):
    if not isinstance(raw, dict):
        raise ValueError('Each detector configuration must be an object.')
    algorithm = raw.get('algorithm', DEFAULT_DETECTOR['algorithm'])
    if not isinstance(algorithm, str) or algorithm not in ALGORITHMS:
        raise ValueError('Choose an available detection algorithm.')
    signals = raw.get('signals', DEFAULT_DETECTOR['signals'])
    required = raw.get('requiredSignals', [])
    if (not isinstance(signals, list) or not signals or any(not isinstance(s, str) or s not in available for s in signals)
            or len(set(signals)) != len(signals)):
        raise ValueError('Select unique observed channels for each detector.')
    if (not isinstance(required, list) or any(not isinstance(s, str) or s not in signals for s in required)
            or len(set(required)) != len(required)):
        raise ValueError('Required signals must be unique selected detector channels.')
    training = raw.get('training', {})
    if not isinstance(training, dict) or set(training) - {'seed', 'noise', 'initial', 'parameters'}:
        raise ValueError('Training supports seed, noise, initial conditions and model parameters.')
    reference = validate_scenario(dict(seed=_seed(training.get('seed', TRAINING_SEED), 'Training seed'),
        measurement=dict(noise=training.get('noise', .002)), initial=training.get('initial', {}),
        parameters=training.get('parameters', {})))
    clean_training = dict(seed=reference['seed'], noise=reference['measurement']['noise'],
                          initial=reference['initial'], parameters=reference['parameters'])
    keys = ('alpha', 'minCoverage', 'persistence', 'fitFraction', *PARAMETERS[algorithm])
    config = {key: numeric(key, raw.get(key, DEFAULT_DETECTOR.get(key, DEFAULTS[key]))) for key in keys}
    return dict(algorithm=algorithm, signals=list(signals), requiredSignals=list(required),
                training=clean_training, **config)


def _measurement_matrix(observations, signals):
    times = np.asarray([row['t'] for row in observations], dtype=float)
    values = np.asarray([[row['values'].get(key) for key in signals] for row in observations], dtype=float)
    return times, values


def _analyze(observations, detector):
    """The detector boundary admits only the delivered values and polling clock."""
    signals = detector['signals']
    times, values = _measurement_matrix(observations, signals)
    if len(times) < 2:
        raise ValueError('Detection requires at least two acquisition polls.')
    period = float(times[1] - times[0])
    training = detector['training']
    reference = simulate_scenario(dict(seed=training['seed'], initial=training['initial'],
        parameters=training['parameters'], measurement=dict(noise=training['noise'], signals=signals),
        duration=math.nextafter(float(319 * Decimal(str(period))), math.inf), sample_interval=period,
        integration_step=max(.05, min(.25, period))), stream_namespace='training')
    training_times, normal = _measurement_matrix(reference['observations'], signals)
    # Put the independently generated reference on a disjoint analysis clock.
    # The test clock stays unchanged for reports and alarm/event matching.
    training_times = training_times - training_times[-1] - period + times[0]
    analysis_config = {key: value for key, value in detector.items() if key != 'training'}
    analysis_config.update(baselineRange=[float(training_times[0]), float(training_times[-1])],
                           analysisRange=[float(times[0]), float(times[-1])])
    joined = np.concatenate((normal, values), axis=0)
    result = run_analysis(np.concatenate((training_times, times)), joined, signals, analysis_config,
                          observed=np.isfinite(joined))
    result['training'] = dict(source='independent healthy simulation', streamNamespace='training', **deepcopy(training),
                              sampleInterval=period, samples=len(training_times))
    return result


def _event_mask(times, event, duration):
    active = np.zeros(len(times), dtype=bool)
    for interval in event['intervals']:
        start, end = interval['start'], interval['end']
        inside = (times >= start) & (times < end)
        if not interval.get('endExclusive', end != duration or event['recovery'] is not None):
            inside |= (times == end) & (times >= start)
        active |= inside
    return active


def _match_starts(candidates):
    """Maximum-cardinality one-to-one matching of events and alarm episode starts."""
    owner = {}

    def assign(event_index, visited):
        for start in candidates[event_index]:
            if start not in owner:
                owner[start] = event_index
                return True
        for start in candidates[event_index]:
            if start in visited:
                continue
            visited.add(start)
            if assign(owner[start], visited):
                owner[start] = event_index
                return True
        return False

    # Visit event onsets and episode starts chronologically for stable ties.
    for event_index in range(len(candidates)):
        assign(event_index, set())
    return {index: start for start, index in owner.items()}


def score_events(analysis, events, duration):
    """Score event windows retrospectively on the observable polling clock.

    Presence counts active alarm samples. Event matching credits a distinct
    alarm episode start to at most one active event. Matching is temporal
    evidence, and makes no claim about identifying the causal fault type.
    """
    times, states = np.asarray(analysis['times'], dtype=float), np.asarray(analysis['states'])
    alarm, valid = states == 'alarm', states != 'abstain'
    starts = alarm & ~np.r_[False, alarm[:-1]]
    inactive_ids = [event['id'] for event in events if not event['intervals']]
    events = sorted((event for event in events if event['intervals']), key=lambda event: (event['onset'], event['id']))
    masks = [_event_mask(times, event, duration) for event in events]
    matched = _match_starts([np.flatnonzero(mask & starts).tolist() for mask in masks])
    active = np.any(masks, axis=0) if masks else np.zeros(len(times), dtype=bool)
    simultaneous = np.sum(masks, axis=0) >= 2 if masks else active
    details = []
    for index, (event, mask) in enumerate(zip(events, masks)):
        start = float(times[matched[index]]) if index in matched else None
        details.append(dict(id=event['id'], type=event['type'], target=event['target'],
            onset=event['onset'], recovery=event['recovery'], observedSamples=int((mask & valid).sum()),
            activeSamples=int(mask.sum()), presenceDetected=bool((mask & alarm).any()),
            detected=start is not None, firstDetection=start,
            delay=start - event['onset'] if start is not None else None))

    def burden(mask):
        intervals = [dict(kind='normal', **interval) for interval in spans(times, mask)]
        return detection_metrics(analysis, dict(intervals=intervals))['normal']

    pre = burden(times < min(interval['start'] for event in events for interval in event['intervals'])) if events else None
    inactive = burden(~active)
    # Tank states can still be settling after a recovery. Only the interval
    # before any fault, or the full healthy control, is verified nominal.
    normal = pre if pre is not None else inactive
    hits = len(matched)
    delays = [event['delay'] for event in details if event['delay'] is not None]
    presence = times[active & alarm]
    coverage = float(valid.mean())
    miss_rate = ratio(len(events) - hits, len(events))
    delay_loss = []
    for event in details:
        end = event['recovery'] if event['recovery'] is not None else duration
        follow_up = max(0., end - event['onset'])
        delay_loss.append(min(1., event['delay'] / follow_up) if event['delay'] is not None and follow_up else 1.)
    return dict(totalEvents=len(events), detectedEvents=hits, missedEvents=len(events)-hits,
                unobservedEvents=sum(not event['observedSamples'] for event in details),
                eventDetectionRate=ratio(hits, len(events)), meanDelay=ratio(sum(delays), len(delays)),
                presenceDetected=bool(len(presence)) if events else None,
                presenceFirstDetection=float(presence[0]) if len(presence) else None,
                allEventsMatched=hits == len(events) if events else None, coverage=coverage,
                meanObservationFraction=float(np.mean(analysis['observedFraction'])),
                simultaneousSamples=int(simultaneous.sum()),
                simultaneousObservedSamples=int((simultaneous & valid).sum()),
                simultaneousAlarmSamples=int((simultaneous & alarm).sum()),
                normal=normal, preFault=pre, inactive=inactive, events=details, inactiveEventIds=inactive_ids,
                searchScores=dict(missed=miss_rate or 0., delay=ratio(sum(delay_loss), len(delay_loss)) or 0.,
                                  false_alarms=normal['alarmFraction'] or 0., suppression=0., coverage=1.-coverage))


def _suppression(simulation, detector, combined):
    """Paired single-fault counterfactuals keep conditions and all seeds fixed."""
    scenario = simulation['scenario']
    faults = {fault['id']: fault for fault in scenario['faults']}
    comparisons = []
    for detail in combined['events']:
        single = simulate_scenario({**scenario, 'faults': [faults[detail['id']]]})
        analysis = _analyze(single['observations'], detector)
        event = score_events(analysis, single['truth']['events'], scenario['duration'])['events'][0]
        comparisons.append(dict(id=detail['id'], isolatedPresence=event['presenceDetected'],
            combinedPresence=detail['presenceDetected'], isolatedMatched=event['detected'],
            combinedMatched=detail['detected'], isolatedDelay=event['delay'], combinedDelay=detail['delay']))
    isolated_hits = sum(row['isolatedPresence'] for row in comparisons)
    lost = sum(row['isolatedPresence'] and not row['combinedPresence'] for row in comparisons)
    return dict(events=comparisons, isolatedPresenceEvents=isolated_hits, lostPresenceEvents=lost,
                lostMatches=sum(row['isolatedMatched'] and not row['combinedMatched'] for row in comparisons),
                lostPresenceFraction=ratio(lost, isolated_hits))


def evaluate_case(simulation, detector, *, objective=None):
    started = perf_counter()
    detector = _detector(detector, {signal['key'] for signal in simulation['signals']})
    # Materialize only delivered values and the detector clock at this call boundary.
    observations = [{key: row[key] for key in ('t', 'values')} for row in simulation['observations']]
    analysis = _analyze(observations, detector)
    duration = simulation['scenario']['duration']
    metrics = score_events(analysis, simulation['truth']['events'], duration)
    if objective == 'suppression' and metrics['totalEvents'] > 1:
        if metrics['totalEvents'] > MAX_SUPPRESSION_EVENTS:
            raise ValueError(f'Suppression comparisons support at most {MAX_SUPPRESSION_EVENTS} events per case.')
        metrics['suppression'] = _suppression(simulation, detector, metrics)
        metrics['searchScores']['suppression'] = metrics['suppression']['lostPresenceFraction'] or 0.
    metrics['runtimeMs'] = round((perf_counter() - started) * 1000, 2)
    return dict(analysis=analysis, metrics=metrics)


def _fault(identity, kind, target, *, onset=45., recovery=None, severity=.6, profile='step', **parameters):
    return dict(id=identity, type=kind, target=target, onset=onset, recovery=recovery,
                severity=severity, profile=profile, parameters=parameters)


def _benchmark():
    pump = _fault('pump', 'pump_degradation', 'pump')
    valve = _fault('valve', 'valve_restriction', 'valve')
    leak = _fault('leak', 'tank_leak', 'tank1')
    # With nominal inlet and transfer both .03 m³/s, equal short reductions
    # cancel the initial Tank 1 imbalance when both begin together.
    short_pump = {**pump, 'severity': .55, 'recovery': 48.}
    short_valve = {**valve, 'severity': .55, 'recovery': 48., 'parameters': {'maximum_loss': .7}}
    mismatch = {'initial': {'initial1': 1.4, 'initial2': .85}, 'parameters': {'outlet': .035}}
    rows = [
        ('healthy', [], {}),
        ('healthy-replicate', [], {'seed': BENCHMARK_SEED + 1}),
        ('pump', [pump], {}),
        ('valve', [valve], {}),
        ('tank-leak', [leak], {}),
        ('simultaneous-pump-leak', [pump, leak], {}),
        ('sequential-valve-leak', [valve, {**leak, 'onset': 78.}], {}),
        ('pump-with-stuck-level', [pump, _fault('stuck', 'sensor_stuck', 'level2', severity=1.)], {}),
        ('gradual-pump-with-dropout', [{**pump, 'profile': 'progressive', 'parameters': {'time_constant': 24.}},
            _fault('drop', 'sensor_dropout', 'level2', onset=48., severity=1., profile='intermittent',
                   period=8., active_duration=3.)], {}),
        ('leak-during-blackout', [{**leak, 'onset': 48.},
            _fault('blackout', 'communication_blackout', 'all', onset=42., recovery=64., severity=1.)], {}),
        ('temporary-valve-recovery', [{**valve, 'profile': 'temporary', 'recovery': 72.}], {}),
        ('healthy-with-model-mismatch', [], mismatch),
        ('pump-with-model-mismatch', [pump], mismatch),
        ('short-pump', [short_pump], {}),
        ('short-valve', [short_valve], {}),
        ('short-canceling-pair', [short_pump, short_valve], {}),
    ]
    return [(name, dict(name=name, duration=120., sample_interval=.2, seed=BENCHMARK_SEED, faults=faults) | changes)
            for name, faults, changes in rows]


def _axis_path(path):
    if not isinstance(path, str) or len(path) > 160:
        raise ValueError('Every campaign axis needs a supported path.')
    parts = path.split('.')
    if path in SCENARIO_AXES or (len(parts) == 2 and parts[0] == 'parameters' and parts[1]):
        return parts
    if len(parts) == 3 and parts[0] == 'faults' and parts[1] and parts[2] in FAULT_AXES:
        return parts
    if len(parts) == 4 and parts[0] == 'faults' and parts[1] and parts[2] == 'parameters' and parts[3]:
        return parts
    if len(parts) == 4 and parts[:2] == ['detector', 'training'] and parts[2] in ('parameters', 'initial') and parts[3]:
        return parts
    if path in ('detector.training.seed', 'detector.training.noise'):
        return parts
    raise ValueError(f'Unsupported campaign axis {path}.')


def _vary(scenario, detector, axes, values):
    scenario, detector = deepcopy(scenario), deepcopy(detector)
    for parts, value in zip(axes, values):
        if parts == ['duration']:
            scenario['duration'] = value
        if parts == ['faults']:
            scenario['faults'] = deepcopy(value)
    if any(parts == ['faults'] for parts in axes):
        scenario = validate_scenario(scenario)
    event_axes = {parts[1] for parts in axes if parts[0] == 'faults' and len(parts) > 1}
    missing = event_axes - {fault['id'] for fault in scenario['faults']}
    if missing:
        raise ValueError(f'Campaign axis refers to absent event {min(missing)}.')
    for fault in scenario['faults']:
        if fault['id'] not in event_axes:
            continue
        changes = {parts[2]: value for parts, value in zip(axes, values)
                   if len(parts) == 3 and parts[:2] == ['faults', fault['id']]}
        if {'type', 'profile'} & changes.keys():
            fault_type = changes.get('type', fault['type'])
            profile = changes.get('profile', fault['profile'])
            if not isinstance(fault_type, str) or not isinstance(profile, str):
                raise ValueError('Fault type and profile axes require supported names.')
            specs = FAULT_PARAMETERS.get(fault_type, []) + PROFILE_FIELDS.get(profile, [])
            supported = {spec['key'] for spec in specs}
            fault['parameters'] = {key: value for key, value in fault['parameters'].items() if key in supported}
        if 'duration' in changes:
            length = changes['duration']
            if 'recovery' in changes or (length is not None and (isinstance(length, bool) or not isinstance(length, (float, int)) or not math.isfinite(length))):
                raise ValueError('A fault duration axis needs finite seconds or null and cannot be combined with recovery.')
            onset = changes.get('onset', fault['onset'])
            if isinstance(onset, bool) or not isinstance(onset, (int, float)) or not math.isfinite(onset):
                raise ValueError('Fault onset must be finite seconds.')
            fault['recovery'] = onset + length if length is not None else None
    for parts, value in zip(axes, values):
        if parts == ['faults'] or (parts[0] == 'faults' and len(parts) == 3 and parts[2] == 'duration'):
            continue
        target = scenario
        if parts[0] == 'faults':
            target = next(fault for fault in scenario['faults'] if fault['id'] == parts[1])
            parts = parts[2:]
        elif parts[0] == 'detector':
            target, parts = detector, parts[1:]
        for key in parts[:-1]:
            target = target.setdefault(key, {})
            if not isinstance(target, dict):
                raise ValueError(f'Campaign axis traverses a non-object at {key}.')
        target[parts[-1]] = value
    return scenario, detector


def _axis_values(raw_axes, mode, detector_count, budget, rng):
    if not isinstance(raw_axes, list) or len(raw_axes) > 12 or any(not isinstance(axis, dict) for axis in raw_axes):
        raise ValueError('Provide up to 12 campaign axes.')
    axes = [_axis_path(axis.get('path')) for axis in raw_axes]
    if len(set(map(tuple, axes))) != len(axes):
        raise ValueError('Campaign axis paths must be unique.')
    if mode == 'grid':
        levels = [axis.get('values') for axis in raw_axes]
        if any(not isinstance(values, list) or not 1 <= len(values) <= MAX_CASES for values in levels):
            raise ValueError('Each grid axis needs a nonempty list of values.')
        if math.prod(map(len, levels)) * detector_count > MAX_CASES:
            raise ValueError(f'Campaigns support at most {MAX_CASES} detector cases.')
        if any(parts == ['faults'] and any(not isinstance(value, list) for value in values)
               for parts, values in zip(axes, levels)):
            raise ValueError('The faults axis needs complete fault arrays as values.')
        return axes, product(*levels)
    if not axes:
        raise ValueError('Search needs at least one bounded numeric axis.')
    bounds = [(axis.get('min'), axis.get('max')) for axis in raw_axes]
    for parts, (low, high) in zip(axes, bounds):
        if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in (low, high)) or low >= high:
            raise ValueError('Each search axis needs finite bounds with minimum below maximum.')
        if parts == ['faults'] or (parts[0] == 'faults' and parts[-1] in ('type', 'target', 'profile')):
            raise ValueError('Search axes must address numeric fields. Use a grid for event and profile choices.')
        if parts[-1] == 'seed':
            _seed(low, 'Minimum seed')
            _seed(high, 'Maximum seed')
    values = [tuple(rng.randint(low, high) if parts[-1] == 'seed' else rng.uniform(low, high)
                    for parts, (low, high) in zip(axes, bounds)) for _ in range(budget)]
    return axes, values


def _case(name, scenario, detector, phase, objective=None, coordinates=None):
    scenario = validate_scenario(scenario)
    detector = _detector(detector, set(scenario['measurement']['signals']))
    count = len(scenario['faults'])
    family = 'healthy' if count == 0 else 'single' if count == 1 else 'multiple'
    case = dict(name=name, scenario=scenario, detector=detector, phase=phase, family=family)
    if objective:
        if objective == 'suppression' and not 2 <= count <= MAX_SUPPRESSION_EVENTS:
            raise ValueError(f'Suppression search needs 2–{MAX_SUPPRESSION_EVENTS} events per case.')
        case['objective'] = objective
    if coordinates:
        case['coordinates'] = coordinates
    return case


def prepare_campaign(raw):
    if not isinstance(raw, dict):
        raise ValueError('Campaign configuration must be an object.')
    mode = raw.get('mode', 'grid')
    if mode not in ('grid', 'search', 'benchmark'):
        raise ValueError('Choose grid, search or benchmark campaign mode.')
    detectors = raw.get('detectors', BENCHMARK_DETECTORS if mode == 'benchmark' else [DEFAULT_DETECTOR])
    if not isinstance(detectors, list) or not 1 <= len(detectors) <= len(ALGORITHMS) or any(not isinstance(d, dict) for d in detectors):
        raise ValueError('Provide one or more valid detector configurations.')
    if mode == 'benchmark':
        scenarios = _benchmark()
        if len(scenarios) * len(detectors) > MAX_CASES:
            raise ValueError(f'The fixed benchmark supports up to {MAX_CASES // len(scenarios)} detector configurations.')
        return [_case(name, scenario, detector, 'evaluation') for name, scenario in scenarios for detector in detectors]

    base = raw.get('scenario')
    if not isinstance(base, dict):
        raise ValueError('Choose a base scenario for the campaign.')
    objective, budget = None, 0
    rng = Random(_seed(raw.get('seed', SEARCH_SEED), 'Campaign search seed'))
    if mode == 'search':
        if len(detectors) != 1:
            raise ValueError('Failure search uses exactly one fixed detector configuration.')
        objective = raw.get('objective', 'missed')
        if objective not in OBJECTIVES:
            raise ValueError('Choose an available failure search objective.')
        budget = raw.get('budget', 12)
        if isinstance(budget, bool) or not isinstance(budget, int) or not 1 <= budget <= MAX_SEARCH_CASES:
            raise ValueError(f'Search budget must be an integer in [1, {MAX_SEARCH_CASES}].')
        base = {**base, 'seed': rng.randrange(100000, 2147483648)}
    else:
        base = {'seed': DEVELOPMENT_SEED, **base}
    base = validate_scenario(base)
    paths, variants = _axis_values(raw.get('axes', []), mode, len(detectors), budget, rng)
    if mode == 'search' and any(parts[0] == 'detector' for parts in paths):
        raise ValueError('Failure search varies the scenario while the detector configuration stays fixed.')
    prefix = 'Search' if mode == 'search' else 'Grid'
    phase = 'search' if mode == 'search' else 'development'
    cases = []
    for ordinal, values in enumerate(variants, start=1):
        coordinates = dict(zip(('.'.join(parts) for parts in paths), values))
        for detector in detectors:
            scenario, detector = _vary(base, detector, paths, values)
            cases.append(_case(f'{prefix} {ordinal}', scenario, detector, phase, objective, coordinates))
    return cases
