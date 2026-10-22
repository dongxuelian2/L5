"""Multimode MAT input guardrails, fixed train/cal/test isolation and transfer."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from benchmarks.multimode_normal import (
    CAL_END, FIT_END, FEATURES, GIT_BLOB_SHA1, MODE_IDS,
    METHODS, original_git_blob_sha, parse_normal_matrix, render_markdown,
    run_transfer, source_url, write_report,
)


class OriginalFormatTests(unittest.TestCase):
    def test_specific_pinned_raw_source_file_per_mode(self):
        self.assertEqual(len(GIT_BLOB_SHA1),6)
        self.assertEqual(set(GIT_BLOB_SHA1),set(MODE_IDS))
        for mode in MODE_IDS:
            url=source_url(mode)
            self.assertIn("09c194f78281bb495da6669cae7a726515f4a4cb",url)
            self.assertIn(f"/M{mode}/m{mode}d00.mat",url)
        with self.assertRaises(ValueError):
            source_url(7)
        self.assertEqual(original_git_blob_sha(b"hello"),"b6fc4c620b67d95f953a5c1c1230aaab5db5a1b0")

    def test_exactly_53_monitoring_features_28_disturbances_discarded(self):
        x=np.arange(1200*81,dtype=float).reshape(1200,81)
        parsed=parse_normal_matrix(x,name="m1d00")
        self.assertEqual(parsed.shape,(1200,53))
        np.testing.assert_array_equal(parsed[0],x[0,:53])
        x[0,53:]=1e90
        np.testing.assert_array_equal(parse_normal_matrix(x,name="m1d00")[0],parsed[0])

    def test_nonfinite_but_non_monitoring_columns_still_fail(self):
        x=np.zeros((1200,81))
        x[3,77]=np.nan
        with self.assertRaisesRegex(ValueError,"nonfinite"):
            parse_normal_matrix(x,name="m3d00")
        for wrong in (np.zeros((1200,52)),np.zeros((1100,81))):
            with self.assertRaisesRegex(ValueError,"81 raw columns"):
                parse_normal_matrix(wrong,name="m4d00")
        with self.assertRaisesRegex(ValueError,"numeric"):
            parse_normal_matrix(np.full((1200,81),"bad",dtype=object),name="m2d00")


class TransferProtocolTests(unittest.TestCase):
    def setUp(self):
        rng=np.random.default_rng(40)
        mixing=rng.normal(size=(3,53))
        def draw(mode):
            normal=rng.normal(size=(1250,3))@mixing + rng.normal(scale=.22,size=(1250,53))
            normal[:,0]+=mode*.25
            return normal
        self.data={1:draw(1),2:draw(2)}

    def test_causal_fixed_train_calibration_test_rows(self):
        r=run_transfer(self.data,modes=(1,2),methods=("robust-maxz","dpca-q-lag2"))
        self.assertEqual(r["fit_samples"],FIT_END)
        self.assertEqual(r["calibration_samples"],CAL_END-FIT_END)
        self.assertEqual(len(r["rows"]),8)
        self.assertEqual(len(r["comparison"]),4)
        self.assertEqual({row["test"]["observations"] for row in r["rows"]},{170})
        for row in r["rows"]:
            self.assertEqual(row["fit_metadata"]["features"],FEATURES)
            self.assertEqual(row["same_mode"],row["train_mode"]==row["test_mode"])
            self.assertGreaterEqual(row["test"]["episodes"],0)
            self.assertLessEqual(row["test"]["active_samples"],170)
        with tempfile.TemporaryDirectory() as p:
            js,md=write_report(r,Path(p))
            self.assertEqual(json.loads(js.read_text()),r)
            self.assertEqual(md.read_text(),render_markdown(r))
            self.assertIn("off-diagonal",md.read_text())

    def test_mutated_cross_mode_untouched_test_cannot_change_threshold(self):
        before=run_transfer(self.data,modes=(1,2),methods=("robust-maxz",))
        self.data[2][CAL_END:,:]+=8000
        after=run_transfer(self.data,modes=(1,2),methods=("robust-maxz",))
        assert_key=lambda r:{(x["train_mode"],x["test_mode"],x["method"]):x["threshold"] for x in r["rows"]}
        self.assertEqual(assert_key(before),assert_key(after))
        self.assertNotEqual(before["rows"][1]["test"]["active_samples"],after["rows"][1]["test"]["active_samples"])

    def test_frozen_source_threshold_does_not_depend_on_target_fit_data(self):
        before=run_transfer(self.data,modes=(1,2),methods=("robust-maxz",))
        first={x["test_mode"]:x["threshold"] for x in before["rows"] if x["train_mode"]==1}
        self.data[2][:CAL_END,:]+=1000
        after=run_transfer(self.data,modes=(1,2),methods=("robust-maxz",))
        self.assertEqual(first,{x["test_mode"]:x["threshold"] for x in after["rows"] if x["train_mode"]==1})

    def test_invalid_configs_fail_loudly(self):
        for kwargs in (
            {"modes":(1,1)}, {"modes":(1,7)},
            {"methods":("robust-maxz","robust-maxz")},
            {"methods":("cusum-maxz",)},
        ):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                run_transfer(self.data,**kwargs)
        shortened={1:self.data[1][:1000],2:self.data[2]}
        with self.assertRaisesRegex(ValueError,"1200"):
            run_transfer(shortened,modes=(1,2),methods=("robust-maxz",))


if __name__=="__main__":
    unittest.main()
