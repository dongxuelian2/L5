"""Closed-loop process integration across persistence, statistics and control."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np

from l5.industrial_study import study
from l5.workspace import WorkspaceStore
from simulation.tep import executable, simulate


class CoolingStudy(unittest.TestCase):
    def test_matched_intervention_and_workspace_reuse(self):
        with TemporaryDirectory() as directory:
            store = WorkspaceStore(Path(directory))
            self.addCleanup(store.close)
            wid = store.create_workspace('Cooling study')['id']
            first = study(store, wid, 'measurements')
            result = study(store, wid, 'investigation')
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
