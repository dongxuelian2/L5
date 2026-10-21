"""Deterministic tests of causal lag-augmented PCA, history reset and TEP protocol."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from benchmarks.coverage import ABSTAIN, CoveragePolicy, decide, score_with_observation_resets
from benchmarks.dynamic_pca import DynamicPCAMonitor
from benchmarks.dynamic_pca_evaluate import METHODS, run_comparison, write_report
from benchmarks.evaluate import run_benchmark
from benchmarks.monitoring import build_monitor, calibrate, split_normal_training
from benchmarks.tep import VARIABLES


class DynamicPCAMathsTests(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(36201)
        common = self.rng.normal(size=(280, 3))
        mixing = self.rng.normal(size=(3, 52))
        self.training = common @ mixing + self.rng.normal(scale=.25, size=(280, 52))
        self.test = self.rng.normal(size=(64, 3)) @ mixing + self.rng.normal(scale=.25, size=(64, 52))

    def test_no_future_data_lags_use_only_current_or_past(self):
        model = DynamicPCAMonitor("q", lags=2)
        model.fit(self.training)
        first = model._lag_matrix(self.test)
        np.testing.assert_allclose(first[0, :52], self.test[0])
        np.testing.assert_allclose(first[0, 52:104], model.pad_center)
        np.testing.assert_allclose(first[0, 104:156], model.pad_center)
        np.testing.assert_allclose(first[1, 52:104], self.test[0])
        np.testing.assert_allclose(first[2, 104:156], self.test[0])
        for i in (0, 1, 2, 20, 63):
            np.testing.assert_allclose(first[i], model._lag_matrix(self.test[:i+1])[-1])
        future_changed = self.test.copy()
        future_changed[20:] += 10_000
        np.testing.assert_allclose(model.score(self.test)[:20], model.score(future_changed)[:20])

    def test_q_and_t2_nonnegative_finite_and_normal_fitted(self):
        for mode in ("q", "t2"):
            model = DynamicPCAMonitor(mode, lags=2)
            model.fit(self.training)
            scores = model.score(self.test)
            self.assertEqual(scores.shape, (64,))
            self.assertTrue(np.isfinite(scores).all())
            self.assertTrue(np.all(scores >= -1e-10))
            self.assertEqual(model.metadata()["lagged_features"], 156)
            self.assertEqual(model.metadata()["causal_past_lags"], 2)
            self.assertLessEqual(model.metadata()["components"], 20)
            self.assertEqual(model.explain_at(self.test, 8, VARIABLES),
                             model.explain_at(self.test[:9], 8, VARIABLES))
            with self.assertRaisesRegex(ValueError, "observed prefix"):
                model.explain(self.test[8], VARIABLES)
            with self.assertRaisesRegex(ValueError, "Explanation index"):
                model.explain_at(self.test, 100, VARIABLES)

    def test_file_boundaries_reset_past_and_do_not_change_fit(self):
        for mode in ("q", "t2"):
            model = DynamicPCAMonitor(mode, lags=2)
            model.fit(self.training)
            initial = model.score(self.test)
            _ = model.score(self.test * 12.0)
            np.testing.assert_allclose(model.score(self.test), initial)
            np.testing.assert_allclose(model.score(self.test[:5]), initial[:5])

    def test_abstention_resets_lagged_window_history(self):
        model = DynamicPCAMonitor("q", lags=2)
        model.fit(self.training)
        values = self.test.copy()
        observed = np.ones(values.shape, dtype=bool)
        observed[18:22] = False
        policy = CoveragePolicy()
        scores = score_with_observation_resets(model, values, observed, policy)
        normal_scores = model.score(values)
        self.assertEqual(scores[18:22].tolist(), [0.] * 4)
        # A post-gap score must be scored with a fresh normal-fit history,
        # not the two pre-gap values.
        np.testing.assert_allclose(scores[22], model.score(values[22:]) [0])
        states = decide(scores, observed, threshold=1e9, consecutive=3, policy=policy)
        self.assertTrue(all(states[i] == ABSTAIN for i in range(18, 22)))
        self.assertEqual(states[22], "normal")
        self.assertNotEqual(float(scores[22]), float(normal_scores[22]))

    def test_invalid_configurations_are_rejected(self):
        for params in (
            {"mode": "bad"}, {"lags": 0}, {"lags": -1},
            {"lags": 9}, {"lags": 1.5}, {"lags": True},
            {"variance": 1}, {"variance": .4},
            {"max_components": 0},
        ):
            with self.subTest(params=params), self.assertRaises(ValueError):
                DynamicPCAMonitor(**params)
        with self.assertRaisesRegex(ValueError, "Fit"):
            DynamicPCAMonitor().score(np.zeros((3, 52)))
        with self.assertRaisesRegex(ValueError, "30"):
            DynamicPCAMonitor().fit(np.zeros((10, 52)))


class TEPFormatComparisonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        rng = np.random.default_rng(20261021)
        mixing = rng.normal(size=(4, 52))
        def trajectory(n):
            return rng.normal(size=(n, 4)) @ mixing + rng.normal(scale=.2, size=(n, 52))
        self.train = trajectory(500)
        self.normal = trajectory(960)
        self.fault = trajectory(960)
        self.fault[160:, 9] += 18
        np.savetxt(self.root / "d00.dat", self.train.T, fmt="%.8f")
        np.savetxt(self.root / "d00_te.dat", self.normal, fmt="%.8f")
        np.savetxt(self.root / "d01_te.dat", self.fault, fmt="%.8f")

    def test_all_methods_old_static_invariants_report_outputs(self):
        report = run_comparison(self.root, faults=(1,))
        self.assertEqual(report["methods"], list(METHODS))
        self.assertEqual(len(report["rows"]), 5)
        old = run_benchmark(self.root, faults=(1,), methods=("robust-maxz", "pca-q", "pca-t2"))
        for row in report["rows"][:3]:
            expected = old["methods"][row["method"]]
            self.assertEqual(row["normal_calibration_threshold"], expected["threshold"])
            self.assertEqual(row["early_detected"], expected["aggregate"]["faults_detected_early"])
        for row in report["rows"][3:]:
            self.assertEqual(row["kind"], "dynamic-lag2")
            self.assertEqual(row["training_model_metadata"]["lagged_features"], 156)
            self.assertEqual(row["faults_evaluated"], 1)
            self.assertEqual(len(row["per_case"]), 2)
            self.assertTrue(set(row["per_case"][1]["first_post_onset_alarm_variables"]) <= set(VARIABLES))
        paths = write_report(report, self.root / "dpca")
        self.assertEqual(json.loads(paths[0].read_text()), report)
        self.assertIn("dpca-q-lag2", paths[1].read_text())
        self.assertIn("dpca-t2-lag2", paths[1].read_text())
        self.assertIn("SHA-256", paths[1].read_text())

    def test_test_fault_mutation_cannot_affect_any_fit_threshold(self):
        first = run_comparison(self.root, faults=(1,))
        self.fault[160:, :] += 400
        np.savetxt(self.root / "d01_te.dat", self.fault, fmt="%.8f")
        second = run_comparison(self.root, faults=(1,))
        before = {r["method"]: r["normal_calibration_threshold"] for r in first["rows"]}
        after = {r["method"]: r["normal_calibration_threshold"] for r in second["rows"]}
        self.assertEqual(before, after)
        self.assertNotEqual(first["source_files"][-1]["sha256"], second["source_files"][-1]["sha256"])

    def test_fixed_models_are_registered_not_dynamic_grid_search(self):
        self.assertEqual(build_monitor("dpca-q-lag2").mode, "q")
        self.assertEqual(build_monitor("dpca-t2-lag2").mode, "t2")
        with self.assertRaisesRegex(ValueError, "Unknown"):
            build_monitor("dpca-q-lag6")


if __name__ == "__main__":
    unittest.main()
