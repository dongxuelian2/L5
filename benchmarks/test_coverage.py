"""Regression tests: no imputed sensor can masquerade as a reliable normal reading."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from benchmarks.coverage import (
    ABSTAIN, ALARM, NORMAL, CoveragePolicy, decide, observation_summary,
    render_markdown, run_coverage, write_report,
)
from benchmarks.evaluate import run_benchmark
from benchmarks.tep import VARIABLES


class DecisionStateTests(unittest.TestCase):
    def test_unobserved_row_abstains_and_resets_alarm_confirmation(self):
        # All scores exceed threshold; invalid rows must break confirmation.
        visible = np.ones((8, 52), dtype=bool)
        visible[2, 6] = False
        visible[6, :] = False
        result = decide(
            np.full(8, 10.0), visible, threshold=5.0,
            consecutive=3, policy=CoveragePolicy(),
        )
        self.assertEqual(result, (
            NORMAL, NORMAL, ABSTAIN, NORMAL, NORMAL, ALARM, ABSTAIN, NORMAL,
        ))
        self.assertNotIn(ALARM, (result[2], result[6]))
        self.assertNotIn(NORMAL, (result[2], result[6]))

    def test_policy_fraction_and_critical_channels_are_both_enforced(self):
        visible = np.ones((4, 52), dtype=bool)
        visible[0, :6] = False   # 46 / 52 < 90%, must abstain
        visible[1, :5] = False   # 47 / 52 >= 90%, must remain valid
        visible[2, 8] = False    # required temperature channel is missing
        states = decide(
            np.zeros(4), visible, threshold=10.0, consecutive=1,
            policy=CoveragePolicy(),
        )
        self.assertEqual(states, (ABSTAIN, NORMAL, ABSTAIN, NORMAL))
        states_without_critical = decide(
            np.zeros(4), visible, threshold=10.0, consecutive=1,
            policy=CoveragePolicy(required_channels=()),
        )
        self.assertEqual(states_without_critical, (ABSTAIN, NORMAL, NORMAL, NORMAL))

    def test_invalid_policy_and_boolean_mask_contract(self):
        for params in (
            {"min_observed_fraction": 0},
            {"min_observed_fraction": 1.1},
            {"required_channels": ("xmeas_7", "xmeas_7")},
            {"required_channels": ("pressure",)},
        ):
            with self.subTest(params=params), self.assertRaises(ValueError):
                CoveragePolicy(**params)
        with self.assertRaisesRegex(ValueError, "Boolean"):
            decide(np.zeros(3), np.ones((3, 52)), threshold=1,
                   consecutive=1, policy=CoveragePolicy())
        with self.assertRaisesRegex(ValueError, "one score"):
            decide(np.zeros(2), np.ones((3, 52), dtype=bool), threshold=1,
                   consecutive=1, policy=CoveragePolicy())

    def test_metrics_separate_abstain_from_valid_normal_and_false_alarm(self):
        states = (NORMAL, ALARM, ALARM, ABSTAIN, NORMAL, NORMAL, ALARM, ALARM)
        summary = observation_summary(states, onset_sample=5, early_window_samples=2)
        self.assertEqual(summary["normal_samples"], 5)
        self.assertEqual(summary["normal_observed_samples"], 4)
        self.assertEqual(summary["normal_abstained_samples"], 1)
        self.assertEqual(summary["normal_false_alarm_active_samples"], 2)
        self.assertEqual(summary["normal_false_alarm_episodes"], 1)
        self.assertEqual(summary["early_window_total_samples"], 3)
        self.assertEqual(summary["early_window_observed_samples"], 3)
        self.assertEqual(summary["first_new_post_onset_alarm_sample"], 6)
        self.assertTrue(summary["detected_within_early_window"])
        self.assertEqual(summary["delay_minutes"], 3)

    def test_prefault_alarm_continuation_not_new_fault_detection(self):
        summary = observation_summary(
            (NORMAL, ALARM, ALARM, ALARM, ALARM, ALARM),
            onset_sample=3,
        )
        self.assertFalse(summary["detected_after_onset"])
        self.assertEqual(summary["normal_false_alarm_episodes"], 1)
        self.assertEqual(summary["post_onset_observed_samples"], 3)

    def test_all_missing_normal_window_has_no_reportable_conditional_fpr(self):
        summary = observation_summary((ABSTAIN,) * 5, onset_sample=None)
        self.assertEqual(summary["normal_coverage_fraction"], 0)
        self.assertEqual(summary["normal_abstained_samples"], 5)
        self.assertIsNone(summary["false_alarm_active_fraction_observed_samples"])
        self.assertEqual(summary["normal_false_alarm_episodes"], 0)


class RealFormatSyntheticAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        rng = np.random.default_rng(819)
        matrix = rng.normal(size=(5, 52))

        def make(n):
            return rng.normal(size=(n, 5)) @ matrix + rng.normal(scale=0.2, size=(n, 52))

        self.fit = make(500)
        self.normal = make(960)
        self.fault = make(960)
        self.fault[160:, 6] += 25
        np.savetxt(self.root / "d00.dat", self.fit.T, fmt="%.8f")
        np.savetxt(self.root / "d00_te.dat", self.normal, fmt="%.8f")
        np.savetxt(self.root / "d01_te.dat", self.fault, fmt="%.8f")

    def audit(self, scenarios=("clean", "loss-xmeas7", "random-missing-05", "blackout-15samples")):
        return run_coverage(
            self.root, faults=(1,), methods=("robust-maxz",),
            scenarios=scenarios,
        )

    def test_clean_exactly_preserves_prior_benchmark(self):
        report = self.audit()
        raw = run_benchmark(self.root, faults=(1,), methods=("robust-maxz",))
        clean = report["scenarios"]["clean"]["robust-maxz"]
        self.assertEqual(clean["early_detected"], raw["methods"]["robust-maxz"]["aggregate"]["faults_detected_early"])
        self.assertEqual(clean["healthy_abstained_samples"], 0)
        self.assertEqual(clean["healthy_coverage_fraction"], 1)
        self.assertEqual(clean["healthy_false_alarm_active_samples"],
                         raw["methods"]["robust-maxz"]["aggregate"]["healthy_test_false_alarm_samples"])
        self.assertEqual(clean["cases"][0]["decisions"][ABSTAIN], 0)
        self.assertEqual(report["policy"]["required_channels"], ["xmeas_7", "xmeas_9"])

    def test_critical_channel_dropout_never_claims_reliable_prediction(self):
        report = self.audit()
        missing = report["scenarios"]["loss-xmeas7"]["robust-maxz"]
        self.assertEqual(missing["healthy_coverage_fraction"], 0)
        self.assertEqual(missing["healthy_abstained_samples"], 960)
        self.assertEqual(missing["early_detected"], 0)
        self.assertEqual(missing["eventually_detected"], 0)
        self.assertEqual(missing["healthy_false_alarm_episodes"], 0)
        self.assertEqual(missing["cases"][1]["decisions"][ABSTAIN], 960)
        self.assertEqual(missing["cases"][1]["early_window_coverage_fraction"], 0)

    def test_blackout_and_random_missing_are_explicitly_counted(self):
        report = self.audit()
        blackout = report["scenarios"]["blackout-15samples"]["robust-maxz"]
        self.assertEqual(blackout["healthy_abstained_samples"], 15)
        self.assertEqual(blackout["cases"][1]["decisions"][ABSTAIN], 15)
        self.assertLess(blackout["cases"][1]["early_window_coverage_fraction"], 1.0)
        partial = report["scenarios"]["random-missing-05"]["robust-maxz"]
        self.assertGreater(partial["healthy_abstained_samples"], 0)
        self.assertLess(partial["healthy_abstained_samples"], 960)
        self.assertTrue(report["normal_fit_and_calibration_only"])
        self.assertTrue(report["fixed_model_and_threshold_for_all_scenarios"])

    def test_untouched_training_threshold_and_reproducible_json(self):
        report = self.audit()
        repeat = self.audit()
        self.assertEqual(report, repeat)
        thresholds = {entry["threshold"] for entry in
                      (report["scenarios"][s]["robust-maxz"] for s in report["scenarios"])}
        self.assertEqual(len(thresholds), 1)
        modified = self.fault.copy()
        modified[160:, :] += 1000
        np.savetxt(self.root / "d01_te.dat", modified, fmt="%.8f")
        changed = self.audit()
        self.assertEqual(report["scenarios"]["clean"]["robust-maxz"]["threshold"],
                         changed["scenarios"]["clean"]["robust-maxz"]["threshold"])
        self.assertNotEqual(report["reference_input_files"][-1]["sha256"],
                            changed["reference_input_files"][-1]["sha256"])
        output = write_report(report, self.root / "coverage-report")
        self.assertEqual(json.loads(output[0].read_text()), report)
        markdown = render_markdown(report)
        self.assertIn("ABSTAIN", markdown)
        self.assertIn("blackout-15samples", markdown)
        self.assertIn("SHA-256", markdown)

    def test_invalid_scenarios_rejected_before_results(self):
        for scenarios in ((), ("loss-xmeas7",), ("clean", "clean"), ("clean", "unknown")):
            with self.subTest(scenarios=scenarios), self.assertRaises(ValueError):
                self.audit(scenarios=scenarios)


if __name__ == "__main__":
    unittest.main()
