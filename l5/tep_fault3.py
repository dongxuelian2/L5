"""Exploratory fault-3 controls reconstructed from saved model parameters.

The shared axis is simulation elapsed time, not evidence of a common physical
clock or a guaranteed paired random seed. No model is fitted by this view.
"""
from __future__ import annotations

import hashlib
import numpy as np

from .analysis import build_monitor, contribution_matrix
from .independent import file_hash

TARGET = 167580
ONSET = 28800


def compare_fault3(store, study, simulation_run=1):
    allowed = {p['simulationRun'] for p in study['protocol']['tests'] if p['faultNumber'] == 3}
    if type(simulation_run) is not int or simulation_run not in allowed:
        raise ValueError('Choose a declared fault-3 Testing run.')
    candidates = [t for t in study['tasks'] if t['algorithm'] == 'dpca-q' and t['external']['simulationRun'] == simulation_run
                  and t['external']['faultNumber'] in (0, 3) and t['status'] == 'succeeded']
    result_cache, raw_cache = {}, {}

    def result_for(task):
        if task['id'] not in result_cache:
            result_cache[task['id']] = store.result(task['result_id'])
        return result_cache[task['id']]

    def raw_for(task):
        dataset = store.dataset(task['datasetId'])
        if dataset['id'] not in raw_cache:
            saved = result_for(task)['training']['test']['dataset']
            path = store.root / dataset['workspace_id'] / 'datasets' / dataset['id'] / 'series.npz'
            if file_hash(path) != saved['sha256']:
                raise ValueError('Fault-3 raw measurements changed since scoring; saved-model comparison refused.')
            raw_cache[dataset['id']] = store.load_data(dataset)
        return raw_cache[dataset['id']]

    configurations, variables, diagnostics = [], [], None
    for configuration in study['protocol']['configurations']:
        pair = {t['external']['faultNumber']: t for t in candidates if t['benchmark']['configuration'] == configuration}
        if set(pair) != {0, 3}:
            continue
        normal_task, fault_task = pair[0], pair[3]
        normal, fault = result_for(normal_task), result_for(fault_task)
        times, normal_values = raw_for(normal_task)
        fault_times, fault_values = raw_for(fault_task)
        if not np.array_equal(times, fault_times):
            raise ValueError('Exploratory control requires identical elapsed timestamps; no interpolation is used.')
        columns = normal['config']['signals']
        index = int(np.flatnonzero(times == TARGET)[0])
        model = build_monitor('dpca-q', normal['config'])
        saved = normal['model']
        model.features = saved['features']
        model.pad_center = np.asarray(saved['lagPaddingCenter'])
        model.center, model.scale = np.asarray(saved['center']), np.asarray(saved['scale'])
        model.components, model.eigenvalues = np.asarray(saved['loadings']), np.asarray(saved['eigenvalues'])
        contributions = {}
        for key, values, result in (('normal', normal_values, normal), ('fault', fault_values, fault)):
            weights = contribution_matrix(model, values)
            np.testing.assert_allclose(weights.sum(axis=1), result['scores'], rtol=1e-9, atol=1e-9)
            order = sorted(range(len(columns)), key=lambda i: (-float(weights[index, i]), i))[:8]
            contributions[key] = [dict(signal=columns[i], value=float(weights[index, i]), fraction=float(weights[index, i]/weights[index].sum())) for i in order]
            variables.extend(columns[i] for i in order[:4])
        other_methods = []
        for task in study['tasks']:
            if task['benchmark']['configuration'] != configuration or task['external']['simulationRun'] != simulation_run or task['external']['faultNumber'] not in (0, 3) or task['status'] != 'succeeded':
                continue
            result = result_for(task)
            other_methods.append(dict(algorithm=task['algorithm'], faultNumber=task['external']['faultNumber'],
                score=result['scores'][index], threshold=result['threshold'], ratio=result['scores'][index]/result['threshold'],
                state=result['states'][index], scoreWindow=result['scores'][max(0,index-6):index+7]))
        def curve(result, task):
            return dict(times=result['times'], scores=result['scores'], states=result['states'], intervals=result['intervals'],
                        datasetId=task['datasetId'], experimentId=task['experimentId'], runId=task['run_id'], analysisId=task['result_id'],
                        metrics=task['metrics'], threshold=result['threshold'])
        configurations.append(dict(configuration=configuration, threshold=normal['threshold'], normal=curve(normal, normal_task),
            fault=curve(fault, fault_task), contributionsAtTarget=contributions, otherMethodsAtTarget=other_methods,
            scoreCorrelation=float(np.corrcoef(normal['scores'][160:], fault['scores'][160:])[0,1]),
            localScoreCorrelation=float(np.corrcoef(normal['scores'][index-6:index+7], fault['scores'][index-6:index+7])[0,1])))
        if diagnostics is None:
            diagnostics = {}
            for key, mask in dict(preInjection=times < ONSET, postInjection=times >= ONSET,
                                  aroundAlarm=(times >= TARGET-1080) & (times <= TARGET+1080)).items():
                delta = fault_values[mask]-normal_values[mask]
                diagnostics[key] = dict(samples=int(mask.sum()), exactlyEqual=bool(np.array_equal(normal_values[mask], fault_values[mask])),
                    equalEntries=int((delta == 0).sum()), totalEntries=delta.size, maxAbsoluteDifference=float(np.abs(delta).max()))
            diagnostics['rawArrayHashes'] = {k: hashlib.sha256(np.asarray(v, dtype='<f8').tobytes()).hexdigest() for k,v in (('normal',normal_values),('fault',fault_values))}
            diagnostics['perVariable'] = []
            for col, name in enumerate(columns):
                n, f = normal_values[160:, col], fault_values[160:, col]
                diagnostics['perVariable'].append(dict(signal=name, postMeanDifference=float(np.mean(f-n)),
                    postMaxAbsoluteDifference=float(np.max(np.abs(f-n))),
                    correlation=float(np.corrcoef(n,f)[0,1]) if np.std(n) and np.std(f) else None))
            variables.extend(columns[i] for i in np.argsort(np.max(np.abs(fault_values-normal_values)/np.maximum(saved['scale'][:52],1e-10),axis=0))[-2:])
    raw = []
    if configurations:
        normal_task = next(t for t in candidates if t['external']['faultNumber'] == 0)
        fault_task = next(t for t in candidates if t['external']['faultNumber'] == 3)
        times, normal_values = raw_for(normal_task)
        _, fault_values = raw_for(fault_task)
        columns = result_for(normal_task)['config']['signals']
        for name in dict.fromkeys(variables):
            col = columns.index(name)
            def means(values):
                return dict(preInjection=float(values[times < ONSET,col].mean()),
                    firstPostHour=float(values[(times >= ONSET)&(times <= ONSET+3600),col].mean()),
                    aroundAlarm=float(values[(times >= TARGET-1080)&(times <= TARGET+1080),col].mean()))
            raw.append(dict(signal=name, times=times.tolist(), normal=normal_values[:,col].tolist(), fault=fault_values[:,col].tolist(),
                            normalMeans=means(normal_values), faultMeans=means(fault_values)))
    controls = []
    for task in study['tasks']:
        if task['algorithm'] == 'dpca-q' and task['external']['faultNumber'] in (0, 3) and task['status'] == 'succeeded':
            result = result_for(task)
            index = int(np.argmax(result['scores']))
            target = result['times'].index(TARGET)
            controls.append(dict(configuration=task['benchmark']['configuration'], faultNumber=task['external']['faultNumber'],
                simulationRun=task['external']['simulationRun'], threshold=result['threshold'], peakScore=result['scores'][index],
                peakTime=result['times'][index], peakRatio=result['scores'][index]/result['threshold'],
                targetScore=result['scores'][target], targetState=result['states'][target],
                alarmSpans=task['metrics']['behavior']['alarmSpans'], events=task['metrics']['detection']['events']))
    return dict(simulationRun=simulation_run, onset=ONSET, targetTime=TARGET, configurations=configurations,
                raw=raw, diagnostics=diagnostics, controls=controls,
                interpretation='Elapsed-time exploratory controls. Equality before injection is an observed data property. The published description establishes distinct simulationRun RNG states and non-overlapping training/testing seeds, but does not guarantee identical physical/noise realizations across fault identities. A coincident late alarm is retained as a nominal hit, not evidence of fault-specific discrimination.')
