"""Forecast physics, causal evidence, and uncertainty contracts."""
import json
import unittest

import numpy as np

from l5.models.tanks import CoupledTankModel, SIGNALS, integrate
from l5.safety_forecast import forecast_constraints


class SafetyForecastTests(unittest.TestCase):
    def setUp(self):
        self.model = CoupledTankModel()
        self.columns = [dict(id=f"test-{signal['key']}", name=signal['key'], unit=signal['unit']) for signal in SIGNALS]
        self.level = dict(id='tank-limit', name='Tank 1 maximum', kind='value', unit='m',
                          terms=[dict(signalId='test-level1')], upper=1.8)

    def simulate(self, **changes):
        config = self.model.validate(dict(duration=100, step=.2, noise=0) | changes)
        rows = self.model.simulate(config)
        dataset = dict(metadata=dict(columns=self.columns, model=dict(id=self.model.id, version=self.model.version, config=config)))
        times = np.asarray([row['t'] for row in rows])
        values = np.asarray([[row[column['name']] for column in self.columns] for row in rows])
        return dataset, times, values

    def test_no_future_measurement_hidden_state_or_fault_schedule_enters(self):
        dataset, times, values = self.simulate(fault='valve_restriction', start=20, severity=.9)
        options = dict(asOf=10, horizonSeconds=65)
        baseline = forecast_constraints(dataset, times, values, [self.level], options)
        poisoned = values.copy()
        poisoned[times > 10] = np.nan
        model = dataset['metadata']['model']
        model['groundTruth'] = dict(secretFuture=True)
        model['config'].update(initial1=8, initial2=8, fault='tank_leak', start=7, severity=1., noise=.08,
                               pumpControl=5, valve=.5, seed=92, step=1.3, leakCoefficient=.1)
        model['scenarioSnapshot'] = {'config': dict(start=12, pumpRate=.14)}
        self.assertEqual(baseline, forecast_constraints(dataset, times, poisoned, [self.level], options))
        before = times <= 10
        self.assertEqual(baseline, forecast_constraints(dataset, times[before], values[before], [self.level], options))
        self.assertEqual(baseline['inputMeasurements']['time'], 10)
        self.assertEqual(baseline['constraints'][0]['status'], 'no-crossing')

    def test_integration_restarts_from_measurements_and_tcv_interpolates(self):
        dataset, times, values = self.simulate(initial1=1.8, initial2=1.3, pumpRate=.048)
        config = dataset['metadata']['model']['config']
        definition = dict(self.level, upper=2.3)
        forecast = forecast_constraints(dataset, times, values, [definition], dict(asOf=10, horizonSeconds=60, stepSeconds=.8))
        self.assertEqual(forecast['status'], 'available')
        trajectory = forecast['trajectory']
        expected = integrate(dict(config, step=.02, integrationStep=.02))[1]
        reference_times = np.asarray([row['t'] for row in expected])
        for signal in ('level1', 'level2', 'inlet', 'transfer', 'outlet'):
            reference = np.interp(trajectory['times'], reference_times, [row[signal] for row in expected])
            np.testing.assert_allclose(trajectory['values'][signal], reference, rtol=0, atol=1e-7)
        expected_cross = np.interp(2.3, [row['level1'] for row in expected], reference_times)
        assessment = forecast['constraints'][0]
        self.assertAlmostEqual(assessment['firstCrossingTime'], expected_cross, delta=.003)
        self.assertAlmostEqual(assessment['timeToViolation'], expected_cross - 10, delta=.003)
        self.assertAlmostEqual(assessment['violationDuration'], 70 - expected_cross, delta=.003)
        self.assertEqual(assessment['currentMargin'], 2.3 - values[np.searchsorted(times, 10), 0])
        self.assertLess(assessment['minimumMargin'], 0)

    def test_dwell_seed_continues_causal_measurements(self):
        dataset, times, values = self.simulate(initial1=1.8, initial2=1.3, pumpRate=.048)
        # Level 1 is already above 1.7 m from the first sample.
        definition = dict(self.level, upper=1.7, dwellSeconds=5.)
        pending = forecast_constraints(dataset, times, values, [definition], dict(asOf=3, horizonSeconds=5))['constraints'][0]
        self.assertAlmostEqual(pending['firstCrossingTime'], 5.)
        self.assertAlmostEqual(pending['timeToViolation'], 2.)
        confirmed = forecast_constraints(dataset, times, values, [definition], dict(asOf=6, horizonSeconds=5))['constraints'][0]
        self.assertTrue(confirmed['startedInViolation'])
        self.assertEqual(confirmed['timeToViolation'], 0.)

    def test_hysteresis_release_and_incomplete_forecast_intervals(self):
        dataset, times, values = self.simulate(initial1=2.1, initial2=1.)
        definition = dict(self.level, upper=2., hysteresis=.1)
        options = dict(asOf=0, horizonSeconds=40, stepSeconds=.4, input=dict(mode='override', pumpCommand=0))
        forecast = forecast_constraints(dataset, times, values, [definition], options)
        constraint = forecast['constraints'][0]
        self.assertTrue(constraint['startedInViolation'])
        self.assertEqual(constraint['timeToViolation'], 0)
        interval = constraint['intervals'][0]
        self.assertGreater(interval['end'], interval['lastSampleTime'])
        trajectory = forecast['trajectory']
        expected_release = np.interp(1.9, trajectory['values']['level1'][::-1], trajectory['times'][::-1])
        self.assertAlmostEqual(interval['end'], expected_release)
        no_crossing = dict(self.level, upper=2.5, maxGapSeconds=.1)
        incomplete = forecast_constraints(dataset, times, values, [no_crossing], options)['constraints'][0]
        self.assertEqual((incomplete['status'], incomplete['reasonCode']),
                         ('unavailable', 'incomplete-constraint-trajectory'))
        self.assertIsNone(incomplete['violationDuration'])

    def test_active_rate_policy_carries_into_first_forward_rate(self):
        dataset, times, values = self.simulate(initial1=1.8, initial2=1.3, pumpRate=.048)
        definition = dict(self.level, kind='rate', unit='m/s', upper=.01, dwellSeconds=2.)
        constraint = forecast_constraints(dataset, times, values, [definition],
                                          dict(asOf=5, horizonSeconds=5))['constraints'][0]
        self.assertEqual(constraint['series']['states'][0], 'unavailable')
        self.assertTrue(constraint['startedInViolation'])
        self.assertEqual(constraint['timeToViolation'], 0)
        self.assertEqual(constraint['intervals'][0]['start'], 5)
        self.assertEqual(constraint['intervals'][0]['firstSampleTime'], 5.2)
        self.assertEqual(constraint['violationDuration'], 5)

    def test_fixed_assumptions_take_effect_after_causal_warmup(self):
        dataset, times, values = self.simulate()
        definition = dict(self.level, terms=[dict(signalId='test-pump')], unit='%', upper=90.)
        options = dict(asOf=10.1, horizonSeconds=5, input=dict(mode='override', pumpCommand=80.))
        result = forecast_constraints(dataset, times, values, [definition], options)
        self.assertEqual(result['observedThrough'], 10.)
        self.assertEqual(result['trajectory']['times'][0], 10.1)
        self.assertEqual(result['trajectory']['values']['level1'][0], 1.5625)
        self.assertTrue(all(pump == 80. for pump in result['trajectory']['values']['pump']))
        assessment = result['constraints'][0]
        self.assertEqual(assessment['currentState'], 'violation')
        self.assertEqual(assessment['status'], 'no-crossing')
        options['asOf'] = 10.
        exact = forecast_constraints(dataset, times, values, [definition], options)
        self.assertEqual(exact['constraints'][0]['status'], 'no-crossing')

    def test_observed_inlet_exposes_difference_from_declared_model(self):
        dataset, times, values = self.simulate(fault='pump_degradation', start=15, severity=.8)
        forecast = forecast_constraints(dataset, times, values, [self.level], dict(asOf=20, horizonSeconds=5))
        comparison = forecast['assumptions']['observedInputComparison']
        self.assertAlmostEqual(comparison['measuredInlet'], .0132)
        self.assertAlmostEqual(comparison['modeledInlet'], .03)
        self.assertAlmostEqual(comparison['measuredMinusModeledInlet'], -.0168)
        self.assertAlmostEqual(forecast['trajectory']['values']['inlet'][0], .03)

    def test_missing_stale_ambiguous_incompatible_and_unreliable_inputs(self):
        dataset, times, values = self.simulate()
        options = dict(asOf=10, horizonSeconds=5)
        index = np.searchsorted(times, 10)
        observed = np.ones(values.shape, dtype=bool)
        observed[index, 0] = False
        missing = forecast_constraints(dataset, times, values, [self.level], options, observed=observed)
        self.assertEqual((missing['status'], missing['reasonCode']), ('unavailable', 'missing-observation'))
        self.assertIsNone(missing['inputMeasurements']['values']['level1'])
        stale = forecast_constraints(dataset, times[:index], values[:index], [self.level],
                                     dict(options, maxObservationAgeSeconds=.1))
        self.assertEqual(stale['reasonCode'], 'stale-observation')
        duplicate = forecast_constraints(dataset, np.insert(times, index, times[index]),
                                         np.insert(values, index, values[index], axis=0), [self.level], options)
        self.assertEqual(duplicate['reasonCode'], 'ambiguous-observation')
        self.columns[0]['unit'] = 'cm'
        relabelled = forecast_constraints(dataset, times, values, [self.level], options)
        self.assertEqual(relabelled['reasonCode'], 'incompatible-measurement-unit')
        self.columns[0]['unit'] = 'm'
        large_time = forecast_constraints(dataset, times + 1e16, values, [self.level],
                                          dict(options, asOf=float(times[-1] + 1e16)))
        self.assertEqual(large_time['status'], 'unavailable')  # The final timestamp is ambiguous.
        unreliable = forecast_constraints(dataset, np.asarray([1e16]), values[:1], [self.level], dict(asOf=1e16))
        self.assertEqual((unreliable['status'], unreliable['reasonCode']), ('unreliable', 'numerical-check'))
        for invalid in [dict(asOf=float('nan')), dict(horizonSeconds=3600, stepSeconds=.02), dict(input=dict(pumpCommand=80)),
                        dict(uncertainty=dict(samples=1)), dict(parameters=dict(fault='tank_leak'))]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                forecast_constraints(dataset, times, values, [self.level], invalid)

    def test_seeded_uncertainty_preserves_invalid_draws_and_sensitivity_cases(self):
        dataset, times, values = self.simulate(initial1=1.8, initial2=1.3, pumpRate=.048)
        definition = dict(self.level, upper=2.3)
        ranges = dict(pumpRateFraction=[-.6, .6], pumpCommand=[0, 90])
        options = dict(asOf=10, horizonSeconds=40, uncertainty=dict(samples=24, seed=98, ranges=ranges))
        baseline = forecast_constraints(dataset, times, values, [definition], options)
        self.assertEqual(baseline, forecast_constraints(dataset, times, values, [definition], options))
        changed = forecast_constraints(dataset, times, values, [definition], dict(options, uncertainty=dict(options['uncertainty'], seed=99)))
        self.assertNotEqual(baseline['uncertainty']['scenarios'], changed['uncertainty']['scenarios'])
        self.assertEqual(baseline['trajectory'], changed['trajectory'])
        result = baseline['uncertainty']['constraints'][0]
        self.assertGreater(result['unavailableScenarios'], 0)
        self.assertGreater(result['evaluatedScenarios'], 0)
        self.assertEqual(result['evaluatedScenarios'] + result['unavailableScenarios'], 24)
        self.assertEqual(result['violationFraction'], result['crossingScenarios'] / result['evaluatedScenarios'])
        sensitivity = {item['parameter']: item for item in result['sensitivity']}
        self.assertLess(sensitivity['pumpRateFraction']['marginChange'], 0.)
        self.assertIsNone(sensitivity['pumpCommand']['upperMargin'])
        self.assertEqual(len(baseline['uncertainty']['sensitivityScenarios']), 4)
        json.dumps(baseline, allow_nan=False)
