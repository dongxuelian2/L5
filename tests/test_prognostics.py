"""First-passage laws, causal fitting, and maintenance cost calculations."""
from dataclasses import replace
import math
import unittest

import numpy as np

from l5.prognostics import (
    Asset,
    ConditionHistory,
    Indicator,
    MaintenanceEvent,
    Observation,
    _first_passage,
    failure_probability,
    forecast,
    plan_maintenance,
)


def condition(rows, *, direction='increasing', threshold=10., **metadata):
    asset = Asset('pump-1', 'Pump 1', ('capacity', 'load'))
    indicator = Indicator('capacity', 'Rated-flow-equivalent capacity', 'L/s', threshold, direction)
    return ConditionHistory(asset, indicator, tuple(Observation(*row) for row in rows), **metadata)


ECONOMICS = dict(preventive_cost=100., corrective_cost=400., downtime_cost=10., preventive_duration=2.,
                 corrective_duration=4., failure_consequence=60., replacement_cost=130., replacement_duration=1.)


class PrognosticForecastTests(unittest.TestCase):
    def test_irregular_decreasing_indicator_with_missing_cutoff_and_duplicate_time(self):
        history = condition([(0, 100), (2, 96), (2, 96), (3.5, 93), (6, 88), (7, np.nan), (8, None)],
                            direction='decreasing', threshold=70.)
        result = forecast(history, method='linear', horizon=20., probability_horizons=[0., 6., 8., 20.])
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['cutoff'], 8.)
        self.assertEqual(result['diagnostics']['last_measurement_time'], 6.)
        self.assertEqual(result['diagnostics']['n_missing'], 2)
        self.assertEqual(result['diagnostics']['n_observations'], 5)
        self.assertAlmostEqual(result['trajectory'][0]['median'], 84.)
        self.assertAlmostEqual(result['rul']['median'], 7.)
        self.assertEqual([row['probability'] for row in result['rul']['probabilities']], [0., 0., 1., 1.])
        self.assertEqual(failure_probability(result, result['rul']['median']), 1.)
        self.assertEqual(failure_probability(result, result['rul']['median'] - 1e-5), 0.)
        self.assertIsNone(failure_probability(result, 21.))

    def test_future_measurements_failure_and_reset_cannot_influence_a_cutoff(self):
        rows = [(0, 0., .3), (1.5, .3, .4), (3, .7, .5), (4, 1., .4), (5, None), (6, 1.5, .7)]
        prefix = condition(rows, operating_periods=((0., 6.),), observed_until=6.)
        full = condition(rows + [(7, 300., 9.), (10, 200., 2.)], events=(MaintenanceEvent(8.),),
                         operating_periods=((0., 7.), (8., 10.)), end_status='failed', failure_time=7., observed_until=10.)
        for method in ('linear', 'stochastic'):
            with self.subTest(method=method):
                causal = forecast(full, method=method, cutoff=6., horizon=20.)
                self.assertEqual(causal, forecast(prefix, method=method, cutoff=6., horizon=20.))
                self.assertEqual(causal['diagnostics']['load_range'], [.3, .7])
                self.assertEqual(causal['diagnostics']['operating_periods'], [[0., 6.]])
                self.assertEqual(forecast(full, method=method, cutoff=7.)['status'], 'threshold_reached')
                after_reset = forecast(full, method=method, cutoff=10.)
                self.assertEqual(after_reset['status'], 'insufficient_data')
                self.assertEqual(after_reset['diagnostics']['latest_maintenance'], dict(time=8., action='restore'))
                self.assertEqual(after_reset['diagnostics']['n_excluded_pre_maintenance'], 7)
                self.assertEqual(len(after_reset['history']), 8)

    def test_pre_maintenance_measurements_remain_visible_and_unfitted(self):
        history = condition([(0, 20), (1, 30), (2, 1), (3, 2), (4, 3), (5, 4), (6, 5)],
                            events=(MaintenanceEvent(2., 'replace'),))
        result = forecast(history, method='linear')
        self.assertEqual(result['diagnostics']['fit_start'], 2.)
        self.assertEqual(result['diagnostics']['n_excluded_pre_maintenance'], 2)
        self.assertEqual([point['fitted'] for point in result['history'][:2]], [None, None])
        self.assertAlmostEqual(result['history'][2]['fitted'], 1.)

    def test_linear_non_crossing_and_distinct_insufficient_cases(self):
        away = forecast(condition([(0, 5), (1, 4), (3, 2)]), method='linear', horizon=15)
        self.assertEqual(away['status'], 'beyond_horizon')
        self.assertIsNone(away['rul']['median'])
        self.assertEqual(failure_probability(away, 15), 0.)
        self.assertEqual(forecast(condition([(0, 2), (1, None)]))['status'], 'insufficient_data')
        self.assertEqual(forecast(condition([(0, i) for i in range(5)]))['status'], 'not_identifiable')
        self.assertEqual(forecast(condition([(i, 2) for i in range(5)]))['status'], 'not_identifiable')
        extreme = forecast(condition([(0, -1e308), (1, 0), (3, 1e308)]), method='linear')
        self.assertEqual(extreme['status'], 'numerical_failure')

    def test_stochastic_forecast_propagates_process_and_parameter_uncertainty(self):
        rows = [(0, 0.), (.7, .4), (2.2, .2), (3.3, None), (4.9, .9), (5.3, 1.6), (8.2, 1.9),
                (9., 1.1), (12., 2.3), (14., None)]
        history = condition(rows, threshold=4.)
        result = forecast(history, horizon=30., seed=7)
        self.assertEqual(result, forecast(history, horizon=30., seed=7))
        self.assertEqual(result['status'], 'ok')
        self.assertGreater(result['diagnostics']['process_variance_rate'], 0.)
        self.assertGreater(result['diagnostics']['measurement_sd'], 0.)
        self.assertGreater(np.ptp(result['diagnostics']['drift_interval']), 0.)
        self.assertEqual(result['diagnostics']['drift_confidence'], result['rul']['confidence'])
        first, last = result['trajectory'][0], result['trajectory'][-1]
        self.assertGreater(last['upper'] - last['lower'], first['upper'] - first['lower'])
        self.assertIsNotNone(result['history'][3]['fitted'])
        cdf = [point['probability'] for point in result['distribution']]
        self.assertTrue(all(0 <= a <= b <= 1 for a, b in zip(cdf, cdf[1:])))
        self.assertTrue(0 < cdf[-1] < 1)
        self.assertIsNone(forecast(history, horizon=10., seed=7)['rul']['upper'])
        rescaled = forecast(condition([(t * 60, value) for t, value in rows], threshold=4.), horizon=1800., seed=7)
        self.assertAlmostEqual(rescaled['rul']['median'], 60 * result['rul']['median'])

    def test_brownian_first_passage_matches_reflection_law_and_defective_tail(self):
        n = 120_000
        a, q, duration = 1.25, .7, 2.5

        def normal_cdf(x):
            return .5 * math.erfc(-x / math.sqrt(2.))

        for mu in (-.4, 0., .55):
            with self.subTest(mu=mu):
                hits = _first_passage(np.full(n, a), np.full(n, mu), np.full(n, q), np.random.default_rng(172))
                scale = math.sqrt(q * duration)
                eventual = math.exp(2 * mu * a / q)
                exact = normal_cdf((mu * duration - a) / scale) + eventual * normal_cdf((-mu * duration - a) / scale)
                self.assertAlmostEqual(float(np.mean(hits <= duration)), exact, delta=.006)
                self.assertAlmostEqual(float(np.mean(np.isfinite(hits))), min(1., eventual), delta=.006)

    def test_validation_of_indicator_and_operating_periods(self):
        with self.assertRaisesRegex(ValueError, 'operating threshold'):
            Indicator('capacity', 'Capacity', 'L/s', 70., 'decreasing', 60.)
        with self.assertRaisesRegex(ValueError, 'non-overlapping'):
            condition([(0., 1.)], operating_periods=((0., 2.), (1., 3.)))
        with self.assertRaisesRegex(ValueError, 'forecast horizon'):
            forecast(condition([(0., 1.)]), horizon=10., probability_horizons=[20.])


class MaintenancePlanningTests(unittest.TestCase):
    def test_costs_follow_cdf_and_separate_failure_from_planned_intervention(self):
        prediction = dict(status='ok', horizon=10., distribution=[dict(time=t, probability=p)
                          for t, p in [(0., 0.), (5., .2), (10., .6)]])
        result = plan_maintenance(prediction, **ECONOMICS, scheduled_time=5.)
        options = {option['action']: option for option in result['options']}
        self.assertEqual(options['continue']['expected_cost'], 300.)
        self.assertEqual(options['schedule']['expected_failure_cost'], 100.)
        self.assertEqual(options['schedule']['expected_intervention_cost'], 96.)
        self.assertEqual(options['preventive']['expected_cost'], 120.)
        self.assertEqual(options['replace']['expected_cost'], 140.)
        self.assertEqual(result['recommended']['action'], 'preventive')
        self.assertEqual(result['savings_vs_continue'], 180.)
        shortened = plan_maintenance(prediction, **ECONOMICS, planning_horizon=2.5)
        self.assertEqual(shortened['recommended']['action'], 'continue')
        self.assertEqual(shortened['recommended']['expected_cost'], 50.)

    def test_failure_ties_and_discounted_deferral(self):
        prediction = forecast(condition([(0, 0), (1, 1), (2, 2)], threshold=7), method='linear', horizon=10.)
        crossing = prediction['rul']['median']
        result = plan_maintenance(prediction, **ECONOMICS, scheduled_time=crossing, discount_rate=.5)
        on_crossing = next(o for o in result['options'] if o['action'] == 'schedule' and o['time'] == crossing)
        self.assertEqual(on_crossing['failure_probability'], 1.)
        self.assertAlmostEqual(on_crossing['expected_cost'], 500 * math.exp(-.5 * crossing / 10))
        self.assertEqual(result['recommended']['action'], 'schedule')
        self.assertAlmostEqual(result['schedule_resolution'], 10 / 60)
        self.assertAlmostEqual(result['recommended']['time'], 29 * result['schedule_resolution'])
        self.assertLessEqual(result['recommended']['time'], crossing - result['schedule_resolution'] / 2)
        self.assertLess(result['recommended']['expected_cost'], 120.)

    def test_confirmed_failure_and_unavailable_forecasts(self):
        history = condition([(0, 0), (1, 11)], threshold=10.)
        observed = forecast(replace(history, end_status='failed', failure_time=1.))
        self.assertEqual(observed['rul']['median'], 0.)
        self.assertEqual(failure_probability(observed, 0.), 1.)
        plan = plan_maintenance(observed, **ECONOMICS)
        self.assertEqual([row['action'] for row in plan['options']], ['corrective'])
        self.assertEqual(plan['recommended']['expected_cost'], 500.)
        unknown = forecast(history)
        self.assertEqual(unknown['diagnostics']['observed_threshold_exceedances'], 1)
        self.assertIsNone(plan_maintenance(unknown, **ECONOMICS)['recommended'])


if __name__ == '__main__':
    unittest.main()
