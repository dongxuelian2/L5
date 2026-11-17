import json
import unittest

import numpy as np

from l5.regimes import FittedRegimes, evaluate_regimes, fit_regimes


class RegimeTests(unittest.TestCase):
    signals = ['load', 'temperature', 'pressure']

    def setUp(self):
        rng = np.random.default_rng(83)

        def partition(location):
            load = rng.normal(location, .24, 120)
            temperature = rng.normal(location / 2, .32, 120)
            pressure = temperature + rng.normal(0, .12, 120)
            return np.column_stack((load, temperature, pressure))

        self.partitions = {'low': (partition(-8), partition(-8)), 'high': (partition(8), partition(8))}
        self.low = [-8, -4, -4]
        self.high = [8, 4, 4]
        self.fault = [8, 4, 9]

    def fit(self, **config):
        return fit_regimes(self.partitions, self.signals, {'recognitionSignals': ['load'], 'dwell': 3, **config})

    def evaluate(self, model, observations, times=None, **options):
        return evaluate_regimes(model, np.arange(len(observations)) if times is None else times, observations, **options)

    def test_recognition_dwell_transient_and_confirmation_times(self):
        values = [self.low] * 3 + [self.high, self.low, [0, 0, 0]] + [self.high] * 4
        result = self.evaluate(self.fit(), values)
        self.assertEqual([row['mode'] for row in result['decisions']],
                         [None, None, 'low', None, 'low', None, None, None, 'high', 'high'])
        self.assertEqual(result['decisions'][5]['recognition'], 'unknown')
        self.assertEqual(result['decisions'][5]['activeMode'], 'low')
        self.assertTrue(result['decisions'][5]['alarm'])
        self.assertEqual(result['decisions'][5]['alarmKind'], 'unknown')
        transient, confirmed = result['transitions']
        self.assertEqual((transient['candidateTime'], transient['endTime'], transient['resolvedTime'], transient['outcome']),
                         (3, 3, 4, 'transient'))
        self.assertEqual((confirmed['startTime'], confirmed['candidateTime'], confirmed['confirmedTime'], confirmed['outcome']),
                         (5, 6, 8, 'confirmed'))
        self.assertEqual(result['summary']['confirmedTransitions'], 1)

    def test_detector_scores_cannot_override_recognition_or_hide_transition_alarms(self):
        values = [self.low] * 3 + [self.fault] * 4
        result = self.evaluate(self.fit(), values)
        self.assertTrue(all(row['candidateMode'] == 'high' for row in result['decisions'][3:]))
        first = result['decisions'][3]
        self.assertIsNone(first['mode'])
        self.assertEqual((first['status'], first['scoringMode'], first['alarmKind']), ('abnormal', 'high', 'transition'))
        self.assertTrue(first['transition'] and first['alarm'])
        self.assertEqual(result['intervals'][0]['signals'][0], 'pressure')
        self.assertEqual(result['intervals'][1]['kind'], 'mode')
        self.assertEqual(result['intervals'][1]['samples'], 1)
        healthy = self.evaluate(self.fit(), [self.low] * 3 + [self.high] * 4)
        self.assertEqual(healthy['summary']['alarmSamples'], 0)
        self.assertEqual(healthy['summary']['singleAlarmSamples'], 4)

    def test_ambiguous_models_abstain_even_when_global_detector_can_score(self):
        model = fit_regimes({'first': self.partitions['low'], 'second': self.partitions['low']}, self.signals)
        row = self.evaluate(model, [self.low])['decisions'][0]
        self.assertEqual(row['recognition'], 'ambiguous')
        self.assertEqual(row['margin'], 0)
        self.assertIsNone(row['score'])
        self.assertIsNotNone(row['globalScore'])
        self.assertTrue(all(item['supported'] for item in row['evidence'].values()))

    def test_gaps_and_missing_observations_reset_dwell_and_alarm_persistence(self):
        model = self.fit(persistence=3)
        times = [0, 1, 2, 3, 4, 100, 101, 102, 103, 104, 105, 106]
        values = [self.low] * 3 + [self.fault] * 5 + [[8, 4, np.nan]] + [self.fault] * 3
        result = self.evaluate(model, values, times, gap_threshold=2)
        decisions = result['decisions']
        self.assertEqual([row['time'] for row in decisions if row['alarm']], [102, 106])
        self.assertEqual(decisions[5]['candidateSamples'], 1)
        self.assertTrue(decisions[5]['gapBefore'])
        self.assertEqual(decisions[8]['recognition'], 'supported')
        self.assertIsNone(decisions[8]['score'])
        self.assertEqual(decisions[8]['status'], 'unknown')
        self.assertEqual(result['transitions'][1]['confirmedTime'], 102)
        missing_recognition = self.evaluate(model, [self.low] * 3 + [[np.nan, -4, -4]])['decisions'][-1]
        self.assertEqual(missing_recognition['recognition'], 'insufficient')
        self.assertEqual(missing_recognition['activeMode'], 'low')
        self.assertIsNone(missing_recognition['mode'])

    def test_singular_covariance_is_regularized_and_pca_parameters_reopen(self):
        partitions = {mode: tuple(np.column_stack((part[:, 0], part[:, 1], part[:, 1])) for part in datasets)
                      for mode, datasets in self.partitions.items()}
        model = fit_regimes(partitions, self.signals, {'algorithm': 'pca-q', 'detectors': {'high': {'algorithm': 'pca-t2'}}})
        payload = model.to_dict()
        low = payload['modes']['low']
        self.assertEqual(np.linalg.matrix_rank(low['covariance']), 2)
        self.assertTrue((np.linalg.eigvalsh(low['regularizedCovariance']) > 0).all())
        self.assertEqual(payload['modes']['high']['detector']['algorithm'], 'pca-t2')
        self.assertEqual(payload['globalDetector']['algorithm'], 'pca-q')
        reopened = FittedRegimes.from_dict(json.loads(json.dumps(payload, sort_keys=True, allow_nan=False)))
        self.assertEqual(reopened.to_dict(), payload)
        values = [self.low] * 4 + [self.high] * 4 + [self.fault] * 2
        self.assertEqual(self.evaluate(model, values), self.evaluate(reopened, values))

    def test_prefix_decisions_are_causal(self):
        model = self.fit()
        values = [self.low] * 3 + [self.high] * 3 + [self.fault]
        prefix = self.evaluate(model, values[:5])
        complete = self.evaluate(model, values)
        self.assertEqual(prefix['decisions'], complete['decisions'][:5])
        self.assertEqual(prefix['transitions'][0]['outcome'], 'pending')
        self.assertEqual(complete['transitions'][0]['outcome'], 'confirmed')

    def test_invalid_options_and_nonchronological_evaluation_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Covariance shrinkage'):
            self.fit(shrinkage=0)
        with self.assertRaisesRegex(ValueError, 'reference declared'):
            self.fit(detectors={'elsewhere': {}})
        with self.assertRaisesRegex(ValueError, 'strictly increasing'):
            self.evaluate(self.fit(), [self.low, self.high], [1, 1])
        too_short = {'low': (self.partitions['low'][0][:29], self.partitions['low'][1]), 'high': self.partitions['high']}
        with self.assertRaisesRegex(ValueError, '30 complete fit'):
            fit_regimes(too_short, self.signals)


if __name__ == '__main__':
    unittest.main()
