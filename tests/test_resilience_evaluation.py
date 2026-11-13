from copy import deepcopy
import unittest
from unittest.mock import patch

from l5 import resilience_evaluation as evaluation
from l5.resilience_simulation import simulate_scenario


def event(identity, start, end, *, exclusive=True):
    return dict(id=identity, type='pump_degradation', target='pump', onset=start, recovery=end,
                intervals=[dict(start=start, end=end, endExclusive=exclusive)])


def analysis(states):
    return dict(times=list(range(len(states))), states=states,
                observedFraction=[0 if state == 'abstain' else 1 for state in states])


class ResilienceScoringTests(unittest.TestCase):
    def test_one_overlapping_alarm_credits_one_event(self):
        result = analysis(['normal', 'normal', 'alarm', 'alarm', 'alarm', 'normal'])
        metrics = evaluation.score_events(result, [event('a', 1, 5), event('b', 2, 5)], 5)
        self.assertTrue(metrics['presenceDetected'])
        self.assertFalse(metrics['allEventsMatched'])
        self.assertEqual(metrics['eventDetectionRate'], .5)
        self.assertEqual(metrics['simultaneousAlarmSamples'], 3)
        self.assertEqual(metrics['events'][0]['delay'], 1)
        self.assertIsNone(metrics['events'][1]['delay'])

    def test_assignment_maximizes_matched_events_and_respects_recovery(self):
        result = analysis(['normal', 'normal', 'alarm', 'normal', 'alarm', 'normal'])
        metrics = evaluation.score_events(result, [event('wide', 1, 5), event('narrow', 2, 4)], 5)
        self.assertTrue(metrics['allEventsMatched'])
        self.assertEqual([(item['id'], item['firstDetection']) for item in metrics['events']], [('wide', 4), ('narrow', 2)])
        end_only = evaluation.score_events(result, [event('recovered', 3, 4)], 4)
        self.assertFalse(end_only['presenceDetected'])

    def test_preexisting_alarm_and_unobserved_event(self):
        result = analysis(['alarm', 'alarm', 'alarm', 'normal', 'abstain', 'abstain'])
        metrics = evaluation.score_events(result, [event('later', 1, 3), event('gap', 4, 5, exclusive=False)], 5)
        self.assertTrue(metrics['presenceDetected'])
        self.assertEqual(metrics['detectedEvents'], 0)
        self.assertEqual(metrics['preFault']['alarmEvents'], 1)
        self.assertEqual(metrics['unobservedEvents'], 1)
        self.assertEqual(metrics['missedEvents'], 2)
        self.assertEqual(metrics['coverage'], 4/6)
        self.assertEqual(metrics['events'][1]['activeSamples'], 2)

    def test_unrealized_event_stays_out_of_denominator(self):
        metrics = evaluation.score_events(analysis(['normal', 'alarm']), [{**event('disabled', 0, 1), 'intervals': []}], 1)
        self.assertEqual(metrics['totalEvents'], 0)
        self.assertEqual(metrics['inactiveEventIds'], ['disabled'])
        self.assertIsNone(metrics['presenceDetected'])
        self.assertEqual(metrics['normal']['alarmFraction'], .5)

    def test_analysis_receives_only_measurements_and_independent_training(self):
        scenario = dict(duration=60., seed=evaluation.TRAINING_SEED, faults=[evaluation._fault('p', 'pump_degradation', 'pump')])
        simulation = simulate_scenario(scenario)
        scenario_without_fault = simulate_scenario({**scenario, 'faults': []})
        detector = {'algorithm': 'robust-maxz'}
        baseline = evaluation.evaluate_case(simulation, detector)
        self.assertEqual(baseline['metrics']['detectedEvents'], 1)
        revised = deepcopy(simulation)
        revised['truth'] = scenario_without_fault['truth']
        revised['scenario']['faults'] = []
        revised['observation_packets'] = []
        for row in revised['observations']:
            row['quality'] = {'level1': 'injected-label'}
        with patch.object(evaluation, 'run_analysis', wraps=evaluation.run_analysis) as run:
            modified = evaluation.evaluate_case(revised, detector)
            times, values, channels, settings = run.call_args.args
            self.assertEqual(channels, ['level1', 'level2'])
            self.assertNotIn('faults', settings)
            self.assertLess(settings['baselineRange'][1], settings['analysisRange'][0])
            self.assertEqual(len(times), 621)
            self.assertNotEqual(values[0, 0], values[320, 0])
        self.assertEqual(baseline['analysis']['scores'], modified['analysis']['scores'])
        self.assertEqual(baseline['analysis']['threshold'], modified['analysis']['threshold'])
        self.assertEqual(baseline['analysis']['states'], modified['analysis']['states'])
        self.assertEqual(modified['metrics']['totalEvents'], 0)


class ResilienceCampaignTests(unittest.TestCase):
    def setUp(self):
        self.base = dict(duration=100, faults=[evaluation._fault('p', 'pump_degradation', 'pump', onset=32.)])

    def test_grid_freezes_normalized_conditions_and_applies_duration_axis(self):
        cases = evaluation.prepare_campaign(dict(scenario=self.base, axes=[
            dict(path='faults.p.onset', values=[40, 45]), dict(path='faults.p.duration', values=[3, 6]),
            dict(path='measurement.noise', values=[.001, .01]),
            dict(path='detector.training.parameters.outlet', values=[.02, .03]),
        ]))
        self.assertEqual(len(cases), 16)
        self.assertEqual({case['scenario']['faults'][0]['recovery'] for case in cases}, {43, 46, 48, 51})
        self.assertEqual({case['detector']['training']['parameters']['outlet'] for case in cases}, {.02, .03})
        self.assertEqual(self.base['faults'][0]['onset'], 32)

    def test_grid_validates_fault_sets_and_configuration_bounds(self):
        with self.assertRaisesRegex(ValueError, 'Fault event'):
            evaluation.prepare_campaign(dict(scenario=self.base, axes=[dict(path='faults', values=[[None]])]))
        with self.assertRaisesRegex(ValueError, 'absent event'):
            evaluation.prepare_campaign(dict(scenario=self.base, axes=[dict(path='faults.absent.duration', values=[3])]))
        with self.assertRaisesRegex(ValueError, 'at most 64'):
            evaluation.prepare_campaign(dict(scenario=self.base, axes=[dict(path='seed', values=list(range(9))),
                                                                         dict(path='duration', values=list(range(90, 98)))]))

    def test_search_is_reproducible_and_keeps_fixed_detector(self):
        body = dict(mode='search', scenario=self.base, objective='delay', budget=5,
                    axes=[dict(path='faults.p.severity', min=.05, max=.8),
                          dict(path='faults.p.duration', min=2, max=8)])
        first = evaluation.prepare_campaign(body)
        self.assertEqual(first, evaluation.prepare_campaign(body))
        self.assertNotEqual(first, evaluation.prepare_campaign({**body, 'seed': 22}))
        self.assertEqual({row['phase'] for row in first}, {'search'})
        self.assertEqual(len({row['scenario']['seed'] for row in first}), 1)
        self.assertEqual({row['detector']['algorithm'] for row in first}, {'robust-maxz'})
        with self.assertRaisesRegex(ValueError, 'fixed'):
            evaluation.prepare_campaign({**body, 'axes': [dict(path='detector.training.parameters.outlet', min=.02, max=.03)]})

    def test_fixed_benchmark_detects_paired_presence_suppression(self):
        suite = evaluation.prepare_campaign({'mode': 'benchmark'})
        self.assertEqual(len(suite), 64)
        self.assertEqual({case['phase'] for case in suite}, {'evaluation'})
        rows = [case for case in suite if case['name'].startswith('short-') and case['detector']['signals'] == ['level1']]
        self.assertEqual(len(rows), 3)
        metrics = {case['name']: evaluation.evaluate_case(simulate_scenario(case['scenario']), case['detector'],
                    objective='suppression')['metrics'] for case in rows}
        self.assertTrue(metrics['short-pump']['presenceDetected'])
        self.assertTrue(metrics['short-valve']['presenceDetected'])
        combined = metrics['short-canceling-pair']
        self.assertFalse(combined['presenceDetected'])
        self.assertEqual(combined['coverage'], 1.)
        self.assertEqual(combined['suppression']['lostPresenceEvents'], 2)
        self.assertEqual(combined['searchScores']['suppression'], 1.)


if __name__ == '__main__':
    unittest.main()
