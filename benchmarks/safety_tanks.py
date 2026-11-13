"""Fixed coupled-tank operating-limit benchmark with causal forecast cutoffs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter

import numpy as np

from l5.models.tanks import CoupledTankModel, SIGNALS, integrate
from l5.safety_constraints import evaluate_constraints
from l5.safety_forecast import forecast_constraints


MODEL = CoupledTankModel()
BASE = dict(duration=220, step=.2, integrationStep=.05, noise=0, seed=128)
HORIZON = 85.
TRUTH_STEP = .05
CASES = (
    dict(id='healthy', config={}, signal='level1', upper=2.5, cutoffs=[0, 25, 70]),
    dict(id='approaching-limit', config=dict(initial1=1.8, initial2=1.3, pumpRate=.048),
         signal='level1', upper=2.3, warningUpper=2.1, cutoffs=[0, 15, 25, 35, 45]),
    dict(id='degraded-pump', config=dict(fault='pump_degradation', severity=.8, start=35),
         signal='outlet', lower=.025, cutoffs=[15, 25, 40, 60, 105]),
    dict(id='restricted-valve', config=dict(fault='valve_restriction', severity=.85, start=35),
         signal='level1', upper=2.05, cutoffs=[0, 25, 40, 55, 65]),
    dict(id='leak', config=dict(fault='tank_leak', severity=.85, start=35),
         signal='level1', lower=1.28, cutoffs=[0, 25, 40, 55, 65]),
    dict(id='overflow', config=dict(initial1=2.2, initial2=1.6, pumpRate=.06),
         signal='level1', upper=2.5, cutoffs=[0, 5, 10, 13]),
    dict(id='high-noise', config=dict(noise=.075), signal='level1', upper=1.62,
         cutoffs=[5, 15, 25, 35, 45, 55, 65, 75]),
    dict(id='missing-at-crossing', config=dict(initial1=1.8, initial2=1.3, pumpRate=.048),
         signal='level1', upper=2.3, missing=[39., 40.4], cutoffs=[0, 38, 39.4, 40.2, 45]),
    dict(id='parameter-mismatch', config=dict(initial1=2.2, initial2=1.6, pumpRate=.06),
         signal='level1', upper=2.5, modelOverride=dict(pumpRate=.035), cutoffs=[0, 5, 10]),
    dict(id='never-reached', config=dict(pumpRate=.032), signal='level1', upper=2.35, cutoffs=[0, 30, 70]),
)


def margin(value, case):
    return case['upper'] - value if 'upper' in case else value - case['lower']


def truth_crossing(times, margins, start, end):
    """Locate the first violation over the horizon on the fine retrospective grid."""
    grid = np.r_[start, times[(times > start) & (times < end)], end]
    values = np.interp(grid, times, margins)
    hits = np.flatnonzero(values < 0.)
    if not len(hits):
        return None
    right = hits[0]
    if right == 0:
        return float(start)
    left = right - 1
    return float(grid[left] + (grid[right] - grid[left]) * values[left] / (values[left] - values[right]))


def run_case(case):
    config = MODEL.validate(BASE | case['config'])
    observations = MODEL.simulate(config)
    # This trace exists only inside retrospective scoring. Forecast receives
    # the independent sampled measurement array and a fault-free parameter set.
    _, physical = integrate(dict(config, step=TRUTH_STEP, noise=0.))
    true_times = np.asarray([row['t'] for row in physical])
    signal = case['signal']
    margins = np.asarray([margin(row[signal], case) for row in physical])
    times = np.asarray([row['t'] for row in observations])
    columns = [dict(id=spec['key'], name=spec['key'], unit=spec['unit']) for spec in SIGNALS]
    values = np.asarray([[row[column['name']] for column in columns] for row in observations])
    index = next(i for i, col in enumerate(columns) if col['name'] == signal)
    if 'missing' in case:
        lo, hi = case['missing']
        values[(times >= lo) & (times <= hi), index] = np.nan
    forecast_parameters = {key: config[key] for key in ('area1', 'area2', 'pumpRate', 'connection',
                                                        'outlet', 'outletValve', 'tankHeight', 'integrationStep')}
    dataset = dict(metadata=dict(columns=columns, model=dict(id=MODEL.id, version=MODEL.version,
                                                              config=forecast_parameters)))
    definition = dict(id='operating-limit', name='Operating limit', kind='value', unit=columns[index]['unit'],
                      terms=[dict(signalId=signal)], **{key: case[key] for key in ('lower', 'upper', 'warningUpper') if key in case})
    clock_start = perf_counter()
    monitored = evaluate_constraints(times, {signal: values[:, index]}, {signal: columns[index]}, [definition])[0]
    monitor_ms = (perf_counter() - clock_start) * 1000
    truth = np.interp(times, true_times, margins) < 0
    measured = np.asarray(monitored['series']['rawStates'])
    available = measured != 'unavailable'
    violating = measured == 'violation'
    counts = dict(trueViolations=int(np.sum(available & truth & violating)),
                  missedMeasuredViolations=int(np.sum(available & truth & ~violating)),
                  falseMeasuredViolations=int(np.sum(available & ~truth & violating)),
                  trueNonViolations=int(np.sum(available & ~truth & ~violating)),
                  unavailable=int(np.sum(~available)), unavailableDuringViolation=int(np.sum(~available & truth)))
    predictions = []
    for cutoff in case['cutoffs']:
        expected = truth_crossing(true_times, margins, cutoff, cutoff + HORIZON)
        prefix = np.searchsorted(times, cutoff, side='right')
        variants = {'declared': case.get('modelOverride', {})}
        if 'modelOverride' in case:
            variants['matching-parameters-reference'] = {}
        for variant, parameters in variants.items():
            options = dict(asOf=cutoff, horizonSeconds=HORIZON, stepSeconds=.2, parameters=parameters)
            if case['id'] == 'approaching-limit' and cutoff == 25:
                options['uncertainty'] = dict(samples=12, seed=74, ranges=dict(
                    level1=[-.02, .02], level2=[-.02, .02], pumpRateFraction=[-.1, .1], leakCoefficient=[0, .008]))
            clock_start = perf_counter()
            forecast = forecast_constraints(dataset, times[:prefix], values[:prefix], [definition], options)
            forecast_ms = (perf_counter() - clock_start) * 1000
            result = forecast['constraints'][0] if forecast['constraints'] else {}
            predicted = result.get('firstCrossingTime')
            if forecast['status'] != 'available' or result.get('status') == 'unavailable':
                outcome = forecast['status'] if forecast['status'] != 'available' else 'unavailable'
            elif predicted is None:
                outcome = 'missed-crossing' if expected is not None else 'true-no-crossing'
            else:
                outcome = 'false-crossing' if expected is None else 'true-crossing'
            predictions.append(dict(cutoff=cutoff, variant=variant, truthCrossingTime=expected,
                                    predictedCrossingTime=predicted, timeToViolation=result.get('timeToViolation'),
                                    crossingTimeError=predicted - expected if predicted is not None and expected is not None else None,
                                    outcome=outcome, reasonCode=forecast.get('reasonCode'), elapsedMs=forecast_ms,
                                    uncertainty=forecast['uncertainty']['constraints'][0] if forecast['uncertainty'] else None))
    return dict(id=case['id'], simulationConfig=config, constraint=definition, missingWindow=case.get('missing'),
                forecastParameterOverride=case.get('modelOverride'), observed=counts, monitoringElapsedMs=monitor_ms,
                warningSamples=int(np.sum(measured == 'warning')),
                truthFirstCrossingTime=truth_crossing(true_times, margins, 0., true_times[-1]),
                spilledVolume=physical[-1]['spilled'], predictions=predictions)


def run_benchmark():
    cases = [run_case(case) for case in CASES]
    forecasts = [prediction for case in cases for prediction in case['predictions'] if prediction['variant'] == 'declared']
    outcomes = {kind: sum(record['outcome'] == kind for record in forecasts) for kind in
                ('true-crossing', 'missed-crossing', 'false-crossing', 'true-no-crossing', 'unavailable', 'unreliable')}
    errors = [abs(record['crossingTimeError']) for record in forecasts if record['crossingTimeError'] is not None]
    future_errors = [abs(record['crossingTimeError']) for record in forecasts
                     if record['crossingTimeError'] is not None and record['truthCrossingTime'] > record['cutoff']]
    observed = {key: sum(case['observed'][key] for case in cases) for key in cases[0]['observed']}
    classified = sum(observed[key] for key in ('trueViolations', 'trueNonViolations', 'missedMeasuredViolations',
                                              'falseMeasuredViolations'))
    return dict(format='coupled-tank-safety-benchmark-v1', modelVersion=MODEL.version, horizonSeconds=HORIZON,
                truthStepSeconds=TRUTH_STEP, observationStepSeconds=BASE['step'],
                summary=dict(observed=observed, observedAccuracy=(observed['trueViolations'] + observed['trueNonViolations']) / classified,
                             forecastOutcomes=outcomes, meanAbsoluteCrossingTimeErrorSeconds=sum(errors) / len(errors) if errors else None,
                             matchedFutureCrossings=len(future_errors),
                             meanAbsoluteFutureCrossingTimeErrorSeconds=sum(future_errors) / len(future_errors) if future_errors else None,
                             maxAbsoluteCrossingTimeErrorSeconds=max(errors, default=None),
                             totalMonitoringElapsedMs=sum(case['monitoringElapsedMs'] for case in cases),
                             totalForecastElapsedMs=sum(record['elapsedMs'] for record in forecasts)),
                cases=cases)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Write the JSON report to this path.')
    args = parser.parse_args()
    report = json.dumps(run_benchmark(), indent=2, ensure_ascii=False, allow_nan=False) + '\n'
    if args.output:
        args.output.write_text(report, encoding='utf-8')
    else:
        print(report, end='')


if __name__ == '__main__':
    main()
