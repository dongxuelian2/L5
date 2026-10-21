"""Normal-only fold and calibration-budget TEP validation regression tests."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from benchmarks.monitoring import build_monitor, persistent_alarms
from benchmarks.robustness import alarm_episodes
from benchmarks.normal_budget_validation import (
    METHODS, POLICIES, _normal_folds,
    calibration_budget_threshold, render_markdown, run_validation, write_report,
)


class CalibrationBudgetContractTests(unittest.TestCase):
    def test_select_least_strict_feasible_healthy_only_threshold(self):
        # Exactly one episode and two active samples satisfies (<=1, <=2%).
        scores = np.array([0.] * 40 + [3.] * 4 + [0.] * 56)
        threshold = calibration_budget_threshold(scores, persistence=3)
        self.assertEqual(threshold, 0.)
        observed = alarm_episodes(persistent_alarms(scores, threshold, 3), len(scores))
        self.assertEqual(observed["count"], 1)
        self.assertEqual(observed["active_samples"], 2)

    def test_larger_alarm_duration_forces_stricter_threshold(self):
        scores = np.array([0.] * 40 + [3.] * 7 + [0.] * 53)
        threshold = calibration_budget_threshold(scores, persistence=3)
        self.assertEqual(threshold, 3.)
        outcome = alarm_episodes(persistent_alarms(scores, threshold, 3), len(scores))
        self.assertEqual(outcome["active_samples"], 0)

    def test_budget_never_uses_test_data_or_changes_on_permutation(self):
        scores = np.array([0.] * 35 + [1.] * 3 + [0.] * 20 + [3.] * 4 + [0.] * 38)
        threshold = calibration_budget_threshold(scores)
        changed_test_not_provided = np.ones(960) * 1e9
        self.assertEqual(calibration_budget_threshold(scores), threshold)
        self.assertEqual(len(changed_test_not_provided), 960)
        self.assertEqual(_normal_folds(500)[0], ("forward-A", 250, 350, 425))
        self.assertEqual(_normal_folds(480)[1], ("forward-B", 300, 400, 480))

    def test_bad_budget_contracts_fail_loudly(self):
        scores = np.linspace(0, 1, 100)
        for kwargs in (
            {"persistence": 0}, {"persistence": True},
            {"max_episodes": -1}, {"max_episodes": 1.5},
            {"max_active_fraction": -0.1}, {"max_active_fraction": 1},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                calibration_budget_threshold(scores, **kwargs)
        with self.assertRaises(ValueError):
            calibration_budget_threshold(np.ones(20))
        with self.assertRaises(ValueError):
            calibration_budget_threshold(np.full(60, float("nan")))


class ForwardReferenceFormatTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        rng = np.random.default_rng(8888)
        mixing = rng.normal(size=(3, 52))

        def sample(n):
            return rng.normal(size=(n, 3)) @ mixing + rng.normal(scale=.22, size=(n, 52))

        self.fit = sample(500)
        self.normal = sample(960)
        self.fault = sample(960)
        self.fault[160:, 8] += 20
        np.savetxt(self.path / "d00.dat", self.fit.T, fmt="%.8f")
        np.savetxt(self.path / "d00_te.dat", self.normal, fmt="%.8f")
        np.savetxt(self.path / "d01_te.dat", self.fault, fmt="%.8f")

    def small_run(self, **overrides):
        return run_validation(
            self.path, faults=(1,),
            methods=("robust-maxz", "dpca-q-lag2"),
            policies=POLICIES, **overrides,
        )

    def test_precommitted_folds_reports_and_calibration_caps(self):
        result = self.small_run()
        self.assertEqual(len(result["rows"]), 2 * 2 * len(POLICIES))
        self.assertEqual(len(result["paired_vs_maxz"]), 2 * len(POLICIES))
        self.assertEqual(result["budget"]["maximum_calibration_confirmed_episodes"], 1)
        self.assertEqual(result["budget"]["maximum_calibration_alarm_active_fraction"], .02)
        self.assertEqual(result["folds"][1]["normal_validation"], [400, 500])
        self.assertTrue(all(f["usage"] == "read_only_external_evaluation"
                            for f in result["data_provenance"][1:]))
        for row in result["rows"]:
            self.assertEqual(row["faults_evaluated"], 1)
            self.assertEqual(row["per_fault"][0]["fault_id"], 1)
            self.assertEqual(row["normal_calibration_workload"]["observations"], 100)
            self.assertEqual(row["external_healthy_test_workload"]["observations"], 960)
            self.assertGreaterEqual(row["normal_forward_validation_workload"]["observations"], 75)
            if row["policy"] == "calibration-1episode-2pct-active":
                self.assertLessEqual(row["normal_calibration_workload"]["episodes"], 1)
                self.assertLessEqual(row["normal_calibration_workload"]["alarm_active_fraction"], .02)
        js, md = write_report(result, self.path / "budget")
        self.assertEqual(json.loads(js.read_text()), result)
        self.assertIn("Per-fault paired early detections", md.read_text())
        self.assertIn("SHA-256", md.read_text())
        self.assertEqual(md.read_text(), render_markdown(result))

    def test_mutating_external_normal_or_fault_cannot_affect_calibration(self):
        first = self.small_run()
        altered_normal = self.normal.copy()
        altered_normal[:, :] += 300.
        altered_fault = self.fault.copy()
        altered_fault[160:, :] += 900.
        np.savetxt(self.path / "d00_te.dat", altered_normal, fmt="%.8f")
        np.savetxt(self.path / "d01_te.dat", altered_fault, fmt="%.8f")
        second = self.small_run()
        as_key = lambda x: (x["fold"], x["method"], x["policy"])
        old = {as_key(r): r["threshold"] for r in first["rows"]}
        new = {as_key(r): r["threshold"] for r in second["rows"]}
        self.assertEqual(old, new)
        self.assertNotEqual(first["data_provenance"][-1]["sha256"], second["data_provenance"][-1]["sha256"])
        self.assertNotEqual(first["data_provenance"][1]["sha256"], second["data_provenance"][1]["sha256"])

    def test_late_normal_validation_does_not_affect_fit_or_calibration(self):
        first = self.small_run()
        # From index 400 to the end, *only* validation observations are changed
        # for both predeclared forward folds.
        train = self.fit.copy()
        train[400:, :] += 500.
        np.savetxt(self.path / "d00.dat", train.T, fmt="%.8f")
        second = self.small_run()
        old = {(r["fold"], r["method"], r["policy"]): r["threshold"] for r in first["rows"]}
        new = {(r["fold"], r["method"], r["policy"]): r["threshold"] for r in second["rows"]}
        self.assertEqual(old, new)

    def test_480_sample_normal_training_supported(self):
        np.savetxt(self.path / "d00.dat", self.fit[:480].T, fmt="%.8f")
        result = self.small_run()
        self.assertEqual(result["folds"][-1]["normal_validation"], [400, 480])
        self.assertTrue(all(
            x["normal_forward_validation_workload"]["observations"] in (75, 80)
            for x in result["rows"]
        ))

    def test_missing_or_unsupported_method_rejected(self):
        with self.assertRaisesRegex(ValueError, "distinct prespecified"):
            self.small_run(methods=("robust-maxz", "robust-maxz"))
        with self.assertRaisesRegex(ValueError, "distinct prespecified"):
            self.small_run(methods=("window-cusum-12",))
        with self.assertRaisesRegex(ValueError, "distinct prespecified"):
            self.small_run(policies=("not-valid",))

    def test_models_share_exactly_the_same_normal_only_split(self):
        report = self.small_run()
        self.assertEqual(set(report["methods"]), {"robust-maxz", "dpca-q-lag2"})
        self.assertEqual([f["calibration"] for f in report["folds"]],
                         [[250, 350], [300, 400]])
        self.assertEqual([f["normal_validation"] for f in report["folds"]],
                         [[350, 425], [400, 500]])
        for row in report["rows"]:
            self.assertEqual(row["training_metadata"]["features"], 52)


if __name__ == "__main__":
    unittest.main()
