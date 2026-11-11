import unittest

import numpy as np

from .regime_evaluate import APPROACHES, Fault, Transition, Trial, _summary, _trial_metrics, synthetic_partitions


class RegimeBenchmarkMetricsTest(unittest.TestCase):
    def test_reports_abstentions_missed_faults_and_candidate_delay(self):
        trial = Trial('test', np.zeros((10, 1)), np.array(['A', 'A', 'A', 'transition', 'B', 'B',
                                                         'B', 'B', 'unknown', 'ambiguous']),
                      (Transition('A', 'B', 3, 4, 8),),
                      (Fault('already-active', 2, 4), Fault('new-alarm', 6, 8)))
        decisions = [dict(mode=mode, recognition=evidence,
                          **{field: alarm for field, _ in APPROACHES.values()},
                          **{field: None if evidence == 'ambiguous' else 0 for _, field in APPROACHES.values()})
                     for mode, evidence, alarm in zip(
                         ['A', 'A', 'A', None, None, 'B', 'B', 'B', 'B', None],
                         ['supported'] * 9 + ['ambiguous'],
                         [False, True, True, False, False, False, False, True, True, False])]
        result = dict(decisions=decisions, transitions=[dict(outcome='confirmed', fromMode='A', toMode='B',
                                                            candidateTime=3, confirmedTime=5)])
        summary = _summary([_trial_metrics(trial, result)])
        recognition = summary['recognition']
        self.assertEqual(recognition['confusion'], {'A': {'A': 2}, 'B': {'B': 1, 'unconfirmed': 1}})
        self.assertEqual(recognition['openSet']['unknown']['rejectionFraction'], 0)
        self.assertEqual(recognition['openSet']['ambiguous']['rejectionFraction'], 1)
        self.assertEqual(summary['transitions']['medianDelay'], 2)
        self.assertEqual(summary['transitions']['cases'][0]['candidate'], 3)
        monitor = summary['monitoring']['regimeAware']
        self.assertEqual(monitor['faults']['detected'], 1)
        self.assertEqual(monitor['faults']['missed'], 1)
        self.assertTrue(monitor['faults']['cases'][0]['activeBeforeOnset'])
        self.assertEqual(monitor['faults']['cases'][1]['delay'], 1)
        self.assertEqual(monitor['unknownHealthy']['alarmSamples'], 1)
        self.assertEqual(monitor['unknownHealthy']['alarmStarts'], 0)
        self.assertEqual(monitor['ambiguousHealthy']['coverage'], 0)

    def test_synthetic_fit_and_calibration_are_independent_reproducible_draws(self):
        partitions, rerun = synthetic_partitions(), synthetic_partitions()
        for mode, (fit, calibration) in partitions.items():
            self.assertEqual(fit.shape, (600, 5))
            self.assertEqual(calibration.shape, (300, 5))
            self.assertFalse(np.array_equal(fit[:len(calibration)], calibration))
            np.testing.assert_array_equal(fit, rerun[mode][0])
            np.testing.assert_array_equal(calibration, rerun[mode][1])


if __name__ == '__main__':
    unittest.main()
