"""Regression contracts for finite-lookback Page CUSUM and healthy-only budgets."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from benchmarks.bounded_evaluate import (
    METHODS, run_comparison, write_report, zero_episode_calibration,
)
from benchmarks.monitoring import (
    build_monitor, calibrate, persistent_alarms, split_normal_training,
)
from benchmarks.temporal import CUSUMMonitor
from benchmarks.window_cusum import WindowCUSUMMonitor


class WindowCUSUMMathematicsTests(unittest.TestCase):
    def simple(self, window: int = 3):
        model = WindowCUSUMMonitor(window=window, reference=0.5)
        model.center = np.zeros(2)
        model.scale = np.ones(2)
        model.features = 2
        return model

    def test_two_sided_suffix_formula_and_expiring_history(self):
        monitor = self.simple(window=3)
        x = np.asarray([[1., 0.], [1., 0.], [1., 0.], [1., 0.],
                        [0., 0.], [0., 0.], [0., 0.]])
        np.testing.assert_allclose(
            monitor.score(x), [.5, 1., 1.5, 1.5, 1.0, .5, 0.]
        )
        neg = np.asarray([[-1., 0.], [-1., 0.], [-1., 0.], [-1., 0.]])
        np.testing.assert_allclose(monitor.score(neg), [.5, 1., 1.5, 1.5])

    def test_no_future_data_and_fresh_file_state(self):
        rng = np.random.default_rng(77)
        fit = rng.normal(size=(150, 52))
        test = rng.normal(size=(75, 52))
        for window in (12, 24):
            monitor = WindowCUSUMMonitor(window=window)
            monitor.fit(fit)
            full = monitor.score(test)
            for t in (1, 8, 22, 45, 74):
                np.testing.assert_allclose(full[t], monitor.score(test[:t + 1])[-1], atol=1e-10)
            altered = test.copy()
            altered[40:] += 100_000
            np.testing.assert_allclose(full[:40], monitor.score(altered)[:40], atol=1e-10)
            _ = monitor.score(rng.normal(size=(500, 52)))
            np.testing.assert_allclose(full, monitor.score(test), atol=1e-10)

    def test_large_old_excursion_expires_but_unbounded_keeps_accumulating(self):
        limited = self.simple(window=3)
        unbounded = CUSUMMonitor(reference=.5)
        unbounded.center = np.zeros(2)
        unbounded.scale = np.ones(2)
        unbounded.features = 2
        x = np.zeros((18, 2))
        x[:3, 0] = 10.
        self.assertAlmostEqual(limited.score(x)[-1], 0)
        self.assertGreater(unbounded.score(x)[-1], 15)

    def test_history_correct_explanation_and_metadata(self):
        monitor = self.simple(window=3)
        x = np.asarray([[2., 0.], [2., 0.], [2., 0.], [0., 0.]])
        self.assertEqual(monitor.explain_at(x, 3, ["sensor_a", "sensor_b"])[0], "sensor_a")
        self.assertEqual(monitor.metadata()["window_samples"], 3)
        self.assertTrue(monitor.metadata()["bounded_lookback"])
        with self.assertRaisesRegex(ValueError, "full observed prefix"):
            monitor.explain(x[-1], ["sensor_a", "sensor_b"])

    def test_reject_invalid_window_or_unfitted_score(self):
        for w in (0, 1, 1.5, True):
            with self.subTest(window=w), self.assertRaises(ValueError):
                WindowCUSUMMonitor(window=w)
        with self.assertRaisesRegex(ValueError, "Fit"):
            WindowCUSUMMonitor().score(np.zeros((2, 52)))


class NormalCalibrationBudgetTests(unittest.TestCase):
    def test_zero_episodes_and_minimum_required_threshold(self):
        series = np.asarray([0., 3., 3., 3., 0., 2., 2.] + [0.] * 33)
        threshold = zero_episode_calibration(series, 1.0, persistence=3)
        self.assertEqual(threshold, 3.0)
        self.assertFalse(any(persistent_alarms(series, threshold, 3)))
        self.assertTrue(any(persistent_alarms(series, threshold - 0.01, 3)))
        self.assertEqual(zero_episode_calibration(series, 10., persistence=3), 10.)

    def test_invalid_calibration_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "30"):
            zero_episode_calibration(np.ones(20), 1, 3)
        with self.assertRaisesRegex(ValueError, "Persistence"):
            zero_episode_calibration(np.ones(35), 1, 0)
        with self.assertRaisesRegex(ValueError, "finite"):
            zero_episode_calibration(np.full(35, float("nan")), 1, 3)


class SyntheticBenchmarkComparisonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        rng = np.random.default_rng(10128)
        mixing = rng.normal(size=(5, 52))

        def sample(n):
            return rng.normal(size=(n, 5)) @ mixing + rng.normal(scale=.2, size=(n, 52))

        fit = sample(500)
        healthy = sample(960)
        faulty = sample(960)
        faulty[160:, 4] += 14.
        np.savetxt(self.root / "d00.dat", fit.T, fmt="%.9f")
        np.savetxt(self.root / "d00_te.dat", healthy, fmt="%.9f")
        np.savetxt(self.root / "d01_te.dat", faulty, fmt="%.9f")

    def test_comparison_reports_all_prespecified_methods_and_calibration_policies(self):
        report = run_comparison(self.root, faults=(1,))
        self.assertEqual(len(report["rows"]), 2 * len(METHODS))
        self.assertEqual(report["precommitted_windows_samples"], [12, 24])
        self.assertEqual(report["healthy_calibration_episode_target"], 0)
        for row in report["rows"]:
            self.assertEqual(row["faults_evaluated"], 1)
            self.assertGreaterEqual(row["healthy_test_false_alarm_episodes"], 0)
            self.assertEqual(len(row["per_fault"]), 2)
            self.assertEqual(row["per_fault"][0]["source"], "d00_te.dat")
            if row["threshold_policy"] == "healthy-calibration-zero-episodes":
                self.assertEqual(row["healthy_calibration_episodes"], 0)
        self.assertEqual({r["method"] for r in report["rows"]}, set(METHODS))
        paths = write_report(report, self.root / "out")
        self.assertEqual(json.loads(paths[0].read_text()), report)
        self.assertIn("window-cusum-12", paths[1].read_text())
        self.assertIn("No choice of a held-out winner", paths[1].read_text())

    def test_fault_modifications_cannot_change_any_normal_threshold(self):
        original = run_comparison(self.root, faults=(1,))
        data = np.loadtxt(self.root / "d01_te.dat")
        data[160:, :] += 900
        np.savetxt(self.root / "d01_te.dat", data, fmt="%.9f")
        altered = run_comparison(self.root, faults=(1,))
        key = lambda row: (row["method"], row["threshold_policy"])
        first = {key(row): row["calibration_threshold"] for row in original["rows"]}
        second = {key(row): row["calibration_threshold"] for row in altered["rows"]}
        self.assertEqual(first, second)
        self.assertNotEqual(original["source_files"][-1]["sha256"], altered["source_files"][-1]["sha256"])

    def test_predeclared_monitors_are_registered(self):
        self.assertEqual(build_monitor("window-cusum-12").window, 12)
        self.assertEqual(build_monitor("window-cusum-24").window, 24)
        with self.assertRaisesRegex(ValueError, "Unknown"):
            build_monitor("window-cusum-5")


if __name__ == "__main__":
    unittest.main()
