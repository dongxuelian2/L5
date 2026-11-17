"""Operating-limit comparison, coverage and state-policy contracts."""
import json
import unittest

import numpy as np

from l5.safety_constraints import evaluate_constraints, normalize_constraints


def definition(**options):
    return dict(id='limit', name='Operating limit', unit='m', terms=[dict(signalId='level')]) | options


def evaluate(values, constraint, *, times=None, observed=None, include_series=True, initial_policies=None):
    return evaluate_constraints(np.arange(len(values)) if times is None else times,
                                {'level': values}, {'level': {'unit': 'm'}}, [constraint], observed=observed,
                                include_series=include_series, initial_policies=initial_policies)[0]


class SafetyConstraintTests(unittest.TestCase):
    def test_physical_units_inclusive_limits_and_signed_margins(self):
        signals = {'level': {'unit': 'cm'}}
        bounds = definition(lower=1, upper=2.5, warningLower=1.2, warningUpper=2.3)
        normalized = normalize_constraints([bounds], signals)
        self.assertEqual(normalize_constraints(normalized, signals), normalized)
        result, = evaluate_constraints(np.arange(7), {'level': [90, 100, 120, 210, 230, 250, 255]}, signals, [bounds])
        self.assertEqual(result['series']['states'], ['violation', 'warning', 'warning', 'normal', 'warning', 'warning', 'violation'])
        np.testing.assert_allclose(result['series']['margins'], [-.1, 0, .2, .4, .2, 0, -.05], atol=1e-14)
        self.assertAlmostEqual(result['maximumExceedance'], .1)
        self.assertEqual(result['current']['measurements'], {'level': 255.})
        self.assertEqual(result['sourceUnits'], {'level': 'cm'})
        self.assertEqual(result['marginUnit'], 'm')
        self.assertEqual([span['boundary'] for span in result['rawViolationIntervals']], ['lower', 'upper'])
        json.dumps(result, allow_nan=False)

    def test_dimensionless_percent_and_custom_units(self):
        pump = definition(unit='fraction', upper=1.2)
        result, = evaluate_constraints([0, 1], {'level': [120, 125]}, {'level': {'unit': '%'}}, [pump])
        self.assertEqual(result['series']['rawStates'], ['normal', 'violation'])
        self.assertAlmostEqual(result['current']['margin'], -.05)
        vendor = definition(unit='vendor-unit', upper=1)
        result, = evaluate_constraints([0], {'level': [2]}, {'level': {'unit': 'vendor-unit'}}, [vendor])
        self.assertEqual(result['current']['margin'], -1)
        for output in ('m', 'another-vendor-unit'):
            with self.assertRaisesRegex(ValueError, 'No explicit conversion'):
                normalize_constraints([vendor | {'unit': output}], {'level': {'unit': 'vendor-unit'}})

    def test_unlabeled_signals_keep_as_recorded_scale(self):
        signals = {'level': {'unit': ''}, 'other': {'unit': '%'}}
        value = definition(unit='', upper=2)
        rate = definition(id='rate', unit='1/s', upper=2, kind='rate')
        configured = normalize_constraints([value, rate], signals)
        results = evaluate_constraints([0, 1], {'level': [0, 3]}, signals, configured)
        self.assertEqual([item['current']['margin'] for item in results], [-1, -1])
        for invalid in (value | {'unit': '%'}, value | {'unit': 'fraction'},
                        value | {'kind': 'relationship', 'unit': '1',
                                 'terms': [{'signalId': 'level'}, {'signalId': 'other'}]}):
            with self.assertRaisesRegex(ValueError, 'Signal Catalog'):
                normalize_constraints([invalid], signals)

    def test_linear_relationship_uses_one_common_scale(self):
        signals = {'a': {'unit': 'bar'}, 'b': {'unit': 'kPa'}}
        constraint = definition(kind='relationship', unit='kPa', lower=8, upper=12,
                                terms=[dict(signalId='a'), dict(signalId='b', coefficient=-2)])
        result, = evaluate_constraints([0, 1, 2], {'a': [1, 1, 1], 'b': [46, 44, 43]}, signals, [constraint])
        self.assertEqual(result['series']['values'], [8., 12., 14.])
        self.assertEqual(result['series']['rawStates'], ['normal', 'normal', 'violation'])
        self.assertEqual(result['maximumExceedance'], 2)

    def test_affine_temperatures_and_temperature_rates(self):
        signals = {'level': {'unit': '°F'}, 'second': {'unit': '°C'}}
        value = definition(unit='°C', upper=0)
        relationship = definition(id='difference', kind='relationship', unit='Δ°C', upper=0,
                                  terms=[dict(signalId='level'), dict(signalId='second', coefficient=-1)])
        rate = definition(id='rate', kind='rate', unit='Δ°C/s', upper=3)
        a, b, c = evaluate_constraints([0, 2, 3], {'level': [32, 50, 59], 'second': [0, 10, 10]},
                                       signals, [value, relationship, rate])
        self.assertEqual(a['series']['rawStates'][0], 'normal')
        self.assertEqual(a['marginUnit'], 'Δ°C')
        self.assertEqual(b['series']['rawStates'], ['normal', 'normal', 'violation'])
        self.assertAlmostEqual(b['current']['value'], 5)
        np.testing.assert_allclose(c['series']['values'][1:], [5, 5])
        with self.assertRaisesRegex(ValueError, 'subtract two temperatures'):
            normalize_constraints([relationship | {'unit': '°C'}], signals)

    def test_hysteresis_and_dwell_keep_raw_singletons_and_confirm_with_samples(self):
        bounds = definition(upper=10, warningUpper=8, hysteresis=.5, dwellSeconds=2)
        result = evaluate([7, 8.1, 7.8, 10.2, 9.9, 10.3, 10.5, 10.1, 9.8, 9.5, 7.4], bounds)
        self.assertEqual(result['series']['rawStates'], ['normal', 'warning', 'normal', 'violation', 'warning', 'violation',
                                                       'violation', 'violation', 'warning', 'warning', 'normal'])
        self.assertEqual(result['series']['states'], ['normal', 'warning', 'warning', 'warning', 'warning', 'warning',
                                                    'warning', 'violation', 'violation', 'warning', 'normal'])
        raw = result['rawViolationIntervals']
        self.assertEqual([(i['start'], i['end'], i['duration']) for i in raw], [(3, 3, 0), (5, 7, 2)])
        self.assertAlmostEqual(raw[0]['maximumExceedance'], .2)
        episode, = [i for i in result['intervals'] if i['state'] == 'violation']
        self.assertEqual((episode['candidateStart'], episode['confirmedAt'], episode['start'], episode['end']), (5, 7, 7, 8))
        self.assertEqual((result['violationDuration'], result['rawViolationDuration']), (1, 2))

    def test_hysteresis_does_not_latch_wrong_side(self):
        result = evaluate([3., -1., -1., 3., 3.], definition(lower=0, upper=2, hysteresis=.5, dwellSeconds=1))
        intervals = [i for i in result['intervals'] if i['state'] == 'violation']
        self.assertEqual([(i['boundary'], i['start'], i['end']) for i in intervals], [('lower', 2, 2), ('upper', 4, 4)])
        self.assertEqual(result['series']['states'], ['warning', 'warning', 'violation', 'warning', 'violation'])

    def test_hysteresis_clears_at_recovery_and_requires_feasible_range(self):
        upper = evaluate([2.6, 2.55, 2.5], definition(upper=2.55, hysteresis=.05))
        lower = evaluate([2.49, 2.5, 2.55], definition(lower=2.5, hysteresis=.05))
        for result, side in ((upper, 'upper'), (lower, 'lower')):
            self.assertEqual(result['series']['states'], ['violation', 'violation', 'normal'])
            self.assertEqual(result['series'][f'{side}RecoveryMargins'][-1], 0)
        with self.assertRaisesRegex(ValueError, 'no common recovery range'):
            evaluate([2], definition(lower=0, upper=10, warningLower=4, warningUpper=6, hysteresis=1.5))

    def test_gaps_and_nonobserved_values_split_evidence(self):
        result = evaluate([2, 2, 2, 2, 2, 0, np.nan], definition(upper=1, dwellSeconds=1),
                          times=[0, 1, 2, 12, 13, 14, 15], observed={'level': [True, True, False, True, True, False, True]})
        self.assertEqual(result['series']['states'], ['warning', 'violation', 'unavailable', 'warning', 'violation',
                                                    'unavailable', 'unavailable'])
        self.assertEqual(result['series']['measurements']['level'][2], 2)
        self.assertFalse(result['series']['measurementObserved']['level'][2])
        self.assertEqual(result['quality']['gaps'], [dict(start=2, end=12, duration=10)])
        self.assertEqual(result['quality']['missingSamples'], 1)
        self.assertEqual(result['quality']['unobservedSamples'], 2)
        self.assertEqual(result['coverage']['evaluatedSamples'], 4)
        self.assertAlmostEqual(result['coverage']['durationFraction'], 2 / 15)
        self.assertIsNone(result['current']['margin'])

    def test_gap_and_dwell_at_decimal_sample_boundary(self):
        constraint = definition(upper=1, maxGapSeconds=.1, dwellSeconds=.2)
        result = evaluate([2, 2, 2, 2], constraint, times=[.3, .4, .5, .601])
        self.assertEqual(result['series']['states'], ['warning', 'warning', 'violation', 'warning'])
        self.assertEqual([(gap['start'], gap['end']) for gap in result['quality']['gaps']], [(.5, .601)])

    def test_rate_respects_irregular_grid_gaps_missing_and_duplicates(self):
        constraint = definition(kind='rate', unit='m/s', upper=2, absolute=True, maxGapSeconds=4)
        values = [0, 2, -2, 4, 8, 5, 12, np.nan, 14, 18]
        times = [0, 1, 2.5, 3, 3, 4, 9, 10, 11, 13]
        result = evaluate(values, constraint, times=times)
        self.assertEqual(result['series']['rawStates'], ['unavailable', 'normal', 'violation', 'unavailable',
                                                       'unavailable', 'unavailable', 'unavailable', 'unavailable',
                                                       'unavailable', 'normal'])
        self.assertAlmostEqual(result['series']['values'][2], 4 / 1.5)
        self.assertEqual(result['quality']['duplicateCount'], 1)
        self.assertEqual(result['quality']['rateUnavailableSamples'], 6)
        duplicate = evaluate([1, 2, 0, 1], definition(upper=1.5), times=[0, 1, 1, 2])
        episode, = duplicate['rawViolationIntervals']
        self.assertEqual((episode['start'], episode['end'], episode['samples']), (1, 1, 1))
        self.assertTrue(evaluate([1, 2, 0], definition(upper=1.5), times=[0, 1, 1])['current']['duplicateTimestamp'])

    def test_value_and_rate_policy_can_resume_causally(self):
        bounds = definition(upper=1, dwellSeconds=2)
        prior = evaluate([0, 2, 2], bounds, include_series=False)
        next_part = evaluate([2, 2, 2], bounds, times=[2, 3, 4], initial_policies={'limit': prior['policy']})
        self.assertEqual(next_part['series']['states'], ['warning', 'violation', 'violation'])
        self.assertEqual(next_part['policy']['confirmedAt'], 3)
        rate = definition(kind='rate', unit='m/s', upper=1, dwellSeconds=2)
        prior = evaluate([0, 2, 4], rate, include_series=False)
        next_part = evaluate([4, 6, 8], rate, times=[2, 3, 4], initial_policies={'limit': prior['policy']})
        self.assertEqual(next_part['series']['states'], ['unavailable', 'violation', 'violation'])
        self.assertEqual(next_part['policy']['candidateStart'], 1)

    def test_short_spike_survives_on_full_grid(self):
        values = np.zeros(5000)
        values[3003] = 3
        result = evaluate(values, definition(upper=1), include_series=False)
        interval, = result['rawViolationIntervals']
        self.assertEqual((interval['start'], interval['end'], interval['maximumExceedance']), (3003, 3003, 2))
        self.assertNotIn('series', result)

    def test_numerical_overflow_is_unavailable_and_json_safe(self):
        constraint = definition(lower=-1e308)
        result = evaluate([1e308], constraint)
        self.assertEqual(result['current']['state'], 'unavailable')
        self.assertEqual(result['quality']['numericalUnavailableSamples'], 1)
        self.assertIsNone(result['maximumExceedance'])
        json.dumps(result, allow_nan=False)

    def test_reject_invalid_configuration_or_time_axes(self):
        for fields in ({'upper': True}, {'lower': 2, 'upper': 2}, {'lower': 1, 'warningLower': .5},
                       {'upper': 2, 'warningUpper': 3}, {'upper': 2, 'dwellSeconds': -1}, {'upper': 2, 'hysteresis': -1},
                       {'upper': 2, 'maxGapSeconds': 0}, {'upper': 2, 'absolute': True},
                       {'upper': 2, 'terms': [{'signalId': 'elsewhere'}]}, {'upper': 2, 'kind': 'rate', 'unit': 'm'}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                normalize_constraints([definition(**fields)], {'level': {'unit': 'm'}})
        for times in ([2, 1], [1, np.inf], [-1e308, 1e308], [[0, 1]]):
            with self.subTest(times=times), self.assertRaises(ValueError):
                evaluate([1, 2], definition(upper=1), times=times)


if __name__ == '__main__':
    unittest.main()
