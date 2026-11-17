"""Evaluate engineering constraints on one aligned grid of original observations."""
from __future__ import annotations

import math
from numbers import Real

import numpy as np

from .data_quality import cadence
from .units import canonical, conversion, difference_unit, dimension


_FIELDS = {'id', 'name', 'kind', 'unit', 'terms', 'lower', 'upper', 'warningLower', 'warningUpper',
           'dwellSeconds', 'hysteresis', 'maxGapSeconds', 'absolute', 'equipment'}
_UNAVAILABLE, _NORMAL, _WARNING, _VIOLATION = range(4)
_STATES = ('unavailable', 'normal', 'warning', 'violation')
_SIDES = {0: None, -1: 'lower', 1: 'upper'}


def _number(value, label):
    try:
        if not isinstance(value, bool) and isinstance(value, Real) and math.isfinite(float(value)):
            return float(value)
    except OverflowError:
        pass
    raise ValueError(f'{label} must be a finite number.')


def _text(value, label, *, optional=False):
    if not isinstance(value, str) or len(value) > 160 or not (optional or value.strip()):
        raise ValueError(f'{label} must be text of at most 160 characters.')
    return value.strip()


def _term_conversion(definition, signal, *, temperature_difference=False):
    source = canonical(signal.get('unit', ''))
    target = definition['unit']
    if definition['kind'] == 'rate':
        source = f'{difference_unit(source)}/s'
        if target.endswith('/s'):
            target = f'{canonical(target[:-2])}/s'
    if temperature_difference:
        # Subtract on a common absolute scale before converting the difference.
        return conversion(source, 'K')
    return conversion(source, target)


def _temperature_difference(definition, signals):
    return definition['kind'] == 'relationship' and any(
        dimension(signals[term['signalId']].get('unit', '')) == 'temperature' for term in definition['terms'])


def _recovery_bounds(definition):
    hysteresis = definition['hysteresis']
    return {key: None if definition[key] is None else definition[key] + direction * hysteresis
            for key, direction in (('lower', 1), ('upper', -1), ('warningLower', 1), ('warningUpper', -1))}


def normalize_constraints(definitions, signals):
    """Validate stable signal identities, comparable units and policy parameters."""
    if not isinstance(definitions, list) or not 1 <= len(definitions) <= 32:
        raise ValueError('Define between 1 and 32 operating constraints.')
    normalized, identities = [], set()
    for definition in definitions:
        if not isinstance(definition, dict) or definition.keys() - _FIELDS:
            raise ValueError('Invalid constraint fields.')
        identity = _text(definition.get('id'), 'Constraint ID')
        if identity in identities:
            raise ValueError('Constraint IDs must be unique.')
        identities.add(identity)
        name = _text(definition.get('name'), 'Constraint name')
        kind = definition.get('kind', 'value')
        if kind not in ('value', 'rate', 'relationship'):
            raise ValueError('Choose a value, rate or relationship constraint.')
        entered_unit = _text(definition.get('unit'), 'Constraint unit', optional=True)
        unit = canonical(entered_unit)
        if kind == 'rate' and unit.endswith('/s'):
            unit = f'{canonical(unit[:-2])}/s'
        terms = definition.get('terms')
        if not isinstance(terms, list) or (kind == 'relationship' and not 2 <= len(terms) <= 8) or (kind != 'relationship' and len(terms) != 1):
            raise ValueError('Use one signal for a value or rate, or two to eight signals for a relationship.')
        used, normalized_terms = set(), []
        for term in terms:
            if not isinstance(term, dict) or term.keys() - {'signalId', 'coefficient'}:
                raise ValueError('Invalid constraint term.')
            signal_id = term.get('signalId')
            if not isinstance(signal_id, str) or signal_id not in signals or signal_id in used:
                raise ValueError('Each constraint term needs a distinct signal ID from the selected Dataset.')
            source_unit = _text(signals[signal_id].get('unit', ''), 'Signal unit', optional=True)
            if not source_unit:
                allowed = ('', '1') if kind == 'value' else ('1/s',) if kind == 'rate' else ()
                if entered_unit not in allowed:
                    raise ValueError('Assign an engineering unit in the Signal Catalog before converting or combining unlabeled signals.')
            used.add(signal_id)
            coefficient = _number(term.get('coefficient', 1), 'Signal coefficient')
            if not coefficient or (kind != 'relationship' and coefficient != 1):
                raise ValueError('Use nonzero coefficients in relationships and a coefficient of one elsewhere.')
            normalized_terms.append(dict(signalId=signal_id, coefficient=coefficient))

        bounds = {key: None if definition.get(key) is None else _number(definition[key], key)
                  for key in ('lower', 'upper', 'warningLower', 'warningUpper')}
        lower, upper, warning_lower, warning_upper = bounds.values()
        if lower is None and upper is None:
            raise ValueError('Set a lower or upper critical boundary.')
        if lower is not None and upper is not None and lower >= upper:
            raise ValueError('Lower critical boundary must be below the upper boundary.')
        if warning_lower is not None and (lower is None or warning_lower <= lower or (upper is not None and warning_lower >= upper)):
            raise ValueError('Lower warning boundary must be above its critical boundary and within the operating range.')
        if warning_upper is not None and (upper is None or warning_upper >= upper or (lower is not None and warning_upper <= lower)):
            raise ValueError('Upper warning boundary must be below its critical boundary and within the operating range.')
        if warning_lower is not None and warning_upper is not None and warning_lower >= warning_upper:
            raise ValueError('Lower warning boundary must be below the upper warning boundary.')

        dwell = _number(definition.get('dwellSeconds', 0), 'Dwell time')
        hysteresis = _number(definition.get('hysteresis', 0), 'Hysteresis')
        gap = definition.get('maxGapSeconds')
        gap = None if gap is None else _number(gap, 'Maximum observation gap')
        absolute = definition.get('absolute', False)
        if dwell < 0 or hysteresis < 0 or (gap is not None and gap <= 0):
            raise ValueError('Dwell and hysteresis must be nonnegative. Maximum observation gap must be positive.')
        if not isinstance(absolute, bool) or (absolute and kind != 'rate'):
            raise ValueError('Absolute value is available only for rate constraints.')
        normalized_item = dict(id=identity, name=name, kind=kind, unit=unit, terms=normalized_terms, **bounds,
                               dwellSeconds=dwell, hysteresis=hysteresis, maxGapSeconds=gap, absolute=absolute,
                               equipment=_text(definition.get('equipment', ''), 'Equipment', optional=True))
        recovery = _recovery_bounds(normalized_item)
        if any(value is not None and not math.isfinite(value) for value in recovery.values()):
            raise ValueError('Hysteresis recovery boundaries must be finite.')
        recovery_lower = recovery['warningLower'] if warning_lower is not None else recovery['lower']
        recovery_upper = recovery['warningUpper'] if warning_upper is not None else recovery['upper']
        if recovery_lower is not None and recovery_upper is not None and recovery_lower > recovery_upper:
            raise ValueError('Hysteresis leaves no common recovery range between the lower and upper boundaries.')
        temperature = _temperature_difference(normalized_item, signals)
        if temperature and (len(normalized_terms) != 2 or {t['coefficient'] for t in normalized_terms} != {-1, 1} or
                            any(dimension(signals[t['signalId']].get('unit', '')) != 'temperature' for t in normalized_terms) or
                            dimension(unit) != 'temperature-difference'):
            raise ValueError('An absolute-temperature relationship must subtract two temperatures and use a temperature-difference unit.')
        for term in normalized_terms:
            _term_conversion(normalized_item, signals[term['signalId']], temperature_difference=temperature)
        normalized.append(normalized_item)
    return normalized


def _nullable(value):
    return float(value) if np.isfinite(value) else None


def _margins(values, tolerance, lower, upper):
    lower_margin = values - lower if lower is not None else np.full(len(values), np.nan)
    upper_margin = upper - values if upper is not None else np.full(len(values), np.nan)
    for margin in (lower_margin, upper_margin):
        margin[np.isfinite(margin) & (np.abs(margin) <= tolerance)] = 0.
    return lower_margin, upper_margin


def _calculate(definition, source_signals, columns, times, connected, observed):
    ids = [t['signalId'] for t in definition['terms']]
    measured = np.logical_and.reduce([np.isfinite(columns[i]) for i in ids])
    usable = measured & np.logical_and.reduce([observed[i] for i in ids])
    tolerance = np.zeros(len(times))
    rate_unavailable = np.zeros(len(times), dtype=bool)
    temperature = _temperature_difference(definition, source_signals)
    with np.errstate(over='ignore', invalid='ignore', divide='ignore', under='ignore'):
        if definition['kind'] == 'rate':
            relation = _term_conversion(definition, source_signals[ids[0]])
            values = np.full(len(times), np.nan)
            take = np.flatnonzero(connected[1:] & usable[:-1] & usable[1:]) + 1
            values[take] = ((columns[ids[0]][take] - columns[ids[0]][take - 1]) /
                            (times[take] - times[take - 1])) * relation['scale']
            if definition['absolute']:
                np.abs(values, out=values)
            rate_unavailable = usable.copy()
            rate_unavailable[take] = False
        else:
            values = np.zeros(len(times))
            for term in definition['terms']:
                identity, coefficient = term['signalId'], term['coefficient']
                relation = _term_conversion(definition, source_signals[identity], temperature_difference=temperature)
                scaled = columns[identity] * relation['scale']
                converted = (scaled + relation['offset']) * coefficient
                values += converted
                if definition['kind'] == 'relationship' or relation['scale'] != 1 or relation['offset'] != 0:
                    # Allow roundoff from unit conversions and arithmetic near the boundary.
                    tolerance += (np.abs(scaled) + abs(relation['offset'])) * abs(coefficient) * (8 * np.finfo(float).eps)
            if temperature:
                scale = conversion('ΔK', definition['unit'])['scale']
                values *= scale
                tolerance *= scale
        lower, upper = _margins(values, tolerance, definition['lower'], definition['upper'])
        warning_lower, warning_upper = _margins(values, tolerance, definition['warningLower'], definition['warningUpper'])
        margins = np.fmin(lower, upper)
    valid = usable & ~rate_unavailable & np.isfinite(values) & np.isfinite(tolerance)
    for key, margin in zip(('lower', 'upper', 'warningLower', 'warningUpper'), (lower, upper, warning_lower, warning_upper)):
        if definition[key] is not None:
            valid &= np.isfinite(margin)
    for vector in (values, lower, upper, warning_lower, warning_upper, margins):
        vector[~valid] = np.nan
    quality = dict(missingSamples=int((~measured).sum()), unobservedSamples=int((measured & ~usable).sum()),
                   rateUnavailableSamples=int(rate_unavailable.sum()),
                   numericalUnavailableSamples=int((usable & ~rate_unavailable & ~valid).sum()))
    return values, lower, upper, warning_lower, warning_upper, margins, tolerance, valid, quality


def _sample_states(valid, lower, upper, warning_lower, warning_upper):
    critical_side = np.where(lower < 0, -1, np.where(upper < 0, 1, 0))
    warning_side = np.where(warning_lower <= 0, -1, np.where(warning_upper <= 0, 1, 0))
    raw = np.where(valid, np.where(critical_side, _VIOLATION, np.where(warning_side, _WARNING, _NORMAL)), _UNAVAILABLE)
    return raw, critical_side, warning_side


def _elapsed_at_least(now, since, dwell):
    elapsed = now - since
    return elapsed >= dwell or math.isclose(elapsed, dwell, rel_tol=1e-14,
                                            abs_tol=2 * max(math.ulp(now), math.ulp(since)))


def _long_gap(left, right, threshold):
    if threshold is None:
        return np.zeros_like(right, dtype=bool)
    # Decimal sample clocks introduce a small subtraction error at exact policy equality.
    tolerance = 2 * np.finfo(float).eps * np.maximum(threshold, np.maximum(np.abs(left), np.abs(right)))
    return right - left - threshold > tolerance


def _apply_policy(definition, times, connected, valid, raw, critical_side, warning_side, values, tolerance,
                  initial, threshold, rate_only_start):
    dwell = definition['dwellSeconds']
    recovery = _recovery_bounds(definition)
    # Compare with the recovery value to avoid cancellation in small differences
    # of large process values, and preserve conversion roundoff tolerance.
    with np.errstate(over='ignore', invalid='ignore'):
        critical_lower, critical_upper = _margins(values, tolerance, recovery['lower'], recovery['upper'])
        warning_lower, warning_upper = _margins(values, tolerance, recovery['warningLower'], recovery['warningUpper'])
    states, sides = np.zeros(len(times), dtype=np.int8), np.zeros(len(times), dtype=np.int8)
    confirmations, candidates = np.full(len(times), np.nan), np.full(len(times), np.nan)
    state, side, candidate_side = _UNAVAILABLE, 0, 0
    confirmed, candidate, last_time = np.nan, np.nan, None
    if initial and initial['state'] != 'unavailable' and initial['lastTime'] is not None:
        elapsed = times[0] - initial['lastTime']
        if elapsed >= 0 and not _long_gap(initial['lastTime'], times[0], threshold):
            state = _STATES.index(initial['state'])
            side, candidate_side = initial['activeSide'], initial['candidateSide']
            confirmed = np.nan if initial['confirmedAt'] is None else initial['confirmedAt']
            candidate = np.nan if initial['candidateStart'] is None else initial['candidateStart']
            last_time = initial['lastTime']
    for i, time in enumerate(times):
        if i == 0 and rate_only_start and last_time == time:
            # A rate at the forecast origin still needs a pair of predicted observations.
            # Preserve causal carry-in policy until the first such pair is available.
            continue
        if (i > 0 and not connected[i]) or not valid[i]:
            state, side, candidate_side = _UNAVAILABLE, 0, 0
            confirmed, candidate, last_time = np.nan, np.nan, None
        if not valid[i]:
            continue
        last_time = float(time)
        critical, warning = critical_side[i], warning_side[i]
        same_critical_margin = critical_lower[i] if side == -1 else critical_upper[i]
        same_warning_margin = warning_lower[i] if side == -1 else warning_upper[i]
        if state == _VIOLATION and critical in (0, side) and same_critical_margin < 0:
            pass
        elif raw[i] == _VIOLATION:
            if candidate_side != critical or state == _VIOLATION:
                candidate, candidate_side = float(time), critical
            if _elapsed_at_least(float(time), candidate, dwell):
                state, side, confirmed = _VIOLATION, critical, float(time)
            else:
                if state != _WARNING or side != critical:
                    confirmed = float(time)
                state, side = _WARNING, critical
        else:
            candidate, candidate_side = np.nan, 0
            if warning:
                if state != _WARNING or side != warning:
                    confirmed = float(time)
                state, side = _WARNING, warning
            elif state != _WARNING or not same_warning_margin < 0:
                state, side, confirmed = _NORMAL, 0, np.nan
        states[i], sides[i] = state, side
        confirmations[i], candidates[i] = confirmed, candidate
    policy = dict(state=_STATES[state], lastTime=last_time, activeSide=int(side), confirmedAt=_nullable(confirmed),
                  candidateStart=_nullable(candidate), candidateSide=int(candidate_side))
    return states, sides, confirmations, candidates, policy, critical_lower, critical_upper


def _intervals(times, states, sides, connected, values, margins, *, selected, confirmations=None, candidates=None):
    starts = np.flatnonzero(~connected | np.r_[True, states[1:] != states[:-1]] |
                            np.r_[True, sides[1:] != sides[:-1]])
    intervals = []
    for a, b in zip(starts, np.r_[starts[1:] - 1, len(times) - 1]):
        if states[a] not in selected:
            continue
        minimum, peak = None, a
        if states[a] != _UNAVAILABLE:
            peak = int(a + np.argmin(margins[a:b + 1]))
            minimum = float(margins[peak])
        start, end = float(times[a]), float(times[b])
        intervals.append(dict(state=_STATES[states[a]], start=start, end=end, duration=end - start,
                              maximumExceedance=max(0., -minimum) if minimum is not None else None,
                              samples=int(b - a + 1), confirmedAt=start if confirmations is None else _nullable(confirmations[a]),
                              peakTime=float(times[peak]) if minimum is not None else None, peakValue=_nullable(values[peak]),
                              minimumMargin=minimum, startIndex=int(a), endIndex=int(b), boundary=_SIDES[int(sides[a])],
                              candidateStart=start if candidates is None else _nullable(candidates[a])))
    return intervals


def _evaluate_one(times, steps, duplicates, values, signals, observed, definition, gap_threshold, initial, include_series):
    ids = [term['signalId'] for term in definition['terms']]
    source_units = {identity: signals[identity].get('unit', '') for identity in ids}
    threshold = definition['maxGapSeconds'] or gap_threshold
    long_gap = _long_gap(times[:-1], times[1:], threshold)
    gaps = np.flatnonzero(long_gap)
    connected = np.r_[False, (steps > 0) & ~duplicates[:-1] & ~duplicates[1:] & ~long_gap]
    computed, lower, upper, warning_lower, warning_upper, margins, tolerance, valid, quality = _calculate(
        definition, signals, values, times, connected, observed)
    raw, critical_side, warning_side = _sample_states(valid, lower, upper, warning_lower, warning_upper)
    rate_only_start = (definition['kind'] == 'rate' and not duplicates[0] and
                       all(observed[identity][0] and np.isfinite(values[identity][0]) for identity in ids))
    states, sides, confirmations, candidates, policy, recovery_lower, recovery_upper = _apply_policy(
        definition, times, connected, valid, raw, critical_side, warning_side, computed, tolerance,
        initial, threshold, rate_only_start)
    intervals = _intervals(times, states, sides, connected, computed, margins,
                           selected=(_WARNING, _VIOLATION, _UNAVAILABLE), confirmations=confirmations, candidates=candidates)
    raw_intervals = _intervals(times, raw, critical_side, connected, computed, margins, selected=(_VIOLATION,))
    covered = float(steps[connected[1:] & valid[:-1] & valid[1:]].sum())
    duration = float(times[-1] - times[0])
    count = int(valid.sum())
    minimum = float(margins[valid].min()) if count else None
    result = dict(constraint=definition, signalIds=ids, sourceUnits=source_units, marginUnit=difference_unit(definition['unit']),
                  current=dict(time=float(times[-1]), value=_nullable(computed[-1]), margin=_nullable(margins[-1]),
                               lowerMargin=_nullable(lower[-1]), upperMargin=_nullable(upper[-1]),
                               state=_STATES[states[-1]], rawState=_STATES[raw[-1]], duplicateTimestamp=bool(duplicates[-1]),
                               measurements={identity: _nullable(values[identity][-1]) for identity in ids},
                               measurementObserved={identity: bool(observed[identity][-1]) for identity in ids}),
                  quality=dict(gapThreshold=threshold, duplicateCount=int((steps == 0).sum()),
                               gaps=[dict(start=float(times[i]), end=float(times[i + 1]), duration=float(steps[i])) for i in gaps],
                               **quality),
                  coverage=dict(totalSamples=len(times), evaluatedSamples=count, sampleFraction=count / len(times),
                                observedDuration=covered, durationFraction=covered / duration if duration else None),
                  intervals=intervals, rawViolationIntervals=raw_intervals, policy=policy, minimumMargin=minimum,
                  maximumExceedance=max(0., -minimum) if minimum is not None else None,
                  violationDuration=sum(span['duration'] for span in intervals if span['state'] == 'violation'),
                  rawViolationDuration=sum(span['duration'] for span in raw_intervals))
    if include_series:
        breaks = ~connected | ~valid | np.r_[False, ~valid[:-1]]
        result['series'] = dict(times=times.tolist(), values=[_nullable(v) for v in computed],
                                measurements={identity: [_nullable(v) for v in values[identity]] for identity in ids},
                                measurementObserved={identity: observed[identity].tolist() for identity in ids},
                                margins=[_nullable(v) for v in margins], lowerMargins=[_nullable(v) for v in lower],
                                upperMargins=[_nullable(v) for v in upper],
                                lowerRecoveryMargins=[_nullable(v) for v in recovery_lower],
                                upperRecoveryMargins=[_nullable(v) for v in recovery_upper], states=[_STATES[s] for s in states],
                                rawStates=[_STATES[s] for s in raw], segmentIds=np.cumsum(breaks).tolist())
    return result


def evaluate_constraints(times, values, signals, definitions, *, observed=None, gap_threshold=None,
                         include_series=True, initial_policies=None):
    """Evaluate full-resolution aligned rows, without interpolation or gap bridging.

    Critical equality is permitted. A dwell confirms at an observed sample, and an
    interval spans the first and last samples providing evidence for its state.
    Duplicate rows still provide individual value evidence but cannot support a
    rate, elapsed dwell or duration across the ambiguous timestamp.
    """
    definitions = normalize_constraints(definitions, signals)
    times = np.asarray(times, dtype=float)
    if times.ndim != 1 or not len(times) or not np.isfinite(times).all():
        raise ValueError('Safety evaluation requires a nonempty grid of finite timestamps in seconds.')
    with np.errstate(over='ignore'):
        steps = np.diff(times)
        span = times[-1] - times[0]
    if np.any(steps < 0) or not np.isfinite(span):
        raise ValueError('Safety evaluation timestamps must be sorted with finite elapsed time.')
    duplicate = np.r_[False, steps == 0] | np.r_[steps == 0, False]
    if gap_threshold is None:
        default_gap = cadence(times)['gapThreshold']
        gap_threshold = default_gap if default_gap is not None and math.isfinite(default_gap) else None
    else:
        gap_threshold = _number(gap_threshold, 'Maximum observation gap')
        if gap_threshold <= 0:
            raise ValueError('Maximum observation gap must be positive.')
    inputs, masks = {}, {}
    identities = dict.fromkeys(term['signalId'] for definition in definitions for term in definition['terms'])
    for identity in identities:
        if identity not in values:
            raise ValueError('Every selected signal requires aligned sample values.')
        inputs[identity] = np.asarray(values[identity], dtype=float)
        if inputs[identity].shape != times.shape:
            raise ValueError('Selected signals must share a single aligned time grid.')
        mask = None if observed is None else observed.get(identity)
        masks[identity] = (np.ones(len(times), dtype=bool) if mask is None else np.asarray(mask, dtype=bool))
        if masks[identity].shape != times.shape:
            raise ValueError('Observation masks must align with their signal values.')
        masks[identity] = masks[identity] & np.isfinite(inputs[identity])
    policies = initial_policies or {}
    return [_evaluate_one(times, steps, duplicate, inputs, signals, masks, definition, gap_threshold,
                          policies.get(definition['id']), include_series) for definition in definitions]
