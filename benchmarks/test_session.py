import dataclasses
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np

from l5.contracts import Signal, SignalSchema
from benchmarks.fetch_reference import fetch_reference
from benchmarks.monitoring import evaluate_case, persistent_alarms
from benchmarks.robustness import alarm_episodes
from benchmarks.session import ResearchSession, batch


class ResearchBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.schema=SignalSchema('toy','independent synthetic fixture',(Signal('a'),Signal('b')),1)
        data=np.random.default_rng(47).normal(size=(120,2))
        self.fit=batch(data[:60],self.schema,'run','normal_fit')
        self.cal=batch(data[60:],self.schema,'run','normal_calibration',start=60)

    def test_fit_and_calibration_roles_and_time_must_be_disjoint(self):
        for cal in (dataclasses.replace(self.cal,partition='fault_test'),dataclasses.replace(self.cal,timestamps=self.fit.timestamps)):
            with self.assertRaises(ValueError): ResearchSession.fit('robust-maxz',self.fit,cal)
        independent=dataclasses.replace(self.cal,sequence_id='independent run',timestamps=self.fit.timestamps)
        ResearchSession.fit('robust-maxz',self.fit,independent)

    def test_scoring_rejects_same_width_reordering_and_missing_observations(self):
        session=ResearchSession.fit('robust-maxz',self.fit,self.cal)
        reordered=SignalSchema('toy','independent synthetic fixture',(Signal('b'),Signal('a')),1)
        wrong=dataclasses.replace(self.cal,schema=reordered)
        missing=dataclasses.replace(self.cal,values=((None,1),*self.cal.values[1:]))
        gap=dataclasses.replace(self.cal,timestamps=tuple(t*2 for t in self.cal.timestamps))
        for invalid in (wrong,missing,gap):
            with self.assertRaises(ValueError): session.score(invalid)

    def test_temporal_state_resets_and_threshold_stays_frozen(self):
        for method in ('cusum-maxz','ewma-maxz','dpca-q-lag2'):
            with self.subTest(method=method):
                session=ResearchSession.fit(method,self.fit,self.cal)
                threshold=session.threshold
                scores=session.score(self.cal)
                extreme=dataclasses.replace(self.cal,values=tuple((100,100) for _ in self.cal.values))
                session.score(extreme)
                np.testing.assert_array_equal(session.score(self.cal),scores)
                self.assertEqual(session.threshold,threshold)

    def test_fractional_minute_delay_is_not_truncated(self):
        class Monitor:
            def score(self, rows): return np.array([0,0,2,2])
            def explain(self,*args): return ['a']
        result=evaluate_case(source='toy',fault_id=1,samples=np.zeros((4,2)),monitor=Monitor(),
                             threshold=1,consecutive=1,feature_names=('a','b'),onset_sample=1,seconds_per_sample=.5)
        self.assertAlmostEqual(result.detection_delay_minutes,1/120)
        for invalid in (True,1.5,float('nan')):
            with self.assertRaises(ValueError): persistent_alarms((1,2),1,invalid)

    def test_unknown_clock_never_becomes_a_24_hour_rate(self):
        self.assertIsNone(alarm_episodes((False,True,True),3,seconds_per_sample=None)['per_24h'])

    def test_corrupted_cache_is_rejected_without_network_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory)/'d00.dat').write_bytes(b'changed but cached data')
            with patch('benchmarks.fetch_reference.urlopen') as network:
                with self.assertRaisesRegex(ValueError,'SHA-256'): fetch_reference(directory,faults=())
                network.assert_not_called()


if __name__=='__main__': unittest.main()
