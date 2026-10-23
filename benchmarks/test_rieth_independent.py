"""Synthetic/data-integrity contracts for truly separated Rieth simulation runs."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from benchmarks.rieth_independent import (
    DATA_FILES, EXTERNAL_TEST_RUN_IDS, METHODS, POLICIES, FOLDS, VERSION,
    extract_run_arrays, render_markdown, run_independent_runs, source_url,
    write_report,
)
from benchmarks.tep import VARIABLES


class RiethOriginalFormatTests(unittest.TestCase):
    def setUp(self):
        self.columns=("faultNumber","simulationRun","sample",*VARIABLES)
        self.rng=np.random.default_rng(6024)

    def make_matrix(self, *, ids=(1,2), n=8):
        records=[]
        for run_id in ids:
            readings=self.rng.normal(size=(n,52))
            for index,row in enumerate(readings):
                records.append([0,run_id,index+1,*row])
        return np.asarray(records,dtype=float)

    def test_run_extraction_strips_metadata_keeps_proper_order(self):
        raw=self.make_matrix()
        raw=raw[::-1].copy()
        parsed=extract_run_arrays(raw,self.columns,run_ids=(1,2),samples_per_run=8)
        self.assertEqual(list(parsed),[1,2])
        self.assertEqual(parsed[1].shape,(8,52))
        self.assertEqual(parsed[2].shape,(8,52))
        np.testing.assert_allclose(parsed[1][0],raw[15,3:])

    def test_bad_run_schema_faults_duplicates_and_missing_sample_rejected(self):
        raw=self.make_matrix()
        scenarios=[
            (raw,("faultNumber",)*55,(1,2),8),
            (raw[:-1],self.columns,(1,2),8),
            (raw,self.columns,(1,2),9),
        ]
        for arr,cols,ids,n in scenarios:
            with self.subTest(problem=len(arr)),self.assertRaises(ValueError):
                extract_run_arrays(arr,cols,run_ids=ids,samples_per_run=n)
        faulty=raw.copy()
        faulty[0,0]=1
        with self.assertRaisesRegex(ValueError,"Fault-containing"):
            extract_run_arrays(faulty,self.columns,run_ids=(1,2),samples_per_run=8)
        gap=raw.copy()
        gap[0,2]=2  # duplicated sample=2; sample=1 missing
        with self.assertRaisesRegex(ValueError,"contiguous"):
            extract_run_arrays(gap,self.columns,run_ids=(1,2),samples_per_run=8)
        with self.assertRaisesRegex(ValueError,"distinct"):
            extract_run_arrays(raw,self.columns,run_ids=(1,1),samples_per_run=8)

    def test_original_source_is_specific_persistent_file_not_random_mirror(self):
        train=source_url(DATA_FILES["train"][1])
        test=source_url(DATA_FILES["test"][1])
        self.assertIn("dataverse.harvard.edu/api/access/datafile/",train)
        self.assertIn("6C3JR1",train)
        self.assertIn("TMBUVJ",train)
        self.assertIn("Q4NOFD",test)
        self.assertNotEqual(train,test)


class IndependentNormalRunsTests(unittest.TestCase):
    def setUp(self):
        rng=np.random.default_rng(10020)
        mixing=rng.normal(size=(4,52))
        def run(n):
            return rng.normal(size=(n,4))@mixing + rng.normal(scale=.24,size=(n,52))
        self.train={i:run(500) for i in range(1,7)}
        self.test={i:run(960) for i in range(1,11)}

    def audit(self,**kw):
        opts={"methods":("robust-maxz","dpca-q-lag2"),
              "policies":POLICIES,"folds":FOLDS,
              "external_ids":EXTERNAL_TEST_RUN_IDS}
        opts.update(kw)
        return run_independent_runs(self.train,self.test,**opts)

    def test_exclusively_distinct_fit_cal_validate_runs_and_external_tests(self):
        report=self.audit()
        self.assertEqual(report["benchmark"],VERSION)
        self.assertEqual(len(report["rows"]),8)
        self.assertEqual(len(report["external_normal_runs"]),10)
        self.assertEqual(report["folds"][0]["fit_run"],1)
        self.assertEqual(report["folds"][1]["validation_run"],6)
        for row in report["rows"]:
            self.assertEqual(len(row["external_per_run"]),10)
            self.assertEqual(row["calibration"]["total_samples"],500)
            self.assertEqual(row["untouched_training_normal_validation"]["total_samples"],500)
            self.assertEqual(row["external_active_samples"]["sum"],
                sum(r["active_samples"] for r in row["external_per_run"].values()))
            if row["policy"]=="normal-calibration-1episode-2pct":
                self.assertLessEqual(row["calibration"]["episodes"],1)
                self.assertLessEqual(row["calibration"]["active_samples"],10)
        self.assertEqual(len(report["paired_vs_maxz"]),4)

    def test_external_test_mutation_cannot_change_any_normal_fit_threshold(self):
        first=self.audit()
        self.test[1][:]+=9000
        second=self.audit()
        keys=lambda rows:{(r["fold"],r["method"],r["policy"]):r["threshold"] for r in rows}
        self.assertEqual(keys(first["rows"]),keys(second["rows"]))
        self.assertNotEqual(first["rows"][0]["external_per_run"]["1"],
                            second["rows"][0]["external_per_run"]["1"])

    def test_normal_validation_mutation_does_not_change_threshold(self):
        first=self.audit()
        self.train[3][:]+=500
        self.train[6][:]+=500
        after=self.audit()
        self.assertEqual(
            {(r["fold"],r["method"],r["policy"]):r["threshold"] for r in first["rows"]},
            {(r["fold"],r["method"],r["policy"]):r["threshold"] for r in after["rows"]},
        )

    def test_missing_or_shared_runs_are_rejected(self):
        with self.assertRaisesRegex(ValueError,"nonoverlapping"):
            self.audit(folds=(("A",1,2,3),("B",4,2,6)))
        with self.assertRaisesRegex(ValueError,"distinct"):
            self.audit(folds=(("A",1,1,3),))
        with self.assertRaisesRegex(ValueError,"Missing"):
            self.audit(external_ids=(1,99))
        with self.assertRaisesRegex(ValueError,"fixed"):
            self.audit(methods=("cusum-maxz",))

    def test_json_markdown_reproducible(self):
        report=self.audit()
        with tempfile.TemporaryDirectory() as tmp:
            js,md=write_report(report,Path(tmp))
            self.assertEqual(json.loads(js.read_text()),report)
            self.assertEqual(md.read_text(),render_markdown(report))
            self.assertIn("independently seeded",md.read_text())


if __name__=="__main__":
    unittest.main()
