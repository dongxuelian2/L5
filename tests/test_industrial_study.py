"""Closed-loop process integration across persistence, statistics and control."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np

from l5.industrial_study import CHANNELS, diagnose, study
from l5.reports import render_report
from l5.workspace import WorkspaceStore
from simulation.tep import executable, simulate


class CoolingStudy(unittest.TestCase):
    def test_onset_search_uses_only_observations_through_cutoff(self):
        times = np.arange(0, 5400, 180)
        ages = np.arange(-5400, 5400, 180)
        reference = np.maximum(ages[:, None], 0) / 180
        observed = np.maximum(times[:, None] - 1440, 0) / 180
        observed[times >= 2880] = -100
        for alarm in (1620, 2160):
            result = diagnose(times, observed, alarm, {'ramp': (ages, reference)}, [0.], np.eye(1), 720)
            self.assertEqual(result['hypothesis'], 'ramp')
            self.assertEqual(result['estimatedOnsets']['ramp'], 1440)
            self.assertEqual(result['distances']['ramp'], 0.)
            self.assertEqual(result['cutoff'], alarm + 540)

    def test_matched_intervention_and_workspace_reuse(self):
        with TemporaryDirectory() as directory:
            store = WorkspaceStore(Path(directory))
            self.addCleanup(store.close)
            wid = store.create_workspace('Cooling study')['id']
            first = study(store, wid, 'measurements')
            with patch('l5.industrial_study.simulate', side_effect=ValueError('simulation failed')):
                with self.assertRaisesRegex(ValueError, 'simulation failed'):
                    study(store, wid, 'investigation')
            self.assertEqual(study(store, wid)['datasets'], first['datasets'])
            with patch.object(store.incidents, 'create', side_effect=RuntimeError('interrupted')):
                with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                    study(store, wid, 'investigation')
            analysis_id = store.jobs(wid)[0]['id']
            result = study(store, wid, 'investigation')
            self.assertEqual(result['analysisId'], analysis_id)
            self.assertEqual(first['datasets']['evaluation'], result['datasets']['evaluation'])
            report = result['report']
            baseline = report['sources']['evaluation']
            self.assertAlmostEqual(baseline['initialPressureKPaGauge'], 2705, places=3)
            self.assertLess(baseline['componentBalanceMaxLbmolPerHour'], 1e-9)
            self.assertEqual(report['detection']['windows']['1800']['detectedEvents'], 1)
            self.assertLess(report['signatureDistances']['reactor-reference'], report['signatureDistances']['condenser-reference'])
            def series(role):
                return store.load_data(store.dataset(result['datasets'][role]))[1]
            x = series('evaluation')
            y = series('intervention')
            np.testing.assert_array_equal(x[:160], y[:160])
            self.assertLess(report['comparison']['intervention']['coolingValveTravel'],
                            report['comparison']['evaluation']['coolingValveTravel'])
            repeat, _ = simulate(executable(store.root / 'tep-build')[0], 4, baseline['seed'])
            np.testing.assert_allclose(repeat[:, 1:], x, rtol=1e-13)
            self.assertEqual(result['datasets'], study(store, wid)['datasets'])

            analysis = store.result(result['analysisId'])
            model = analysis['model']
            delta = x[:, np.array(CHANNELS)-1] - model['center']
            scores = np.einsum('ij,ij->i', delta, np.linalg.solve(model['covariance'], delta.T).T)
            np.testing.assert_allclose(analysis['scores'], scores)
            self.assertEqual(analysis['config']['industrialStudy']['sources'], result['datasets'])
            self.assertEqual(analysis['experiment']['runId'], result['runId'])
            self.assertEqual(report['diagnosis']['hypothesis'], 'reactor-reference')
            self.assertEqual(report['diagnosis']['cutoff'], analysis['summary']['firstDetection'] + 3420)
            self.assertIn('RMS whitened residual', render_report(store, result['incidentId']))
            edited = store.experiments.get(result['experimentId'])['config']
            edited['persistence'] = 3
            store.experiments.save(wid, dict(config=edited), result['experimentId'])
            source = store.root / wid / 'datasets' / result['datasets']['evaluation'] / 'source.csv'
            original_bytes = source.read_bytes()
            source.unlink()
            self.assertNotIn('evaluation', study(store, wid)['datasets'])
            restored = study(store, wid, 'investigation')
            self.assertEqual(restored, result)
            self.assertEqual(source.read_bytes(), original_bytes)
            self.assertEqual(len(store.jobs(wid)), 1)
            self.assertEqual(len(store.experiments.list(wid)), 1)
            self.assertEqual(len(store.incidents.list(wid)), 1)
            store.close()
            reopened = WorkspaceStore(Path(directory))
            try:
                self.assertEqual(study(reopened, wid), result)
            finally:
                reopened.close()
