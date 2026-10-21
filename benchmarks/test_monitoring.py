"""Deterministic synthetic checks for the dataset-neutral benchmark pipeline."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from benchmarks.evaluate import run_benchmark, write_report
from benchmarks.monitoring import (
    MaxZMonitor, PCAMonitor, calibrate, evaluate_case, persistent_alarms,
    split_normal_training, summarize_cases,
)
from benchmarks.tep import VARIABLES


class MonitoringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        rng = np.random.default_rng(20261021)
        # Common latent process factors + feature-specific measurement noise.
        def series(count: int):
            latent = rng.normal(size=(count, 5))
            mixing = np.arange(5 * 52, dtype=float).reshape(5, 52)
            mixing = np.sin(mixing * 0.39) * 0.8
            return latent @ mixing + rng.normal(scale=0.09, size=(count, 52))
        self.training = series(500)
        self.normal_test = series(960)
        self.fault_test = series(960)
        self.fault_test[160:, 0] += 20
        self._write("d00.dat", self.training, transposed=True)
        self._write("d00_te.dat", self.normal_test)
        self._write("d01_te.dat", self.fault_test)

    def _write(self, name: str, rows: np.ndarray, transposed: bool = False) -> None:
        if transposed:
            rows = rows.T
        np.savetxt(self.root / name, rows, fmt="%.9f")

    def test_three_monitors_complete_without_fault_training(self):
        report = run_benchmark(self.root, faults=(1,))
        self.assertEqual(report["evaluation_protocol"]["fit_samples"], 350)
        self.assertEqual(report["evaluation_protocol"]["calibration_samples"], 150)
        self.assertFalse(report["evaluation_protocol"]["fault_training_used"])
        self.assertEqual(set(report["methods"]), {"robust-maxz", "pca-q", "pca-t2"})
        self.assertEqual(len(report["features"]), 52)
        for method in report["methods"].values():
            self.assertEqual(len(method["cases"]), 2)
            self.assertEqual(method["aggregate"]["faults_evaluated"], 1)
            fault = method["cases"][1]
            self.assertEqual(fault["onset_sample"], 160)
            self.assertLessEqual(fault["false_alarm_rate"], 0.2)
            if fault["detected_after_onset"]:
                self.assertIsNotNone(fault["detection_delay_minutes"])
                self.assertLessEqual(fault["detection_delay_samples"], 30)
            else:
                self.assertIsNone(fault["detection_delay_samples"])
                self.assertIn(1, method["aggregate"]["undetected_faults"])
            self.assertTrue(set(fault["first_post_onset_alarm_variables"]) <= set(VARIABLES))
        # A channel-specific shift must be caught by the univariate reference
        # monitor, while PCA T² is allowed to miss residual-space shifts.
        self.assertTrue(report["methods"]["robust-maxz"]["aggregate"]["faults_detected"])

    def test_test_fault_values_cannot_change_training_threshold(self):
        report = run_benchmark(self.root, faults=(1,))
        changed = self.fault_test.copy()
        changed[160:, :] += 3000
        self._write("d01_te.dat", changed)
        second = run_benchmark(self.root, faults=(1,))
        for name in report["methods"]:
            self.assertEqual(
                report["methods"][name]["threshold"],
                second["methods"][name]["threshold"],
            )
            self.assertEqual(
                report["methods"][name]["model"],
                second["methods"][name]["model"],
            )
        self.assertNotEqual(report["input_files"][-1]["sha256"], second["input_files"][-1]["sha256"])

    def test_deterministic_reports_and_csv(self):
        first = run_benchmark(self.root, faults=(1,), methods=("robust-maxz",))
        second = run_benchmark(self.root, faults=(1,), methods=("robust-maxz",))
        self.assertEqual(first, second)
        paths = write_report(first, self.root / "reports")
        self.assertTrue(all(path.is_file() for path in paths))
        self.assertEqual(json.loads(paths[0].read_text()), first)
        self.assertEqual(len(paths[1].read_text().splitlines()), 3)
        scoreboard = paths[2].read_text()
        self.assertIn("IDV(1)", scoreboard)
        self.assertIn("Early faults", scoreboard)
        self.assertIn("SHA-256", scoreboard)
        self.assertIn("60 minutes", scoreboard)

    def test_missing_reference_files_fail_loudly(self):
        with self.assertRaisesRegex(ValueError, "Missing required reference files"):
            run_benchmark(self.root)
        with self.assertRaisesRegex(ValueError, "distinct"):
            run_benchmark(self.root, faults=(1, 1))
        with self.assertRaisesRegex(ValueError, "Fault IDs"):
            run_benchmark(self.root, faults=(22,))
        with self.assertRaisesRegex(ValueError, "distinct"):
            run_benchmark(self.root, faults=(1,), methods=("pca-q", "pca-q"))

    def test_temporal_split_and_monitor_calibration(self):
        fit, cal = split_normal_training(self.training, fit_fraction=0.7)
        self.assertEqual(len(fit), 350)
        self.assertEqual(len(cal), 150)
        for model in (MaxZMonitor(), PCAMonitor("q"), PCAMonitor("t2")):
            model.fit(fit)
            threshold = calibrate(model, cal, alpha=0.01)
            self.assertTrue(np.isfinite(threshold))
            self.assertGreaterEqual(threshold, 0)
            self.assertEqual(model.score(self.normal_test[:20]).shape, (20,))
        with self.assertRaisesRegex(ValueError, "fit_fraction"):
            split_normal_training(self.training, fit_fraction=0.2)
        with self.assertRaisesRegex(ValueError, "alpha"):
            calibrate(model, cal, alpha=0.0)

    def test_consecutive_alarm_requires_confirmed_run(self):
        self.assertEqual(
            persistent_alarms([0, 5, 5, 0, 5, 5, 5, 5], 1, 3),
            (False, False, False, False, False, False, True, True),
        )
        with self.assertRaisesRegex(ValueError, "positive"):
            persistent_alarms([1], 0, 0)

    def test_prefault_persistent_alarm_is_not_falsely_credited_to_fault(self):
        model = MaxZMonitor()
        model.fit(self.training[:350])
        threshold = calibrate(model, self.training[350:], alpha=0.01)
        permanently_alarms = self.normal_test.copy()
        permanently_alarms[:, 0] += 200
        metrics = evaluate_case(
            source="d01_te.dat", fault_id=1, samples=permanently_alarms,
            monitor=model, threshold=threshold, consecutive=3,
            feature_names=VARIABLES, onset_sample=160, seconds_per_sample=180,
        )
        self.assertGreater(metrics.false_alarm_rate, 0.9)
        self.assertFalse(metrics.detected_after_onset)
        self.assertIsNone(metrics.detection_delay_minutes)

    def test_metrics_exclude_prefault_from_detections(self):
        model = MaxZMonitor()
        model.fit(self.training[:350])
        threshold = calibrate(model, self.training[350:], alpha=0.01)
        data = self.fault_test.copy()
        metrics = evaluate_case(
            source="fault", fault_id=1, samples=data,
            monitor=model, threshold=threshold, consecutive=3,
            feature_names=VARIABLES, onset_sample=160, seconds_per_sample=180,
        )
        self.assertEqual(metrics.normal_samples, 160)
        self.assertTrue(metrics.detected_after_onset)
        self.assertEqual(metrics.detection_delay_minutes, metrics.detection_delay_samples * 3)
        self.assertTrue(metrics.detected_within_early_window)
        self.assertTrue(run_benchmark(self.root, faults=(1,), methods=("robust-maxz",))["methods"]["robust-maxz"]["aggregate"]["faults_detected_early"])
        with self.assertRaisesRegex(ValueError, "within"):
            evaluate_case(
                source="fault", fault_id=1, samples=data, monitor=model,
                threshold=threshold, consecutive=3, feature_names=VARIABLES,
                onset_sample=960, seconds_per_sample=180,
            )


if __name__ == "__main__":
    unittest.main()
