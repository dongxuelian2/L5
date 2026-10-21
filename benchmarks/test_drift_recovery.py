"""Regression tests: adaptive pre-update causality, real recovery, drift stress integrity."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from benchmarks.adaptive import AdaptiveMaxZMonitor
from benchmarks.coverage import ALARM, NORMAL, ABSTAIN, CoveragePolicy, score_with_observation_resets
from benchmarks.drift_recovery import (
    METHODS, POLICIES, SCENARIOS, recovery_decisions, run_experiment,
    stress_case, transient_recovery_metric, write_report,
)
from benchmarks.evaluate import run_benchmark


class AdaptiveDetectorTests(unittest.TestCase):
    def fitted(self, rate=.1):
        model = AdaptiveMaxZMonitor(rate=rate, guard_z=2.5, max_center_shift_z=1.5)
        model.center = np.zeros(2)
        model.scale = np.ones(2)
        model.features = 2
        return model

    def test_scores_before_update_and_guard_is_per_channel(self):
        m = self.fitted()
        data = np.asarray([[1., 0.], [1., 0.], [1., 0.], [12., 0.], [1., 0.]])
        result = m.score(data)
        np.testing.assert_allclose(result, [1., .9, .81, 11.729, .729], atol=1e-9)
        np.testing.assert_allclose(m.score(data), result)

    def test_slow_drift_tracking_vs_large_fault_guard(self):
        adaptive = self.fitted(rate=.1)
        normal_slow = np.ones((100, 2))
        normal_slow[:, 0] = np.linspace(0, 1, 100)
        output = adaptive.score(normal_slow)
        self.assertLess(output[-1], output[1] + .2)
        severe_fault = np.zeros((100, 2))
        severe_fault[:, 0] = 20
        severe_scores = adaptive.score(severe_fault)
        self.assertTrue(np.all(severe_scores == 20))

    def test_no_future_leak_and_history_reset_between_files(self):
        rng = np.random.default_rng(2026)
        m = AdaptiveMaxZMonitor()
        train = rng.normal(size=(160, 52))
        m.fit(train)
        test = rng.normal(size=(80, 52))
        scores = m.score(test)
        changed = test.copy()
        changed[40:, :] += 5000
        np.testing.assert_allclose(m.score(changed)[:40], scores[:40])
        _ = m.score(rng.normal(size=(999, 52)))
        np.testing.assert_allclose(m.score(test), scores)

    def test_blackout_restores_baseline_not_stale_adaptation(self):
        m = AdaptiveMaxZMonitor(rate=.2)
        m.center = np.zeros(52)
        m.scale = np.ones(52)
        m.features = 52
        x = np.zeros((12, 52))
        x[:, 0] = 1
        mask = np.ones((12, 52), dtype=bool)
        mask[6, :] = False
        scores = score_with_observation_resets(m, x, mask, CoveragePolicy())
        self.assertEqual(scores[6], 0)
        self.assertAlmostEqual(scores[7], 1.0)
        self.assertLess(scores[5], scores[7])

    def test_reject_invalid_adaptive_configuration(self):
        for kwargs in (
            {"rate": 0}, {"rate": 1}, {"guard_z": -1},
            {"max_center_shift_z": 0}, {"rate": float("nan")},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                AdaptiveMaxZMonitor(**kwargs)
        with self.assertRaisesRegex(ValueError, "Fit"):
            AdaptiveMaxZMonitor().score(np.zeros((4, 52)))


class AlarmRecoveryTests(unittest.TestCase):
    def test_release_requires_observed_lower_scores(self):
        mask = np.ones((11, 52), dtype=bool)
        states = recovery_decisions(
            np.array([0, 3, 3, 3, 2, 1, 1, 1, 3, 3, 3], dtype=float),
            mask, threshold=2.5, persistence=3, release_fraction=.75,
            release_count=3, policy=CoveragePolicy(),
        )
        self.assertEqual(states, (
            NORMAL, NORMAL, NORMAL, ALARM, ALARM, ALARM,
            ALARM, NORMAL, NORMAL, NORMAL, ALARM,
        ))

    def test_abstention_resets_both_alarm_latch_and_persistence(self):
        m = np.ones((9, 52), dtype=bool)
        m[4] = False
        states = recovery_decisions(
            np.full(9, 9.0), m, threshold=5,
            persistence=3, release_fraction=.75, release_count=3,
            policy=CoveragePolicy(),
        )
        self.assertEqual(states, (
            NORMAL, NORMAL, ALARM, ALARM, ABSTAIN,
            NORMAL, NORMAL, ALARM, ALARM,
        ))

    def test_transient_recovery_marks_censored_and_not_applicable(self):
        quiet = (NORMAL,) * 960
        self.assertTrue(transient_recovery_metric(quiet)["clearance_not_applicable"])
        stuck = (NORMAL,) * 240 + (ALARM,) * 720
        self.assertTrue(transient_recovery_metric(stuck)["clearance_censored"])
        clear = (NORMAL,) * 240 + (ALARM,) * 24 + (NORMAL,) * 696
        self.assertEqual(transient_recovery_metric(clear)["clearance_delay_minutes"], 12)

    def test_release_does_not_use_a_timer_to_hide_persistent_fault(self):
        s = np.array([10.] * 50)
        states = recovery_decisions(
            s, np.ones((50, 52), dtype=bool), threshold=5,
            persistence=3, release_fraction=.75, release_count=3,
            policy=CoveragePolicy(),
        )
        self.assertTrue(all(x == ALARM for x in states[2:]))


class ReferenceFormatExperimentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        rng = np.random.default_rng(2718)
        mixing = rng.normal(size=(5, 52))

        def series(n):
            return rng.normal(size=(n, 5)) @ mixing + rng.normal(scale=.18, size=(n, 52))

        self.training = series(500)
        self.normal = series(960)
        self.fault = series(960)
        self.fault[160:, 0] += 25
        np.savetxt(self.root / "d00.dat", self.training.T, fmt="%.9f")
        np.savetxt(self.root / "d00_te.dat", self.normal, fmt="%.9f")
        np.savetxt(self.root / "d01_te.dat", self.fault, fmt="%.9f")

    def audit(self, scenarios=SCENARIOS):
        return run_experiment(self.root, faults=(1,), scenarios=scenarios)

    def test_all_conditions_both_decisions_and_all_monitors(self):
        report = self.audit()
        self.assertEqual(len(report["rows"]), len(METHODS) * len(SCENARIOS) * len(POLICIES))
        self.assertTrue(report["fit_partition_only_for_drift_scales"])
        self.assertEqual(report["policy_parameters_predeclared"]["release_count"], 3)
        assert_names = {(r["scenario"], r["method"], r["policy"]) for r in report["rows"]}
        self.assertEqual(len(assert_names), len(report["rows"]))
        for row in report["rows"]:
            self.assertEqual(row["faults_evaluated"], 1)
            self.assertEqual(row["per_case"][0]["source"], "d00_te.dat")
            self.assertEqual(len(row["per_case"]), 2)
            self.assertIsNone(row["per_case"][0]["alarm_already_active_at_fault_onset"])
            self.assertIsInstance(row["per_case"][1]["alarm_already_active_at_fault_onset"], bool)
            self.assertEqual(
                row["fault_cases_already_in_alarm_before_onset"],
                int(row["per_case"][1]["alarm_already_active_at_fault_onset"]),
            )
            self.assertEqual(sum(row["per_case"][0]["state_counts"].values()), 960)
            self.assertGreaterEqual(row["healthy_false_alarm_episodes"], 0)
        for row in report["rows"]:
            if row["scenario"] == "blackout-15samples":
                self.assertEqual(row["per_case"][0]["state_counts"][ABSTAIN], 15)
        paths = write_report(report, self.root / "results")
        self.assertEqual(json.loads(paths[0].read_text()), report)
        self.assertIn("recovery-hysteresis", paths[1].read_text())

    def test_clean_legacy_policy_is_exactly_canonical(self):
        report = self.audit(scenarios=("clean",))
        baseline = run_benchmark(self.root, faults=(1,), methods=METHODS)
        for row in report["rows"]:
            if row["policy"] != "legacy-persistence":
                continue
            old = baseline["methods"][row["method"]]
            self.assertEqual(row["early_detected"], old["aggregate"]["faults_detected_early"])
            self.assertEqual(row["healthy_alarm_active_samples"],
                             old["aggregate"]["healthy_test_false_alarm_samples"])

    def test_drift_never_changes_source_training_or_calibration(self):
        before = self.audit(scenarios=("clean", "slow-drift-1sigma"))
        faulty = np.loadtxt(self.root / "d01_te.dat")
        faulty[160:, :] += 1000
        np.savetxt(self.root / "d01_te.dat", faulty, fmt="%.9f")
        after = self.audit(scenarios=("clean", "slow-drift-1sigma"))
        self.assertEqual(
            {(r["scenario"], r["method"], r["policy"]): r["threshold"] for r in before["rows"]},
            {(r["scenario"], r["method"], r["policy"]): r["threshold"] for r in after["rows"]},
        )
        self.assertNotEqual(before["source_files"][-1]["sha256"], after["source_files"][-1]["sha256"])

    def test_scenarios_are_deterministic_and_predeclared(self):
        fit = np.median(self.training[:350], axis=0)
        std = np.maximum(self.training[:350].std(axis=0), 1e-10)
        original = self.normal.copy()
        for scenario in SCENARIOS:
            altered, observed = stress_case(original, scenario, fit, std)
            self.assertEqual(altered.shape, original.shape)
            self.assertEqual(observed.dtype, np.bool_)
        np.testing.assert_array_equal(original, self.normal)
        with self.assertRaisesRegex(ValueError, "Scenarios"):
            self.audit(scenarios=("slow-drift-1sigma",))


if __name__ == "__main__":
    unittest.main()
