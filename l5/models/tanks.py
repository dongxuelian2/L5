"""Interacting tanks with conservative, positivity-preserving SSPRK2 integration.

Areas are m², heads m and flows m³/s. Discharge coefficients incorporate
Cd*a*sqrt(2*g); connection flow is signed for reverse head differences.
Each Euler stage limits all withdrawals by available donor volume. The same
transfer flux enters the other tank, so the limiter preserves mass exactly.
"""
from __future__ import annotations

from bisect import bisect_right
import math
import random
import secrets
from .base import field, finite, ground_truth, validate_fields

FAULTS = dict(healthy='Healthy operation', pump_degradation='Inlet pump degradation',
              valve_restriction='Connection valve restriction', tank_leak='Tank 1 leak',
              sensor_bias='Tank 2 level sensor bias')
DEFAULTS = dict(fault='healthy', start=40., severity=.6, fault_duration=None,
                duration=240., step=.2, integrationStep=.05, seed=1, noise=.002,
                area1=1., area2=1., initial1=1.5625, initial2=1.,
                pumpRate=.03, pumpControl=100., connection=.04, outlet=.03,
                valve=1., outletValve=1., leakCoefficient=.015, sensorBias=.3,
                tankHeight=2.5, targetLevel=1.)
FIELDS = [
    field('area1','Tank 1 area',1,.1,10,unit='m²'), field('area2','Tank 2 area',1,.1,10,unit='m²'),
    field('connection','Connection discharge coefficient',.04,.001,.2,unit='m^(5/2)/s'),
    field('outlet','Outlet discharge coefficient',.03,.001,.2,unit='m^(5/2)/s'),
    field('pumpRate','Nominal pump flow',.03,0,.2,unit='m³/s'),
    field('pumpControl','Pump command',100,0,150,unit='%'),
    field('valve','Connection valve opening',1,.01,1), field('outletValve','Outlet valve opening',1,.01,1),
    field('tankHeight','Overflow height',2.5,.1,10,unit='m'),
    field('targetLevel','Tank 2 target (metric reference)',1,0,10,unit='m'),
    field('initial1','Initial Tank 1 level',1.5625,0,10,group='Initial conditions',unit='m'),
    field('initial2','Initial Tank 2 level',1,0,10,group='Initial conditions',unit='m'),
    field('start','Fault onset',40,0,100000,group='Fault configuration',unit='s'),
    field('severity','Fault intensity',.6,0,1,group='Fault configuration'),
    field('fault_duration','Fault duration (blank = persistent)',None,.01,100000,group='Fault configuration',unit='s',nullable=True),
    field('leakCoefficient','Leak discharge coefficient',.015,0,.1,group='Fault configuration',unit='m^(5/2)/s'),
    field('sensorBias','Sensor bias at full intensity',.3,-2,2,group='Fault configuration',unit='m'),
    field('noise','Level sensor noise standard deviation',.002,0,.1,group='Noise and timing',unit='m'),
    field('duration','Simulation duration',240,.1,100000,group='Noise and timing',unit='s'),
    field('step','Sampling interval',.2,.02,10,group='Noise and timing',unit='s'),
    field('integrationStep','Maximum integration step',.05,.005,.25,group='Noise and timing',unit='s'),
    field('seed','Random seed (blank = generate per run)',1,0,2147483647,group='Noise and timing',integer=True,nullable=True),
]
SIGNALS = [dict(key=k,tag=tag,unit=unit,label=label) for k,tag,unit,label in [
    ('level1','LT-101','m','Tank 1 measured level'), ('level2','LT-102','m','Tank 2 measured level'),
    ('inlet','FT-101','m³/s','Inlet flow'), ('transfer','FT-102','m³/s','Inter-tank flow (signed)'),
    ('outlet','FT-103','m³/s','Outlet delivery flow'), ('pump','PC-101','%','Pump command'),
    ('valve','CV-101','fraction','Connection valve opening'),
]]
ACTIONS = [dict(id='adjust_pump',name='Adjust inlet pump command',parameters=['pumpControl']),
           dict(id='open_valve',name='Change connection valve opening',parameters=['valveOpening']),
           dict(id='backup_pump',name='Switch to backup pump',parameters=['backupControl']),
           dict(id='stop_supply',name='Controlled supply stop',parameters=['rampSeconds'])]
PARAMETERS = dict(pumpControl=dict(default=125.,min=0,max=150,label='Pump command',unit='%'),
                  valveOpening=dict(default=1.,min=.01,max=1,label='Connection valve opening',unit='fraction'),
                  backupControl=dict(default=100.,min=0,max=150,label='Backup pump command',unit='%'),
                  rampSeconds=dict(default=10.,min=.1,max=120,label='Supply stop ramp',unit='s'))


def validate_tank_measurements(store, dataset):
    """Check declared process identities through saved transformation sources."""
    pending = [dataset]
    seen = set()
    while pending:
        source = pending.pop()
        if source['id'] in seen:
            continue
        seen.add(source['id'])
        metadata = source['metadata']
        model = metadata.get('model')
        if metadata.get('processRun') or metadata.get('external', {}).get('kind') == 'tep-rieth' or (
                model and (model.get('id'), model.get('version')) != ('coupled-tanks', CoupledTankModel.version)):
            raise ValueError('Tank measurements require a compatible coupled-tank process and model version.')
        for record in metadata.get('transformation', {}).get('sources', []):
            pending.append(store.dataset(record['datasetId']))


def hydraulic_flows(c, heads, pump, opening, efficiency=1., leak_coefficient=0.,
                    inflow_bias=0., *, tank2_leak=None, inlet_factor=1., outlet_factor=1., ops=math):
    """Square-root orifice flows and free overflow with illustrative K = 0.1 m^(3/2)/s."""
    maximum = max if ops is math else ops.maximum
    h1, h2 = heads
    delta = h1 - h2
    inlet = maximum(0., c['pumpRate'] * pump / 100 * efficiency * inlet_factor + inflow_bias)
    transfer = c['connection'] * opening * ops.copysign(ops.sqrt(abs(delta)), delta)
    outlet = c['outlet'] * c['outletValve'] * ops.sqrt(maximum(0., h2)) * outlet_factor
    leak1 = leak_coefficient * ops.sqrt(maximum(0., h1))
    spill1, spill2 = (.1 * maximum(0., h - c['tankHeight'])**1.5 for h in heads)
    fluxes = [inlet, transfer, outlet, leak1, spill1, spill2]
    if tank2_leak is not None:
        fluxes.append(tank2_leak * ops.sqrt(maximum(0., h2)))
    return fluxes


def donor_stage(c, heads, fluxes, dt, *, ops=math):
    """Advance one conservative Euler stage using the available donor volumes."""
    maximum, minimum = (max, min) if ops is math else (ops.maximum, ops.minimum)
    inlet, transfer, outlet, leak1, spill1, spill2, *additional = fluxes
    leak2 = additional[0] if additional else 0.
    area1, area2 = c['area1'], c['area2']
    demand1 = maximum(0., transfer) + leak1 + spill1
    demand2 = maximum(0., -transfer) + outlet + spill2 + leak2
    scale1 = minimum(1., heads[0] * area1 / (dt * demand1 + (demand1 == 0)))
    scale2 = minimum(1., heads[1] * area2 / (dt * demand2 + (demand2 == 0)))
    transfer = maximum(0., transfer) * scale1 + minimum(0., transfer) * scale2
    leak1, spill1 = leak1 * scale1, spill1 * scale1
    outlet, spill2, leak2 = outlet * scale2, spill2 * scale2, leak2 * scale2
    limits = [inlet, transfer, outlet, leak1, spill1, spill2]
    if additional:
        limits.append(leak2)
    return [maximum(0., heads[0] + dt * (inlet - transfer - leak1 - spill1) / area1),
            maximum(0., heads[1] + dt * (transfer - outlet - spill2 - leak2) / area2)], limits


def euler_stage(c, state, dt, fluxes):
    """Apply a forward Euler stage to precomputed fluxes for model fitting."""
    return donor_stage(c, state, fluxes, dt)


def active_intensities(c, when, faults):
    active = when >= c['start'] and (c['fault_duration'] is None or when < c['start'] + c['fault_duration'])
    if active:
        return {c['fault']: c['severity']} if faults is None else faults
    return {}


def flows(c, heads, time, action=None, at=0., parameters=None, pump_profile=None, *,
          commands=None, disturbance=None, faults=None, inputs=None):
    pump, opening = inputs if inputs is not None else (c['pumpControl'], c['valve'])
    if commands is not None:
        pump, opening = commands['pump'], commands['valve']
    intensities = active_intensities(c, time, faults)
    efficiency = 1 - .7 * intensities.get('pump_degradation', 0.)
    if pump_profile is not None:
        efficiency, pump = pump_profile(time)
    if action and time >= at:
        if action == 'adjust_pump':
            pump = parameters['pumpControl']
        elif action == 'open_valve':
            opening = parameters['valveOpening']
        elif action == 'backup_pump':
            efficiency, pump = 1., parameters['backupControl']
        elif action == 'stop_supply':
            pump *= max(0., 1 - (time - at) / parameters['rampSeconds'])
    opening *= 1 - .85 * intensities.get('valve_restriction', 0.)
    leak = c['leakCoefficient'] * intensities.get('tank_leak', 0.)
    inlet_factor = disturbance['inletFactor'] if disturbance is not None else 1.
    outlet_factor = disturbance['outletFactor'] if disturbance is not None else 1.
    fluxes = hydraulic_flows(c, heads, pump, opening, efficiency, leak,
                            inlet_factor=inlet_factor, outlet_factor=outlet_factor)
    return fluxes, pump, opening, intensities.get(c['fault'], 0.)


def _rk_step(c, heads, start, end, evaluate):
    dt = end - start
    left, flux1 = donor_stage(c, heads, evaluate(heads, start), dt)
    # Sample the left limit at switches. The next step samples the new inputs.
    right, flux2 = donor_stage(c, left, evaluate(left, math.nextafter(end, start)), dt)
    return [(a + b) / 2 for a, b in zip(heads, right)], [(a + b) / 2 for a, b in zip(flux1, flux2)]


def hydraulic_step(c, state, when, dt, action=None, at=0., parameters=None):
    """Advance the hydraulic state used by the state estimator."""
    def evaluate(heads, time):
        return flows(c, heads, time, action, at, parameters or {})[0]

    return _rk_step(c, state, when, when + dt, evaluate)


def integrate_hydraulics(c, targets, boundaries, evaluate, *, inspect_step=None):
    """Integrate the tank state across sample times and discontinuities."""
    heads, t = [c['initial1'], c['initial2']], 0.
    initial_volume = c['area1'] * heads[0] + c['area2'] * heads[1]
    totals = [0.] * 7
    if inspect_step is not None:
        inspect_step(t, heads)

    def fluxes(state, when):
        return evaluate(state, when)[0]

    for target in targets:
        while t < target:
            index = bisect_right(boundaries, t)
            boundary = boundaries[index] if index < len(boundaries) else target
            end = min(round(t + c['integrationStep'], 12), target, boundary)
            heads, accepted = _rk_step(c, heads, t, end, fluxes)
            totals = [volume + (end - t) * flow for volume, flow in zip(totals, accepted)]
            t = end
            if inspect_step is not None:
                inspect_step(t, heads)
        f, pump, opening = evaluate(heads, target)
        volume = c['area1'] * heads[0] + c['area2'] * heads[1]
        leaked = totals[3] + totals[6]
        spilled = totals[4] + totals[5]
        yield dict(t=target, level1=heads[0], level2=heads[1], inlet=f[0], transfer=f[1], outlet=f[2],
                   pump=pump, valve=opening, leak=f[3] + f[6], leak1=f[3], leak2=f[6], spill=f[4] + f[5],
                   volume=volume, delivered=totals[2], spilled=spilled, injected=totals[0], leaked=leaked,
                   massResidual=volume - initial_volume - totals[0] + totals[2] + leaked + spilled)


def integrate(config, action=None, at=0., parameters=None, *, include_at=False,
              feedback=None, control_interval=None, disturbances=(), observation_times=(),
              pump_profile=None, pump_boundaries=(), sample_times=None, faults=None,
              schedule=None, inspect_step=None):
    """Run a tank scenario with measured feedback, pump profiles, or scheduled commands."""
    c = config
    p = {key: value['default'] for key, value in PARAMETERS.items()} | (parameters or {})
    rng = random.Random(c['seed'])
    commands = {'pump': c['pumpControl'], 'valve': c['valve']} if feedback is not None else None
    control_times = set()
    if feedback is not None:
        if not finite(control_interval) or control_interval <= 0:
            raise ValueError('Control interval must be positive.')
        control_times = {round(i * control_interval, 9) for i in range(math.ceil(c['duration'] / control_interval))}

    starts = []
    if schedule is not None:
        schedule = list(schedule)
        starts = [item[0] for item in schedule]
        if (not starts or starts[0] != 0 or starts[-1] >= c['duration']
                or not all(finite(t) for t in starts) or any(b <= a for a, b in zip(starts, starts[1:]))):
            raise ValueError('Tank input schedule must start at zero and increase inside the horizon.')
        if any(not finite(pump) or not 0 <= pump <= 150 + 1e-12
               or not finite(valve) or not .01 - 1e-12 <= valve <= 1 + 1e-12 for _, pump, valve in schedule):
            raise ValueError('Tank input schedule exceeds the physical actuator bounds.')

    disturbance_times = {time for event in disturbances for time in (event['start'], event['end'])}
    boundaries = {c['duration'], c['start'], *starts, *pump_boundaries, *disturbance_times}
    if c['fault_duration'] is not None:
        boundaries.add(c['start'] + c['fault_duration'])
    if action:
        boundaries.add(at)
    if action == 'stop_supply':
        boundaries.add(at + p['rampSeconds'])

    if sample_times is None:
        count = math.ceil(c['duration'] / c['step'])
        targets = {min(round(i * c['step'], 9), c['duration']) for i in range(count)}
        targets.add(c['duration'])
    else:
        targets = set(sample_times)
    targets.update(control_times | disturbance_times)
    targets.update(observation_times)
    if include_at:
        targets.add(at)

    def evaluate(heads, when):
        disturbance = next((event for event in disturbances if event['start'] <= when < event['end']), None)
        inputs = schedule[bisect_right(starts, when) - 1][1:] if schedule is not None else None
        fluxes, pump, opening, _ = flows(c, heads, when, action, at, p, pump_profile, commands=commands,
                                          disturbance=disturbance, faults=faults, inputs=inputs)
        return [*fluxes, 0.], pump, opening

    rows, physical = [], []
    for state in integrate_hydraulics(c, sorted(targets), sorted(boundaries), evaluate, inspect_step=inspect_step):
        target = state['t']
        observed = {key: state[key] for key in ('t', 'level1', 'level2', 'inlet', 'transfer', 'outlet', 'pump', 'valve')}
        bias = c['sensorBias'] * active_intensities(c, target, faults).get('sensor_bias', 0.)
        observed['level1'] += rng.gauss(0, c['noise'])
        observed['level2'] = state['level2'] + bias + rng.gauss(0, c['noise'])
        if commands is not None:
            observed['valve'] = commands['valve']
        if target in control_times:
            # The controller receives observed signals before actuation.
            commands = feedback(dict(observed))
            if (not isinstance(commands, dict) or set(commands) != {'pump', 'valve'}
                    or not finite(commands['pump']) or not 0 <= commands['pump'] <= 150
                    or not finite(commands['valve']) or not .01 <= commands['valve'] <= 1):
                raise ValueError('Feedback returned an invalid tank actuator command.')
            observed.update(commands)
            f, _, _ = evaluate([state['level1'], state['level2']], target)
            state.update(inlet=f[0], transfer=f[1], outlet=f[2], leak=f[3], spill=f[4] + f[5])
        rows.append(observed)
        physical.append({key: value for key, value in state.items()
                         if key not in {'pump', 'valve', 'leak1', 'leak2', 'injected', 'leaked'}})
    return rows, physical


def forecast_path(c, rows, physical, at, action=None, parameters=None):
    after = [i for i,r in enumerate(physical) if r['t'] >= at]
    deviation = sum((abs(physical[b]['level2']-c['targetLevel'])+abs(physical[a]['level2']-c['targetLevel']))/2*(physical[b]['t']-physical[a]['t']) for a,b in zip(after,after[1:]))
    first = after[0]
    elapsed = physical[-1]['t'] - at
    if action == 'stop_supply':
        ramp = (parameters or {}).get('rampSeconds', PARAMETERS['rampSeconds']['default'])
        rising = min(ramp, elapsed)
        effort = c['pumpControl'] * (rising**2 / (2 * ramp) + elapsed - rising)
    else:
        effort = abs(rows[first]['pump'] - c['pumpControl']) * elapsed
    metrics = dict(levelDeviation=deviation, peakLevel=max(max(p['level1'],p['level2']) for p in physical[first:]),
                   delivered=physical[-1]['delivered']-physical[first]['delivered'],
                   overflow=physical[-1]['spilled']-physical[first]['spilled'],
                   controlEffort=effort)
    return dict(action=action, parameters=parameters or {},times=[r['t'] for r in physical],
                values={key:[r[key] for r in physical] for key in ('level1','level2','outlet')},metrics=metrics)


class CoupledTankModel:
    id = 'coupled-tanks'
    version = '1.0.0'

    def describe(self):
        return dict(modelId=self.id,model='Coupled-Tank Process',name='Coupled-Tank Process',version=self.version,
            description='Two interacting liquid tanks with gravity flow, pump faults, leakage and sensor bias.',category='Hydraulic process',
            source=dict(name='L5 interacting tank implementation; mass balance and square-root discharge law',
                url='https://engineering.ju.edu.jo/ar/arabic/Laboratories/Two%20Level%20System.pdf'),
            limitations=['Default parameters describe an illustrative plant.',
                'Closed-loop control uses measured levels and a nominal local model.',
                'Ground truth describes fault injection, including residual transients after a finite fault ends.'],
            defaults=DEFAULTS,configFields=FIELDS,signals=SIGNALS,faults=FAULTS,actions=ACTIONS,actionParameters=PARAMETERS,
            tools=['level_trend','flow_balance','sensor_check'],
            toolDefinitions=[dict(id='level_trend',name='Level trends',fields=[]),
                dict(id='flow_balance',name='Observed mass balance',fields=[]),
                dict(id='sensor_check',name='Compare level with flow integration',fields=[])],
            capabilities=['simulation','observation','investigation-tools','interventions','forecast','topology','ground-truth'],
            edges=[dict(source='inlet',target='level1',kind='material'),dict(source='level1',target='transfer',kind='hydraulic'),
                dict(source='transfer',target='level2',kind='material'),dict(source='level2',target='outlet',kind='hydraulic')])

    def validate(self, raw, *, randomize=False):
        c = validate_fields(raw,FIELDS,DEFAULTS,FAULTS)
        if c['seed'] is None and randomize:
            c['seed'] = secrets.randbelow(2**31)
        if not 0 <= c['start'] <= c['duration']:
            raise ValueError('Fault onset must be inside the simulation horizon.')
        if math.ceil(c['duration']/c['step']) > 100000 or math.ceil(c['duration']/min(c['step'],c['integrationStep'])) > 500000:
            raise ValueError('Use at most 100,000 observations and 500,000 integration steps per tank run.')
        return c

    def simulate(self, config):
        return integrate(config)[0]

    truth = staticmethod(ground_truth)

    def observe(self, session, rows):
        return dict(signals=[dict(**s,value=rows[-1][s['key']],change=rows[-1][s['key']]-rows[0][s['key']]) for s in SIGNALS],
                    status='observed', limitations=['Measured levels include configured sensor noise and possible bias.'])

    def tools(self, session, rows, body):
        calls = body.get('calls')
        if not isinstance(calls,list) or not 1 <= len(calls) <= 8:
            raise ValueError('Choose 1–8 supported investigation calls.')
        c = session['config']; trace = []
        for call in calls:
            if not isinstance(call,dict) or call.get('tool') not in self.describe()['tools'] or call.get('args',{}) != {}:
                raise ValueError('Choose a supported tank tool with empty arguments; the observation window supplies its input.')
            tool = call['tool']; elapsed=rows[-1]['t']-rows[0]['t']
            storage=c['area1']*(rows[-1]['level1']-rows[0]['level1'])+c['area2']*(rows[-1]['level2']-rows[0]['level2'])
            net=sum(((a['inlet']-a['outlet'])+(b['inlet']-b['outlet']))/2*(b['t']-a['t']) for a,b in zip(rows,rows[1:]))
            if tool == 'level_trend':
                result = dict(unit='m/s',rates={k:(rows[-1][k]-rows[0][k])/elapsed for k in ('level1','level2')})
            elif tool == 'flow_balance':
                result = dict(unit='m³',measuredStorageChange=storage,integratedNetInflow=net,
                              unexplainedVolume=net-storage,
                              interpretation='Leakage, overflow, sensor errors and sampling error can all contribute to the residual.')
            else:
                expected = rows[0]['level2'] + sum(((a['transfer']-a['outlet'])+(b['transfer']-b['outlet']))/2*(b['t']-a['t'])/c['area2'] for a,b in zip(rows,rows[1:]))
                result = dict(unit='m',measuredLevel=rows[-1]['level2'],flowIntegratedLevel=expected,
                    discrepancy=rows[-1]['level2']-expected,
                    interpretation='Flow integration starts from the first measured level and tracks changes from that baseline. Overflow and sampling also affect this residual.')
            trace.append(dict(tool=tool,args={},result=result))
        return dict(asOf=rows[-1]['t'],trace=trace)

    def intervene(self, session, rows, body):
        if body.get('mode','known') != 'known':
            raise ValueError('Choose the known-model forecast mode for coupled tanks.')
        if body.get('search'):
            raise ValueError('Specify a start time for each tank intervention.')
        if body.get('hypothesis',session['config']['fault']) != session['config']['fault']:
            raise ValueError('Tank forecasts use the saved scenario fault; create another scenario to change it.')
        horizon=body.get('horizon',session['config']['duration']); at=body.get('at',rows[-1]['t'])
        if not finite(at) or not finite(horizon) or not rows[-1]['t'] <= at <= horizon:
            raise ValueError('Intervene at or after the observed cutoff, inside the prediction horizon.')
        actions=body.get('actions')
        if not isinstance(actions,list) or not actions or any(not isinstance(a,str) for a in actions) or len(set(actions)) != len(actions) or any(a not in {v['id'] for v in ACTIONS} for a in actions):
            raise ValueError('Choose unique supported tank actions.')
        parameters=body.get('parameters',{})
        if not isinstance(parameters,dict) or set(parameters)-PARAMETERS.keys():
            raise ValueError('Unknown tank intervention parameters.')
        p={k:parameters.get(k,v['default']) for k,v in PARAMETERS.items()}
        if any(not finite(p[k]) or not v['min'] <= p[k] <= v['max'] for k,v in PARAMETERS.items()):
            raise ValueError('Intervention parameter outside the model range.')
        config=self.validate({**session['config'],'duration':horizon})
        base,physical=integrate(config,at=at,include_at=True)
        baseline=forecast_path(config,base,physical,at)
        branches=[]
        for action in actions:
            observed,prediction=integrate(config,action,at,p,include_at=True)
            branches.append(forecast_path(config,observed,prediction,at,action,p))
        return dict(format='model-forecast-v1',modelId=self.id,mode='known',hypothesis=config['fault'],
            observedThrough=rows[-1]['t'],at=at,horizon=horizon,fittedParameters=config,baseline=baseline,branches=branches,
            metricDefinitions=[dict(key=k,label=label,unit=unit) for k,label,unit in [
                ('levelDeviation','Tank 2 absolute level deviation','m·s'),('peakLevel','Peak physical level','m'),
                ('delivered','Delivered water','m³'),('overflow','Overflow volume','m³'),('controlEffort','Pump command change','%·s')]],
            signalDefinitions=[{**s,'label':{'level1':'Tank 1 physical level','level2':'Tank 2 physical level','outlet':'Outlet delivery flow'}[s['key']]} for s in SIGNALS if s['key'] in ('level1','level2','outlet')],
            scope='simulation-only',uncertainty='Forecasts use fixed scenario parameters. Metrics start at the action time.')
