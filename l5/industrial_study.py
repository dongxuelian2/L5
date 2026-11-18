"""Connect executable process runs to the existing investigation records."""
import json
from uuid import NAMESPACE_URL, uuid5
import time

import numpy as np

from simulation import cstr
from simulation.tep import executable, simulate
from .datasets import prepare_numeric
from .plants import TEP, TEP_CHANNELS as CHANNELS, SCENARIOS, run_id, run_key, settings


DIAGNOSIS = 'tep-profile-residual-v2'
PLANT_PROTOCOL = 'plant-profile-residual-v1'
DEFAULT = SCENARIOS['reactor-cooling']
ONSET = DEFAULT.onset


def cases(scenario, config):
    p = scenario.plant
    normal = 0 if p is TEP else 'normal'
    return dict(fit=(normal, p.fit_seed, 1.), calibration=(normal, p.calibration_seed, 1.),
                **{role: (*case, 1.) for role, case in p.references.items()},
                evaluation=(scenario.fault, config['seed'], 1.),
                intervention=(scenario.fault, config['seed'], config.get('gain', True)))


CASES = cases(DEFAULT, settings(DEFAULT))


def records(store, wid, key):
    found = {}
    for dataset in store.datasets(wid):
        process = dataset['metadata'].get('processRun', {})
        if process.get('studyId') == key and data_file(store, dataset).is_file():
            found.setdefault(process['role'], dataset)
    return found


def data_file(store, dataset):
    return store.root / dataset['workspace_id'] / 'datasets' / dataset['id'] / 'series.npz'


def save(store, wid, scenario, config, key, role, case, observe, check, existing_compiler=None):
    p = scenario.plant
    fault, seed, action = case
    duration, onset, switch = (config[k] for k in ('durationSeconds', 'onsetSeconds', 'interventionSeconds'))
    options = dict(duration=duration, onset=onset, intervention_at=switch, observe=observe, check=check)
    extra = {}
    if p is TEP:
        states = []
        loop = 11 if scenario.fault == 5 else 10
        binary, compiler = executable(store.root / 'tep-build')
        if existing_compiler is not None and compiler != existing_compiler:
            raise ValueError('Resume with the original GNU Fortran version or change the evaluation seed to start a new study.')
        rows, cost = simulate(binary, fault, seed, action, gain_loop=loop, states=states, **options)
        solver = dict(compiler=compiler, method='Reference Euler', stepSeconds=1,
                      controllerLoop=loop, gainMultiplier=action, initialState='TEINIT mode 1',
                      stateSchema='Native YY(1..50) from teprob.f')
        extra['states'] = np.asarray(states)
        cost['sampledLimits'] = dict(
            peakReactorPressureKPaGauge=float(rows[:, 7].max()),
            peakReactorTemperatureC=float(rows[:, 9].max()),
            valveCommandsOutsideLimits=int(((rows[:, 42:] < 0) | (rows[:, 42:] > 100)).sum()))
        has_event = fault != 0
    else:
        rows, cost, states = cstr.simulate(fault, seed, control=role == 'intervention', **options)
        solver = dict(method='Fixed-step RK4', stepSeconds=1, initialState=states[0].tolist(),
                      stateSchema='A₁, B₁, T₁, A₂, B₂, T₂ in mol/m³ and K',
                      jacketPI=role == 'intervention')
        extra['states'] = states
        has_event = fault != 'normal'
    process = dict(plant=p.name, plantId=p.id, modelVersion=p.version, scenario=scenario.id,
        protocol=PLANT_PROTOCOL, studyId=key, operationId=run_id(key), role=role, seed=seed, fault=fault,
        onsetSeconds=onset if has_event else None, interventionSeconds=switch if role == 'intervention' else None,
        durationSeconds=duration, controller=p.mode, limits=p.limits, sampleSeconds=p.sample,
        clock='Observation ticks in seconds from initialization.',
        type='counterfactual simulation' if role == 'intervention' else 'dynamic simulation', **solver, **cost)
    process['sequenceId'] = f'{p.id}/{p.version}/{seed}/{fault}/{duration}/{onset}/{switch}/{action}'
    process['randomStreamId'] = f'{p.id}/{p.version}/{seed}'
    if check:
        check()
    for dataset in store.datasets(wid):
        previous = dataset['metadata'].get('processRun', {})
        if previous.get('sequenceId') == process['sequenceId'] and previous.get('studyId') == key:
            if previous.get('role') != role or previous.get('compiler') != process.get('compiler'):
                continue
            series = data_file(store, dataset)
            series.parent.mkdir(parents=True, exist_ok=True)
            _, times, values, observed = prepare_numeric(rows[:, 0], rows[:, 1:], p.signals)
            temporary = series.with_suffix('.restore.npz')
            np.savez_compressed(temporary, times=times, values=values, **extra, observed=observed)
            temporary.replace(series)
            return dataset
    return store.save_numeric(wid, f'{scenario.title} · {role}', rows[:, 0], rows[:, 1:], p.signals,
                              provenance={'processRun': process}, extra_arrays=extra)


def event_intervals(start, end, onset, sample):
    return [dict(kind='normal', start=start, end=onset),
            dict(kind='anomaly', start=onset+sample, end=end, onset=onset)]


def diagnose(times, observations, alarm, references, center, factor, duration=3600, lookback=1800,
             version=DIAGNOSIS):
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
                alarm=alarm, samples=len(ticks), version=version)


def supplemental_evidence(store, scenario, config, found, analysis):
    plant = scenario.plant
    channels = list(plant.channels)
    keys = [plant.signals[i-1]['name'] for i in channels]
    onset = config['onsetSeconds']
    def load(role):
        t, x = store.load_data(found[role])
        return np.column_stack((t, x))

    original = load('evaluation')
    times = original[:, 0]
    post = times > onset
    first = analysis['summary']['firstDetection']
    diagnosis, evidence = None, []
    if first is not None:
        references = {}
        for role in plant.references:
            ref = load(role)
            references[role] = ref[:, 0] - onset, ref[:, channels]
        diagnosis = diagnose(times, original[:, channels], first, references, analysis['model']['center'],
                             np.linalg.cholesky(analysis['model']['covariance']), plant.followup,
                             plant.lookback, PLANT_PROTOCOL)
        for row in original[(times >= diagnosis['start']) & (times <= diagnosis['cutoff'])]:
            evidence.append(dict(seconds=float(row[0]), observations=dict(zip(keys, row[channels].tolist()))))
    comparison = {}
    condenser = scenario.id == 'condenser-cooling'
    comparison_columns = (
        dict(stripperFlowMAE='Stripper underflow MAE (m³/h)', coolingValveTravel='Condenser valve travel (pp)',
             peakReactorPressure='Peak reactor pressure (kPa gauge)', pressureSamplesAbove3000='Samples above 3000 kPa gauge')
        if condenser else
        dict(reactorTemperatureMAE='Reactor temperature MAE (°C)', coolingValveTravel='Cooling valve travel (pp)',
             peakReactorPressure='Peak reactor pressure (kPa gauge)', pressureSamplesAbove3000='Samples above 3000 kPa gauge')
        if plant is TEP else
        dict(reactorTemperatureMAE='Reactor 1 temperature MAE (K)', jacketTravel='Jacket command travel (K)',
             peakTemperature='Peak Reactor 1 temperature (K)', temperatureSamplesAbove335='Samples above 335 K',
             finalConversionPercent='Final A conversion (%)'))
    for role in ('evaluation', 'intervention'):
        r = load(role)
        if not np.array_equal(r[:, 0], times):
            raise ValueError('The paired intervention requires matching sample times.')
        if not np.array_equal(r[times < config['interventionSeconds']], original[times < config['interventionSeconds']]):
            raise ValueError('The paired intervention must share the pre-intervention observations.')
        if condenser:
            comparison[role] = dict(stripperFlowMAE=float(np.mean(abs(r[post, 17]-22.949))),
                coolingValveTravel=float(np.sum(abs(np.diff(r[times >= onset, 52])))),
                peakReactorPressure=float(r[post, 7].max()), pressureSamplesAbove3000=int((r[post, 7]>3000).sum()))
        elif plant is TEP:
            comparison[role] = dict(reactorTemperatureMAE=float(np.mean(abs(r[post, 9]-120.4))),
                coolingValveTravel=float(np.sum(abs(np.diff(r[times >= onset, 51])))),
                peakReactorPressure=float(r[post, 7].max()), pressureSamplesAbove3000=int((r[post, 7]>3000).sum()))
        else:
            with np.load(data_file(store, found[role]), allow_pickle=False) as data:
                state = data['states']
            feed_a = cstr.FEED[0] * (.92 if scenario.fault == 'lean-feed' else 1.)
            comparison[role] = dict(reactorTemperatureMAE=float(np.abs(state[post, 2] - state[0, 2]).mean()),
                jacketTravel=float(np.abs(np.diff(r[times >= onset, 7])).sum()),
                peakTemperature=float(state[post, 2].max()), temperatureSamplesAbove335=int((state[post, 2] > 335).sum()),
                finalConversionPercent=float(100 * (1 - state[-1, 3] / feed_a)))
    dataset_meta = found['evaluation']['metadata']
    quality = {k:dataset_meta['quality'][k] for k in ('timedCount', 'typicalInterval', 'gapCount', 'duplicateCount')}
    quality['missingValues'] = dataset_meta['missingCount']
    return dict(measurementQuality=quality, diagnosticObservations=evidence, diagnosis=diagnosis,
        title=scenario.title, plant=plant.name, scenarioId=scenario.id, intervention=scenario.comparison,
        comparisonColumns=comparison_columns, settings=config,
        assumptions=[f"The first confirmed alarm triggers an onset search over {plant.lookback} s and a follow-up of up to {plant.followup} s.",
                     "Distances are RMS whitened trajectory residuals. The normal hypothesis uses the fitted center.",
                     "Counterfactual and evaluation share initialization, disturbance and noise seed. Actuator travel uses sampled commands."],
        protocol=PLANT_PROTOCOL,
        comparison=comparison,
        sources={k:dict(datasetId=v['id'], **v['metadata']['processRun']) for k,v in found.items()})


def saved_evidence(store, run_id):
    with store.connect() as db:
        row = db.execute('SELECT payload FROM industrial_evidence WHERE run_id=?', (run_id,)).fetchone()
    return json.loads(row[0]) if row else None


def run_report(evidence, analysis, task, definitions, records):
    diagnosis = evidence['diagnosis']
    return dict(**evidence, signals=analysis['config']['signals'], definitions=definitions,
                threshold=analysis['threshold'], signatureDistances=diagnosis['distances'] if diagnosis else {},
                detection=task['metrics']['detection'], detector=analysis['algorithmLabel'],
                alarmIntervals=analysis['intervals'], records=records)


def study(store, wid, stage=None, *, scenario=DEFAULT, config=None, progress=None, observe=None, check=None):
    config = settings(scenario, config)
    key = f'{wid}/{run_key(scenario, config)}'
    if stage:
        with store.plants.study_lock(key):
            return study_records(store, wid, stage, scenario, config, key, progress, observe, check)
    return study_records(store, wid, stage, scenario, config, key, progress, observe, check)


def study_records(store, wid, stage, scenario, config, key, progress, observe, check):
    selected_cases = cases(scenario, config)
    found = records(store, wid, key)
    signals = [scenario.plant.signals[i-1]['name'] for i in scenario.plant.channels]
    if stage:
        roles = ('evaluation',) if stage == 'measurements' else (
            'evaluation', 'fit', 'calibration', *scenario.plant.references, 'intervention')
        for role in roles:
            if check:
                check()
            if role not in found:
                if progress:
                    progress('running' if role == 'evaluation' else 'measurements_available', role=role)
                existing_compiler = next((r['metadata']['processRun'].get('compiler') for r in found.values()), None)
                found[role] = save(store, wid, scenario, config, key, role, selected_cases[role],
                                   observe if role == 'evaluation' else None, check, existing_compiler)
            if progress and role == 'evaluation':
                meta = found['evaluation']['metadata']
                progress('measurements_available', evaluationId=found['evaluation']['id'],
                         sampleCount=meta['rowCount'], latestSeconds=meta['time']['end'])
    if stage and 'evaluation' in found:
        dataset = found['evaluation']
        if not any(v['source'] == PLANT_PROTOCOL for v in store.experiments.label_sets(dataset['id'])):
            axis = dataset['metadata']['time']
            store.experiments.save_labels(dataset['id'], dict(name=scenario.title,
                timeBasis='dataset-seconds', timeSource='First observation after the scheduled disturbance.',
                intervals=event_intervals(axis['start'], axis['end'], config['onsetSeconds'], scenario.plant.sample)),
                source=PLANT_PROTOCOL, provenance=dataset['metadata']['processRun'])
    result = dict(signals=signals, datasets={k:v['id'] for k,v in found.items()})
    if selected_cases.keys() <= found.keys():
        investigation = integrate(store, wid, scenario, config, found, signals,
                                  stage == 'investigation', progress, check)
        result.update(investigation)
    return result


def integrate(store, wid, scenario, config, found, signals, execute, progress, check):
    service = store.experiments
    sources = {role: dataset['id'] for role, dataset in found.items()}
    context = dict(protocol=PLANT_PROTOCOL, modelVersion=scenario.plant.version, scenario=scenario.id, sources=sources)

    # A specialist may revise the experiment definition after the fixed run.
    # Restore the immutable snapshot that owns this investigation's evidence.
    with store.connect() as db:
        saved = db.execute('''SELECT r.id FROM industrial_evidence i
            JOIN experiment_runs r ON i.run_id=r.id JOIN experiments e ON r.experiment_id=e.id
            WHERE e.workspace_id=? AND json_extract(r.snapshot, '$.config.industrialStudy.protocol')=?
            AND json_extract(r.snapshot, '$.config.industrialStudy.sources.evaluation')=?
            ORDER BY r.created_at''', (wid, PLANT_PROTOCOL, sources['evaluation'])).fetchall()
    for row in saved:
        run = service.run(row['id'])
        if run['snapshot']['config']['industrialStudy'] == context:
            analysis = store.result(run['tasks'][0]['result_id'])
            return investigation_result(store, wid, scenario, config, found, run, analysis, execute)

    def interval(role):
        axis = found[role]['metadata']['time']
        return [axis['start'], axis['end']]

    labels = next((item for item in service.label_sets(sources['evaluation']) if item['source'] == PLANT_PROTOCOL), None)
    if labels is None:
        return {}
    definition = dict(datasetId=sources['evaluation'], signals=signals, analysisRange=interval('evaluation'),
                  training={role: dict(datasetId=sources[role], range=interval(role)) for role in ('fit', 'calibration')},
                  persistence=2, minCoverage=1., labelSetId=labels['id'], algorithms=[dict(algorithm='mahalanobis')],
                  industrialStudy=context)
    expected, _ = service.validate(wid, definition)
    experiment = next((e for e in service.list(wid) if e['config'] == expected), None)
    if experiment is None:
        if not execute:
            return {}
        experiment = service.save(wid, dict(name=scenario.title, config=definition,
            description=f'Independent normal fit and calibration. Paired intervention: {scenario.comparison}.'))
    if progress:
        progress('measurements_available', role='monitoring')
    run = detection_run(service, experiment, expected, execute, check)
    if run is None:
        return dict(experimentId=experiment['id'])
    task = run['tasks'][0]
    analysis = store.result(task['result_id'])
    if progress:
        progress('analysis_available', analysisId=analysis['id'], experimentId=run['experiment_id'])
    if check:
        check()
    return investigation_result(store, wid, scenario, config, found, run, analysis, execute)


def detection_run(service, experiment, expected, execute, check):
    runs = service.runs(experiment['id'])
    completed = (service.run(r['id']) for r in reversed(runs) if r['status'] == 'completed')
    run = next((r for r in completed if r['snapshot']['config'] == expected), None)
    if not run:
        if not execute:
            return None
        pending = (service.run(r['id']) for r in runs if r['status'] in ('queued', 'running'))
        run = next((r for r in pending if r['snapshot']['config'] == expected), None)
        if run is None:
            run = service.execute(experiment['id'], {}, expected_revision=experiment['revision'])
        while run['status'] in ('queued', 'running'):
            if check:
                check()
            time.sleep(.05)
            run = service.run(run['id'])
        if run['status'] != 'completed':
            raise ValueError(run['tasks'][0]['error'] or 'Cooling-water analysis interrupted. Run the study to resume.')
    return run


def investigation_result(store, wid, scenario, config, found, run, analysis, execute):
    task = run['tasks'][0]
    sources = analysis['config']['industrialStudy']['sources']
    evidence = saved_evidence(store, run['id'])
    if evidence is None:
        if not execute:
            return {}
        evidence = supplemental_evidence(store, scenario, config, found, analysis)
        with store.connect() as db:
            db.execute('INSERT INTO industrial_evidence VALUES (?,?)', (run['id'], json.dumps(evidence, allow_nan=False)))
    diagnosis = evidence['diagnosis']
    incident_id = uuid5(NAMESPACE_URL, PLANT_PROTOCOL + '/' + analysis['id']).hex
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
        diag = diagnosis
        entries = []
        if diag:
            for role in diag['distances']:
                entries.append(dict(kind='hypothesis', title=role.replace('-reference', '').replace('-', ' ').capitalize(),
                    content="Compared against the selected measurements over the aligned observation window. The report gives residuals.",
                    observed_at=diag['cutoff'], observed_axis_key='dataset:' + sources['evaluation']))
        entries.append(dict(kind='evidence', title='Matched control intervention',
            content=f'The counterfactual applies {scenario.comparison} at {config["interventionSeconds"]} s. The report compares both trajectories.',
            observed_at=float(found['intervention']['metadata']['time']['end']), observed_axis_key='dataset:' + sources['intervention']))
        store.incidents.create(wid, dict(title=scenario.title,
            description=f'{scenario.plant.name}. The linked alarm and measurements use seconds from initialization.',
            conclusion='Closest trajectory: ' + diag['hypothesis'] if diag else 'No confirmed alarm.',
            start_time=event.get('start'), end_time=event.get('end')), identity=incident_id, sources=links, entries=entries)
    result['incidentId'] = incident_id
    return dict(**result, report=run_report(evidence, analysis, task, scenario.plant.signals, result))
