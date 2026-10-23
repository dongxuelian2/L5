"""Stress-audit contract tests using entirely synthetic reference-format fixtures."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from benchmarks.evaluate import run_benchmark
from benchmarks.robustness import (
    SCENARIOS, alarm_episodes, apply_stress, render_markdown,
    run_robustness, stable_seed, write_report,
)


class RobustnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        rng = np.random.default_rng(6420)
        mixing = rng.normal(size=(4, 52))

        def rows(count):
            latent = rng.normal(size=(count, 4))
            return latent @ mixing + rng.normal(scale=0.2, size=(count, 52))

        self.train = rows(500)
        self.healthy = rows(960)
        self.fault = rows(960)
        self.fault[160:, 6] += 12
        np.savetxt(self.root / "d00.dat", self.train.T, fmt="%.9f")
        np.savetxt(self.root / "d00_te.dat", self.healthy, fmt="%.9f")
        np.savetxt(self.root / "d01_te.dat", self.fault, fmt="%.9f")
        self.median = np.median(self.train[:350], axis=0)
        self.scale = np.maximum(self.train[:350].std(axis=0, ddof=1), 1e-10)

    def test_no_input_mutation_and_channel_level_ablation(self):
        source = self.healthy.copy()
        variant = apply_stress(source, "loss-xmeas7", "d00_te.dat", self.median, self.scale, 9)
        np.testing.assert_allclose(source, self.healthy)
        np.testing.assert_allclose(variant.data[:, 6], self.median[6])
        np.testing.assert_allclose(variant.data[:, :6], self.healthy[:, :6])
        np.testing.assert_allclose(variant.data[:, 7:], self.healthy[:, 7:])
        self.assertEqual(variant.missing_cells, 960)
        self.assertAlmostEqual(variant.missing_fraction, 1 / 52, places=6)

    def test_random_mask_determinism_and_independent_seed(self):
        a = apply_stress(self.healthy, "random-missing-05", "d00_te.dat", self.median, self.scale, 100)
        b = apply_stress(self.healthy, "random-missing-05", "d00_te.dat", self.median, self.scale, 100)
        c = apply_stress(self.healthy, "random-missing-05", "d00_te.dat", self.median, self.scale, 101)
        np.testing.assert_array_equal(a.data, b.data)
        self.assertNotEqual(a.missing_cells, 0)
        self.assertFalse(np.array_equal(a.data, c.data))
        self.assertEqual(stable_seed(100, "noise-20pct", "d01_te.dat"),
                         stable_seed(100, "noise-20pct", "d01_te.dat"))
        self.assertNotEqual(stable_seed(100, "noise-20pct", "d01_te.dat"),
                            stable_seed(100, "noise-20pct", "d00_te.dat"))

    def test_noise_shift_and_silent_clean_control(self):
        clean = apply_stress(self.healthy, "clean", "d00_te.dat", self.median, self.scale, 1)
        noise = apply_stress(self.healthy, "noise-20pct", "d00_te.dat", self.median, self.scale, 1)
        shift = apply_stress(self.healthy, "offset-half-sigma", "d00_te.dat", self.median, self.scale, 1)
        np.testing.assert_array_equal(clean.data, self.healthy)
        np.testing.assert_allclose(shift.data, self.healthy + 0.5 * self.scale)
        self.assertNotEqual(noise.data[0, 0], clean.data[0, 0])
        self.assertEqual(noise.missing_cells, 0)
        with self.assertRaisesRegex(ValueError, "Unknown"):
            apply_stress(self.healthy, "invalid", "d00_te.dat", self.median, self.scale, 1)

    def test_alarm_episode_edges_and_long_stretches(self):
        metric = alarm_episodes((False, True, True, True, False, True, True, False), 8)
        self.assertEqual(metric["count"], 2)
        self.assertEqual(metric["active_samples"], 5)
        self.assertEqual(metric["longest_duration_samples"], 3)
        self.assertAlmostEqual(metric["per_24h"], 2 / (8 * 3 / 60) * 24)
        # One persistent alarm across a fault boundary is counted once in normal.
        self.assertEqual(alarm_episodes((True, True, True, True), 2)["count"], 1)
        self.assertEqual(alarm_episodes((False, False, False), 3)["count"], 0)
        with self.assertRaisesRegex(ValueError, "Healthy interval"):
            alarm_episodes((False,), 0)

    def test_held_out_protocol_invariant_and_deterministic_report(self):
        report = run_robustness(self.root, faults=(1,), methods=("robust-maxz", "pca-q"))
        again = run_robustness(self.root, faults=(1,), methods=("robust-maxz", "pca-q"))
        self.assertEqual(report, again)
        self.assertEqual(set(report["scenario_results"]), set(SCENARIOS))
        self.assertFalse(report["base_protocol"]["fault_training_used"])
        self.assertEqual(report["base_protocol"]["calibration_samples"], 150)
        clean = run_benchmark(self.root, faults=(1,), methods=("robust-maxz", "pca-q"))
        for method in ("robust-maxz", "pca-q"):
            reference_threshold = clean["methods"][method]["threshold"]
            for scenario in SCENARIOS:
                result = report["scenario_results"][scenario][method]
                self.assertEqual(result["threshold"], reference_threshold)
                self.assertEqual(result["faults_evaluated"], 1)
                self.assertEqual(len(result["cases"]), 2)
            clean_result = report["scenario_results"]["clean"][method]
            self.assertEqual(clean_result["delta_early_vs_clean"], 0)
            self.assertEqual(clean_result["cases"][0]["missing_cells"], 0)
            self.assertEqual(clean_result["cases"][0]["false_alarm_rate"],
                             clean["methods"][method]["cases"][0]["false_alarm_rate"])
        paths = write_report(report, self.root / "out")
        self.assertEqual(len(paths), 2)
        self.assertEqual(json.loads(paths[0].read_text()), report)
        self.assertIn("Early detected", paths[1].read_text())
        self.assertIn("SHA-256", paths[1].read_text())
        self.assertIn("loss-xmeas7", render_markdown(report))

    def test_no_test_data_in_fitted_baseline(self):
        before = run_robustness(self.root, faults=(1,), methods=("robust-maxz",),
                                scenarios=("clean", "noise-20pct"))
        original = np.loadtxt(self.root / "d01_te.dat")
        original[160:, 6] += 1000
        np.savetxt(self.root / "d01_te.dat", original, fmt="%.9f")
        after = run_robustness(self.root, faults=(1,), methods=("robust-maxz",),
                               scenarios=("clean", "noise-20pct"))
        for scenario in ("clean", "noise-20pct"):
            a = before["scenario_results"][scenario]["robust-maxz"]
            b = after["scenario_results"][scenario]["robust-maxz"]
            self.assertEqual(a["threshold"], b["threshold"])
            self.assertEqual(a["healthy_false_alarm_episodes"], b["healthy_false_alarm_episodes"])
        self.assertNotEqual(before["input_files"][-1]["sha256"], after["input_files"][-1]["sha256"])

    def test_invalid_protocol_cannot_be_silently_reported(self):
        cases = [
            {"scenarios": ()},
            {"scenarios": ("noise-20pct",)},
            {"scenarios": ("clean", "clean")},
            {"scenarios": ("clean", "made-up")},
            {"seed": -1},
        ]
        for params in cases:
            with self.subTest(params=params), self.assertRaises(ValueError):
                run_robustness(self.root, faults=(1,), methods=("robust-maxz",), **params)


if __name__ == "__main__":
    unittest.main()
