"""Interacting tanks with conservative, positivity-preserving SSPRK2 integration.

Areas are m², heads m and flows m³/s. Discharge coefficients incorporate
Cd*a*sqrt(2*g); connection flow is signed for reverse head differences.
Each Euler stage limits all withdrawals by available donor volume. The same
transfer flux enters the other tank, so the limiter preserves mass exactly.
"""
from __future__ import annotations

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


def flows(c, heads, time, action, at, parameters):
    h1, h2 = heads
    active = time >= c['start'] and (c['fault_duration'] is None or time < c['start'] + c['fault_duration'])
    s = c['severity'] if active else 0.
    pump, opening = c['pumpControl'], c['valve']
    efficiency = 1 - .7*s if c['fault'] == 'pump_degradation' else 1.
    if action and time >= at:
        if action == 'adjust_pump':
            pump = parameters['pumpControl']
        elif action == 'open_valve':
            opening = parameters['valveOpening']
        elif action == 'backup_pump':
            efficiency, pump = 1., parameters['backupControl']
        elif action == 'stop_supply':
            pump *= max(0., 1-(time-at)/parameters['rampSeconds'])
    if c['fault'] == 'valve_restriction':
        opening *= 1-.85*s
    delta = h1-h2
    transfer = c['connection']*opening*math.copysign(math.sqrt(abs(delta)), delta)
    inlet = c['pumpRate']*pump/100*efficiency
    outlet = c['outlet']*c['outletValve']*math.sqrt(max(0,h2))
    leak = c['leakCoefficient']*s*math.sqrt(max(0,h1)) if c['fault'] == 'tank_leak' else 0.
    spill1, spill2 = (.1*max(0,h-c['tankHeight'])**1.5 for h in heads)
    return [inlet, transfer, outlet, leak, spill1, spill2], pump, opening, s


def integrate(config, action=None, at=0., parameters=None, *, include_at=False):
    c = config
    p = {k:v['default'] for k,v in PARAMETERS.items()} | (parameters or {})
    rng = random.Random(c['seed'])
    heads, t = [c['initial1'],c['initial2']], 0.
    initial_volume = c['area1']*heads[0]+c['area2']*heads[1]
    totals = [0.]*6
    physical, rows = [], []
    boundaries = sorted(set([c['duration'], c['start'], *([c['start']+c['fault_duration']] if c['fault_duration'] is not None else []), *([at] if action else [])]))

    def stage(state, when, dt):
        f, _, _, _ = flows(c,state,when,action,at,p)
        # Joint donor limiting keeps transfer, leak and overflow conservative.
        demand1 = max(0,f[1])+f[3]+f[4]
        scale1 = min(1., state[0]*c['area1']/(dt*demand1)) if demand1 else 1.
        demand2 = max(0,-f[1])+f[2]+f[5]
        scale2 = min(1., state[1]*c['area2']/(dt*demand2)) if demand2 else 1.
        f[1] *= scale1 if f[1] >= 0 else scale2
        f[3] *= scale1; f[4] *= scale1
        f[2] *= scale2; f[5] *= scale2
        return [max(0.,state[0]+dt*(f[0]-f[1]-f[3]-f[4])/c['area1']),
                max(0.,state[1]+dt*(f[1]-f[2]-f[5])/c['area2'])], f

    count = math.ceil(c['duration']/c['step'])
    targets = {round(min(index*c['step'],c['duration']),9) for index in range(count+1)}
    if include_at:
        targets.add(at)
    for target in sorted(targets):
        while t < target-1e-10:
            next_boundary = next((b for b in boundaries if b > t+1e-10),target)
            dt = min(c['integrationStep'],target-t,next_boundary-t)
            # Both SSP stages use the same side of a discontinuity. The next
            # substep begins at the event with the new fault/action inputs.
            left, flux1 = stage(heads,t,dt)
            right, flux2 = stage(left,t+dt*.999999999,dt)
            heads = [(a+b)/2 for a,b in zip(heads,right)]
            totals = [v+dt*(a+b)/2 for v,a,b in zip(totals,flux1,flux2)]
            t = round(t+dt,12)
        f,pump,opening,s = flows(c,heads,target,action,at,p)
        bias = c['sensorBias']*s if c['fault'] == 'sensor_bias' else 0.
        rows.append(dict(t=target,level1=heads[0]+rng.gauss(0,c['noise']),
                         level2=heads[1]+bias+rng.gauss(0,c['noise']),
                         inlet=f[0],transfer=f[1],outlet=f[2],pump=pump,valve=opening))
        volume = c['area1']*heads[0]+c['area2']*heads[1]
        physical.append(dict(t=target,level1=heads[0],level2=heads[1],inlet=f[0],transfer=f[1],outlet=f[2],
            leak=f[3],spill=f[4]+f[5],volume=volume,delivered=totals[2],spilled=totals[4]+totals[5],
            massResidual=volume-initial_volume-totals[0]+totals[2]+totals[3]+totals[4]+totals[5]))
    return rows, physical


def forecast_path(c, rows, physical, at, action=None, parameters=None):
    after = [i for i,r in enumerate(physical) if r['t'] >= at]
    deviation = sum((abs(physical[b]['level2']-c['targetLevel'])+abs(physical[a]['level2']-c['targetLevel']))/2*(physical[b]['t']-physical[a]['t']) for a,b in zip(after,after[1:]))
    first = after[0]
    metrics = dict(levelDeviation=deviation, peakLevel=max(max(p['level1'],p['level2']) for p in physical[first:]),
                   delivered=physical[-1]['delivered']-physical[first]['delivered'],
                   overflow=physical[-1]['spilled']-physical[first]['spilled'],
                   controlEffort=sum(abs(rows[b]['pump']-c['pumpControl'])*(rows[b]['t']-rows[a]['t']) for a,b in zip(after,after[1:])))
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
            limitations=['Illustrative parameters, not calibrated to a physical plant.',
                'Open-loop pump/valve control; known-model forecasts only.',
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
                              interpretation='A residual may reflect leakage, overflow, sensor errors or sampling error; it is not a fault classification.')
            else:
                expected = rows[0]['level2'] + sum(((a['transfer']-a['outlet'])+(b['transfer']-b['outlet']))/2*(b['t']-a['t'])/c['area2'] for a,b in zip(rows,rows[1:]))
                result = dict(unit='m',measuredLevel=rows[-1]['level2'],flowIntegratedLevel=expected,
                    discrepancy=rows[-1]['level2']-expected,
                    interpretation='Flow integration is anchored at the first measured level. A constant bias already present at the window start is not identifiable; overflow and sampling also affect this residual.')
            trace.append(dict(tool=tool,args={},result=result))
        return dict(asOf=rows[-1]['t'],trace=trace)

    def intervene(self, session, rows, body):
        if body.get('mode','known') != 'known':
            raise ValueError('Coupled tanks support known-model forecasts; observed-data parameter fitting is not available.')
        if body.get('search'):
            raise ValueError('Intervention start-time search is not supported by this model.')
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
            scope='simulation-only',uncertainty='Known illustrative model; no parameter fitting or predictive uncertainty bounds. Metrics start at the action time.')
