"""Coupled-tank pump wear simulation and chronological synthetic validation.

The hydraulic solver receives effective pump efficiency and command. The
estimator receives a noisy flow-derived indicator and recorded command only.
"""
from __future__ import annotations

from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass
import json
import math
import random
from statistics import mean

from .models.tanks import CoupledTankModel, SIGNALS, integrate


PROTOCOL = 'coupled-tank-pump-wear-v1'
DEVELOPMENT_SEED = 521
EVALUATION_SEEDS = (28657, 29123, 30367)
CUTOFFS = (40., 100., 200., 300., 400., 480.)
HORIZONS = (60., 120., 240.)
FORECAST_HORIZON = 360.
PLANNING_HORIZON = 240.
EVALUATION_END = 720.
ECONOMICS = dict(preventive_cost=20., corrective_cost=65., downtime_cost=1.,
                 preventive_duration=8., corrective_duration=20., failure_consequence=30.,
                 replacement_cost=32., replacement_duration=6.)
SIGNAL_UNITS = {item['key']: item['unit'] for item in SIGNALS} | {'capacity_loss': 'fraction'}
INDICATOR_DEFINITION = ('Capacity loss = 1 − measured inlet flow / nominal inlet flow at the recorded pump command. '
                        'Assumes known nominal flow, a linear command-to-flow relation and no other inlet restriction.')

DEFAULTS = dict(duration=300., sample_interval=8., initial_condition=.97, degradation_rate=.00085,
                load_effect=.5, load_profile='constant', flow_noise=.0004, missing_fraction=.08,
                jitter=.25, failure_threshold=.38, operating_threshold=None, seed=DEVELOPMENT_SEED,
                rate_changes=(), maintenance=(), tank_config={})
RANGES = dict(duration=(20, 1800), sample_interval=(1, 120), initial_condition=(.05, 1),
              degradation_rate=(0, .02), load_effect=(0, 4), flow_noise=(0, .005),
              missing_fraction=(0, .85), jitter=(0, .4), failure_threshold=(.01, .99),
              seed=(0, 2**31-1))


def _number(value, low, high, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise ValueError(f'{name} must be between {low} and {high}.')
    return float(value)


def _event_schedule(items, kind, duration):
    if not isinstance(items, (list, tuple)) or len(items) > 30:
        raise ValueError(f'Enter at most 30 {kind} events.')
    parsed = []
    for event in items:
        if not isinstance(event, dict):
            raise ValueError(f'Enter a time and settings for each {kind} event.')
        at = _number(event.get('time'), .001, duration, 'Event time (s)')
        if kind == 'rate change' and set(event) == {'time', 'rate'}:
            parsed.append(dict(time=at, rate=_number(event['rate'], 0, .02, 'Degradation rate')))
        elif kind == 'maintenance' and set(event) <= {'time', 'action', 'condition'} and event.get('action') in ('restore', 'replace'):
            parsed.append(dict(time=at, action=event['action'],
                               condition=_number(event.get('condition', 1.), .05, 1, 'Restored condition')))
        else:
            raise ValueError(f'Invalid {kind} settings.')
    if len({event['time'] for event in parsed}) != len(parsed):
        raise ValueError(f'Use a single {kind} per timestamp.')
    return sorted(parsed, key=lambda event: event['time'])


def _settings(raw):
    if not isinstance(raw, dict) or set(raw) - DEFAULTS.keys():
        raise ValueError('Unknown pump degradation settings.')
    config = DEFAULTS | raw
    for key, (low, high) in RANGES.items():
        config[key] = _number(config[key], low, high, key.replace('_', ' '))
    if not config['seed'].is_integer():
        raise ValueError('Seed must be an integer.')
    config['seed'] = int(config['seed'])
    if config['load_profile'] not in ('constant', 'variable'):
        raise ValueError('Choose a constant or variable pump load profile.')
    if config['operating_threshold'] is None:
        config['operating_threshold'] = .7*config['failure_threshold']
    else:
        config['operating_threshold'] = _number(config['operating_threshold'], 0., config['failure_threshold'], 'Operating threshold')
        if config['operating_threshold'] == config['failure_threshold']:
            raise ValueError('The operating threshold must be below the failure threshold.')
    config['rate_changes'] = _event_schedule(config['rate_changes'], 'rate change', config['duration'])
    config['maintenance'] = _event_schedule(config['maintenance'], 'maintenance', config['duration'])
    native = config['tank_config']
    fixed = {'fault', 'duration', 'step', 'seed', 'start', 'fault_duration'}
    if not isinstance(native, dict) or fixed & native.keys():
        raise ValueError('Tank settings may supply hydraulic parameters without fault or timing overrides.')
    config['tank_config'] = dict(native)
    return config


@dataclass(frozen=True)
class _PumpProfile:
    times: tuple[float, ...]
    conditions: tuple[float, ...]
    rates: tuple[float, ...]
    commands: tuple[float, ...]

    def __call__(self, time):
        index = bisect_right(self.times, time)-1
        return max(0., self.conditions[index] - (time-self.times[index])*self.rates[index]), self.commands[index]

    def first_passage(self, threshold):
        limit = 1-threshold
        for index, (time, condition, rate) in enumerate(zip(self.times, self.conditions, self.rates)):
            if condition <= limit:
                return time
            if rate > 0 and index+1 < len(self.times):
                crossing = time + (condition-limit)/rate
                if crossing <= self.times[index+1]:
                    return crossing
        return None


def _make_profile(config, nominal_command):
    loads = {0.: nominal_command}
    if config['load_profile'] == 'variable':
        for index, time in enumerate(range(0, math.ceil(config['duration']), 54)):
            loads[float(time)] = min(150., nominal_command*(.74, 1.24, .88, 1.12)[index % 4])
    rate_changes = {event['time']:event['rate'] for event in config['rate_changes']}
    resets = {event['time']:event['condition'] for event in config['maintenance']}
    times = tuple(sorted({0., config['duration'], *loads, *rate_changes, *resets}))
    conditions, rates, commands = [], [], []
    condition = config['initial_condition']
    rate = config['degradation_rate']
    command = nominal_command
    for index, at in enumerate(times):
        if index:
            condition = max(0., condition-(at-times[index-1])*rates[-1])
        condition = resets.get(at, condition)
        rate = rate_changes.get(at, rate)
        command = loads.get(at, command)
        conditions.append(condition)
        rates.append(rate*(command/nominal_command)**config['load_effect'])
        commands.append(command)
    return _PumpProfile(times, tuple(conditions), tuple(rates), tuple(commands))


def _sample_times(config, rng):
    step, end = config['sample_interval'], config['duration']
    interior = (step*index for index in range(1, math.ceil(end/step)))
    jittered = (round(time+step*rng.uniform(-config['jitter'], config['jitter']), 8) for time in interior)
    return [0., *(time for time in jittered if time < end), end]


@dataclass(frozen=True)
class PumpTrajectory:
    rows: list[dict]
    physical: list[dict]
    failure_time: float | None
    config: dict
    nominal_flow: float


def simulate_progressive(raw=None):
    """Generate observations and separate truth for retrospective experiments."""
    config = _settings({} if raw is None else raw)
    model = CoupledTankModel()
    try:
        native = model.validate(dict(integrationStep=.25) | config['tank_config'] |
                                dict(fault='healthy', start=0., duration=config['duration'],
                                     step=min(10., config['sample_interval']), seed=config['seed']))
    except OverflowError as error:
        raise ValueError('Use finite hydraulic parameter values within the coupled-tank model ranges.') from error
    if native['pumpControl'] <= 0 or native['pumpRate'] <= 0:
        raise ValueError('Progressive pump experiments require positive nominal flow and command.')
    profile = _make_profile(config, native['pumpControl'])
    if native['pumpRate']*min(profile.commands)/100 <= 0:
        raise ValueError('The nominal flow must be representable at every pump command.')
    sampling = random.Random(config['seed']+1)
    sensor = random.Random(config['seed']+2)
    missing = random.Random(config['seed']+3)
    rows, physical = integrate(native, pump_profile=profile, pump_boundaries=profile.times,
                               sample_times=_sample_times(config, sampling))
    for row in rows:
        measured_flow = row['inlet'] + sensor.gauss(0., config['flow_noise'])
        available = row['t'] == 0 or missing.random() >= config['missing_fraction']
        row['inlet'] = measured_flow if available else None
        nominal_at_command = native['pumpRate']*row['pump']/100
        capacity_loss = 1-measured_flow/nominal_at_command
        if not math.isfinite(capacity_loss):
            raise ValueError('The nominal flow is too small to compute capacity loss from noisy measurements.')
        row['capacity_loss'] = capacity_loss if available else None
    return PumpTrajectory(rows, physical, profile.first_passage(config['failure_threshold']), config, native['pumpRate'])


def _indicator(config):
    return dict(signal='capacity_loss', definition=INDICATOR_DEFINITION, unit='fraction', direction='increasing',
                failure_threshold=config['failure_threshold'], operating_threshold=config['operating_threshold'])


def benchmark_dataset(config=None):
    """Public Dataset view. Only retrospective evaluation may use latent truth."""
    run = simulate_progressive(config)
    config = run.config
    return dict(rows=run.rows, signals=SIGNAL_UNITS.copy(), indicator=_indicator(config), load_signal='pump',
                events=[{key: event[key] for key in ('time', 'action')} for event in config['maintenance']],
                operating_periods=[[0., config['duration']]], end_status='censored', replay_config=config,
                provenance=dict(model_id=CoupledTankModel.id, model_version=CoupledTankModel.version,
                                protocol=PROTOCOL, nominal_flow=run.nominal_flow, sample_interval=config['sample_interval']))


SCENARIOS = {
    'slow': dict(degradation_rate=.00062, flow_noise=.0003),
    'rapid': dict(degradation_rate=.0015, flow_noise=.0004),
    'variable_load': dict(degradation_rate=.00086, load_effect=2., load_profile='variable', flow_noise=.00055),
    'changing_rate': dict(degradation_rate=.00046, rate_changes=[dict(time=260., rate=.00145)], flow_noise=.00035),
    'sparse_missing': dict(degradation_rate=.00083, sample_interval=31., missing_fraction=.35, flow_noise=.00065),
    'censored': dict(degradation_rate=.00062, duration=440., flow_noise=.0003),
    'model_mismatch': dict(degradation_rate=.0011, load_effect=3., load_profile='variable', flow_noise=.0012,
                           maintenance=[dict(time=210., action='restore', condition=.95)],
                           rate_changes=[dict(time=240., rate=.00015), dict(time=360., rate=.00155)]),
    'no_failure': dict(degradation_rate=.00003, flow_noise=.00048),
}


def _evaluation_trajectory(settings, seed):
    rng = random.Random(seed)
    multiplier = math.exp(rng.gauss(0., .09))
    rates = [dict(time=event['time'], rate=event['rate']*multiplier) for event in settings.get('rate_changes', ())]
    return simulate_progressive(dict(duration=EVALUATION_END, initial_condition=rng.uniform(.95, .99), seed=seed) |
                                settings | dict(degradation_rate=settings['degradation_rate']*multiplier, rate_changes=rates))


def _realized_cost(action, at, remaining):
    """One event: failure wins a tie with preventive intervention."""
    failure_before_action = remaining is not None and remaining <= (PLANNING_HORIZON if at is None else at)
    if action == 'corrective' or failure_before_action:
        return ECONOMICS['corrective_cost'] + ECONOMICS['corrective_duration']*ECONOMICS['downtime_cost'] + ECONOMICS['failure_consequence']
    if at is None:
        return 0.
    prefix = 'replacement' if action == 'replace' else 'preventive'
    return ECONOMICS[f'{prefix}_cost'] + ECONOMICS[f'{prefix}_duration']*ECONOMICS['downtime_cost']


def _mean(values):
    return mean(values) if values else None


def _metrics(cases, method):
    rul_errors, coverage, revisions = [], [], []
    probabilities = {horizon: [] for horizon in HORIZONS}
    costs = {name: [] for name in ('policy', 'continue', 'immediate', 'fixed_midpoint')}
    statuses = Counter()
    prior = {}
    observed_failures = 0
    for case in cases:
        prediction = next(item for item in case['predictions'] if item['method'] == method)
        statuses[prediction['status']] += 1
        actual = case['remaining_life']
        estimate = prediction['rul']
        identity = case['scenario'], case['replicate']
        predicted_at = case['cutoff']+estimate['median'] if estimate['median'] is not None else None
        previous = prior.get(identity)
        if previous is not None and predicted_at is not None:
            revisions.append(abs(predicted_at-previous))
        prior[identity] = predicted_at
        if actual is not None:
            observed_failures += 1
            if estimate['median'] is not None:
                rul_errors.append(estimate['median']-actual)
            if estimate['lower'] is not None and estimate['upper'] is not None:
                coverage.append(estimate['lower'] <= actual <= estimate['upper'])
        for item in prediction['probabilities']:
            horizon = item['horizon']
            if item['probability'] is not None and case['cutoff']+horizon <= case['observation_end']:
                probabilities[horizon].append((item['probability'], float(actual is not None and actual <= horizon)))
        if prediction['maintenance'] is not None:
            for name, value in prediction['maintenance']['realized'].items():
                costs[name].append(value)
    reliability = []
    for horizon, pairs in probabilities.items():
        bins = []
        for index in range(4):
            items = [(p,y) for p,y in pairs if min(3, int(4*p)) == index]
            bins.append(dict(lower=index/4, upper=(index+1)/4, count=len(items),
                             predicted=_mean([p for p,_ in items]), observed=_mean([y for _,y in items])))
        reliability.append(dict(horizon=horizon, count=len(pairs), brier=_mean([(p-y)**2 for p,y in pairs]),
                                predicted=_mean([p for p,_ in pairs]), observed=_mean([y for _,y in pairs]), bins=bins))
    return dict(case_count=len(cases), statuses=dict(statuses),
                rul=dict(count=observed_failures, median_available=len(rul_errors), mae=_mean([abs(e) for e in rul_errors]),
                         bias=_mean(rul_errors), interval_count=len(coverage), coverage=_mean(coverage)),
                reliability=reliability, stability=dict(count=len(revisions), mean_absolute_revision=_mean(revisions)),
                maintenance=dict(count=len(costs['policy']), **{name:_mean(values) for name,values in costs.items()}))


def evaluate():
    """Evaluate frozen scenario families, each with three held-out realizations."""
    from .prognostics import (CONFIDENCE, MODEL_VERSION, Asset, ConditionHistory, Indicator, MaintenanceEvent, Observation,
                              failure_probability, forecast, plan_maintenance)

    asset = Asset('benchmark-pump', 'Coupled-tank inlet pump', ('inlet', 'pump', 'capacity_loss'))
    methods = ('linear', 'stochastic')
    cases, trajectories = [], []
    for scenario_index, (scenario, settings) in enumerate(SCENARIOS.items()):
        for replicate, base_seed in enumerate(EVALUATION_SEEDS, 1):
            seed = base_seed + 1000*scenario_index
            run = _evaluation_trajectory(settings, seed)
            end = run.config['duration']
            failure = run.failure_time
            rows = [row for row in run.rows if failure is None or row['t'] < failure]
            trajectories.append(dict(scenario=scenario, replicate=replicate, seed=seed, observation_end=end, failure_time=failure,
                                     observations=len(rows), missing=sum(row['capacity_loss'] is None for row in rows)))
            for cutoff in CUTOFFS:
                if cutoff >= end or (failure is not None and cutoff >= failure):
                    continue
                prefix = [row for row in run.rows if row['t'] <= cutoff]
                # Build an independent prefix; the object contains neither the
                # eventual failure label nor the simulator configuration.
                observations = tuple(Observation(row['t'], row['capacity_loss'], row['pump']) for row in prefix)
                events = tuple(MaintenanceEvent(event['time'], event['action']) for event in run.config['maintenance'] if event['time'] <= cutoff)
                history = ConditionHistory(asset, Indicator(**_indicator(run.config)), observations, events=events)
                episode_end = next((event['time'] for event in run.config['maintenance'] if event['time'] > cutoff), end)
                episode_failure = failure if failure is not None and failure <= episode_end else None
                actual = None if episode_failure is None else episode_failure-cutoff
                case = dict(scenario=scenario, replicate=replicate, cutoff=cutoff, observation_end=episode_end, failure_time=episode_failure,
                            observed_through=next((row['t'] for row in reversed(prefix) if row['capacity_loss'] is not None), None),
                            remaining_life=actual, predictions=[])
                for method in methods:
                    result = forecast(history, method=method, cutoff=cutoff, horizon=FORECAST_HORIZON,
                                      probability_horizons=HORIZONS)
                    rul = result['rul']
                    prediction = dict(method=method, status=result['status'], rul={key:rul[key] for key in ('median', 'lower', 'upper')},
                                      probabilities=[dict(horizon=horizon, probability=failure_probability(result, horizon)) for horizon in HORIZONS],
                                      maintenance=None)
                    if cutoff+PLANNING_HORIZON <= episode_end:
                        plan = plan_maintenance(result, planning_horizon=PLANNING_HORIZON, **ECONOMICS)
                        recommendation = plan['recommended']
                        if recommendation is not None:
                            action, at = recommendation['action'], recommendation['time']
                            prediction['maintenance'] = dict(action=action, time=at, expected_cost=recommendation['expected_cost'],
                                realized={'policy': _realized_cost(action, at, actual), 'continue': _realized_cost('continue', None, actual),
                                          'immediate': _realized_cost('restore', 0., actual),
                                          'fixed_midpoint': _realized_cost('restore', PLANNING_HORIZON/2, actual)})
                    case['predictions'].append(prediction)
                cases.append(case)
    return dict(protocol=dict(id=PROTOCOL, development_seed=DEVELOPMENT_SEED, evaluation_seeds=list(EVALUATION_SEEDS),
                              model_version=MODEL_VERSION, nominal_interval_confidence=CONFIDENCE,
                              seed_offset_per_scenario=1000, cutoffs=list(CUTOFFS), horizons=list(HORIZONS),
                              forecast_horizon=FORECAST_HORIZON, planning_horizon=PLANNING_HORIZON, economics=ECONOMICS.copy(),
                              interval_coverage='Observed failures with both predictive quantiles resolved inside the forecast horizon.',
                              censoring='Administrative observation ends and future recorded resets censor an episode. Reliability and policy costs use complete horizon follow-up. '
                                        'Point and interval metrics are conditional on observed failures and forecast availability.',
                              stability='Mean absolute revision of the predicted calendar failure time between adjacent cutoffs.'),
                trajectories=trajectories, cases=cases,
                models=[dict(method=method, **_metrics(cases, method),
                             by_scenario=[dict(scenario=scenario, **_metrics([case for case in cases if case['scenario'] == scenario], method))
                                          for scenario in SCENARIOS]) for method in methods])


if __name__ == '__main__':
    print(json.dumps(evaluate(), indent=2, allow_nan=False))
