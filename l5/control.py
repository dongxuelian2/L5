"""Closed-loop protocol validation, common-random-number comparisons and metrics."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from time import perf_counter
import numpy as np
import scipy

from .controllers import NOMINAL_KEYS, MPCController, PIController, reference_at
from .models.tanks import CoupledTankModel, integrate
from .models.base import finite

VERSION='tank-control-1'
PI_DEFAULTS=dict(kind='pi',kp=180.,ki=2.,actuateValve=False,valveKp=.5,valveBias=1.)
MPC_DEFAULTS=dict(kind='mpc',predictionHorizon=25,controlHorizon=8,trackingWeight=10.,
                  moveWeight=.08,effortWeight=.002,levelWeight=1000.,maxIterations=1200,
                  tolerance=1e-5,preview=True,actuateValve=False)
CONSTRAINTS=dict(pumpMin=0.,pumpMax=150.,pumpRate=10.,valveMin=.01,valveMax=1.,valveRate=.1,
                 levelMin1=0.,levelMax1=2.3,levelMin2=0.,levelMax2=2.3)
METRICS=[('iae','Measured tracking IAE','m·s'),('physicalIae','Physical tracking IAE','m·s'),
         ('overshoot','Maximum overshoot','m'),('settlingTime','Final setpoint settling time','s'),
         ('pumpEffort','Normalized pump effort','s'),('pumpVariation','Pump total variation','%'),
         ('valveVariation','Valve total variation','fraction'),('levelViolationSeconds','Physical limit violation duration','s'),
         ('maxLevelViolation','Maximum physical limit violation','m'),('overflow','Overflow volume','m³'),
         ('actuatorViolations','Actuator bound violations','count'),('rateViolations','Actuator rate violations','count'),
         ('solverFailures','Solver failures / PI fallback','count'),('infeasibleSteps','Certified infeasible steps','count'),
         ('meanSolveMs','Mean decision time','ms'),('maxSolveMs','Maximum decision time','ms')]


def number(value, name, low, high, *, integer=False, nullable=False):
    if nullable and value is None:
        return None
    if not finite(value) or not low <= value <= high or (integer and int(value) != value):
        raise ValueError(f'Control {name}: expected {"integer" if integer else "number"} in [{low}, {high}].')
    return int(value) if integer else float(value)


def object_keys(raw, allowed, name):
    if not isinstance(raw,dict) or set(raw)-set(allowed):
        raise ValueError(f'Unknown {name} settings.')


def controller_settings(raw):
    if not isinstance(raw,dict) or raw.get('kind') not in ('open-loop','pi','mpc'):
        raise ValueError('Choose open-loop, pi or mpc control.')
    kind=raw['kind']
    defaults={'kind':kind} if kind=='open-loop' else PI_DEFAULTS if kind=='pi' else MPC_DEFAULTS
    object_keys(raw,defaults,'controller')
    s=deepcopy(defaults)|raw
    if kind=='pi':
        for k,limits in dict(kp=(0,2000),ki=(0,100),valveKp=(0,10),valveBias=(.01,1)).items():
            s[k]=number(s[k],k,*limits)
    if kind=='mpc':
        for k,limits in dict(predictionHorizon=(2,60),controlHorizon=(1,20),maxIterations=(1,10000)).items():
            s[k]=number(s[k],k,*limits,integer=True)
        if s['controlHorizon'] > s['predictionHorizon']:
            raise ValueError('Control horizon must not exceed prediction horizon.')
        for k,limits in dict(trackingWeight=(.001,1000),moveWeight=(.0001,100),effortWeight=(0,100),
                             levelWeight=(1,10000),tolerance=(1e-7,1e-3)).items():
            s[k]=number(s[k],k,*limits)
    for key in ('preview','actuateValve'):
        if key in s and not isinstance(s[key],bool):
            raise ValueError(f'Control {key} must be boolean.')
    return s


def validate_protocol(raw, config):
    object_keys(raw,('sampleInterval','reference','constraints','controllers','disturbances','settlingBand','settlingDwell'),'control protocol')
    interval=number(raw.get('sampleInterval',2.),'sampleInterval',.2,30)
    if math.ceil(config['duration']/interval)>1500:
        raise ValueError('Use at most 1,500 control decisions per controller.')
    constraints=deepcopy(CONSTRAINTS)
    changes=raw.get('constraints',{}); object_keys(changes,constraints,'constraints'); constraints.update(changes)
    for key in constraints:
        low,high=(0,150) if key.startswith('pump') else ((0,10) if key.startswith('level') else (.01,1))
        if key=='valveRate': low,high=0,5
        constraints[key]=number(constraints[key],key,low,high,nullable=key.endswith('Rate'))
    for prefix in ('pump','valve'):
        if constraints[prefix+'Min']>constraints[prefix+'Max']:
            raise ValueError('Actuator minimum must not exceed maximum.')
        initial=config['pumpControl'] if prefix=='pump' else config['valve']
        if not constraints[prefix+'Min']<=initial<=constraints[prefix+'Max']:
            raise ValueError('Initial actuator command must lie inside the control bounds.')
    for j in (1,2):
        if constraints[f'levelMin{j}']>=constraints[f'levelMax{j}']:
            raise ValueError('Operational minimum level must be below maximum level.')
    reference=raw.get('reference',[dict(time=0.,level=config['targetLevel'])])
    if not isinstance(reference,list) or not 1<=len(reference)<=50:
        raise ValueError('Provide 1–50 reference points starting at time zero.')
    reference=deepcopy(reference)
    for i,point in enumerate(reference):
        object_keys(point,('time','level'),'reference')
        point['time']=number(point.get('time'),'reference time',0,config['duration'])
        point['level']=number(point.get('level'),'reference level',0,10)
        if (i==0 and point['time']!=0) or (i and point['time']<=reference[i-1]['time']):
            raise ValueError('Reference times must increase strictly from zero.')
    disturbances=deepcopy(raw.get('disturbances',[]))
    if not isinstance(disturbances,list) or len(disturbances)>30:
        raise ValueError('Provide at most 30 nonoverlapping disturbances.')
    for i,d in enumerate(disturbances):
        object_keys(d,('start','end','inletFactor','outletFactor'),'disturbance')
        for k in ('start','end'):
            d[k]=number(d.get(k),k,0,config['duration'])
        for k in ('inletFactor','outletFactor'):
            d[k]=number(d.get(k,1.),k,0,3)
        if d['end']<=d['start'] or (i and d['start']<disturbances[i-1]['end']):
            raise ValueError('Disturbances must be ordered, disjoint, positive-duration intervals.')
    controllers=raw.get('controllers',[{'kind':'open-loop'},PI_DEFAULTS,MPC_DEFAULTS])
    if not isinstance(controllers,list) or not 1<=len(controllers)<=3:
        raise ValueError('Compare 1–3 unique controllers.')
    controllers=[controller_settings(v) for v in controllers]
    if len({v['kind'] for v in controllers})!=len(controllers):
        raise ValueError('Choose each controller once per comparison.')
    # Bound local computation and retained prediction evidence, rather than allow
    # an accidental multi-hour request from a very fine control clock.
    work=sum(math.ceil(config['duration']/interval)*v.get('predictionHorizon',1)*v.get('controlHorizon',1) for v in controllers)
    if work>200000:
        raise ValueError('Reduce the duration, horizons or control sampling frequency (200,000 horizon products maximum).')
    return dict(sampleInterval=interval,reference=reference,constraints=constraints,controllers=controllers,disturbances=disturbances,
                settlingBand=number(raw.get('settlingBand',.02),'settlingBand',.0001,1),
                settlingDwell=number(raw.get('settlingDwell',20.),'settlingDwell',0,10000))


def settling_time(times, errors, start, end, band, dwell):
    indices=[i for i,t in enumerate(times) if start<=t<=end]
    # A sampled settling time is defined only if all remaining samples stay in
    # band AND the remaining duration is at least the requested dwell.
    last_bad=next((i for i in reversed(indices) if abs(errors[i])>band),None)
    candidate=next((i for i in indices if last_bad is None or i>last_bad),None)
    if candidate is None or end-times[candidate]<dwell-1e-9:
        return None
    return times[candidate]-start


def evaluate(rows, physical, decisions, protocol, config):
    times=[r['t'] for r in rows]; ts=np.array(times); dt=np.diff(ts)
    refs=np.array([reference_at(protocol['reference'],t) for t in times])
    measured=np.array([r['level2'] for r in rows]); actual=np.array([r['level2'] for r in physical])
    # Left-rectangle time integration is intentional: a reference step cannot
    # contribute tracking error before it occurs. References are sample targets.
    error=measured-refs; physical_error=actual-refs
    c=protocol['constraints']; violation=np.zeros(len(rows))
    for j in (1,2):
        h=np.array([r[f'level{j}'] for r in physical])
        violation=np.maximum(violation,np.maximum(c[f'levelMin{j}']-h,h-c[f'levelMax{j}']))
    commands=np.array([[r['pump'],r['valve']] for r in rows])
    magnitude=int(np.sum(np.any((commands<[c['pumpMin']-1e-7,c['valveMin']-1e-7])|(commands>[c['pumpMax']+1e-7,c['valveMax']+1e-7]),axis=1)))
    rate_violations=0; previous=np.array([config['pumpControl'],config['valve']])
    for d in decisions:
        current=np.array([d['command']['pump'],d['command']['valve']])
        for j,key in enumerate(('pumpRate','valveRate')):
            if c[key] is not None and abs(current[j]-previous[j])>c[key]*protocol['sampleInterval']+1e-7:
                rate_violations+=1
        previous=current
    last=protocol['reference'][-1]['time']
    settled=settling_time(times,error,last,times[-1],protocol['settlingBand'],protocol['settlingDwell'])
    recovery=[]
    events=[d['end'] for d in protocol['disturbances']]
    if config['fault']!='healthy':
        events.append(config['start']+(config['fault_duration'] or 0))
    for event in sorted(set(events)):
        if event>=times[-1]: continue
        # Stop recovery evaluation at the next reference/fault/disturbance event.
        future=[p['time'] for p in protocol['reference'] if p['time']>event]
        future += [v for d in protocol['disturbances'] for v in (d['start'],d['end']) if v>event]
        if config['fault']!='healthy' and config['start']>event: future.append(config['start'])
        end=min(future+[times[-1]])
        recovery.append(dict(time=event,through=end,settlingSeconds=settling_time(times,error,event,end,protocol['settlingBand'],protocol['settlingDwell'])))
    duration_ms=[d['durationMs'] for d in decisions]
    return dict(iae=float(np.sum(np.abs(error[:-1])*dt)),physicalIae=float(np.sum(np.abs(physical_error[:-1])*dt)),
                overshoot=float(max(0.,np.max(error))),settlingTime=settled,
                pumpEffort=float(np.sum((commands[:-1,0]/100)**2*dt)),
                pumpVariation=float(np.sum(np.abs(np.diff(commands[:,0])))),valveVariation=float(np.sum(np.abs(np.diff(commands[:,1])))),
                levelViolationSeconds=float(np.sum((violation[:-1]>1e-7)*dt)),maxLevelViolation=float(max(0.,max(violation))),
                overflow=physical[-1]['spilled'],maxMassResidual=max(abs(p['massResidual']) for p in physical),
                actuatorViolations=magnitude,rateViolations=rate_violations,solverFailures=sum(d['solver'].get('fallback',False) for d in decisions),
                infeasibleSteps=0,meanSolveMs=float(np.mean(duration_ms)),maxSolveMs=max(duration_ms),recovery=recovery)


def compare(config, protocol):
    """Run already validated inputs. Timing is evidence, not a reproducible value."""
    nominal={k:config[k] for k in NOMINAL_KEYS}; results=[]
    for settings in protocol['controllers']:
        initial=[config['pumpControl']/100,config['valve']]; decisions=[]
        kind=settings['kind']
        effective=deepcopy(settings)
        if kind=='pi': controller=PIController(nominal,settings,protocol['constraints'],initial)
        elif kind=='mpc':
            effective['fallbackPI']=deepcopy(PI_DEFAULTS)|dict(valveBias=config['valve'],actuateValve=settings['actuateValve'])
            controller=MPCController(nominal,effective,protocol['constraints'],initial)
        else: controller=None

        def feedback(measurement):
            begin=perf_counter()
            command,info=controller.step(measurement,protocol['reference'],protocol['sampleInterval']) if controller else (np.array(initial),dict(status='open-loop'))
            output=dict(pump=float(command[0]*100),valve=float(command[1]))
            decisions.append(dict(time=measurement['t'],measurement=measurement,command=output,
                reference=reference_at(protocol['reference'],measurement['t']),solver=info,durationMs=(perf_counter()-begin)*1000))
            return output

        # Reference and disturbance boundaries are included as observations without
        # changing the fixed control clock. Thus feedback is recomputed only at
        # scheduled control ticks, even for an off-clock setpoint change.
        rows,physical=integrate(config,feedback=feedback,control_interval=protocol['sampleInterval'],disturbances=protocol['disturbances'],
                                observation_times=[p['time'] for p in protocol['reference']])
        for row in rows:
            row['reference']=reference_at(protocol['reference'],row['t'])
            row['error']=row['reference']-row['level2']
        metrics=evaluate(rows,physical,decisions,protocol,config)
        results.append(dict(controller=kind,settings=effective,rows=rows,physical=physical,decisions=decisions,metrics=metrics))
    # Noise offsets must be identical across controllers even when plant responses
    # differ. This fingerprint is retained for independent comparison audits.
    noise=[[round(r['level1']-p['level1'],12),round(r['level2']-p['level2'],12)] for r,p in zip(results[0]['rows'],results[0]['physical'])]
    return dict(format=VERSION,modelId='coupled-tanks',modelVersion=CoupledTankModel.version,config=config,protocol=protocol,
                results=results,noiseFingerprint=hashlib.sha256(json.dumps(noise).encode()).hexdigest(),
                metricDefinitions=[dict(key=k,label=label,unit=unit) for k,label,unit in METRICS],
                informationPolicy='Only current measured levels/flows and previous commands enter the controller. Scheduled references may be previewed; fault/disturbance schedules and physical truth are evaluation-only.',
                solver=dict(name='Dense convex QP / SciPy SLSQP with independent KKT checks',version=1,scipyVersion=scipy.__version__,numpyVersion=np.__version__,model='Analytic nominal hydraulic Jacobian with affine RK2 discretization and causal disturbance estimation',
                    constraints='Hard magnitude and slew limits; soft predicted level bounds with two penalized maximum-excursion slacks. No physical safety guarantee.',
                    failure='Reject unconverged iterates; use bounded, rate-limited PI fallback. This solver does not certify infeasibility; infeasibleSteps is zero, iteration limits count as solverFailures.'))
