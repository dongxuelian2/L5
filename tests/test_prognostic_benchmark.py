"""Progressive pump physics and the held-out scoring protocol."""
import json
import unittest
from unittest.mock import patch

from l5.models.tanks import CoupledTankModel, integrate
from l5.prognostic_benchmark import benchmark_dataset, evaluate, simulate_progressive


class ProgressivePumpTests(unittest.TestCase):
    def test_loss_drives_true_hydraulics_and_preserves_mass(self):
        settings = dict(duration=360., sample_interval=10., initial_condition=.9, degradation_rate=.001,
                        failure_threshold=.3, flow_noise=0., jitter=0., missing_fraction=0.)
        run = simulate_progressive(settings)
        healthy = simulate_progressive(settings | {'degradation_rate': 0.})
        self.assertAlmostEqual(run.failure_time, 200.)
        self.assertIsNone(healthy.failure_time)
        self.assertAlmostEqual(run.rows[10]['capacity_loss'], .2)
        self.assertAlmostEqual(run.physical[10]['inlet'], .024)
        self.assertLess(run.physical[-1]['level2'], healthy.physical[-1]['level2'])
        self.assertLess(max(abs(row['massResidual']) for row in run.physical), 1e-9)
        self.assertTrue(all(min(row['level1'], row['level2']) >= 0. for row in run.physical))

    def test_maintenance_resets_condition_without_resetting_tank_inventory(self):
        settings = dict(duration=200., sample_interval=10., degradation_rate=.001, failure_threshold=.17,
                        flow_noise=0., jitter=0., missing_fraction=0.)
        worn = simulate_progressive(settings)
        restored = simulate_progressive(settings | {'maintenance': [dict(time=120., action='replace', condition=.98)]})
        self.assertAlmostEqual(worn.failure_time, 140.)
        self.assertIsNone(restored.failure_time)
        self.assertAlmostEqual(restored.rows[12]['capacity_loss'], .02)
        self.assertAlmostEqual(restored.physical[12]['volume'], worn.physical[12]['volume'])
        self.assertGreater(restored.physical[-1]['level2'], worn.physical[-1]['level2'])
        self.assertLess(max(abs(row['massResidual']) for row in restored.physical), 1e-9)

    def test_observation_noise_and_missing_data_leave_truth_intact(self):
        settings = dict(duration=450., load_profile='variable', seed=78)
        run = simulate_progressive(settings)
        noisy = simulate_progressive(settings | dict(missing_fraction=.7, flow_noise=.002))
        self.assertEqual(run, simulate_progressive(settings))
        self.assertEqual(run.physical, noisy.physical)
        self.assertEqual(run.failure_time, noisy.failure_time)
        self.assertNotEqual(run.rows, noisy.rows)
        self.assertGreater(len({row['pump'] for row in run.rows}), 1)
        self.assertGreater(len({round(b['t']-a['t'], 5) for a,b in zip(run.rows, run.rows[1:])}), 1)
        dataset = benchmark_dataset(settings)
        self.assertEqual(dataset['rows'], run.rows)
        self.assertEqual(dataset['signals']['capacity_loss'], 'fraction')
        self.assertNotIn('failure_time', dataset)
        self.assertNotIn('physical', dataset)

    def test_instantaneous_scenario_retains_its_existing_flow_drop(self):
        config = CoupledTankModel().validate(dict(fault='pump_degradation', start=10., severity=.5, duration=20., step=1.))
        rows, _ = integrate(config)
        self.assertAlmostEqual(rows[9]['inlet'], .03)
        self.assertAlmostEqual(rows[10]['inlet'], .0195)
        self.assertAlmostEqual(rows[-1]['inlet'], .0195)

    def test_invalid_generator_settings_are_rejected(self):
        for config in ({'duration': True}, {'failure_threshold': .1, 'operating_threshold': .1},
                       {'tank_config': {'fault': 'pump_degradation'}}, {'tank_config': {'pumpRate': 0.}},
                       {'rate_changes': [{'time': 400., 'rate': .001}]}, {'seed': 1.5},
                       {'maintenance': [{'time': 40., 'action': 'replace'}, {'time': 40., 'action': 'restore'}]}):
            with self.subTest(config=config), self.assertRaises(ValueError):
                benchmark_dataset(config)


class RetrospectiveTests(unittest.TestCase):
    def test_held_out_scoring_receives_only_causal_prefixes_and_censors_episodes(self):
        from l5.prognostics import forecast

        def check_prefix(history, *, method, cutoff, horizon, probability_horizons):
            self.assertTrue(all(observation.time <= cutoff for observation in history.observations))
            self.assertTrue(all(event.time <= cutoff for event in history.events))
            self.assertIsNone(history.failure_time)
            return forecast(history, method=method, cutoff=cutoff, horizon=horizon,
                            probability_horizons=probability_horizons)

        with patch('l5.prognostics.forecast', side_effect=check_prefix) as model:
            result = evaluate()
        json.dumps(result, allow_nan=False)
        self.assertEqual(model.call_count, 2*len(result['cases']))
        self.assertEqual(len(result['trajectories']), 24)
        self.assertNotIn(result['protocol']['development_seed'], result['protocol']['evaluation_seeds'])
        self.assertTrue(all(case['failure_time'] is None for case in result['cases'] if case['scenario'] in {'no_failure', 'censored'}))
        before_reset = [case for case in result['cases'] if case['scenario'] == 'model_mismatch' and case['cutoff'] < 210.]
        self.assertTrue(all(case['remaining_life'] is None and case['observation_end'] == 210. for case in before_reset))
        self.assertTrue(all(prediction['maintenance'] is None for case in before_reset for prediction in case['predictions']))
        for summary in result['models']:
            self.assertEqual(sum(summary['statuses'].values()), len(result['cases']))
            self.assertGreater(summary['rul']['median_available'], 0)
            self.assertGreater(summary['stability']['count'], 0)
            self.assertGreater(summary['maintenance']['count'], 0)
            for score in summary['reliability']:
                self.assertGreater(score['count'], 0)
                self.assertLessEqual(score['count'], sum(case['cutoff']+score['horizon'] <= case['observation_end'] for case in result['cases']))
                self.assertEqual(sum(bucket['count'] for bucket in score['bins']), score['count'])


if __name__ == '__main__':
    unittest.main()
