import unittest

from benchmarks.alarm_correlation import evaluate, flood_scenario, operational_scenario


class AlarmEvaluationTests(unittest.TestCase):
    def test_close_and_overlapping_independent_faults_stay_separate(self):
        result = evaluate(operational_scenario())
        self.assertEqual(result['rawEventCount'], 12)
        self.assertEqual(result['groupCount'], 8)
        self.assertEqual(result['trueRelatedPairs'], 10)
        self.assertEqual(result['incorrectMergePairs'], 0)
        self.assertEqual(result['incorrectSplitPairs'], 1)  # acquisition blackout
        self.assertTrue(result['eventPreserved'])
        self.assertTrue(result['alarmSamplesPreserved'])
        self.assertEqual({axis['axisId'] for axis in result['axes']}, {'utc', 'dataset:bench'})

    def test_broader_equipment_policy_exposes_false_merges(self):
        traces, policy = operational_scenario()
        result = evaluate((traces, {**policy, 'groupByEquipment': True}))
        self.assertEqual(result['incorrectMergePairs'], 5)
        self.assertTrue(result['eventPreserved'])

    def test_flood_reduces_review_load_with_every_source_alarm_retained(self):
        result = evaluate(flood_scenario())
        self.assertEqual(result['rawEventCount'], 3900)
        self.assertEqual(result['groupCount'], 1500)
        self.assertEqual(result['trueRelatedPairs'], 3600)
        self.assertEqual(result['incorrectMergePairs'], 0)
        self.assertEqual(result['incorrectSplitPairs'], 0)
        self.assertTrue(result['eventPreserved'])
        self.assertTrue(result['alarmSamplesPreserved'])
        self.assertEqual(result['axes'][0]['peakArrivalCount'], 78)
        self.assertEqual(result['axes'][0]['peakConcurrent'], 12)
