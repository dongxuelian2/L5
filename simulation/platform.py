"""TripLens investigation engine. Native Python, observed data in / evidence out.

Fault labels only enter the simulator and the evaluation harness. diagnose() has
no scenario parameter. All scores are rule support, never probabilities.
"""
from __future__ import annotations

import csv
import io
import json
import math
import statistics as stats
from dataclasses import dataclass, asdict
from pathlib import Path

DURATION = 240
THRESHOLD = 3050
BASELINE = 20
# key, display tag, unit, nominal, minimum engineering scale
SIGNALS = [
    ('valve', 'CV-101', '%', 62, .15), ('flow', 'FI-101', '%', 100, .25),
    ('temperature', 'TI-101', '°C', 120, .08), ('pressure', 'PI-101', 'kPa', 2700, 1),
    ('separator', 'PI-201', 'kPa', 2630, 1), ('purity', 'AI-301', '%', 99.2, .015),
    ('cooling_op', 'TIC-101.OP', '%', 62, .2), ('cooling_sp', 'TIC-101.SP', '°C', 120, .08),
    ('temperature_peer', 'TI-102', '°C', 120, .08), ('pressure_peer', 'PI-102', 'kPa', 2700, 1),
    ('feed', 'FI-102', '%', 100, .25), ('feed_op', 'FIC-102.OP', '%', 50, .2),
    ('feed_valve', 'CV-102', '%', 50, .2), ('utility', 'TI-001', '°C', 25, .08),
    ('pump', 'SI-101', '%', 100, .2), ('vibration', 'VI-101', 'mm/s', 1, .03),
    ('composition', 'AI-102', 'ratio', 1, .004), ('cooling_limit', 'TIC-101.MAX', '%', 100, .2),
]
KEYS = [s[0] for s in SIGNALS]
META = {s[0]: dict(key=s[0], tag=s[1], unit=s[2], nominal=s[3], scale=s[4]) for s in SIGNALS}
FAULTS = {
    'cooling_valve': 'Cooling valve sticking', 'feed_valve': 'Feed valve sticking',
    'utility_loss': 'Cooling-water degradation', 'feed_composition': 'Feed composition disturbance',
    'reaction_rate': 'Reaction-rate disturbance', 'pump_loss': 'Pump degradation',
    'separator_restriction': 'Separator restriction', 'pressure_bias': 'Pressure sensor bias',
    'temperature_drift': 'Temperature sensor drift', 'sensor_freeze': 'Pressure sensor freeze',
    'controller_limit': 'Controller output limit', 'loop_oscillation': 'Control-loop oscillation',
}
# Typed edges are also consumed by propagation analysis, not only the drawing.
EDGES = [
    ('utility', 'flow', 'energy'), ('pump', 'flow', 'material'),
    ('cooling_op', 'valve', 'control'), ('valve', 'flow', 'material'),
    ('flow', 'temperature', 'energy'), ('temperature', 'cooling_op', 'feedback'),
    ('feed_op', 'feed_valve', 'control'), ('feed_valve', 'feed', 'material'),
    ('feed', 'temperature', 'material'), ('composition', 'temperature', 'material'),
    ('temperature', 'pressure', 'energy'), ('pressure', 'separator', 'material'),
    ('separator', 'purity', 'material'), ('separator', 'pressure', 'feedback'),
]
ACTIONS = [
    dict(id='bypass', name='Open cooling bypass', severity=2, cost=2),
    dict(id='feed_reduce', name='Reduce feed 30%', severity=2, cost=1),
    dict(id='backup_pump', name='Start backup pump', severity=1, cost=2),
    dict(id='setpoint', name='Lower cooling setpoint', severity=1, cost=1),
    dict(id='emergency', name='Emergency cooling', severity=3, cost=4),
    dict(id='shutdown', name='Controlled shutdown', severity=5, cost=1),
    dict(id='combined', name='Bypass + feed reduction', severity=3, cost=3),
]

@dataclass(frozen=True)
class Config:
    fault: str = 'cooling_valve'
    start: int = 30
    severity: float = 1
    delay: int = 5
    noise: float = 1
    response: float = 1
    operating: float = 0
    seed: int = 1


def simulate(config: Config, action: str | None = None, at: int = 90, *, compact=False):
    """Two PI loops, actuator lag/rate limit, shared utility and thermal feedback.

    Measured pressure is distinct from physical pressure; a sensor alarm is not
    an actual physical trip. A hypothetical branch has an identical pre-action prefix.
    """
    c = config
    temp = 120 + c.operating
    pressure, separator, flow, feed, purity = 2700., 2630., 100., 100., 99.2
    valve, feed_valve, op, feed_op, integral = 62., 50., 62., 50., 0.
    rows, pressure_path = [], []
    trip = None
    prod_loss = quality_loss = utility_cost = 0.
    for t in range(DURATION + 1):
        active = t >= c.start
        s = c.severity if active else 0
        enabled = action is not None and t >= at
        utility = 25 + (9 * s if c.fault == 'utility_loss' else 0)
        pump = 100 - (48 * s if c.fault == 'pump_loss' else 0)
        vibration = 1 + (3.2 * s if c.fault == 'pump_loss' else 0)
        composition = 1 + (.45 * s if c.fault == 'feed_composition' else 0)
        measured_temp = temp + (min(8, (t - c.start) * .065) * s if c.fault == 'temperature_drift' else 0)
        sp = 120 + c.operating - (5 if enabled and action == 'setpoint' else 0)
        error = measured_temp - sp
        integral = max(-25, min(30, integral + error * .024 * c.response))
        limit = 100 - (55 * s if c.fault == 'controller_limit' else 0)
        target_op = max(10, min(limit, 62 + 2.4 * c.response * error + integral))
        if c.fault == 'loop_oscillation' and active:
            target_op = max(10, min(100, 62 + 27 * s * math.sin((t - c.start) / 6)))
        op += max(-2.5, min(2.5, target_op - op))
        target_valve = max(3, 62 - 40 * s) if c.fault == 'cooling_valve' and active else op
        valve += (target_valve - valve) / 2
        feed_sp = 70 if enabled and action in ('feed_reduce', 'combined') else 100
        if enabled and action == 'shutdown':
            feed_sp = 0
        feed_op = max(0, min(100, feed_op + .03 * (feed_sp - feed)))
        target_feed_valve = max(5, 50 - 27 * s) if c.fault == 'feed_valve' and active else feed_op
        feed_valve += (target_feed_valve - feed_valve) / 3
        feed += (2 * feed_valve - feed) / 10
        if enabled and action == 'backup_pump':
            pump = max(pump, 115)
        effective_valve = valve if t >= c.start + c.delay else 62
        cooling = max(0, 100 * effective_valve / 62 * pump / 100 * (1 - (utility - 25) * .035))
        if enabled and action in ('bypass', 'combined'):
            cooling = max(cooling, 110)
        if enabled and action == 'emergency':
            cooling = max(cooling, 145)
        flow += (cooling - flow) / 10
        reaction = 10 * s if c.fault == 'reaction_rate' else 0
        thermal_target = 120 + c.operating + .23 * (100 - flow) + .12 * (feed - 100) + 18 * (composition - 1) + reaction
        temp += (thermal_target - temp) / 33
        restriction = 260 * s if c.fault == 'separator_restriction' else 0
        recycle = max(0, separator - 2630 - .58 * (pressure - 2700)) * .15
        # A normal pressure test ramp exposes a frozen transmitter independently.
        test_ramp = min(180, max(0, t - c.start) * 2) if c.fault == 'sensor_freeze' else 0
        pressure += (2700 + 35 * (temp - 120 - c.operating) + recycle + test_ramp - pressure) / 24
        separator += (2630 + .58 * (pressure - 2700) + restriction - separator) / 27
        purity += (99.2 - .019 * (separator - 2630) - .025 * abs(feed - 100) - purity) / 35
        if pressure >= THRESHOLD and trip is None:
            trip = t
        pressure_path.append(round(pressure, 2))
        prod_loss += max(0, 100 - feed) / 100
        quality_loss += max(0, 99.2 - purity)
        utility_cost += max(0, flow - 100) / 100
        if compact:
            continue
        primary_p = pressure + (180 * s if c.fault == 'pressure_bias' else 0)
        if c.fault == 'sensor_freeze' and active:
            primary_p = 2700
        values = [valve, flow, measured_temp, primary_p, separator, purity, op, sp, temp, pressure,
                  feed, feed_op, feed_valve, utility, pump, vibration, composition, limit]
        row = {'t': t}
        for i, (key, _, _, _, scale) in enumerate(SIGNALS):
            noise = math.sin(t * .71 + i * 1.3 + c.seed) * scale * .4 * c.noise
            if key in ('cooling_sp', 'cooling_limit') or (key == 'pressure' and c.fault == 'sensor_freeze' and active):
                noise = 0
            row[key] = round(values[i] + noise, 4)
        rows.append(row)
    if compact:
        return dict(peak=round(max(pressure_path), 2), trip=trip, pressure=pressure_path,
                    productionLoss=round(prod_loss / (DURATION + 1) * 100, 2),
                    qualityLoss=round(quality_loss / (DURATION + 1), 3), utilityCost=round(utility_cost, 2))
    return rows


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate_rows(rows):
    if not isinstance(rows, list) or not 25 <= len(rows) <= 2000:
        raise ValueError('Supply 25–2000 samples including 20 stable baseline samples.')
    previous = -math.inf
    for row in rows:
        if not isinstance(row, dict) or not finite(row.get('t')) or row['t'] <= previous:
            raise ValueError('Timestamps must be finite, strictly increasing seconds.')
        previous = row['t']
        if any(row.get(key) is not None and not finite(row.get(key)) for key in KEYS):
            raise ValueError('Signal values must be finite numbers or null.')


def evidence(rows):
    validate_rows(rows)
    detections, health, baseline, changes = {}, {}, {}, {}
    for key in KEYS:
        valid = [(r['t'], r[key]) for r in rows if finite(r.get(key))]
        base = [r[key] for r in rows[:BASELINE] if finite(r.get(key))]
        if len(base) < BASELINE * .8 or len(valid) < 25:
            health[key] = dict(status='missing', usable=False, missing=len(rows)-len(valid), detail='Insufficient baseline or signal samples.', freshness=None)
            continue
        center = stats.median(base)
        scale = max(META[key]['scale'], stats.median(abs(v-center) for v in base) * 1.4826)
        baseline[key] = dict(center=center, scale=scale)
        missing = len(rows) - len(valid)
        tail = [r.get(key) for r in rows[-16:]]
        frozen = all(finite(v) for v in tail) and max(tail) == min(tail) and key not in ('cooling_sp', 'cooling_limit')
        gap = rows[-1]['t'] - valid[-1][0]
        status = 'frozen' if frozen else 'stale' if gap > 3 else 'missing' if missing else 'healthy'
        jumps = sum(abs(b[1]-a[1]) > 1000 * scale for a, b in zip(valid, valid[1:]))
        if jumps:
            status = 'outlier'
        health[key] = dict(status=status, usable=status=='healthy', missing=missing,
                           detail=f'{len(valid)}/{len(rows)} samples · age {gap:g}s' + (' · extreme step' if jumps else ''), freshness=gap)
        streak = []
        for row in rows[BASELINE:]:
            value = row.get(key)
            if finite(value) and abs(value - center) / scale >= 6:
                if streak and row['t'] - streak[-1] > 1.5:
                    streak = []
                streak.append(row['t'])
                if len(streak) == 4:
                    detections[key] = dict(onset=streak[0], time=row['t'], direction=1 if value>center else -1)
                    break
            else:
                streak = []
        changes[key] = round(stats.median(v for _, v in valid[-20:]) - center, 4)
    periods = [b['t']-a['t'] for a,b in zip(rows, rows[1:])]
    return dict(detections=detections, health=health, baseline=baseline, changes=changes,
                clock=dict(regular=all(abs(p-1)<.001 for p in periods), gaps=sum(p>1.5 for p in periods)))


def correlate(a, b):
    if len(a) < 4:
        return 0
    ma, mb = stats.mean(a), stats.mean(b)
    cov = sum((x-ma)*(y-mb) for x,y in zip(a,b))
    den = math.sqrt(sum((x-ma)**2 for x in a)*sum((y-mb)**2 for y in b))
    return round(cov/den, 4) if den else 0


def propagation(rows, ev):
    paths = []
    for source, target, kind in EDGES:
        a, b = ev['detections'].get(source), ev['detections'].get(target)
        if not a or not b:
            continue
        lag = b['onset'] - a['onset']
        pairs = [(r.get(source), rows[i+int(lag)].get(target)) for i,r in enumerate(rows)
                 if lag>=0 and i+int(lag)<len(rows)] if ev['clock']['regular'] else []
        pairs = [(x,y) for x,y in pairs if finite(x) and finite(y)]
        corr = correlate([p[0] for p in pairs], [p[1] for p in pairs])
        paths.append(dict(source=source,target=target,kind=kind,lag=lag,correlation=corr,
                          trusted=ev['health'][source]['usable'] and ev['health'][target]['usable']))
    return paths


def diagnose(rows):
    """Blind entry point: only timestamped observations, no labels or config."""
    ev = evidence(rows)
    d, h = ev['changes'], ev['health']
    def delta(key): return d.get(key, 0)
    def median_diff(a,b):
        vals=[r[a]-r[b] for r in rows[-30:] if finite(r.get(a)) and finite(r.get(b))]
        return stats.median(vals) if vals else None
    mismatch=median_diff('cooling_op','valve')
    feed_mismatch=median_diff('feed_op','feed_valve')
    p_disagreement=median_diff('pressure','pressure_peer')
    t_disagreement=median_diff('temperature','temperature_peer')
    oscillations=0
    values=[r['cooling_op'] for r in rows[BASELINE:] if finite(r.get('cooling_op'))]
    if len(values)>10:
        mid=(max(values)+min(values))/2
        oscillations=sum((a-mid)*(b-mid)<0 for a,b in zip(values,values[1:])) if max(values)-min(values)>15 else 0
    sep_residual=delta('separator')-.58*delta('pressure_peer')
    # A transparent weighted set of engineering observations.
    rules = {
        'cooling_valve': [('valve', mismatch is not None and mismatch>12, 42, 'Controller demand exceeds valve feedback'), ('flow', delta('flow') < -12, 28, 'Cooling flow falls'), ('temperature_peer', delta('temperature_peer')>1, 20, 'Independent reactor temperature rises'), ('pump', abs(delta('pump'))<5, 10, 'Pump speed stays within baseline')],
        'feed_valve': [('feed_valve', feed_mismatch is not None and feed_mismatch>10, 50, 'Feed demand exceeds actuator feedback'), ('feed', delta('feed')<-15, 35, 'Feed delivery falls'), ('purity', delta('purity')<-.2, 15, 'Product quality deteriorates')],
        'utility_loss': [('utility', delta('utility')>3, 55, 'Cooling supply temperature rises'), ('flow', delta('flow')<-2, 20, 'Available cooling falls'), ('valve', mismatch is not None and abs(mismatch)<5, 25, 'Cooling actuator follows demand')],
        'feed_composition': [('composition', delta('composition')>.1, 60, 'Feed analyzer composition changes'), ('temperature_peer', delta('temperature_peer')>1, 25, 'Independent temperature rises'), ('feed', abs(delta('feed'))<8, 15, 'Feed flow remains stable')],
        'reaction_rate': [('temperature_peer', delta('temperature_peer')>2, 40, 'Temperature rise on independent sensor'), ('composition', abs(delta('composition'))<.03, 20, 'Feed composition remains stable'), ('flow', delta('flow')>5, 20, 'Cooling demand and delivery increase'), ('utility', abs(delta('utility'))<1, 20, 'Cooling supply remains stable')],
        'pump_loss': [('pump', delta('pump')<-15, 45, 'Pump speed falls'), ('vibration', delta('vibration')>1, 35, 'Pump vibration increases'), ('flow', delta('flow')<-2, 20, 'Cooling flow falls')],
        'separator_restriction': [('separator', sep_residual>45, 60, 'Separator pressure exceeds upstream-driven estimate'), ('pressure_peer', delta('pressure_peer')>5, 20, 'Upstream backpressure rises'), ('purity', delta('purity')<-.3, 20, 'Separator upset reaches product quality')],
        'pressure_bias': [('pressure', p_disagreement is not None and abs(p_disagreement)>40, 65, 'Pressure transmitters disagree'), ('pressure_peer', abs(delta('pressure_peer'))<15, 35, 'Independent pressure remains stable')],
        'temperature_drift': [('temperature', t_disagreement is not None and abs(t_disagreement)>.8, 70, 'Temperature transmitters diverge'), ('cooling_op', delta('cooling_op')>3, 30, 'Controller responds to primary temperature')],
        'sensor_freeze': [('pressure', h.get('pressure',{}).get('status')=='frozen', 70, 'Primary pressure is exactly frozen'), ('pressure_peer', abs(delta('pressure_peer'))>20, 30, 'Independent pressure continues to move')],
        'controller_limit': [('cooling_limit', delta('cooling_limit')<-10, 55, 'Controller output ceiling falls'), ('cooling_op', delta('cooling_op')<-8, 25, 'Controller output is constrained'), ('temperature_peer', delta('temperature_peer')>1, 20, 'Positive temperature error persists')],
        'loop_oscillation': [('cooling_op', oscillations>=4, 70, 'Repeated large-amplitude output reversals'), ('valve', mismatch is not None and abs(mismatch)<12, 30, 'Actuator follows oscillating demand')],
    }
    paths=propagation(rows,ev)
    candidates=[]
    for fid, checks in rules.items():
        support, against, unresolved, parts=[],[],[],[]
        score=0
        for key, passes, weight, text in checks:
            dependencies = {
                ('cooling_valve','valve'): ['valve','cooling_op'],
                ('feed_valve','feed_valve'): ['feed_valve','feed_op'],
                ('utility_loss','valve'): ['valve','cooling_op'],
                ('pressure_bias','pressure'): ['pressure','pressure_peer'],
                ('temperature_drift','temperature'): ['temperature','temperature_peer'],
                ('loop_oscillation','valve'): ['valve','cooling_op'],
                ('separator_restriction','separator'): ['separator','pressure_peer'],
            }.get((fid,key),[key])
            unusable = [k for k in dependencies if not h.get(k,{}).get('usable',False)]
            usable = not unusable
            # Sensor health itself is evidence of a fault, never evidence of process causality.
            if fid=='sensor_freeze' and key=='pressure' and h.get(key,{}).get('status')=='frozen':
                usable=True
            if not usable:
                unresolved.append(' / '.join(META[k]['tag'] for k in unusable) + ': unreliable or missing evidence excluded')
                contribution=0
            elif passes:
                support.append(text)
                contribution=weight
            else:
                against.append(text+' — not observed')
                contribution=-round(weight*.35)
            parts.append(dict(signal=key,weight=weight,contribution=contribution))
            score+=contribution
        trusted_paths=[p for p in paths if p['trusted'] and p['lag']>=0 and any(p['source']==r[0] for r in checks)]
        # A small, explicit topology term cannot dominate contradictory channel evidence.
        topology=min(6,len(trusted_paths)*2)
        score=max(0,min(100,score+topology))
        candidates.append(dict(id=fid,name=FAULTS[fid],score=score,support=support,against=against,
                               unresolved=unresolved,parts=parts,topology=topology,
                               confidence='strong' if score>=80 else 'moderate' if score>=50 else 'weak'))
    candidates.sort(key=lambda c:(-c['score'],c['id']))
    leader=candidates[0]
    if not ev['detections'] and all(v['status']=='healthy' for v in h.values()):
        status='nominal'
    elif leader['score']<50:
        status='unresolved'
    elif leader['score']-candidates[1]['score']<12:
        status='ambiguous'
    else:
        status='investigating'
    next_checks=[]
    top=candidates[:2]
    for key in KEYS:
        parts=[next((p for p in c['parts'] if p['signal']==key),None) for c in top]
        value = (abs(parts[0]['weight']-parts[1]['weight']) if all(parts) and parts[0]['contribution']*parts[1]['contribution']>0 else sum(p['weight'] for p in parts if p)) + (35 if not h.get(key,{}).get('usable') else 0)
        if not any(parts): continue
        next_checks.append(dict(signal=key,tag=META[key]['tag'],value=value,
            distinguishes=[c['name'] for c in top],reason='Restore missing or unreliable evidence' if not h.get(key,{}).get('usable') else 'Independently verify the discriminator between the two leading hypotheses'))
    next_checks.sort(key=lambda c:-c['value'])
    return dict(**ev,candidates=candidates,paths=paths,status=status,nextMeasurements=next_checks[:3],
                firstDetection=min((v['time'] for v in ev['detections'].values()),default=None),
                controllers=[dict(id='TIC-101',sp=rows[-1].get('cooling_sp'),pv=rows[-1].get('temperature'),op=rows[-1].get('cooling_op'),feedback=rows[-1].get('valve'),limit=rows[-1].get('cooling_limit'),mismatch=mismatch),
                             dict(id='FIC-102',sp=100,pv=rows[-1].get('feed'),op=rows[-1].get('feed_op'),feedback=rows[-1].get('feed_valve'),limit=100,mismatch=feed_mismatch)])


ALARM_RULES=[('flow','LOW',80,'cooling'),('temperature','HIGH',124,'reactor'),('pressure','HIGH',2900,'reactor'),('pressure','HH',3050,'reactor'),('separator','HIGH',2740,'separation'),('purity','LOW',97,'separation'),('vibration','HIGH',2.5,'cooling'),('feed','LOW',85,'feed')]

def alarm_analysis(rows):
    events,conditions=[],[]
    for key,level,threshold,chain in ALARM_RULES:
        cid=f'{META[key]["tag"]}.{level}'
        active=False
        starts=[]
        spans=[]
        last_announce=-99
        for r in rows:
            if not finite(r.get(key)): continue
            hit=r[key]<threshold if level=='LOW' else r[key]>=threshold
            if hit and not active:
                starts.append(r['t']); start=r['t']
                events.append(dict(t=r['t'],condition=cid,kind='activation',chain=chain)); last_announce=r['t']
            elif hit and r['t']-last_announce>=3:
                events.append(dict(t=r['t'],condition=cid,kind='reannunciation',chain=chain)); last_announce=r['t']
            elif active and not hit:
                spans.append(r['t']-start)
                events.append(dict(t=r['t'],condition=cid,kind='return',chain=chain))
            active=hit
        if active: spans.append(rows[-1]['t']-start+1)
        if starts:
            classification='chattering' if len(starts)>=4 else 'fleeting' if max(spans)<10 else 'persistent'
            conditions.append(dict(id=cid,signal=key,chain=chain,first=starts[0],activations=len(starts),duration=sum(spans),classification=classification,
                                   events=sum(e['condition']==cid for e in events),actionable=level=='HH' or key in ('flow','vibration','feed')))
    events.sort(key=lambda e:(e['t'],e['condition']))
    floods=[]; flood_start=None
    for r in rows:
        rate=sum(r['t']-30<e['t']<=r['t'] and e['kind']!='return' for e in events)
        if rate>=10 and flood_start is None: flood_start=r['t']
        if rate<10 and flood_start is not None:
            floods.append(dict(start=flood_start,end=r['t'])); flood_start=None
    if flood_start is not None: floods.append(dict(start=flood_start,end=rows[-1]['t']))
    chains=sorted(set(c['chain'] for c in conditions))
    recommendations=[dict(condition=c['id'],kind=c['classification'],recommendation='Review deadband and on-delay; preserve safety priority.' if c['classification']=='chattering' else 'Review repeat annunciation after acknowledgement; preserve independent trip alarms.',repeats=sum(e['condition']==c['id'] and e['kind']=='reannunciation' for e in events)) for c in conditions if c['events']>3]
    return dict(events=events,conditions=conditions,floods=floods,clusters=chains,
                eventCount=len(events),uniqueConditions=len(conditions),reannunciations=sum(e['kind']=='reannunciation' for e in events),
                firstAlarm=events[0]['t'] if events else None,rationalization=recommendations)


def fit_hypothesis(rows, diagnosis):
    leader=diagnosis['candidates'][0]['id']
    onset=min((v['onset'] for v in diagnosis['detections'].values()),default=30)
    best=None
    # Fit numerical parameters to observed traces; never pass the case's ground truth.
    for start in sorted(set(max(20,int(onset)-d) for d in (0,3,6))):
        for severity in (.5,.75,1,1.25):
            c=Config(fault=leader,start=start,severity=severity)
            predicted=simulate(c)
            errors=[((r[k]-predicted[int(r['t'])][k]) / max(1,abs(META[k]['nominal'])*.05))**2
                    for r in rows if 0<=r['t']<=DURATION and int(r['t'])==r['t']
                    for k in ('flow','temperature_peer','pressure_peer','separator','feed','utility','pump','composition','pressure','valve')
                    if finite(r.get(k)) and diagnosis['health'][k]['usable']]
            rmse=math.sqrt(stats.mean(errors)) if errors else math.inf
            if best is None or rmse<best[0]: best=(rmse,c)
    return best[1], round(best[0],4)


def interventions(config):
    base=simulate(config,compact=True)
    results=[]
    for action in ACTIONS:
        trials=[]
        # Exhaustive 1s grid: no untested monotonicity assumption or binary-search shortcut.
        for t in range(BASELINE,DURATION+1):
            result=simulate(config,action['id'],t,compact=True)
            trials.append(dict(time=t,peak=result['peak'],safe=result['trip'] is None,
                               productionLoss=result['productionLoss'],qualityLoss=result['qualityLoss'],utilityCost=result['utilityCost']))
        safe=[r for r in trials if r['safe']]
        latest=safe[-1]['time'] if safe else None
        chosen=latest if latest is not None else 90
        branch=simulate(config,action['id'],chosen,compact=True)
        intervals=[]
        for r in safe:
            if not intervals or r['time']>intervals[-1][1]+1: intervals.append([r['time'],r['time']])
            else: intervals[-1][1]=r['time']
        results.append(dict(**action,latest=latest,intervals=intervals,selectedTime=chosen,margin=round(THRESHOLD-branch['peak'],2),
                            **branch, trials=trials))
    safe=[r for r in results if r['latest'] is not None]
    return dict(threshold=THRESHOLD,resolution=1,horizon=DURATION,base=base,actions=results,
                evaluated=len(ACTIONS)*(DURATION-BASELINE+1),
                safest=max(safe,key=lambda r:r['margin'])['id'] if safe else None,
                lowestLoss=min(safe,key=lambda r:(r['productionLoss'],r['severity'],r['utilityCost']))['id'] if safe else None,
                latest=max(safe,key=lambda r:r['latest'])['id'] if safe else None)


def sop_alignment(diagnosis):
    h=diagnosis['health']; c=diagnosis['controllers'][0]
    observations=[('Independent pressure available',h.get('pressure_peer',{}).get('usable',False)),
                  ('Independent temperature available',h.get('temperature_peer',{}).get('usable',False)),
                  ('Cooling actuator mismatch confirmed',h.get('valve',{}).get('usable',False) and h.get('cooling_op',{}).get('usable',False) and c['mismatch'] is not None and c['mismatch']>12)]
    return dict(id='EOP-CW-01',title='Loss of reactor cooling',revision='1.0',
                preconditions=[dict(name=n,satisfied=ok) for n,ok in observations],
                applicable=all(ok for _,ok in observations),
                action='Verify independent measurements and bypass availability before testing the cooling-recovery procedure.',
                status='Review required · no plant actuation',
                conflict='Procedure applicability is conditional on cooling-loss evidence, not on an alarm alone.')


def tool_trace(rows, diagnosis, alarms, fit=None):
    leader=diagnosis['candidates'][0]
    trace=[]
    def add(tool,args,result): trace.append(dict(index=len(trace)+1,tool=tool,args=args,result=result,status='completed'))
    add('inspect_signal_window',dict(start=rows[0]['t'],end=rows[-1]['t']),dict(samples=len(rows),health=diagnosis['health']))
    add('find_change_point',dict(baselineSamples=BASELINE,confirmation=4,zThreshold=6),diagnosis['detections'])
    add('inspect_controller',dict(controller='TIC-101'),diagnosis['controllers'][0])
    add('trace_downstream',dict(edgeTypes=['material','energy','control','feedback']),diagnosis['paths'])
    add('inspect_alarm_history',dict(windowSeconds=30,floodEvents=10),{k:alarms[k] for k in ('eventCount','uniqueConditions','clusters','floods')})
    add('compare_hypotheses',dict(candidateCount=len(FAULTS)),[dict(id=c['id'],score=c['score'],against=c['against']) for c in diagnosis['candidates'][:4]])
    if fit: add('simulate_fault',dict(hypothesis=leader['id'],parameters=asdict(fit[0])),dict(normalizedRMSE=fit[1]))
    add('query_sop',dict(procedure='EOP-CW-01'),sop_alignment(diagnosis))
    add('recommend_next_measurement',dict(competing=[c['id'] for c in diagnosis['candidates'][:2]]),diagnosis['nextMeasurements'])
    return trace


def analyze_rows(rows):
    diagnosis=diagnose(rows); alarms=alarm_analysis(rows)
    return dict(diagnosis=diagnosis,alarms=alarms,sop=sop_alignment(diagnosis),trace=tool_trace(rows,diagnosis,alarms),
                source='observed rows',schemaVersion=2)



def run_tools(rows, calls=None):
    """Validated structured tool boundary for a future model-authored plan.

    Native callers and a model can use the same {tool, args} objects. The caller
    cannot pass fault labels or replace numerical results. No external I/O tools.
    """
    validate_rows(rows)
    diagnosis=diagnose(rows)
    alarms=alarm_analysis(rows)
    defaults=tool_trace(rows, diagnosis, alarms)
    if calls is None:
        return defaults
    if not isinstance(calls,list) or not 1<=len(calls)<=16:
        raise ValueError('calls must contain 1–16 structured tool requests.')
    allowed={step['tool']:step for step in defaults}
    trace=[]
    for call in calls:
        if not isinstance(call,dict) or call.get('tool') not in allowed:
            raise ValueError('Unknown or unavailable investigation tool.')
        args=call.get('args',{})
        if not isinstance(args,dict):
            raise ValueError('Tool args must be an object.')
        name=call['tool']
        # Only signal-window inspection accepts a parameter in this version.
        if name=='inspect_signal_window':
            if set(args)-{'signal'} or args.get('signal') not in KEYS:
                raise ValueError('inspect_signal_window requires a known signal key.')
            key=args['signal']
            result={'signal':key,'samples':[{'t':r['t'],'value':r.get(key)} for r in rows],
                    'health':diagnosis['health'][key]}
        else:
            if args:
                raise ValueError('This tool accepts an empty args object.')
            result=allowed[name]['result']
        trace.append(dict(index=len(trace)+1,tool=name,args=args,result=result,status='completed'))
    return trace

def parse_csv(text):
    reader=csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or 't' not in reader.fieldnames:
        raise ValueError('CSV requires a t column in seconds; signal columns use documented keys.')
    unknown=set(reader.fieldnames)-{'t',*KEYS}
    if unknown: raise ValueError('Unknown CSV columns: '+', '.join(sorted(unknown)))
    rows=[]
    for record in reader:
        if len(rows)>=2000: raise ValueError('CSV exceeds 2000 rows.')
        try: rows.append({key:float(record[key]) if record.get(key,'').strip() else None for key in ['t',*KEYS]})
        except (ValueError,AttributeError): raise ValueError('CSV contains a nonnumeric value.') from None
    validate_rows(rows)
    return rows


def benchmark():
    records=[]
    for fid in FAULTS:
        for variant in range(3):
            config=Config(fault=fid,start=30+variant*11,severity=.65+variant*.25,noise=1+variant*.6,delay=3+variant*2,response=.8+variant*.2,operating=variant*.3,seed=variant+7)
            diag=diagnose(simulate(config)); ranking=[c['id'] for c in diag['candidates']]
            records.append(dict(fault=fid,variant=variant,top1=ranking[0]==fid,top3=fid in ranking[:3],predicted=ranking[0],
                                delay=diag['firstDetection']-config.start if diag['firstDetection'] is not None else None))
    controls=[diagnose(simulate(Config(fault='healthy',noise=n,seed=i+13))) for i,n in enumerate((.5,1,2))]
    return dict(source='TripLens reduced-order simulator',independent=False,scenarioCount=len(records),faultCoverage=len(FAULTS),
                top1=round(sum(r['top1'] for r in records)/len(records),4),top3=round(sum(r['top3'] for r in records)/len(records),4),
                medianDelay=stats.median(r['delay'] for r in records if r['delay'] is not None),healthyRuns=len(controls),
                falsePositiveRuns=sum(r['status']!='nominal' for r in controls),records=records,
                limitation='Internal varied-parameter regression, not independent validation. No Tennessee Eastman dataset has been evaluated.')


def build_platform():
    cases=[]
    for i,fid in enumerate(FAULTS):
        print(f'Computing case {i+1}/{len(FAULTS)}: {fid}',flush=True)
        rows=simulate(Config(fault=fid,seed=i+1))
        analyzed=analyze_rows(rows)
        fit=fit_hypothesis(rows,analyzed['diagnosis'])
        recovery=interventions(fit[0])
        snapshots=[]
        for end in (40,70,110,180,240):
            prefix=[r for r in rows if r['t']<=end]
            snapshots.append(dict(time=end,**analyze_rows(prefix)))
        trace=tool_trace(rows,analyzed['diagnosis'],analyzed['alarms'],fit)
        trace.append(dict(index=len(trace)+1,tool='simulate_intervention',args=dict(actions=len(ACTIONS),resolution=1),result=dict(evaluated=recovery['evaluated'],latest=recovery['latest']),status='completed'))
        analyzed['trace']=trace
        cases.append(dict(id=f'INC-{i+101}',title=f'Process session {i+1:02}',rows=rows,**analyzed,snapshots=snapshots,
                          fit=dict(hypothesis=fit[0].fault,parameters=asdict(fit[0]),error=fit[1]),recovery=recovery))
    # Historical matches use observed signal fingerprints, with no asserted root-cause labels.
    for case in cases:
        fingerprint=case['diagnosis']['changes']
        matches=[]
        for other in cases:
            if case is other: continue
            distance=sum(min(4,abs(fingerprint.get(k,0)-other['diagnosis']['changes'].get(k,0))/max(1,abs(META[k]['nominal'])*.05)) for k in KEYS)/len(KEYS)
            shared=[META[k]['tag'] for k in case['diagnosis']['detections'] if k in other['diagnosis']['detections'] and case['diagnosis']['detections'][k]['direction']==other['diagnosis']['detections'][k]['direction']]
            matches.append(dict(id=other['id'],similarity=round(max(0,1-distance/4)*100),shared=shared,leading=other['diagnosis']['candidates'][0]['name']))
        case['similar']=sorted(matches,key=lambda m:-m['similarity'])[:3]
    return dict(schemaVersion=2,model='TripLens coupled process model v2',signals=list(META.values()),edges=[dict(source=a,target=b,kind=k) for a,b,k in EDGES],
                faults=FAULTS,cases=cases,benchmark=benchmark(),limitations=['Evidence scores are not calibrated probabilities.','Counterfactuals depend on the fitted leading hypothesis and a 240-second horizon.','Local deterministic investigation policy; external model inference is not enabled.'])


if __name__=='__main__':
    target=Path(__file__).resolve().parents[1]/'src/data/platform.json'
    target.write_text(json.dumps(build_platform(),separators=(',',':'),allow_nan=False)+'\n')
    print(f'Wrote {target}')
