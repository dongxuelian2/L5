"""Fixed Mode 1 cooling-water experiment using ordinary workspace datasets."""
import csv
import io
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
import threading
import time

import numpy as np

from simulation.tep import MODEL, SIGNALS, describe_columns, executable, simulate
from .datasets import prepare_csv
from .detection_metrics import detection_metrics

LOCK = threading.Lock()
PROTOCOL = 'tep-cooling-v1'
ONSET = 28800
# Native row is [elapsed seconds, XMEAS(1..41), XMV(1..11)].
CHANNELS = [9, 21, 22, 51, 52]
KEYS = [SIGNALS[i-1]['name'] for i in CHANNELS]
CASES = {
    'fit': (0, 4243534565, 1.), 'calibration': (0, 1254545354, 1.),
    'reactor-reference': (4, 4346024432, 1.), 'condenser-reference': (5, 5784921734, 1.),
    'evaluation': (4, 4598956239, 1.), 'intervention': (4, 4598956239, .5),
}


def records(store, wid):
    found = {}
    for dataset in store.datasets(wid):
        process = dataset['metadata'].get('processRun', {})
        if process.get('protocol') == PROTOCOL and process.get('modelVersion') == MODEL:
            found[process['role']] = dataset
    return found


def save(store, wid, binary, compiler, role, found):
    if role in found:
        return
    fault, seed, gain = CASES[role]
    rows, cost = simulate(binary, fault, seed, gain)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['t', *(s['name'] for s in SIGNALS)])
    writer.writerows(rows)
    source = output.getvalue()
    meta, times, values = prepare_csv(source, dict(timeColumn='t', timeKind='numeric', timeUnit='seconds'))
    describe_columns(meta['columns'])
    meta['processRun'] = dict(plant='Tennessee Eastman', model='Russell–Chiang–Braatz', modelVersion=MODEL,
        protocol=PROTOCOL, studyId=f'{wid}/{PROTOCOL}/{MODEL[:12]}', role=role, seed=seed,
        initialState='TEINIT mode 1', controller='temain_mod multi-rate velocity PI',
        gain10MultiplierAfter8h=gain, fault=fault, onsetSeconds=ONSET if fault else None,
        type='counterfactual simulation' if role == 'intervention' else 'dynamic simulation',
        stepSeconds=1, sampleSeconds=180, clock='Driver tick from initialization; recorded before integration.',
        compiler=compiler, **cost)
    found[role] = store.save_dataset(wid, 'TEP · ' + role, meta, times, values, source)


def event_intervals(end):
    return [dict(kind='normal', start=180., end=ONSET),
            dict(kind='anomaly', start=ONSET+180., end=float(end), onset=ONSET)]


def summarize(store, found):
    def load(role):
        t, x = store.load_data(found[role])
        return np.column_stack((t, x))

    fit = load('fit')[:, CHANNELS]
    mean = fit.mean(axis=0)
    factor = np.linalg.cholesky(np.cov(fit.T))
    def whiten(x):
        return np.linalg.solve(factor, (x - mean).T).T
    def score(rows):
        z = whiten(rows[:, CHANNELS])
        return np.sum(z*z, axis=1)
    limit = float(np.quantile(score(load('calibration')), .99, method='higher'))
    original = load('evaluation')
    times = original[:, 0]
    post = times > ONSET
    start = time.perf_counter()
    scores = score(original)
    exceed = scores > limit
    alarms = exceed & np.r_[False, exceed[:-1]]
    elapsed = time.perf_counter()-start
    labels = event_intervals(times[-1])
    detection = detection_metrics(dict(times=times, states=np.where(alarms, 'alarm', 'normal')),
                                  dict(intervals=labels), gap_threshold=270)
    # Compare averages over the first hour after a confirmed alarm to reference signatures.
    first = float(times[alarms][0]) if alarms.any() else None
    distance = {}
    evidence = []
    if first is not None:
        window = (times >= first) & (times < first + 3600)
        for row in original[window]:
            evidence.append(dict(seconds=float(row[0]), observations=dict(zip(KEYS, row[CHANNELS].tolist()))))
        for role in ('reactor-reference', 'condenser-reference'):
            ref = load(role)
            expected = ref[(times > ONSET) & (times <= ONSET+3600), :][:, CHANNELS].mean(0)
            delta = original[window, :][:, CHANNELS].mean(0) - expected
            distance[role] = float(np.linalg.norm(np.linalg.solve(factor, delta)))
    comparison = {}
    for role in ('evaluation', 'intervention'):
        r = load(role)
        comparison[role] = dict(reactorTemperatureMAE=float(np.mean(abs(r[post, 9]-120.4))),
            coolingValveTravel=float(np.sum(abs(np.diff(r[times >= ONSET, 51])))),
            peakReactorPressure=float(r[post, 7].max()), pressureSamplesAbove3000=int((r[post, 7]>3000).sum()),
            runtimeSeconds=found[role]['metadata']['processRun']['runtimeSeconds'])
    dataset_meta = found['evaluation']['metadata']
    quality = {k:dataset_meta['quality'][k] for k in ('timedCount', 'typicalInterval', 'gapCount', 'duplicateCount')}
    quality['missingValues'] = dataset_meta['missingCount']
    return dict(measurementQuality=quality, diagnosticObservations=evidence, alarmTimesSeconds=times[alarms].tolist(), assumptions=[
        "Independent normal seeds fit the covariance and calibrate the 99th percentile.",
        "Distances compare the first hour from the first confirmed alarm to two independent simulated signatures.",
        "The intervention changes only the cooling-loop gain at 8 h. Valve travel and pressure limits use 180 s samples."],
        protocol=PROTOCOL, signals=KEYS, definitions=SIGNALS, threshold=limit, score='Squared Mahalanobis distance',
        covariance=np.cov(fit.T).tolist(), center=mean.tolist(), scoringSeconds=elapsed, persistenceSamples=2,
        labels=labels, detection=detection, signatureDistances=distance, comparison=comparison,
        sources={k:dict(datasetId=v['id'], **v['metadata']['processRun']) for k,v in found.items()})


def study(store, wid, stage=None):
    with LOCK:
        found = records(store, wid)
        if stage:
            roles = ('fit', 'calibration', 'evaluation') if stage == 'measurements' else tuple(CASES)
            if any(k not in found for k in roles):
                binary, compiler = executable(store.root / 'tep-build')
                for role in roles:
                    save(store, wid, binary, compiler, role, found)
        if stage and 'evaluation' in found:
            dataset = found['evaluation']
            if not any(v['source'] == PROTOCOL for v in store.experiments.label_sets(dataset['id'])):
                store.experiments.save_labels(dataset['id'], dict(name='Reactor coolant inlet step',
                    timeBasis='dataset-seconds', timeSource='Scenario IDV(4) after driver tick 28800.',
                    intervals=event_intervals(dataset['metadata']['time']['end'])),
                    source=PROTOCOL, provenance=dataset['metadata']['processRun'])
        result = dict(datasets={k:v['id'] for k,v in found.items()})
        if set(CASES) <= found.keys():
            path = store.root / wid / f'{PROTOCOL}-{MODEL[:12]}.json'
            if path.exists():
                report = json.loads(path.read_text(encoding='utf-8'))
                if {k:v['datasetId'] for k,v in report['sources'].items()} == result['datasets']:
                    return dict(**result, report=report)
            result['report'] = summarize(store, found)
            payload = json.dumps(result['report'], allow_nan=False)
            with NamedTemporaryFile(mode='w', dir=path.parent, encoding='utf-8', delete=False) as temp:
                temp.write(payload)
            try:
                os.replace(temp.name, path)
            finally:
                Path(temp.name).unlink(missing_ok=True)
        return result
