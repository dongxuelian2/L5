"""Causal degradation forecasts and one-intervention maintenance economics."""
from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real

import numpy as np


MODEL_VERSION = '1.0.0'
CONFIDENCE = .90
POSTERIOR_DRAWS = 8192
MAX_PLOT_ROWS = 1600
_LOG_VARIANCE_RATIOS = np.arange(-12, 13, dtype=float)
_DRIFT_PRIOR_PRECISION = .01
_SCALE_PRIOR_SHAPE = .001
_SCALE_PRIOR_RATE = 1e-6


def _number(value, label):
    if not isinstance(value, Real) or isinstance(value, (bool, np.bool_)) or not math.isfinite(value):
        raise ValueError(f'{label} must be a finite number.')
    return float(value)


def _name(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{label} must be specified.')


@dataclass(frozen=True)
class Asset:
    id: str
    name: str
    signals: tuple[str, ...] = ()

    def __post_init__(self):
        _name(self.id, 'Asset ID')
        _name(self.name, 'Asset name')
        if isinstance(self.signals, str):
            raise ValueError('Asset signals must be a sequence of signal IDs.')
        signals = tuple(self.signals)
        for signal in signals:
            _name(signal, 'Asset signal')
        object.__setattr__(self, 'signals', signals)


@dataclass(frozen=True)
class Indicator:
    signal: str
    definition: str
    unit: str
    failure_threshold: float
    direction: str = 'increasing'
    operating_threshold: float | None = None

    def __post_init__(self):
        _name(self.signal, 'Indicator signal')
        _name(self.definition, 'Indicator definition')
        _name(self.unit, 'Indicator unit')
        _number(self.failure_threshold, 'Failure threshold')
        if self.direction not in ('increasing', 'decreasing'):
            raise ValueError('Choose an increasing or decreasing failure direction.')
        if self.operating_threshold is not None:
            operating = _number(self.operating_threshold, 'Operating threshold')
            if self.sign * operating >= self.sign * self.failure_threshold:
                raise ValueError('The operating threshold must be reached before the failure threshold.')

    @property
    def sign(self):
        return 1 if self.direction == 'increasing' else -1


@dataclass(frozen=True)
class Observation:
    time: float
    value: float | None
    load: float | None = None

    def __post_init__(self):
        object.__setattr__(self, 'time', _number(self.time, 'Observation time'))
        for key in ('value', 'load'):
            value = getattr(self, key)
            if value is None:
                continue
            if isinstance(value, Real) and math.isnan(value):
                object.__setattr__(self, key, None)
            else:
                object.__setattr__(self, key, _number(value, f'Observation {key}'))


@dataclass(frozen=True)
class MaintenanceEvent:
    time: float
    action: str = 'restore'

    def __post_init__(self):
        object.__setattr__(self, 'time', _number(self.time, 'Maintenance time'))
        if self.action not in ('restore', 'replace'):
            raise ValueError('Choose restoration or replacement for a maintenance event.')


@dataclass(frozen=True)
class ConditionHistory:
    """Measurements and follow-up metadata, independent of any acquisition source."""

    asset: Asset
    indicator: Indicator
    observations: tuple[Observation, ...]
    events: tuple[MaintenanceEvent, ...] = ()
    operating_periods: tuple[tuple[float, float], ...] = ()
    end_status: str = 'censored'
    failure_time: float | None = None
    observed_until: float | None = None

    def __post_init__(self):
        if self.asset.signals and self.indicator.signal not in self.asset.signals:
            raise ValueError('The indicator signal must be associated with the asset.')
        if self.end_status not in ('censored', 'failed'):
            raise ValueError('Choose a censored or failed history.')
        if self.failure_time is not None:
            _number(self.failure_time, 'Failure time')
            if self.end_status != 'failed':
                raise ValueError('An observed failure time requires a failed history.')
        observations = tuple(sorted(self.observations, key=lambda row: row.time))
        events = tuple(sorted(self.events, key=lambda row: row.time))
        periods = sorted((_number(lo, 'Operating period start'), _number(hi, 'Operating period end'))
                         for lo, hi in self.operating_periods)
        if any(lo >= hi for lo, hi in periods) or any(a[1] > b[0] for a, b in zip(periods, periods[1:])):
            raise ValueError('Operating periods must be non-overlapping intervals of positive duration.')
        if self.observed_until is not None:
            end = _number(self.observed_until, 'History end')
            if (observations and observations[-1].time > end) or (self.failure_time is not None and self.failure_time > end):
                raise ValueError('History end must include the recorded observations and failure.')
        object.__setattr__(self, 'observations', observations)
        object.__setattr__(self, 'events', events)
        object.__setattr__(self, 'operating_periods', tuple(periods))


_ASSUMPTIONS = {
    'elapsed_time': 'Time is elapsed time. Future load and operating regime are assumed comparable to the fitted period. Recorded load and operating periods provide context only.',
    'latest_maintenance': 'The fit starts at or after the most recent recorded restoration or replacement. Observations at the event time are treated as post-maintenance.',
    'latent_threshold': 'The limit applies to latent condition. Noisy observations can cross it without confirming failure. Right-censored follow-up records no observed failure.',
    'linear_model': 'A constant linear latent trend is fitted by least squares with independent Gaussian measurement errors. Forecast bands propagate intercept and slope uncertainty. Future process variation is zero.',
    'stochastic_model': 'Latent condition follows Brownian motion with constant drift and variance rate. Independent Gaussian measurement noise is estimated separately. The model integrates parameter uncertainty and samples continuous-time first passage. The fit uses measurement likelihood and recorded resets.',
    'one_event': 'The first failure or planned intervention ends the modeled risk through the horizon. Costs include the full duration of that event.',
    'retired_risk': 'Restoration and replacement have their configured cost and downtime. Both remove the modeled failure risk for the remainder of the horizon.',
    'no_discount': 'Costs are undiscounted. A strategy with no event by the planning horizon has zero event cost.',
    'discount': 'Costs are discounted continuously to the forecast cutoff. The discount rate applies across the whole planning horizon.',
    'failure_wins_ties': 'Failure at the scheduled intervention time incurs corrective cost. Failure at the planning horizon counts as a failure within it.',
    'schedule_grid': 'The comparison searches a regular 60-interval schedule grid and includes the selected schedule time.',
}


def _assumptions(keys):
    return dict(assumption_keys=list(keys), assumptions=[_ASSUMPTIONS[key] for key in keys])


def _history_points(rows, fitted=None):
    if len(rows) <= MAX_PLOT_ROWS:
        indexes = range(len(rows))
    else:
        selected = {0, len(rows) - 1}
        for group in np.array_split(np.arange(len(rows)), MAX_PLOT_ROWS // 4):
            selected.update((int(group[0]), int(group[-1])))
            valid = [int(i) for i in group if rows[i].value is not None]
            if valid:
                selected.update((min(valid, key=lambda i: rows[i].value), max(valid, key=lambda i: rows[i].value)))
        indexes = sorted(selected)
    return [dict(time=float(rows[i].time), value=rows[i].value, load=rows[i].load,
                 fitted=None if fitted is None or not np.isfinite(fitted[i]) else float(fitted[i])) for i in indexes]


def _linear_fit(times, values, at, plot_times, rng):
    design = np.column_stack((np.ones(len(times)), times))
    params, _, rank, _ = np.linalg.lstsq(design, values, rcond=None)
    if rank != 2:
        raise _Unidentifiable('The linear design has insufficient independent observation times.')
    residuals = values - design @ params
    dof = len(values) - 2
    noise = np.linalg.norm(residuals) / math.sqrt(dof)
    if noise <= 32 * np.finfo(float).eps * max(1., float(np.max(np.abs(values)))):
        noise = 0.
    covariance = np.linalg.inv(design.T @ design)
    standardized = rng.standard_normal((POSTERIOR_DRAWS, 2)) @ np.linalg.cholesky(covariance).T
    draws = params + noise * standardized * np.sqrt(dof / rng.chisquare(dof, POSTERIOR_DRAWS))[:, None]
    fitted = params[0] + params[1] * plot_times
    return draws[:, 0] + draws[:, 1] * at, draws[:, 1], np.zeros(POSTERIOR_DRAWS), fitted, noise, {}


class _Unidentifiable(Exception):
    pass


def _smooth_history(times, values, plot_times, drift, rate, noise):
    """Conditional Kalman smoothing at measured and missing timestamps."""
    fitted = np.full(len(plot_times), np.nan)
    timeline = np.unique(plot_times[plot_times >= times[0]])
    levels = np.empty(len(timeline))
    variances = np.empty(len(timeline))
    level, variance, observation = values[0], noise, 1
    for index, time in enumerate(timeline):
        if index:
            dt = time - timeline[index - 1]
            level += drift * dt
            variance += rate * dt
        while observation < len(times) and times[observation] == time:
            innovation_variance = variance + noise
            level += (variance / innovation_variance) * (values[observation] - level)
            variance *= noise / innovation_variance
            observation += 1
        levels[index], variances[index] = level, variance
    for index in range(len(timeline) - 2, -1, -1):
        dt = timeline[index + 1] - timeline[index]
        weight = variances[index] / (variances[index] + rate * dt)
        levels[index] += weight * (levels[index + 1] - levels[index] - drift * dt)
    valid = plot_times >= times[0]
    fitted[valid] = levels[np.searchsorted(timeline, plot_times[valid])]
    return fitted


def _stochastic_fit(times, values, at, plot_times, rng):
    """Integrate variance ratio on a grid and integrate drift and scale analytically."""
    if np.ptp(values) <= 32 * np.finfo(float).eps:
        raise _Unidentifiable('Constant measurements provide no identifiable stochastic degradation scale.')

    # On a standardized clock the latent variance rate and measurement variance
    # share an unknown scale. A flat prior on the initial level is conditioned
    # on the first reading. Each innovation is affine in the unknown drift.
    q = 1 / (1 + np.exp(-_LOG_VARIANCE_RATIOS))
    r = 1 - q
    level = np.zeros_like(q)
    coefficient = np.zeros_like(q)
    variance = r.copy()
    precision = np.full_like(q, _DRIFT_PRIOR_PRECISION)
    drift = np.zeros_like(q)
    residual_sum = np.zeros_like(q)
    log_innovation_det = np.zeros_like(q)

    for dt, value in zip(np.diff(times), values[1:]):
        coefficient += dt
        variance += q * dt
        innovation_variance = variance + r
        innovation = value - level
        updated_precision = precision + coefficient**2 / innovation_variance
        residual = innovation - coefficient * drift
        residual_sum += residual**2 * precision / (innovation_variance * updated_precision)
        drift += coefficient * residual / (innovation_variance * updated_precision)
        precision = updated_precision
        log_innovation_det += np.log(innovation_variance)
        gain = variance / innovation_variance
        level += gain * innovation
        coefficient *= r / innovation_variance
        variance *= r / innovation_variance

    shape = _SCALE_PRIOR_SHAPE + (len(values) - 1) / 2
    rate = _SCALE_PRIOR_RATE + residual_sum / 2
    log_weight = -.5 * (log_innovation_det + np.log(precision)) - shape * np.log(rate)
    weights = np.exp(log_weight - np.max(log_weight))
    weights /= weights.sum()
    indexes = rng.choice(len(q), size=POSTERIOR_DRAWS, p=weights)
    scale = rate[indexes] / rng.gamma(shape, size=POSTERIOR_DRAWS)
    drift_draws = drift[indexes] + rng.standard_normal(POSTERIOR_DRAWS) * np.sqrt(scale / precision[indexes])
    age = at - times[-1]
    latent = (level[indexes] + (coefficient[indexes] + age) * drift_draws
              + rng.standard_normal(POSTERIOR_DRAWS) * np.sqrt(scale * (variance[indexes] + q[indexes] * age)))
    process_variance = scale * q[indexes]
    # Historical fitted values show one conditional smooth at the most supported
    # variance ratio. The forecast integrates over all ratios instead.
    best = int(np.argmax(weights))
    fitted = _smooth_history(times, values, plot_times, drift[best], q[best], r[best])
    diagnostics = dict(variance_ratio_edge_probability=float(weights[0] + weights[-1]))
    return latent, drift_draws, process_variance, fitted, float(np.median(np.sqrt(scale * r[indexes]))), diagnostics


def _first_passage(gap, drift, rate, rng):
    """First passage of drifted Brownian motion to an upper absorbing limit."""
    hits = np.full(len(gap), np.inf)
    hits[gap <= 0] = 0.
    deterministic = (gap > 0) & (rate == 0) & (drift > 0)
    hits[deterministic] = gap[deterministic] / drift[deterministic]
    stochastic = np.flatnonzero((gap > 0) & (rate > 0))
    a, mu, q = gap[stochastic], drift[stochastic], rate[stochastic]
    # A negative drift yields an atom at infinity. Given a hit, the law is
    # inverse Gaussian with mean a/abs(mu) and shape a²/q. Zero drift is Levy.
    hit_probability = np.exp(2 * np.minimum(0., mu) * a / q)
    normal_sq = np.maximum(rng.standard_normal(len(a))**2, np.finfo(float).tiny)
    with np.errstate(over='ignore'):
        times = a**2 / (q * normal_sq)
    moving = mu != 0
    distance, speed, variation = a[moving], np.abs(mu[moving]), q[moving] * normal_sq[moving]
    twice_drift = 2 * distance * speed
    # Rationalized inverse-Gaussian sampler avoids subtracting close numbers.
    smaller = (2 * distance**2 / (variation + twice_drift
               + np.sqrt(variation * (variation + 2 * twice_drift))))
    inverse_mean = speed / distance
    reflect = rng.random(len(smaller)) > 1 / (1 + smaller * inverse_mean)
    with np.errstate(over='ignore', divide='ignore'):
        smaller[reflect] = 1 / (inverse_mean[reflect]**2 * smaller[reflect])
    times[moving] = smaller
    eventual = rng.random(len(a)) < hit_probability
    hits[stochastic[eventual]] = times[eventual]
    return hits


def _trajectory(latent, drift, rate, duration, offsets, origin, scale, sign, cutoff, rng):
    # A shared standardized normal draw reduces Monte Carlo variation across
    # marginal bands. It is not used as a simulated path for first passage.
    process_noise = np.sqrt(rate) * rng.standard_normal(POSTERIOR_DRAWS)
    result = []
    for offset in offsets:
        dt = offset / duration
        future = origin + sign * scale * (latent + drift * dt + process_noise * np.sqrt(dt))
        lower, center, upper = np.quantile(future, [.05, .5, .95])
        result.append(dict(time=float(cutoff + offset), offset=float(offset), median=float(center),
                           lower=float(lower), upper=float(upper)))
    return result


def _failure_summary(hits, horizon, horizons):
    hits.sort()

    def quantile(p):
        value = hits[math.ceil(p * len(hits)) - 1]
        return float(value) if value <= horizon else None

    # Keep a regular grid for planning and quantile knots to preserve steep
    # transitions even when the event times are small relative to the horizon.
    knots = set(float(value) for value in np.linspace(0., horizon, 201))
    knots.update(horizons)
    probabilities = np.arange(1, 201) / 200
    knots.update(value for p in probabilities if (value := quantile(p)) is not None)
    lower, median, upper = (quantile(p) for p in (.05, .5, .95))
    for point in tuple(knots):
        first, last = np.searchsorted(hits, point, side='left'), np.searchsorted(hits, point, side='right')
        if point > 0 and first < last:
            # Encode a jump using adjacent floats and retain F(t) at t exactly.
            knots.add(math.nextafter(point, 0.))

    def probability(offset):
        return float(np.searchsorted(hits, offset, side='right') / len(hits))

    return (dict(lower=lower, median=median, upper=upper, confidence=CONFIDENCE,
                 probability_not_reached_by_horizon=1 - probability(horizon),
                 probability_never_reached_under_model=float(np.mean(np.isinf(hits))),
                 probabilities=[dict(horizon=offset, probability=probability(offset)) for offset in horizons]),
            [dict(time=offset, probability=probability(offset)) for offset in sorted(knots)])


def forecast(history: ConditionHistory, *, method='stochastic', start=None, cutoff=None, horizon=100.,
             seed=35, probability_horizons=None):
    """Fit observations at or before cutoff and forecast first passage within horizon.

    All times and offsets share the caller's time unit. A null quantile is
    undefined within the finite forecast horizon. A known failure has RUL zero.
    """
    if method not in ('linear', 'stochastic'):
        raise ValueError('Choose a linear or stochastic prognostic model.')
    horizon = _number(horizon, 'Forecast horizon')
    if horizon <= 0:
        raise ValueError('Forecast horizon must be positive.')
    if not isinstance(seed, (int, np.integer)) or isinstance(seed, (bool, np.bool_)) or not 0 <= seed < 2**64:
        raise ValueError('Forecast seed must be a nonnegative integer smaller than 2^64.')
    horizons = sorted({_number(t, 'Probability horizon') for t in probability_horizons}) if probability_horizons is not None else [horizon / 4, horizon / 2, horizon]
    if any(not 0 <= t <= horizon for t in horizons):
        raise ValueError('Probability horizons must be within the forecast horizon.')

    end = history.observed_until
    if end is None and history.observations:
        end = history.observations[-1].time
    if history.observed_until is None and history.failure_time is not None:
        end = history.failure_time if end is None else max(end, history.failure_time)
    cutoff = end if cutoff is None else _number(cutoff, 'Forecast cutoff')
    start = (history.observations[0].time if history.observations else None) if start is None else _number(start, 'Training start')
    if start is not None and cutoff is not None and start > cutoff:
        raise ValueError('Training start must be at or before the forecast cutoff.')
    if cutoff is not None and history.observed_until is not None and cutoff > history.observed_until:
        raise ValueError('Forecast cutoff must be within the recorded follow-up.')
    requested_start = start
    maintenance = next((event for event in reversed(history.events) if cutoff is not None and event.time <= cutoff), None)
    if maintenance is not None:
        start = maintenance.time if start is None else max(start, maintenance.time)
    display_rows = [row for row in history.observations if cutoff is not None and row.time <= cutoff
                    and (requested_start is None or row.time >= requested_start)]
    pre_maintenance = sum(row.time < start for row in display_rows) if start is not None else 0
    rows = display_rows[pre_maintenance:]
    valid = [i for i, row in enumerate(rows) if row.value is not None]
    observed_times = np.array([rows[i].time for i in valid], dtype=float)
    distinct_times = len(np.unique(observed_times))
    indicator = history.indicator
    signed_limit = indicator.sign * indicator.failure_threshold
    loads = [row.load for row in rows if row.load is not None]
    periods = [[max(lo, start), min(hi, cutoff)] for lo, hi in history.operating_periods
               if start is not None and cutoff is not None and max(lo, start) < min(hi, cutoff)]
    last = rows[valid[-1]] if valid else None
    diagnostics = dict(n_observations=len(valid), n_missing=len(rows) - len(valid), n_distinct_times=distinct_times,
                       n_load_measurements=len(loads), load_range=[min(loads), max(loads)] if loads else None,
                       operating_periods=periods, requested_start=requested_start, fit_start=start,
                       n_excluded_pre_maintenance=pre_maintenance, last_measurement_time=last.time if last else None,
                       last_measurement=last.value if last else None,
                       observed_threshold_exceedances=sum(indicator.sign * rows[i].value >= signed_limit for i in valid),
                       latest_maintenance=dict(time=maintenance.time, action=maintenance.action) if maintenance else None)
    result = dict(method=method, model_version=MODEL_VERSION, cutoff=cutoff, horizon=horizon,
                  history=[], trajectory=[], distribution=[],
                  rul=dict(lower=None, median=None, upper=None, confidence=CONFIDENCE,
                           probability_not_reached_by_horizon=None, probability_never_reached_under_model=None,
                           probabilities=[dict(horizon=t, probability=None) for t in horizons]),
                  diagnostics=diagnostics,
                  **_assumptions(('elapsed_time', 'latest_maintenance', 'latent_threshold', f'{method}_model')))

    def unavailable(status, reason):
        diagnostics['reason'] = reason
        return dict(result, status=status, history=_history_points(display_rows))

    known_failure = history.failure_time if history.failure_time is not None else end
    if (history.end_status == 'failed' and cutoff is not None and known_failure is not None and known_failure <= cutoff
            and (maintenance is None or maintenance.time < known_failure)):
        rul, distribution = _failure_summary(np.zeros(1), horizon, horizons)
        diagnostics['observed_failure_time'] = float(known_failure)
        return dict(result, status='threshold_reached', history=_history_points(display_rows), rul=rul, distribution=distribution)

    minimum = 3 if method == 'linear' else 5
    if len(valid) < minimum:
        return unavailable('insufficient_data', f'{minimum} finite readings are required for this model.')
    if distinct_times < (2 if method == 'linear' else 3):
        return unavailable('not_identifiable', 'The fit has too few distinct measurement times.')

    try:
        with np.errstate(over='raise', invalid='raise', divide='raise', under='ignore'):
            span = float(observed_times[-1] - observed_times[0])
            times = (observed_times - observed_times[0]) / span
            plot_times = (np.array([row.time for row in rows]) - observed_times[0]) / span
            at = (cutoff - observed_times[0]) / span
            origin = rows[valid[0]].value
            values = indicator.sign * (np.array([rows[i].value for i in valid]) - origin)
            value_scale = float(np.max(np.abs(values))) or 1.
            standardized = values / value_scale
            rng = np.random.default_rng(int(seed))
            fit = _linear_fit if method == 'linear' else _stochastic_fit
            latent, drift, rate, fitted, noise, model_diagnostics = fit(times, standardized, at, plot_times, rng)
            gap = indicator.sign * (indicator.failure_threshold - origin) / value_scale - latent
            hits = _first_passage(gap, drift, rate, rng) * span
            offsets = np.linspace(0., horizon, 81)
            trajectory = _trajectory(latent, drift, rate, span, offsets, origin, value_scale, indicator.sign, cutoff, rng)
            rul, distribution = _failure_summary(hits, horizon, horizons)
            drift_units = indicator.sign * value_scale / span * drift
            drift_lower, drift_median, drift_upper = np.quantile(drift_units, [.05, .5, .95])
            fitted_error = float(np.sqrt(np.mean((standardized - fitted[valid])**2)) * value_scale)
            fitted = origin + indicator.sign * value_scale * fitted
            measurement_sd = float(noise * value_scale)
            process_variance_rate = float(np.median(rate) * value_scale / span * value_scale)
            if not all(math.isfinite(x) for x in (span, cutoff + horizon, fitted_error, measurement_sd, process_variance_rate)):
                raise FloatingPointError('Prognostics exceeded the representable range.')
            diagnostics.update(model_diagnostics, training_span=span, drift=float(drift_median),
                               drift_interval=[float(drift_lower), float(drift_upper)], drift_confidence=CONFIDENCE,
                               measurement_sd=measurement_sd, process_variance_rate=process_variance_rate,
                               residual_rmse=fitted_error, parameter_draws=POSTERIOR_DRAWS, seed=int(seed))
    except _Unidentifiable as error:
        return unavailable('not_identifiable', str(error))
    except (np.linalg.LinAlgError, FloatingPointError, OverflowError, ZeroDivisionError):
        return unavailable('numerical_failure', 'The fit exceeded numerical precision or could not be factored.')

    return dict(result, status='ok' if rul['median'] is not None else 'beyond_horizon',
                history=_history_points(display_rows, np.r_[np.full(pre_maintenance, np.nan), fitted]),
                trajectory=trajectory, rul=rul, distribution=distribution)


def failure_probability(forecast_result, time):
    """CDF at a horizon-relative offset using the exported distribution."""
    time = _number(time, 'Failure probability offset')
    distribution = forecast_result['distribution']
    if not distribution or not 0 <= time <= forecast_result['horizon']:
        return None
    return float(np.interp(time, [row['time'] for row in distribution], [row['probability'] for row in distribution]))


def plan_maintenance(forecast_result, *, preventive_cost, corrective_cost, downtime_cost, preventive_duration,
                     corrective_duration, failure_consequence, replacement_cost, replacement_duration,
                     scheduled_time=None, discount_rate=0., planning_horizon=None):
    """Compare expected present costs for one event over the forecast horizon."""
    parameters = (preventive_cost, corrective_cost, downtime_cost, preventive_duration, corrective_duration,
                  failure_consequence, replacement_cost, replacement_duration, discount_rate)
    if any(_number(value, 'Maintenance parameter') < 0 for value in parameters):
        raise ValueError('Maintenance parameters must be nonnegative.')
    forecast_horizon = forecast_result['horizon']
    horizon = forecast_horizon if planning_horizon is None else _number(planning_horizon, 'Planning horizon')
    if not 0 < horizon <= forecast_horizon:
        raise ValueError('Planning horizon must be positive and within the forecast horizon.')
    scheduled_time = horizon / 2 if scheduled_time is None else _number(scheduled_time, 'Scheduled time')
    if not 0 <= scheduled_time <= horizon:
        raise ValueError('Scheduled time must be within the planning horizon.')
    corrective_total = float(corrective_cost + downtime_cost * corrective_duration + failure_consequence)
    preventive_total = float(preventive_cost + downtime_cost * preventive_duration)
    replacement_total = float(replacement_cost + downtime_cost * replacement_duration)
    if not all(math.isfinite(cost) for cost in (corrective_total, preventive_total, replacement_total)):
        raise ValueError('Total maintenance costs must be finite.')
    costs = dict(corrective=corrective_total, preventive=preventive_total, replacement=replacement_total)
    result = dict(status='unavailable', recommended=None, options=[], curve=[], savings_vs_continue=None,
                  costs=costs, discount_rate=float(discount_rate), horizon=horizon, schedule_resolution=horizon / 60,
                  **_assumptions(('one_event', 'retired_risk', 'failure_wins_ties', 'schedule_grid',
                                  'discount' if discount_rate else 'no_discount')))
    distribution = forecast_result['distribution']
    if not distribution:
        return result
    if forecast_result['status'] == 'threshold_reached':
        corrective = dict(action='corrective', time=0., failure_probability=1., expected_cost=corrective_total,
                          expected_failure_cost=corrective_total, expected_intervention_cost=0.)
        return dict(result, status='threshold_reached', recommended=corrective, options=[corrective])

    grid = np.linspace(0., horizon, 61)
    distribution_knots = {row['time'] for row in distribution if row['time'] <= horizon}
    times = np.array(sorted(distribution_knots | {scheduled_time} | set(grid)))
    cdf = np.interp(times, [row['time'] for row in distribution], [row['probability'] for row in distribution])
    discounts = np.exp(-discount_rate * (times / horizon))
    if discount_rate:
        width = discount_rate * (np.diff(times) / horizon)
        discount_mean = np.ones_like(width)
        np.divide(-np.expm1(-width), width, out=discount_mean, where=width > 0)
        discounted_cdf = np.r_[cdf[0], cdf[0] + np.cumsum(np.diff(cdf) * discounts[:-1] * discount_mean)]
    else:
        discounted_cdf = cdf

    def option(action, offset, intervention_cost):
        index = np.searchsorted(times, horizon if offset is None else offset)
        risk = float(cdf[index])
        # Each term represents disjoint events. Multiply their probabilities
        # before summing the two mutually exclusive event costs.
        failure = min(risk, float(discounted_cdf[index])) * corrective_total
        intervention = float(discounts[index]) * (1 - risk) * intervention_cost
        return dict(action=action, time=offset, failure_probability=risk, expected_cost=failure + intervention,
                    expected_failure_cost=failure, expected_intervention_cost=intervention)

    options = [option('continue', None, 0.), option('preventive', 0., preventive_total),
               option('schedule', scheduled_time, preventive_total), option('replace', 0., replacement_total)]
    # CDF knots preserve sharp changes in the risk integral. Schedule choices
    # use an independent time grid so a CDF jump cannot induce a near-tie.
    visible_times = set(grid) | {scheduled_time}
    curve = [option('schedule', float(offset), preventive_total) for offset in sorted(visible_times)]
    recommended = min((*options, *curve), key=lambda candidate: candidate['expected_cost'])
    if recommended not in options:
        options.append(recommended)
    return dict(result, status='ok', options=options, curve=curve, recommended=recommended,
                savings_vs_continue=options[0]['expected_cost'] - recommended['expected_cost'])
