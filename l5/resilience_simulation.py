"""Reproducible fault schedules, coupled-tank physics and causal observation delivery."""
from __future__ import annotations

from bisect import bisect_right
from copy import deepcopy
from decimal import Decimal
import hashlib
import math
import random

from .models import resolve
from .models.base import field
from .models.tanks import hydraulic_flows, integrate_hydraulics

MODEL_ID = 'coupled-tanks'
MAX_FAULTS = 24
MAX_SAMPLES = 6001
MAX_INTEGRATION_STEPS = 120000
MAX_PULSES = 4096

PROFILE_FIELDS = {
    'step': [],
    'linear': [field('rise_time', 'Ramp rise time', 10., .001, 100000., unit='s')],
    'progressive': [field('time_constant', 'Degradation time constant', 10., .001, 100000., unit='s')],
    'intermittent': [field('period', 'Cycle period', 2., .001, 100000., unit='s'),
                     field('active_duration', 'Active time per cycle', .5, .001, 100000., unit='s'),
                     field('cycle_probability', 'Probability of an active cycle', .5, 0., 1.)],
    'temporary': [],
    'repeating': [field('period', 'Cycle period', 2., .001, 100000., unit='s'),
                  field('active_duration', 'Active time per cycle', .5, .001, 100000., unit='s')],
}
FAULT_FIELDS = {
    'pump_degradation': [field('maximum_loss', 'Efficiency loss at full severity', .7, 0., 1.)],
    'valve_restriction': [field('maximum_loss', 'Opening loss at full severity', .85, 0., 1.)],
    'tank_leak': [field('coefficient', 'Leak coefficient at full severity', .015, 0., .1, unit='m^(5/2)/s')],
    'sensor_bias': [field('offset', 'Offset at full severity', .3, -1000., 1000.)],
    'sensor_drift': [field('rate', 'Drift rate at full severity', .01, -100., 100., unit='signal units/s')],
    'sensor_stuck': [field('value', 'Stuck value (blank captures first sample)', None, -10000., 10000., nullable=True)],
    'frozen_timestamp': [],
    'sensor_spike': [field('amplitude', 'Spike magnitude at full severity', .4, -1000., 1000.),
                     field('probability', 'Spike probability per sample', .05, 0., 1.)],
    'sensor_noise': [field('stddev', 'Additional standard deviation at full severity', .1, 0., 1000.)],
    'sensor_dropout': [],
    'communication_blackout': [],
    'observation_delay': [field('delay', 'Delay at full severity', 1., 0., 100000., unit='s')],
    'out_of_order': [field('delay', 'Late packet delay at full severity', 2., 0., 100000., unit='s'),
                     field('probability', 'Late packet probability per sample', .3, 0., 1.)],
}
PROCESS_TARGETS = {'pump_degradation': ['pump'], 'valve_restriction': ['valve'], 'tank_leak': ['tank1', 'tank2']}
ACQUISITION_TYPES = {'communication_blackout', 'observation_delay', 'out_of_order'}
MEASUREMENT_FIELDS = [field('noise', 'Base level sensor standard deviation', .002, 0., .1, unit='m'),
                      field('missing_fraction', 'Independent missing probability per signal', 0., 0., 1.),
                      field('physical_noise', 'Inlet flow relative standard deviation', 0., 0., 1.)]
SCENARIO_DEFAULTS = dict(name='Coupled-tank scenario', model_id=MODEL_ID, duration=240., sample_interval=.2,
                         integration_step=.05, seed=1, initial={}, parameters={}, measurement={}, faults=[])


def _targets(fault_type, signals):
    if fault_type in PROCESS_TARGETS:
        return PROCESS_TARGETS[fault_type]
    return [*signals, 'all'] if fault_type in ACQUISITION_TYPES else signals


def _model_fields(model):
    fields = model.describe()['configFields']
    return ([spec for spec in fields if spec['group'] == 'Initial conditions'],
            [spec for spec in fields if spec['group'] == 'Model parameters'])


def scenario_catalog():
    model = resolve(MODEL_ID)
    descriptor = model.describe()
    initial, parameters = _model_fields(model)
    signals = [signal['key'] for signal in descriptor['signals']]
    return deepcopy(dict(
        models=[dict(id=model.id, name=descriptor['name'], version=model.version, parameters=parameters,
                     initial=initial, signals=descriptor['signals'])],
        fault_types=[dict(id=kind, targets=_targets(kind, signals), parameters=fields)
                     for kind, fields in FAULT_FIELDS.items()],
        profiles=[dict(id=kind, parameters=fields) for kind, fields in PROFILE_FIELDS.items()],
        measurement=MEASUREMENT_FIELDS, defaults=validate_scenario({}),
        limits=dict(max_faults=MAX_FAULTS, max_samples=MAX_SAMPLES, max_pulses=MAX_PULSES)))


def _object(raw, keys, label):
    if not isinstance(raw, dict) or set(raw).difference(keys):
        raise ValueError(f'{label} must be an object with supported fields.')
    return raw


def _number(value, low, high, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise ValueError(f'{label} must be between {low} and {high}.')
    return value


def _fields(raw, specs, label):
    _object(raw, {spec['key'] for spec in specs}, label)
    values = {}
    for spec in specs:
        value = raw.get(spec['key'], spec['default'])
        if value is not None or not spec['nullable']:
            value = _number(value, spec['min'], spec['max'], spec['label'])
        values[spec['key']] = value
    return values


def _clock_count(duration, interval):
    return int(Decimal(str(duration)) // Decimal(str(interval)))+1


def validate_scenario(raw):
    """Normalize all inputs and assign no seed or identity implicitly to events."""
    scenario = {**SCENARIO_DEFAULTS, **_object(raw, SCENARIO_DEFAULTS, 'Scenario')}
    name = scenario['name']
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 160:
        raise ValueError('Scenario name must contain 1–160 characters.')
    if scenario['model_id'] != MODEL_ID:
        raise ValueError('Choose a registered resilience model.')
    model = resolve(scenario['model_id'])
    signal_keys = [signal['key'] for signal in model.describe()['signals']]
    initial, parameters = _model_fields(model)
    scenario['name'] = name.strip()
    scenario['initial'] = _fields(scenario['initial'], initial, 'Initial conditions')
    scenario['parameters'] = _fields(scenario['parameters'], parameters, 'Model parameters')
    duration = _number(scenario['duration'], .1, 100000., 'Duration')
    interval = _number(scenario['sample_interval'], .02, 10., 'Sampling interval')
    integration = _number(scenario['integration_step'], .005, .25, 'Integration step')
    seed = _number(scenario['seed'], 0, 2147483647, 'Seed')
    if int(seed) != seed:
        raise ValueError('Seed must be an integer.')
    scenario['seed'] = int(seed)
    if not 2 <= _clock_count(duration, interval) <= MAX_SAMPLES:
        raise ValueError(f'Use 2–{MAX_SAMPLES} observation times per scenario.')
    settings = _object(scenario['measurement'], {s['key'] for s in MEASUREMENT_FIELDS} | {'signals'},
                       'Measurement settings')
    signals = settings.get('signals', signal_keys)
    if (not isinstance(signals, list) or not signals or
            any(not isinstance(key, str) or key not in signal_keys for key in signals) or
            len(set(signals)) != len(signals)):
        raise ValueError('Select unique observed signal keys from the process model.')
    scenario['measurement'] = {**_fields({key: value for key, value in settings.items() if key != 'signals'},
                                         MEASUREMENT_FIELDS, 'Measurement settings'), 'signals': list(signals)}
    raw_events = scenario['faults']
    if not isinstance(raw_events, list) or len(raw_events) > MAX_FAULTS:
        raise ValueError(f'Use at most {MAX_FAULTS} fault events.')
    events, identities = [], set()
    pulse_count = 0
    for item in raw_events:
        event = _object(item, {'id', 'type', 'target', 'onset', 'recovery', 'severity', 'profile', 'parameters'}, 'Fault event')
        identity, kind, target = (event.get(key) for key in ('id', 'type', 'target'))
        if (not isinstance(identity, str) or not 1 <= len(identity) <= 80 or
                identity.strip() != identity or not identity.isprintable() or identity in identities):
            raise ValueError('Each fault event needs a unique, printable ID of 1–80 characters.')
        identities.add(identity)
        if not isinstance(kind, str) or kind not in FAULT_FIELDS or target not in _targets(kind, signal_keys):
            raise ValueError('Choose a supported fault type and a valid target for it.')
        onset = _number(event.get('onset'), 0., duration, 'Fault onset')
        recovery = event.get('recovery')
        if recovery is not None:
            _number(recovery, onset, duration, 'Fault recovery')
        if onset >= duration or recovery == onset:
            raise ValueError('A fault event must have a positive duration within the simulation horizon.')
        severity = _number(event.get('severity', 1.), 0., 1., 'Fault severity')
        profile = event.get('profile', 'step')
        if not isinstance(profile, str) or profile not in PROFILE_FIELDS:
            raise ValueError('Choose a supported fault evolution profile.')
        if profile == 'temporary' and recovery is None:
            raise ValueError('A temporary fault requires a recovery time.')
        params = _fields(event.get('parameters', {}), FAULT_FIELDS[kind]+PROFILE_FIELDS[profile], 'Fault parameters')
        if profile in ('intermittent', 'repeating'):
            if params['active_duration'] > params['period']:
                raise ValueError('Active time per cycle cannot exceed the period.')
            pulse_count += math.ceil(((duration if recovery is None else recovery)-onset)/params['period'])
        events.append(dict(id=identity, type=kind, target=target, onset=onset, recovery=recovery,
                           severity=severity, profile=profile, parameters=params))
    if pulse_count > MAX_PULSES:
        raise ValueError(f'Use at most {MAX_PULSES} pulse cycles per scenario.')
    # Each poll and transition can introduce one partial step beyond duration/integration.
    upper_steps = math.ceil(duration/integration)+_clock_count(duration, interval)+2*pulse_count+3*len(events)
    if upper_steps > MAX_INTEGRATION_STEPS:
        raise ValueError('Use a shorter duration or a larger integration step.')
    scenario['faults'] = events
    return scenario


def _stream(seed, purpose, *keys):
    digest = hashlib.sha256(repr((seed, purpose, *keys)).encode('utf-8')).digest()
    return random.Random(int.from_bytes(digest, 'big'))


def _intervals(event, horizon, seed):
    """Resolve cycles on the simulation clock, independently of sample times."""
    onset, recovery = event['onset'], event['recovery']
    end = horizon if recovery is None else recovery
    if event['severity'] == 0:
        return []
    if event['profile'] not in ('repeating', 'intermittent'):
        return [dict(start=onset, end=end, endExclusive=recovery is not None)]
    parameters = event['parameters']
    rng = _stream(seed, 'profile', event['id'])
    start = Decimal(str(onset))
    limit = Decimal(str(end))
    period = Decimal(str(parameters['period']))
    active_duration = Decimal(str(parameters['active_duration']))
    probability = parameters.get('cycle_probability', 1.)
    intervals = []
    while start < limit:
        pulse_end = start+active_duration
        if rng.random() < probability:
            interval = dict(start=float(start), end=float(min(pulse_end, limit)),
                            endExclusive=recovery is not None or pulse_end <= limit)
            if intervals and intervals[-1]['end'] == interval['start']:
                intervals[-1].update(end=interval['end'], endExclusive=interval['endExclusive'])
            else:
                intervals.append(interval)
        start += period
    return intervals


def _schedule(scenario, seed):
    return [dict(**event, intervals=_intervals(event, scenario['duration'], seed))
            for event in scenario['faults']]


def preview_scenario(raw):
    scenario = validate_scenario(raw)
    return dict(scenario=scenario, schedule=_schedule(scenario, scenario['seed']))


class _ScheduledFault:
    def __init__(self, event):
        self.event = event
        self.kind = event['type']
        self.target = event['target']
        self.identity = event['id']
        self.profile = event['profile']
        self.parameters = event['parameters']
        self.intervals = event['intervals']
        self.starts = [interval['start'] for interval in self.intervals]

    def strength(self, time):
        index = bisect_right(self.starts, time)-1
        if index < 0:
            return 0., None
        interval = self.intervals[index]
        if time > interval['end'] or (interval['endExclusive'] and time == interval['end']):
            return 0., None
        elapsed = time-interval['start']
        scale = self.event['severity']
        if self.profile == 'linear':
            scale *= min(1., elapsed/self.parameters['rise_time'])
        elif self.profile == 'progressive':
            scale *= -math.expm1(-elapsed/self.parameters['time_constant'])
        return scale, interval['start']

    def boundaries(self):
        for interval in self.intervals:
            yield interval['start']
            yield interval['end']
            if self.profile == 'linear':
                knee = interval['start']+self.parameters['rise_time']
                if knee < interval['end']:
                    yield knee


def _physical_trajectory(scenario, faults, times, seed):
    settings = scenario['measurement']
    config = {**scenario['initial'], **scenario['parameters'], 'integrationStep': scenario['integration_step']}
    targets = times if times[-1] == scenario['duration'] else [*times, scenario['duration']]
    boundaries = sorted({time for fault in faults for time in fault.boundaries()})
    process_rng = _stream(seed, 'physical inlet disturbance')
    inlet_multipliers = [max(0., 1.+process_rng.gauss(0., settings['physical_noise'])) for _ in times]

    def components(time):
        valve, efficiency = config['valve'], 1.
        leaks = {'tank1': 0., 'tank2': 0.}
        for fault in faults:
            strength, _ = fault.strength(time)
            if fault.kind == 'pump_degradation':
                efficiency *= 1.-strength*fault.parameters['maximum_loss']
            elif fault.kind == 'valve_restriction':
                valve *= 1.-strength*fault.parameters['maximum_loss']
            else:
                leaks[fault.target] += strength*fault.parameters['coefficient']
        return valve, efficiency, inlet_multipliers[bisect_right(times, time)-1], leaks

    def evaluate(heads, time):
        pump = config['pumpControl']
        valve, efficiency, disturbance, leaks = components(time)
        return hydraulic_flows(config, heads, pump, valve, efficiency*disturbance,
                               leaks['tank1'], leaks['tank2']), pump, valve

    physical = list(integrate_hydraulics(config, targets, boundaries, evaluate))
    for row in physical:
        _, efficiency, disturbance, leaks = components(row['t'])
        row.update(pumpEfficiency=efficiency, inletDisturbanceMultiplier=disturbance,
                   leakCoefficient1=leaks['tank1'], leakCoefficient2=leaks['tank2'])
    return physical


def _sample_packets(settings, faults, signal, physical, seed):
    base_noise = _stream(seed, 'base sensor noise', signal)
    base_loss = _stream(seed, 'base packet loss', signal)
    streams = {fault.identity: _stream(seed, 'fault effect', fault.identity, signal) for fault in faults}
    blackouts = [fault for fault in faults if fault.kind == 'communication_blackout']
    anchors = {}
    previous_source = 0.
    for row in physical:
        time = row['t']
        nominal = row[signal]
        if signal in ('level1', 'level2'):
            nominal += base_noise.gauss(0., settings['noise'])
        value, source_time, delay = nominal, time, 0.
        lost = 'missing' if base_loss.random() < settings['missing_fraction'] else None
        for fault in faults:
            strength, start = fault.strength(time)
            if strength <= 0:
                continue
            parameters = fault.parameters
            kind = fault.kind
            rng = streams[fault.identity]
            if kind == 'sensor_bias':
                value += strength*parameters['offset']
            elif kind == 'sensor_drift':
                value += strength*parameters['rate']*(time-start)
            elif kind == 'sensor_stuck':
                anchor = anchors.setdefault((fault.identity, start), nominal)
                stuck = anchor if parameters['value'] is None else parameters['value']
                value = (1-strength)*value+strength*stuck
            elif kind == 'frozen_timestamp':
                source_time = anchors.setdefault((fault.identity, start), previous_source)
            elif kind == 'sensor_spike' and rng.random() < parameters['probability']:
                value += strength*parameters['amplitude']
            elif kind == 'sensor_noise':
                value += strength*rng.gauss(0., parameters['stddev'])
            elif kind == 'sensor_dropout' and rng.random() < strength:
                lost = lost or 'missing'
            elif kind == 'communication_blackout':
                lost = 'blackout'
            elif kind == 'observation_delay':
                delay += strength*parameters['delay']
            elif kind == 'out_of_order' and rng.random() < parameters['probability']:
                delay += strength*parameters['delay']
        previous_source = source_time
        arrival = float(Decimal(str(time))+Decimal(str(delay))) if delay else time
        if delay and any(fault.strength(arrival)[0] > 0 for fault in blackouts):
            lost = 'blackout'
        flags = []
        if source_time != time:
            flags.append('frozen_timestamp')
        if delay:
            flags.append('delayed')
        if nominal != value:
            flags.append('distorted')
        if lost:
            flags.insert(0, lost)
        yield dict(signal=signal, sample_time=time, source_time=source_time,
                   acquisition_time=None if lost else arrival, value=None if lost else value,
                   undistorted_value=nominal, generated_value=value, flags=flags,
                   quality=flags[0] if flags else 'observed')


def _measurement_trajectory(settings, faults, physical, seed):
    frames = [dict(t=row['t'], values={}, quality={}, source_times={}, acquisition_times={}) for row in physical]
    packets = []
    for signal in settings['signals']:
        targeted_faults = [fault for fault in faults if fault.target in (signal, 'all')]
        samples = list(_sample_packets(settings, targeted_faults, signal, physical, seed))
        packets.extend(samples)
        arrivals = sorted((packet for packet in samples if packet['acquisition_time'] is not None),
                          key=lambda packet: (packet['acquisition_time'], packet['sample_time']))
        latest_sample = -math.inf
        for packet in arrivals:
            if packet['sample_time'] < latest_sample:
                packet['quality'] = 'out_of_order'
                packet['flags'].insert(0, 'out_of_order')
            latest_sample = max(latest_sample, packet['sample_time'])
        index = 0
        for frame, sample in zip(frames, samples):
            packet = sample if sample['acquisition_time'] is None else None
            # Deliver at most one value per signal per poll, retaining every packet in evidence.
            while index < len(arrivals) and arrivals[index]['acquisition_time'] <= frame['t']:
                packet = arrivals[index]
                index += 1
            frame['values'][signal] = packet['value'] if packet else None
            frame['source_times'][signal] = packet['source_time'] if packet and packet['value'] is not None else None
            frame['acquisition_times'][signal] = packet['acquisition_time'] if packet else None
            quality = packet['quality'] if packet else 'unavailable'
            # The simulated cause and value distortion are only available retrospectively.
            frame['quality'][signal] = {'distorted': 'observed', 'blackout': 'missing'}.get(quality, quality)
    packets.sort(key=lambda packet: (packet['sample_time'], packet['signal']))
    return frames, packets


def simulate_scenario(raw, *, stream_namespace='scenario'):
    scenario = validate_scenario(raw)
    seed = scenario['seed'] if stream_namespace == 'scenario' else (stream_namespace, scenario['seed'])
    schedule = _schedule(scenario, seed)
    faults = [_ScheduledFault(event) for event in sorted(schedule, key=lambda event: event['id'])]
    process_faults = [fault for fault in faults if fault.kind in PROCESS_TARGETS]
    measurement_faults = [fault for fault in faults if fault.kind not in PROCESS_TARGETS]
    interval = Decimal(str(scenario['sample_interval']))
    times = [float(index*interval) for index in range(_clock_count(scenario['duration'], interval))]
    physical = _physical_trajectory(scenario, process_faults, times, seed)
    observations, packets = _measurement_trajectory(scenario['measurement'], measurement_faults, physical[:len(times)], seed)
    model = resolve(scenario['model_id'])
    signals = {signal['key']: signal for signal in model.describe()['signals']}
    return dict(scenario=scenario, schedule=schedule, model_version=model.version,
                signals=[signals[key] for key in scenario['measurement']['signals']], observations=observations,
                observation_packets=packets,
                truth=dict(physical=physical, events=schedule,
                           severities={fault.identity: [fault.strength(row['t'])[0] for row in physical] for fault in faults}))
