"""Small synthetic reference-format tests for predeclared TEP sensitivity sweeps."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from benchmarks.sensitivity import (
    DEFAULT_ALPHAS, DEFAULT_SCENARIOS, _validate, render_markdown,
    run_sensitivity, write_report,
)


class SensitivityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        rng = np.random.default_rng(20261021)
        mixing = rng.normal(size=(4, 52))

        def sample(count):
            return rng.normal(size=(count, 4)) @ mixing + rng.normal(scale=0.18, size=(count, 52))

        self.train = sample(500)
        self.healthy = sample(960)
        self.fault = sample(960)
        self.fault[160:, 6] += 15
        np.savetxt(self.root / "d00.dat", self.train.T, fmt="%.8f")
        np.savetxt(self.root / "d00_te.dat", self.healthy, fmt="%.8f")
        np.savetxt(self.root / "d01_te.dat", self.fault, fmt="%.8f")

    def run_small(self):
        return run_sensitivity(
            self.root, faults=(1,), methods=("robust-maxz",),
            seeds=(19, 23, 29), alphas=(0.005, 0.05),
            scenarios=("clean", "random-missing-05", "noise-20pct"),
        )

    def test_all_seeds_preserve_clean_reference_and_frozen_thresholds(self):
        report = self.run_small()
        self.assertEqual(report["declared_alphas"], [0.005, 0.05])
        self.assertEqual(len(report["per_seed"]), 6)
        self.assertEqual(set(report["summary_by_alpha"]), {"0.005", "0.05"})
        self.assertEqual(report["faults"], [1])
        for alpha, methods in report["summary_by_alpha"].items():
            clean = methods["clean"]["robust-maxz"]
            self.assertEqual(clean["paired_delta_early_vs_clean"]["max"], 0)
            self.assertEqual(clean["paired_delta_false_episodes_vs_clean"]["min"], 0)
            self.assertEqual(clean["early_detected"]["min"], clean["early_detected"]["max"])
            thresholds = {
                seed_row["results"]["clean"]["robust-maxz"]["threshold"]
                for seed_row in report["per_seed"] if str(seed_row["alpha"]) == alpha
            }
            self.assertEqual(len(thresholds), 1)
            self.assertEqual(clean["threshold"], thresholds.pop())
            hits = clean["fault_early_hits_across_seeds"]
            self.assertEqual(set(hits), {"1"})
            self.assertIn(hits["1"], (0, 3))

    def test_report_reproducibility_and_json_roundtrip(self):
        first = self.run_small()
        second = self.run_small()
        self.assertEqual(first, second)
        json_path, md_path = write_report(first, self.root / "results")
        self.assertEqual(json.loads(json_path.read_text()), first)
        self.assertEqual(md_path.read_text(), render_markdown(first))
        self.assertIn("No test-optimal alpha", md_path.read_text())

    def test_noise_seeds_are_paired_and_do_not_affect_clean(self):
        report = self.run_small()
        records = [r for r in report["per_seed"] if r["alpha"] == 0.005]
        clean_stats = [r["results"]["clean"]["robust-maxz"] for r in records]
        self.assertTrue(all(row == clean_stats[0] for row in clean_stats))
        # The seeds create different perturbations, but never different
        # source hashes, calibration thresholds or normal-only training.
        self.assertEqual(len(report["data_provenance"]), 3)
        for row in records:
            self.assertEqual(
                row["results"]["noise-20pct"]["robust-maxz"]["threshold"],
                row["results"]["clean"]["robust-maxz"]["threshold"],
            )
        self.assertFalse(any("optimal alpha" in key for key in report.keys()))

    def test_test_fault_mutation_does_not_change_normal_thresholds(self):
        before = self.run_small()
        self.fault[160:, :] += 500
        np.savetxt(self.root / "d01_te.dat", self.fault, fmt="%.8f")
        after = self.run_small()
        for alpha in ("0.005", "0.05"):
            for scenario in DEFAULT_SCENARIOS:
                self.assertEqual(
                    before["summary_by_alpha"][alpha][scenario]["robust-maxz"]["threshold"],
                    after["summary_by_alpha"][alpha][scenario]["robust-maxz"]["threshold"],
                )
        self.assertNotEqual(before["data_provenance"][-1]["sha256"],
                            after["data_provenance"][-1]["sha256"])

    def test_invalid_sweep_contract_rejected(self):
        bad = [
            ((19,), (.01, .05), ("clean",)),
            ((19, 19), (.01, .05), ("clean",)),
            ((-1, 20), (.01, .05), ("clean",)),
            ((19, 20), (.01, .01), ("clean",)),
            ((19, 20), (.01, float("nan")), ("clean",)),
            ((19, 20), (.01, .05), ("noise-20pct",)),
            ((19, 20), (.01, .05), ("clean", "clean")),
            ((19, 20), (.01, .05), ("clean", "unsupported")),
        ]
        for seeds, alphas, scenarios in bad:
            with self.subTest(seeds=seeds, alphas=alphas, scenarios=scenarios):
                with self.assertRaises(ValueError):
                    _validate(seeds, alphas, scenarios)

    def test_default_grid_is_fixed_before_evaluation(self):
        self.assertEqual(DEFAULT_ALPHAS, (.005, .01, .05))
        self.assertEqual(DEFAULT_SCENARIOS, ("clean", "random-missing-05", "noise-20pct"))


if __name__ == "__main__":
    unittest.main()
