"""Fixed Mode 1 cooling-water experiment using ordinary workspace datasets."""
import csv
import io
import json
from uuid import NAMESPACE_URL, uuid5
import threading
import time

import numpy as np

from simulation.tep import MODEL, SIGNALS, describe_columns, executable, simulate
from .datasets import prepare_csv


LOCK = threading.Lock()
ACTIVE = {}
DIAGNOSIS = 'tep-profile-residual-v2'
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
            folder = store.root / wid / 'datasets' / dataset['id']
            if all((folder / name).is_file() for name in ('series.npz', 'source.csv')):
                found.setdefault(process['role'], dataset)
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
    # Restore missing source files under their original identity when the generator matches.
    for dataset in store.datasets(wid):
        process = dataset['metadata'].get('processRun', {})
        if all(process.get(key) == meta['processRun'][key] for key in
               ('protocol', 'role', 'modelVersion', 'compiler', 'seed', 'fault', 'gain10MultiplierAfter8h')):
            folder = store.root / wid / 'datasets' / dataset['id']
            folder.mkdir(parents=True, exist_ok=True)
            series = folder / 'series.npz'
            csv_path = folder / 'source.csv'
            if not series.exists():
                temporary = folder / 'restore.npz'
                np.savez_compressed(temporary, times=times, values=values)
                temporary.replace(series)
            if not csv_path.exists():
                temporary = folder / 'restore.csv'
                temporary.write_text(source, encoding='utf-8')
                temporary.replace(csv_path)
            found[role] = dataset
            return
    found[role] = store.save_dataset(wid, 'TEP · ' + role, meta, times, values, source)


def event_intervals(end):
    return [dict(kind='normal', start=180., end=ONSET),
            dict(kind='anomaly', start=ONSET+180., end=float(end), onset=ONSET)]


def diagnose(times, observations, alarm, references, center, factor, duration=3600, lookback=1800):
    """Profile each reference over sampled onsets preceding the observed alarm."""
    window = (times >= alarm - lookback) & (times < alarm + duration)
    ticks, observed = times[window], observations[window]
    def rms(expected):
        residual = np.linalg.solve(factor, (observed - expected).T)
        return float(np.sqrt(np.sum(residual**2) / len(ticks)))
    distances, onsets = {'normal': rms(center)}, {}
    for role, (ages, values) in references.items():
        candidates = []
        for onset in ticks[ticks <= alarm]:
            indexes = np.searchsorted(ages, ticks - onset)
            if np.any(indexes >= len(ages)) or not np.array_equal(ages[indexes], ticks - onset):
                continue
            candidates.append((rms(values[indexes]), float(onset)))
        if not candidates:
            raise ValueError('Reference trajectories do not cover the observed sample grid.')
        distances[role], onsets[role] = min(candidates)
    return dict(hypothesis=min(distances, key=distances.get), distances=distances,
                estimatedOnsets=onsets, start=float(ticks[0]), cutoff=float(ticks[-1]),
                alarm=alarm, samples=len(ticks), version=DIAGNOSIS)


def supplemental_evidence(store, found, analysis):
    def load(role):
        t, x = store.load_data(found[role])
        return np.column_stack((t, x))

    original = load('evaluation')
    times = original[:, 0]
    post = times > ONSET
    first = analysis['summary']['firstDetection']
    diagnosis, evidence = None, []
    if first is not None:
        references = {}
        for role in ('reactor-reference', 'condenser-reference'):
            ref = load(role)
            references[role] = ref[:, 0] - found[role]['metadata']['processRun']['onsetSeconds'], ref[:, CHANNELS]
        diagnosis = diagnose(times, original[:, CHANNELS], first, references, analysis['model']['center'],
                             np.linalg.cholesky(analysis['model']['covariance']))
        for row in original[(times >= diagnosis['start']) & (times <= diagnosis['cutoff'])]:
            evidence.append(dict(seconds=float(row[0]), observations=dict(zip(KEYS, row[CHANNELS].tolist()))))
    comparison = {}
    for role in ('evaluation', 'intervention'):
        r = load(role)
        if not np.array_equal(r[:, 0], times):
            raise ValueError('The paired intervention requires matching sample times.')
        comparison[role] = dict(reactorTemperatureMAE=float(np.mean(abs(r[post, 9]-120.4))),
            coolingValveTravel=float(np.sum(abs(np.diff(r[times >= ONSET, 51])))),
            peakReactorPressure=float(r[post, 7].max()), pressureSamplesAbove3000=int((r[post, 7]>3000).sum()),
            runtimeSeconds=found[role]['metadata']['processRun']['runtimeSeconds'])
    dataset_meta = found['evaluation']['metadata']
    quality = {k:dataset_meta['quality'][k] for k in ('timedCount', 'typicalInterval', 'gapCount', 'duplicateCount')}
    quality['missingValues'] = dataset_meta['missingCount']
    return dict(measurementQuality=quality, diagnosticObservations=evidence, diagnosis=diagnosis,
        assumptions=["The first confirmed alarm triggers a 30-minute onset search and one hour of follow-up.",
                     "Distances are RMS whitened trajectory residuals. The normal hypothesis uses the fitted center.",
                     "Counterfactual and evaluation share initialization and noise seed. Valve travel uses sampled commands."],
        protocol=DIAGNOSIS,
        comparison=comparison,
        sources={k:dict(datasetId=v['id'], **v['metadata']['processRun']) for k,v in found.items()})


def saved_evidence(store, run_id):
    with store.connect() as db:
        row = db.execute('SELECT payload FROM industrial_evidence WHERE run_id=?', (run_id,)).fetchone()
    return json.loads(row[0]) if row else None


def study(store, wid, stage=None):
    if stage is None:
        active = ACTIVE.get(wid)
        result = study_records(store, wid, None)
        if active or wid in ACTIVE:
            result['activeStage'] = active or ACTIVE.get(wid)
        return result
    with LOCK:
        ACTIVE[wid] = stage
        try:
            return study_records(store, wid, stage)
        finally:
            ACTIVE.pop(wid, None)


def study_records(store, wid, stage):
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
    result = dict(signals=KEYS, datasets={k:v['id'] for k,v in found.items()})
    if set(CASES) <= found.keys():
        investigation = integrate(store, wid, found, stage == 'investigation')
        result.update(investigation)
    return result


def integrate(store, wid, found, execute):
    service = store.experiments
    sources = {role: found[role]['id'] for role in CASES}
    context = dict(protocol=DIAGNOSIS, modelVersion=MODEL, sources=sources)

    def interval(role):
        axis = found[role]['metadata']['time']
        return [axis['start'], axis['end']]

    labels = next((item for item in service.label_sets(sources['evaluation']) if item['source'] == PROTOCOL), None)
    if labels is None:
        return {}
    config = dict(datasetId=sources['evaluation'], signals=KEYS, analysisRange=interval('evaluation'),
                  training={role: dict(datasetId=sources[role], range=interval(role)) for role in ('fit', 'calibration')},
                  persistence=2, minCoverage=1., labelSetId=labels['id'], algorithms=[dict(algorithm='mahalanobis')],
                  industrialStudy=context)
    expected, _ = service.validate(wid, config)
    experiment = next((e for e in service.list(wid) if e['config'] == expected), None)
    if experiment is None:
        if not execute:
            return {}
        experiment = service.save(wid, dict(name='Mode 1 cooling-water investigation', config=config,
            description='Independent normal fit and calibration, reactor inlet step and paired half-gain intervention.'))
    run = detection_run(service, experiment, expected, execute)
    if run is None:
        return dict(experimentId=experiment['id'])
    task = run['tasks'][0]
    analysis = store.result(task['result_id'])
    return investigation_result(store, wid, found, run, analysis, execute)


def detection_run(service, experiment, expected, execute):
    runs = service.runs(experiment['id'])
    completed = (service.run(r['id']) for r in reversed(runs) if r['status'] == 'completed')
    run = next((r for r in completed if r['snapshot']['config'] == expected), None)
    if not run:
        if not execute:
            return None
        active = next((r for r in runs if r['status'] in ('queued', 'running')), None)
        run = service.run(active['id']) if active else service.execute(experiment['id'], {}, expected_revision=experiment['revision'])
        while run['status'] in ('queued', 'running'):
            time.sleep(.05)
            run = service.run(run['id'])
        if run['status'] != 'completed':
            raise ValueError(run['tasks'][0]['error'] or 'Cooling-water analysis interrupted. Run the study to resume.')
    return run


def investigation_result(store, wid, found, run, analysis, execute):
    task = run['tasks'][0]
    sources = analysis['config']['industrialStudy']['sources']
    evidence = saved_evidence(store, run['id'])
    if evidence is None:
        if not execute:
            return {}
        evidence = supplemental_evidence(store, found, analysis)
        with store.connect() as db:
            db.execute('INSERT INTO industrial_evidence VALUES (?,?)', (run['id'], json.dumps(evidence, allow_nan=False)))
    diagnosis = evidence['diagnosis']
    report = dict(**evidence, signals=KEYS, definitions=SIGNALS, threshold=analysis['threshold'],
                  signatureDistances=diagnosis['distances'] if diagnosis else {}, detection=task['metrics']['detection'])
    incident_id = uuid5(NAMESPACE_URL, DIAGNOSIS + '/' + analysis['id']).hex
    result = dict(analysisId=analysis['id'], experimentId=run['experiment_id'], runId=run['id'])
    try:
        store.incidents.row(incident_id)
    except KeyError:
        if not execute:
            return result
        links = [dict(kind='dataset', datasetId=sources['evaluation']), dict(kind='analysis', analysisId=analysis['id'])]
        event = analysis['intervals'][0] if analysis['intervals'] else {}
        if event:
            links.append(dict(kind='interval', analysisId=analysis['id'], intervalIndex=0))
        links.append(dict(kind='dataset', datasetId=sources['intervention']))
        diag = report['diagnosis']
        entries = []
        if diag:
            for role in diag['distances']:
                entries.append(dict(kind='hypothesis', title=role.replace('-reference', ' cooling water'),
                    content="Compared against the five measured channels over the aligned observation window. See the investigation report for residuals.",
                    observed_at=diag['cutoff'], observed_axis_key='dataset:' + sources['evaluation']))
        entries.append(dict(kind='evidence', title='Matched control intervention',
            content='The counterfactual halves the reactor cooling-loop gain at the scheduled switch. The report compares tracking error, sampled valve travel and peak pressure.',
            observed_at=float(found['intervention']['metadata']['time']['end']), observed_axis_key='dataset:' + sources['intervention']))
        store.incidents.create(wid, dict(title='Tennessee Eastman cooling-water event',
            description='Mode 1 closed-loop simulation. The linked alarm and measurements use seconds from initialization.',
            conclusion='Closest trajectory: ' + diag['hypothesis'] if diag else 'No confirmed alarm.',
            start_time=event.get('start'), end_time=event.get('end')), identity=incident_id, sources=links, entries=entries)
    result['incidentId'] = incident_id
    report.update(records=result.copy(), detector=analysis['algorithmLabel'], alarmIntervals=analysis['intervals'])
    return dict(**result, report=report)
