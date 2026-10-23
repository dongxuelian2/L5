"""Causal/integrity tests for Page CUSUM and EWMA TEP benchmarks."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from benchmarks.evaluate import run_benchmark
from benchmarks.monitoring import build_monitor, calibrate, evaluate_case, split_normal_training
from benchmarks.temporal import CUSUMMonitor, EWMAMonitor
from benchmarks.temporal_evaluate import METHODS, run_comparison, write_comparison
from benchmarks.tep import VARIABLES


class TemporalCausalityTests(unittest.TestCase):
    def test_exact_page_cusum_recurrence(self):
        monitor = CUSUMMonitor(reference=0.5)
        # Fixed fit statistics make the reference calculation transparent.
        monitor.center = np.zeros(2)
        monitor.scale = np.ones(2)
        monitor.features = 2
        samples = np.array([[0., 0.], [1., 0.], [1., 0.], [1., 0.]])
        np.testing.assert_allclose(monitor.score(samples), [0., .5, 1., 1.5])
        # Negative evidence must accumulate independently (two-sided).
        other = np.array([[0., -1.], [0., -1.], [0., -1.]])
        np.testing.assert_allclose(monitor.score(other), [.5, 1., 1.5])

    def test_exact_ewma_recurrence(self):
        monitor = EWMAMonitor(smoothing=0.25)
        monitor.center = np.zeros(2)
        monitor.scale = np.ones(2)
        monitor.features = 2
        np.testing.assert_allclose(
            monitor.score(np.array([[4., 0.], [0., 0.], [0., 0.]])),
            [1., .75, .5625],
        )

    def test_no_future_leakage_and_new_file_state_reset(self):
        rng = np.random.default_rng(208)
        normal = rng.normal(size=(180, 52))
        test = rng.normal(size=(60, 52))
        for detector in (CUSUMMonitor(), EWMAMonitor()):
            detector.fit(normal)
            score = detector.score(test)
            # Score(t) must be exactly the same if all later values change.
            late = test.copy()
            late[20:, :] = 10_000
            np.testing.assert_allclose(score[:20], detector.score(late)[:20])
            np.testing.assert_allclose(score, detector.score(test))
            # Calibration on another file must not alter this record's state.
            _ = detector.score(normal)
            np.testing.assert_allclose(score, detector.score(test))

    def test_explain_at_requires_history_and_uses_past_not_future(self):
        detector = CUSUMMonitor(reference=0.5)
        detector.center = np.zeros(2)
        detector.scale = np.ones(2)
        detector.features = 2
        trace = np.array([[1., 0.], [1., 0.], [1., 0.], [0., 0.], [50., 0.]])
        names = ("first_channel", "second_channel")
        self.assertEqual(detector.explain_at(trace, 3, names, 2)[0], "first_channel")
        self.assertEqual(
            detector.explain_at(trace, 3, names, 2),
            detector.explain_at(trace[:4], 3, names, 2),
        )
        with self.assertRaisesRegex(ValueError, "full observed prefix"):
            detector.explain(trace[3], names)
        with self.assertRaisesRegex(ValueError, "outside"):
            detector.explain_at(trace, 99, names)

    def test_config_validation(self):
        for constructor in (
            lambda: CUSUMMonitor(reference=0),
            lambda: CUSUMMonitor(reference=float("nan")),
            lambda: EWMAMonitor(smoothing=0),
            lambda: EWMAMonitor(smoothing=1.1),
        ):
            with self.assertRaises(ValueError):
                constructor()

    def test_monitors_produce_valid_scores_on_constant_train(self):
        normal = np.zeros((80, 52))
        evaluation = np.zeros((20, 52))
        for detector in (CUSUMMonitor(), EWMAMonitor()):
            detector.fit(normal)
            self.assertEqual(detector.score(evaluation).shape, (20,))
            self.assertTrue(np.isfinite(detector.score(evaluation)).all())
            self.assertTrue(np.all(detector.score(evaluation) == 0))


class SyntheticReferenceComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        rng = np.random.default_rng(741)
        mix = rng.normal(size=(4, 52))

        def trajectory(n):
            return rng.normal(size=(n, 4)) @ mix + rng.normal(scale=0.14, size=(n, 52))

        fit = trajectory(500)
        healthy = trajectory(960)
        fault = trajectory(960)
        fault[160:, 11] += 12
        np.savetxt(self.root / "d00.dat", fit.T, fmt="%.9f")
        np.savetxt(self.root / "d00_te.dat", healthy, fmt="%.9f")
        np.savetxt(self.root / "d01_te.dat", fault, fmt="%.9f")

    def test_temporal_comparison_preserves_original_three_reference_algorithms(self):
        report = run_comparison(self.root, faults=(1,))
        old = run_benchmark(self.root, faults=(1,))
        self.assertEqual([r["method"] for r in report["rows"]], list(METHODS))
        for row in report["rows"][:3]:
            reference = old["methods"][row["method"]]
            self.assertEqual(row["threshold"], reference["threshold"])
            self.assertEqual(row["early_detected"], reference["aggregate"]["faults_detected_early"])
            self.assertEqual(row["healthy_false_alarm_active_samples"],
                             reference["aggregate"]["healthy_test_false_alarm_samples"])
        for temporal in report["rows"][3:]:
            self.assertEqual(temporal["faults_evaluated"], 1)
            self.assertEqual(temporal["kind"], "temporal")
            self.assertGreaterEqual(temporal["healthy_false_alarm_episodes"], 0)
            self.assertTrue(report["method_parameters_selected_before_held_out_evaluation"])
        json_path, md_path = write_comparison(report, self.root / "report")
        self.assertEqual(json.loads(json_path.read_text()), report)
        self.assertIn("cusum-maxz", md_path.read_text())
        self.assertIn("ewma-maxz", md_path.read_text())

    def test_future_fault_values_cannot_change_fitted_threshold(self):
        first = run_comparison(self.root, faults=(1,))
        faulty = np.loadtxt(self.root / "d01_te.dat")
        faulty[160:, :] += 300
        np.savetxt(self.root / "d01_te.dat", faulty, fmt="%.9f")
        second = run_comparison(self.root, faults=(1,))
        a = {r["method"]: r["threshold"] for r in first["rows"]}
        b = {r["method"]: r["threshold"] for r in second["rows"]}
        self.assertEqual(a, b)
        self.assertNotEqual(first["source_files"][-1]["sha256"], second["source_files"][-1]["sha256"])

    def test_causal_attribution_recorded_at_detection_time(self):
        monitor = CUSUMMonitor()
        x = np.random.default_rng(71).normal(size=(120, 52))
        monitor.fit(x)
        fault = np.random.default_rng(72).normal(size=(60, 52))
        fault[15:, 0] += 30
        fit, calibration = split_normal_training(x)
        monitor.fit(fit)
        limit = calibrate(monitor, calibration, alpha=.01)
        result = evaluate_case(
            source="synthetic", fault_id=1, samples=fault,
            monitor=monitor, threshold=limit, consecutive=2,
            feature_names=VARIABLES, onset_sample=15, seconds_per_sample=180,
        )
        if result.detected_after_onset:
            self.assertIn("xmeas_1", result.first_post_onset_alarm_variables)


if __name__ == "__main__":
    unittest.main()
