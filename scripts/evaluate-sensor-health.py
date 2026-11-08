"""Fixed, reproducible held-out simulation protocol; no parameter search.

Run: node scripts/python.mjs scripts/evaluate-sensor-health.py
The seeds, noise/intensity grid, thresholds and metrics below are declared before
evaluation. Development smoke cases use seed 1 or 17, never these test seeds.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from l5.models import resolve
from l5.models.tanks import integrate
from l5.sensor_health import DEFAULTS, VERSION, diagnose
from l5.sensor_health_tanks import PARAMETERS, ROLES

PROTOCOL = dict(version='sensor-health-heldout-v1', seeds=[401, 409],
    levelNoise=[.001, .003, .008], intensity=[.25, .7], baselineRange=[0, 30],
    analysisRange=[30.2, 180], sampleInterval=.2, settings=DEFAULTS,
    cases=['healthy', 'offset', 'drift', 'stuck', 'spike', 'dropout', 'noise',
           'pump_degradation', 'valve_restriction', 'tank_leak'])


def case(kind, seed, noise, intensity):
    model = resolve('coupled-tanks')
    rng = np.random.default_rng(seed)
    onset = float(rng.integers(350, 450))*.2
    process = kind in ('pump_degradation', 'valve_restriction', 'tank_leak')
    c = model.validate(dict(fault=kind if process else 'healthy', start=onset,
        duration=180, step=.2, noise=noise, severity=intensity, seed=seed))
    if kind == 'stuck':
        # A declared, observed command change excites the system before freezing.
        rows = integrate(c, 'adjust_pump', onset-8, dict(pumpControl=145))[0]
    else:
        rows = model.simulate(c)
    names = list(ROLES)
    times = np.asarray([r['t'] for r in rows])
    values = np.asarray([[r[s] for s in names] for r in rows])
    selected = times >= onset
    signal = names.index('level2')
    if kind == 'offset':
        values[selected, signal] += .3*intensity
    elif kind == 'drift':
        values[selected, signal] += .004*intensity*(times[selected]-onset)
    elif kind == 'stuck':
        values[selected, signal] = values[np.flatnonzero(selected)[0], signal]
    elif kind == 'spike':
        positions = np.flatnonzero(selected)[::125]
        values[positions, signal] += .5*intensity
    elif kind == 'dropout':
        positions = np.flatnonzero(selected)
        # Intermittent 2-second outages, not deletion of timestamp rows.
        values[positions[(np.arange(len(positions)) % 100) < 10], signal] = np.nan
    elif kind == 'noise':
        values[selected, signal] += rng.normal(0, .05*intensity, int(selected.sum()))
    return times, values, names, onset


def evaluate(kind, seed, noise, intensity):
    times, values, names, onset = case(kind, seed, noise, intensity)
    config = dict(**DEFAULTS, signals=names, baselineRange=PROTOCOL['baselineRange'],
        analysisRange=PROTOCOL['analysisRange'], model=dict(kind='coupled-tanks',
            mapping={s:s for s in names}, parameters=PARAMETERS.copy()))
    result = diagnose(times, values, names, config)
    pre = np.asarray(result['times']) < onset
    alarms = np.zeros(len(result['times']), bool)
    for episode in result['episodes']:
        alarms |= (np.asarray(result['times']) >= episode['start']) & (np.asarray(result['times']) <= episode['end'])
    # An episode may already be active after a legitimate excitation. Measure
    # new confirmed indicator intervals, rather than losing later detections
    # when the union of indicators is one continuous episode.
    detected = [s['detectedAt'] for i in result['indicators'] for s in i['intervals'] if s['detectedAt'] >= onset]
    # Dominant interval by evaluated duration, with abstention retained as an outcome.
    after = [e for e in result['episodes'] if e['end'] >= onset]
    dominant = max(after, key=lambda e: e['samples'], default=None)
    assessment = dominant['assessment'] if dominant else 'normal'
    best = dominant['candidates'][0]['key'] if dominant and dominant['candidates'] else None
    expected_indicator = dict(offset='level_shift', drift='drift', stuck='stuck', spike='spike', dropout='dropout', noise='noise').get(kind)
    identified = expected_indicator is not None and any(i['kind'] == expected_indicator and 'level2' in i['signals'] and any(s['end'] >= onset for s in i['intervals']) for i in result['indicators'])
    return dict(case=kind, seed=seed, noise=noise, intensity=intensity, onset=onset,
        detected=bool(detected), delaySeconds=min(detected)-onset if detected else None,
        falseAlarmSamples=int((alarms & pre).sum()), preFaultSamples=int(pre.sum()),
        healthyAlarmSamples=int(alarms.sum()) if kind == 'healthy' else None,
        analysisSamples=len(alarms), assessment=assessment, leadingHypothesis=best,
        sensorTypeAndChannelIdentified=identified if expected_indicator else None)


def summarize(rows):
    sensor_kinds = {'offset', 'drift', 'stuck', 'spike', 'dropout', 'noise'}
    confusion = {kind: {k: 0 for k in ('sensor', 'process', 'insufficient_evidence', 'normal')} for kind in ('sensor', 'process', 'healthy')}
    for r in rows:
        truth = 'sensor' if r['case'] in sensor_kinds else 'healthy' if r['case'] == 'healthy' else 'process'
        confusion[truth][r['assessment']] += 1
    faults = [r for r in rows if r['case'] != 'healthy']
    identified = [r for r in rows if r['case'] in sensor_kinds]
    healthy = [r for r in rows if r['case'] == 'healthy']
    delays = [r['delaySeconds'] for r in faults if r['delaySeconds'] is not None]
    return dict(runs=len(rows), detectedFaultRuns=sum(r['detected'] for r in faults), faultRuns=len(faults),
        medianDetectionDelaySeconds=float(np.median(delays)) if delays else None,
        sensorTypeAndChannelAccuracy=sum(r['sensorTypeAndChannelIdentified'] for r in identified)/len(identified) if identified else None,
        preFaultFalseAlarmFraction=sum(r['falseAlarmSamples'] for r in rows)/sum(r['preFaultSamples'] for r in rows),
        healthyAlarmFraction=sum(r['healthyAlarmSamples'] for r in healthy)/sum(r['analysisSamples'] for r in healthy) if healthy else None,
        confusion=confusion)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='docs/sensor-health-evaluation.json')
    args = parser.parse_args()
    results = []
    for noise in PROTOCOL['levelNoise']:
        for intensity in PROTOCOL['intensity']:
            for seed in PROTOCOL['seeds']:
                for kind in PROTOCOL['cases']:
                    results.append(evaluate(kind, seed, noise, intensity))
            print(f"Completed noise={noise}, intensity={intensity}", flush=True)
    payload = dict(engineVersion=VERSION, protocol=PROTOCOL, summary=summarize(results),
        byNoise={str(n): summarize([r for r in results if r['noise'] == n]) for n in PROTOCOL['levelNoise']},
        byIntensity={str(n): summarize([r for r in results if r['intensity'] == n]) for n in PROTOCOL['intensity']},
        results=results)
    Path(args.output).write_text(json.dumps(payload, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps(payload['summary'], indent=2))


if __name__ == '__main__':
    main()
