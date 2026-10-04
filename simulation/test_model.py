import unittest

from generate import FAULT_TIME, alarms, build_scenario, correlation, detect, simulate


class ProcessModelTests(unittest.TestCase):
    def test_reproducible_trajectory(self):
        self.assertEqual(simulate(), simulate())

    def test_branch_prefix_and_effect(self):
        observed = simulate()
        for time in (90, 120, 150):
            with self.subTest(time=time):
                branch = simulate(time)
                self.assertEqual(observed[:time], branch[:time])
                self.assertLess(max(p['pressure'] for p in branch), max(p['pressure'] for p in observed))
                self.assertLess(branch[-1]['pressure'], 2800)
                self.assertAlmostEqual(branch[-1]['valve'], observed[-1]['valve'])

    def test_healthy_run_has_no_incident(self):
        healthy = simulate(fault=False)
        self.assertEqual(detect(healthy), {})
        self.assertEqual(alarms(healthy), [])

    def test_incident_is_detected_after_fault_and_before_pressure(self):
        detected = detect(simulate())
        self.assertGreaterEqual(detected['valve']['time'], FAULT_TIME)
        self.assertLess(detected['valve']['time'], detected['pressure']['time'])

    def test_complete_evidence_and_alarm_membership(self):
        scenario = build_scenario()
        self.assertTrue(all(check['passed'] for check in scenario['checks']))
        ids = [event['id'] for event in scenario['alarms']]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(sorted(e['t'] for e in scenario['alarms']), [e['t'] for e in scenario['alarms']])
        self.assertTrue(all(event['chain'] in {chain['id'] for chain in scenario['chains']} for event in scenario['alarms']))
        self.assertIsNotNone(scenario['tripTime'])

    def test_correlation_and_score_bounds(self):
        self.assertEqual(correlation([1, 2, 3], [2, 4, 6]), 1)
        self.assertEqual(correlation([1, 2, 3], [6, 4, 2]), -1)
        self.assertEqual(correlation([1, 1, 1], [1, 2, 3]), 0)
        scenario = build_scenario()
        scores = [candidate['score'] for candidate in scenario['candidates']]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertTrue(all(0 <= score <= 100 for score in scores))

    def test_early_intervention_avoids_threshold_but_late_does_not(self):
        scenario = build_scenario()
        self.assertFalse(scenario['branches'][0]['trip'])
        self.assertTrue(scenario['branches'][1]['trip'])
        self.assertTrue(scenario['branches'][2]['trip'])

    def test_committed_artifact_matches_current_engine(self):
        import json
        from pathlib import Path
        committed = json.loads((Path(__file__).resolve().parents[1] / 'src/data/scenario.json').read_text())
        self.assertEqual(committed, json.loads(json.dumps(build_scenario())))


if __name__ == '__main__':
    unittest.main()
