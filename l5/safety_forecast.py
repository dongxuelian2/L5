"""Causal engineering-limit forecasts for the coupled-tank model."""
from __future__ import annotations

import math
import random

import numpy as np

from .data_quality import cadence
from .models.base import finite
from .models.tanks import CoupledTankModel, DEFAULTS, FIELDS, SIGNALS, integrate
from .safety_constraints import evaluate_constraints, normalize_constraints
from .units import conversion


MODEL = CoupledTankModel()
UNITS = {signal['key']: signal['unit'] for signal in SIGNALS}
INITIAL_KEYS = ('level1', 'level2', 'pump', 'valve')
PARAMETER_KEYS = ('area1', 'area2', 'pumpRate', 'connection', 'outlet', 'outletValve',
                  'tankHeight', 'integrationStep')
BOUNDS = {field['key']: (field['min'], field['max']) for field in FIELDS}
RANGE_BOUNDS = {
    'level1': (-10, 10), 'level2': (-10, 10), 'pumpRateFraction': (-1, 1),
    'connectionFraction': (-1, 1), 'outletFraction': (-1, 1), 'pumpCommand': (-150, 150),
    'valveOpening': (-1, 1), 'outletValve': (-1, 1), 'leakCoefficient': (-.1, .1),
}


def fields(value, allowed, label):
    if not isinstance(value, dict) or value.keys() - set(allowed):
        raise ValueError(f'Unknown or invalid {label}.')
    return value


def number(value, low, high, label):
    if not finite(value) or not low <= value <= high:
        raise ValueError(f'{label} must be between {low} and {high}.')
    return float(value)


def integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{label} must be an integer between {low} and {high}.')
    return value


def forecast_options(options):
    fields(options, ('asOf', 'horizonSeconds', 'stepSeconds', 'maxObservationAgeSeconds',
                     'input', 'parameters', 'uncertainty'), 'forecast options')
    if 'asOf' in options and not finite(options['asOf']):
        raise ValueError('Forecast observation cutoff must be a finite time in seconds.')
    horizon = number(options.get('horizonSeconds', 60), .02, 3600, 'Forecast horizon')
    step = number(options.get('stepSeconds', .2), .02, 10, 'Forecast sampling step')
    if math.ceil(horizon / step) > 4000:
        raise ValueError('Use at most 4,000 forecast sampling steps per trajectory.')
    age = options.get('maxObservationAgeSeconds')
    if 'maxObservationAgeSeconds' in options:
        age = number(age, 0, 300, 'Maximum observation age')
    inputs = fields(options.get('input', {}), ('mode', 'pumpCommand', 'valveOpening', 'leakCoefficient'),
                    'future input assumptions')
    mode = inputs.get('mode', 'hold')
    overridden = inputs.keys() & {'pumpCommand', 'valveOpening'}
    if mode not in ('hold', 'override') or bool(overridden) != (mode == 'override'):
        raise ValueError('Hold the observed inputs or supply at least one fixed input override.')
    inputs = dict(mode=mode, leakCoefficient=number(inputs.get('leakCoefficient', 0), *BOUNDS['leakCoefficient'],
                                                    'Assumed leak coefficient'))
    for key, physical_key in (('pumpCommand', 'pumpControl'), ('valveOpening', 'valve')):
        if key in overridden:
            inputs[key] = number(options['input'][key], *BOUNDS[physical_key], key)
    parameters = {key: number(value, *BOUNDS[key], key) for key, value in
                  fields(options.get('parameters', {}), PARAMETER_KEYS, 'model parameter overrides').items()}
    raw_uncertainty = fields(options.get('uncertainty', {}), ('samples', 'seed', 'ranges'), 'uncertainty options')
    samples = integer(raw_uncertainty.get('samples', 0), 0, 128, 'Uncertainty sample count')
    seed = integer(raw_uncertainty.get('seed', 1), 0, 2147483647, 'Uncertainty seed')
    raw_ranges = fields(raw_uncertainty.get('ranges', {}), RANGE_BOUNDS, 'uncertainty ranges')
    ranges = {}
    for key, limits in RANGE_BOUNDS.items():
        if key not in raw_ranges:
            continue
        bounds = raw_ranges[key]
        if not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
            raise ValueError(f'{key} uncertainty needs two endpoints.')
        lower = number(bounds[0], *limits, f'{key} uncertainty lower endpoint')
        upper = number(bounds[1], *limits, f'{key} uncertainty upper endpoint')
        if lower > upper:
            raise ValueError(f'{key} uncertainty lower endpoint must not exceed the upper endpoint.')
        ranges[key] = [lower, upper]
    if samples and not ranges:
        raise ValueError('Set at least one uncertainty range before sampling trajectories.')
    return dict(horizonSeconds=horizon, stepSeconds=step, maxObservationAgeSeconds=age, input=inputs,
                parameters=parameters, uncertainty=dict(samples=samples, seed=seed, ranges=ranges))


def model_projection(columns):
    """Raw simulator values retain their native scales even if a label is edited."""
    projection = {}
    for i, column in enumerate(columns):
        key = column['name']
        if key not in UNITS:
            continue
        try:
            transform = conversion(column.get('unit', ''), UNITS[key])
        except ValueError:
            continue
        if transform['scale'] == 1 and transform['offset'] == 0:
            projection[key] = (i, column['id'])
    return projection


def checked_integrate(config):
    rows, physical = integrate(config)
    scale = max(1., max(row[key] for row in physical for key in ('volume', 'delivered', 'spilled')))
    if (any(not math.isfinite(row[key]) for row in rows for key in UNITS)
            or any(not math.isfinite(row['massResidual']) or abs(row['massResidual']) > 1e-8 * scale
                   for row in physical)):
        raise ArithmeticError('Tank trajectory failed the finite-value or mass-balance check.')
    return rows


def simulate_trajectory(as_of, snapshot, parameters, assumptions, perturbations):
    sample = snapshot['values']
    initial = {key: sample[key] + perturbations.get(key, 0.) for key in ('level1', 'level2')}
    pump = assumptions['input'].get('pumpCommand', sample['pump']) + perturbations.get('pumpCommand', 0.)
    valve = assumptions['input'].get('valveOpening', sample['valve']) + perturbations.get('valveOpening', 0.)
    leak = assumptions['input']['leakCoefficient'] + perturbations.get('leakCoefficient', 0.)
    effective = dict(parameters, outletValve=parameters['outletValve'] + perturbations.get('outletValve', 0.))
    for key in ('pumpRate', 'connection', 'outlet'):
        effective[key] *= 1 + perturbations.get(key + 'Fraction', 0.)
    domain = {**effective, 'initial1': initial['level1'], 'initial2': initial['level2'],
              'pumpControl': pump, 'valve': valve, 'leakCoefficient': leak}
    if any(not BOUNDS[key][0] <= value <= BOUNDS[key][1] for key, value in domain.items()):
        raise ValueError('Scenario leaves the supported range of the tank model.')
    # A nonzero leak here is a declared, constant disturbance. No scenario
    # schedule, severity, original initial condition, or hidden state enters.
    config = dict(DEFAULTS, **domain)
    config.update(fault='tank_leak' if leak else 'healthy', start=0., severity=1.,
                  fault_duration=None, noise=0., seed=0)
    age = as_of - snapshot['time']
    if age > 1e-9:
        warmup = checked_integrate(dict(config, duration=age, step=age,
                                        pumpControl=sample['pump'], valve=sample['valve']))
        config.update(initial1=warmup[-1]['level1'], initial2=warmup[-1]['level2'])
    rows = checked_integrate(dict(config, duration=assumptions['horizonSeconds'], step=assumptions['stepSeconds']))
    times = np.asarray([as_of + row['t'] for row in rows])
    if not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
        raise ArithmeticError('The forecast time grid cannot be represented at this cutoff.')
    values = {key: np.asarray([row[key] for row in rows]) for key in UNITS}
    inputs = dict(pumpCommand=pump, valveOpening=valve, leakCoefficient=leak, initialLevels=initial,
                  cutoffLevels={key: rows[0][key] for key in ('level1', 'level2')},
                  parameters=effective)
    return times, values, inputs


def interpolate_boundary(times, margins, left, right):
    a, b = margins[left], margins[right]
    if a is None or b is None or a == b or not min(a, b) <= 0 <= max(a, b):
        return None
    return times[left] + (times[right] - times[left]) * (-a / (b - a))


def refine_intervals(result):
    series, definition = result['series'], result['constraint']
    times, segments = series['times'], series['segmentIds']
    intervals = []
    for item in result['intervals']:
        if item['state'] != 'violation':
            continue
        start, end = item['start'], item['end']
        first, last = item['startIndex'], item['endIndex']
        side = item['boundary']
        margins = series[f'{side}Margins']
        if first and definition['dwellSeconds'] == 0 and segments[first - 1] == segments[first]:
            crossing = interpolate_boundary(times, margins, first - 1, first)
            if crossing is not None:
                start = crossing
        after = last + 1
        if after < len(times) and segments[after] == segments[last]:
            crossing = interpolate_boundary(times, series[f'{side}RecoveryMargins'], last, after)
            if crossing is not None:
                end = crossing
        intervals.append(dict(item, start=start, end=end, duration=end - start,
                              firstSampleTime=item['start'], lastSampleTime=item['end']))
    return intervals


def summarize_constraint(result, historical, as_of, *, include_series):
    constraint = result['constraint']
    intervals = refine_intervals(result)
    current = historical['current']
    already_violating = (current['time'] == as_of and current['state'] == 'violation'
                         and result['series']['states'][0] == 'unavailable')
    if already_violating and intervals and intervals[0]['confirmedAt'] == historical['policy']['confirmedAt']:
        # The first forward rate needs two forecast levels. An unchanged
        # carried confirmation links that interval to the measured rate.
        first_interval = intervals[0]
        first_interval.update(start=as_of, duration=first_interval['end'] - as_of)
    starts_with_violation = bool(intervals and intervals[0]['start'] == as_of and
                                 result['series']['states'][0] == 'violation')
    started_in_violation = already_violating or starts_with_violation
    first = as_of if started_in_violation else intervals[0]['start'] if intervals else None
    coverage = result['coverage']
    expected = coverage['totalSamples'] - (constraint['kind'] == 'rate')
    complete = coverage['evaluatedSamples'] == expected and not result['quality']['gaps']
    summary = dict(constraintId=constraint['id'], marginUnit=result['marginUnit'],
                   status='crossing' if first is not None else 'no-crossing' if complete else 'unavailable',
                   startedInViolation=started_in_violation, firstCrossingTime=first,
                   timeToViolation=first - as_of if first is not None else None,
                   minimumMargin=result['minimumMargin'], currentMargin=current['margin'],
                   currentState=current['state'], maximumExceedance=result['maximumExceedance'],
                   violationDuration=sum(item['duration'] for item in intervals) if first is not None or complete else None,
                   coverage=coverage, quality=result['quality'])
    if not complete:
        summary['reasonCode'] = 'incomplete-constraint-trajectory'
    if include_series:
        summary.update(intervals=intervals, series=result['series'], current=current)
    return summary


def unavailable_constraint(definition, reason_code, *, include_series):
    result = dict(constraintId=definition['id'], marginUnit=definition['unit'], status='unavailable',
                  reasonCode=reason_code, startedInViolation=False, firstCrossingTime=None,
                  timeToViolation=None, minimumMargin=None, currentMargin=None, currentState='unavailable',
                  maximumExceedance=None, violationDuration=None)
    if include_series:
        result.update(intervals=[], series=None, current=None)
    return result


def evaluate_trajectory(times, values, definitions, signals, projection, historical, as_of, step, *, include_series):
    projected = {identity: values[key] for key, (_, identity) in projection.items()}
    policies = {key: result['policy'] for key, result in historical.items()
                if result['quality']['gapThreshold'] is None or
                as_of - result['current']['time'] <= result['quality']['gapThreshold']}
    evaluated = evaluate_constraints(
        times, projected, signals, definitions, gap_threshold=step * 5,
        initial_policies=policies) if definitions else []
    return {item['constraint']['id']: summarize_constraint(
        item, historical[item['constraint']['id']], as_of, include_series=include_series) for item in evaluated}


def run_uncertainty(as_of, snapshot, parameters, assumptions, definitions, supported, signals, projection, historical):
    options = assumptions['uncertainty']
    ranges, count = options['ranges'], options['samples']
    if not ranges:
        return None
    rng = random.Random(options['seed'])

    def run(identity, deviations):
        inputs = None
        try:
            times, values, inputs = simulate_trajectory(as_of, snapshot, parameters, assumptions, deviations)
            summaries = evaluate_trajectory(times, values, supported, signals, projection, historical, as_of,
                                            assumptions['stepSeconds'], include_series=False)
        except ValueError as error:
            return dict(id=identity, perturbations=deviations, status='unavailable', reason=str(error),
                        reasonCode='scenario-outside-model-domain', inputs=inputs, constraints=[])
        except ArithmeticError as error:
            return dict(id=identity, perturbations=deviations, status='unreliable', reason=str(error),
                        reasonCode='numerical-check', inputs=inputs, constraints=[])
        constraints = [summaries.get(c['id']) or unavailable_constraint(c, 'signal-outside-model', include_series=False)
                       for c in definitions]
        return dict(id=identity, perturbations=deviations, status='available', inputs=inputs, constraints=constraints)

    scenarios = [run(i + 1, {key: rng.uniform(*bounds) for key, bounds in ranges.items()})
                 for i in range(count)]
    endpoints = [(key, run(f'{key}:lower', {key: lo}), run(f'{key}:upper', {key: hi}))
                 for key, (lo, hi) in ranges.items()]
    summaries = []
    for i, definition in enumerate(definitions):
        available = [case['constraints'][i] for case in scenarios if case['status'] == 'available'
                     and case['constraints'][i]['status'] != 'unavailable']
        crossings = [result['firstCrossingTime'] for result in available if result['firstCrossingTime'] is not None]
        margins = [result['minimumMargin'] for result in available if result['minimumMargin'] is not None]
        sensitivity = []
        for key, lower, upper in endpoints:
            a = lower['constraints'][i]['minimumMargin'] if lower['status'] == 'available' else None
            b = upper['constraints'][i]['minimumMargin'] if upper['status'] == 'available' else None
            lo, hi = ranges[key]
            sensitivity.append(dict(parameter=key, lowerValue=lo, upperValue=hi, lowerMargin=a, upperMargin=b,
                                    marginChange=b - a if a is not None and b is not None else None))
        summaries.append(dict(constraintId=definition['id'], evaluatedScenarios=len(available),
                              unavailableScenarios=count - len(available), crossingScenarios=len(crossings),
                              violationFraction=len(crossings) / len(available) if available else None,
                              earliestCrossingTime=min(crossings, default=None),
                              latestCrossingTime=max(crossings, default=None), worstMargin=min(margins, default=None),
                              sensitivity=sensitivity))
    return dict(**options, method='independent-uniform', sensitivityMethod='one-at-a-time-endpoints',
                interpretation='Empirical fraction among evaluated trajectories. No certified probability or bounds.',
                scenarios=scenarios, sensitivityScenarios=[case for _, lower, upper in endpoints for case in (lower, upper)],
                constraints=summaries)


def forecast_constraints(dataset, times, values, definitions, options, *, observed=None):
    """Forecast from a synchronized prefix measurement on the native Dataset clock."""
    assumptions = forecast_options(options)
    assumptions.update(timeBasis='dataset-native-seconds', warmup='hold-last-observed-inputs',
                       dwellBasis='carried-through-observed-prefix-then-sampled-confirmation',
                       crossingMethod='linear-margin-interpolation-within-adjacent-valid-samples')
    metadata = dataset['metadata']
    source = metadata.get('model', {})
    times = np.asarray(times, dtype=float)
    as_of = float(options['asOf']) if 'asOf' in options else float(times[-1]) if len(times) else None
    result = dict(status='unavailable', requestedAsOf=as_of, observedThrough=None, model=None, inputMeasurements=None,
                  assumptions=assumptions, trajectory=None, constraints=[], uncertainty=None)
    if source.get('id') != MODEL.id or metadata.get('transformation'):
        return dict(result, reasonCode='unsupported-model', reason='Choose a raw coupled-tank simulation Dataset.')
    if source.get('version') != MODEL.version:
        return dict(result, reasonCode='unsupported-model-version', reason='The saved tank model version is unavailable.')
    saved = source.get('config', {})
    parameters = {}
    for key in PARAMETER_KEYS:
        value = assumptions['parameters'].get(key, saved.get(key, DEFAULTS[key]))
        if not finite(value) or not BOUNDS[key][0] <= value <= BOUNDS[key][1]:
            return dict(result, reasonCode='invalid-model-parameters', reason='Saved tank model parameters are invalid.')
        parameters[key] = float(value)
    result['model'] = dict(id=MODEL.id, version=MODEL.version, parameters=parameters)
    columns = metadata['columns']
    projection = model_projection(columns)
    if any(key not in projection for key in INITIAL_KEYS):
        return dict(result, reasonCode='incompatible-measurement-unit',
                    reason='Required level and input measurements must retain their native model units.')
    end = int(np.searchsorted(times, as_of, side='right')) if as_of is not None else 0
    if not end:
        return dict(result, reasonCode='no-prior-observation', reason='No measurement exists at or before this cutoff.')
    prefix = times[:end]
    last = float(prefix[-1])
    result['observedThrough'] = last
    if end > 1 and prefix[-2] == last:
        return dict(result, reasonCode='ambiguous-observation', reason='The latest timestamp has duplicate observations.')
    values = np.asarray(values)
    if observed is not None:
        observed = np.asarray(observed, dtype=bool)
    snapshot = dict(time=last, values={}, units={}, signalIds={})
    for key, (i, identity) in projection.items():
        value = values[end - 1, i]
        snapshot['values'][key] = float(value) if np.isfinite(value) and (observed is None or observed[end - 1, i]) else None
        snapshot['units'][key] = UNITS[key]
        snapshot['signalIds'][key] = identity
    result['inputMeasurements'] = snapshot
    cadence_info = cadence(prefix)
    max_age = assumptions['maxObservationAgeSeconds']
    if max_age is None:
        max_age = min(300., 2 * (cadence_info['typicalInterval'] or 0.))
        assumptions['maxObservationAgeSeconds'] = max_age
    age = as_of - last
    if age > max_age + 1e-9:
        return dict(result, reasonCode='stale-observation', reason='The latest observation is older than the permitted age.')
    if any(snapshot['values'][key] is None for key in INITIAL_KEYS):
        return dict(result, reasonCode='missing-observation', reason='A measured level or control input is unavailable at the latest timestamp.')
    for key, physical_key in zip(INITIAL_KEYS, ('initial1', 'initial2', 'pumpControl', 'valve')):
        if not BOUNDS[physical_key][0] <= snapshot['values'][key] <= BOUNDS[physical_key][1]:
            return dict(result, reasonCode='invalid-observation',
                        reason='A measured level or control input falls outside the tank model domain.')
    measured_inlet = snapshot['values'].get('inlet')
    modeled_inlet = parameters['pumpRate'] * snapshot['values']['pump'] / 100
    assumptions['observedInputComparison'] = dict(
        measuredInlet=measured_inlet, modeledInlet=modeled_inlet, unit=UNITS['inlet'],
        measuredMinusModeledInlet=measured_inlet - modeled_inlet if measured_inlet is not None else None)

    step, horizon = assumptions['stepSeconds'], assumptions['horizonSeconds']
    count = 1 + assumptions['uncertainty']['samples'] + 2 * len(assumptions['uncertainty']['ranges'])
    # Each output time is an integration endpoint, so partial substeps recur.
    integration_steps = math.ceil(horizon / step) * math.ceil(step / parameters['integrationStep'])
    integration_steps += math.ceil(age / parameters['integrationStep'])
    if integration_steps > 500000 or integration_steps * count > 1000000:
        raise ValueError('Shorten the forecast or reduce the uncertainty sample count to fit the integration budget.')

    signals = {column['id']: column for column in columns}
    definitions = normalize_constraints(definitions, signals)
    projected_ids = {identity for _, identity in projection.values()}
    supported = [c for c in definitions if all(term['signalId'] in projected_ids for term in c['terms'])]
    if count * (math.ceil(horizon / step) + 1) * len(supported) > 2000000:
        raise ValueError('Shorten the forecast, increase the output step, or reduce the uncertainty sample count.')
    historical = {}
    if supported:
        used = {term['signalId'] for c in supported for term in c['terms']}
        indexes = {identity: i for i, identity in projection.values() if identity in used}
        prior = evaluate_constraints(prefix, {key: values[:end, i] for key, i in indexes.items()}, signals, supported,
                                     observed={key: observed[:end, i] for key, i in indexes.items()} if observed is not None else None,
                                     gap_threshold=cadence_info['gapThreshold'], include_series=False)
        historical = {item['constraint']['id']: item for item in prior}
    try:
        forecast_times, forecast_values, inputs = simulate_trajectory(as_of, snapshot, parameters, assumptions, {})
        summarized = evaluate_trajectory(forecast_times, forecast_values, supported, signals, projection, historical, as_of,
                                         step, include_series=True)
    except ValueError as error:
        return dict(result, reasonCode='scenario-outside-model-domain', reason=str(error))
    except ArithmeticError as error:
        return dict(result, status='unreliable', reasonCode='numerical-check', reason=str(error))
    assumptions['effectiveInputs'] = inputs
    constraints = [summarized.get(c['id']) or unavailable_constraint(c, 'signal-outside-model', include_series=True)
                   for c in definitions]
    trajectory = dict(times=forecast_times.tolist(), values={key: column.tolist() for key, column in forecast_values.items()},
                      units=UNITS)
    uncertainty = run_uncertainty(as_of, snapshot, parameters, assumptions, definitions, supported, signals, projection, historical)
    return dict(result, status='available', trajectory=trajectory, constraints=constraints, uncertainty=uncertainty)
