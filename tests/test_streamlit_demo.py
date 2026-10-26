"""Regression tests for the stateless online demo adapters."""
import unittest

from demo.logic import (
    analyze,
    example_data,
    load_uploaded_csv,
    tep_faults,
    tep_table,
    validated_frame,
)


class StreamlitDemoTests(unittest.TestCase):
    def test_synthetic_process_is_repeatable(self):
        first = example_data()
        second = example_data()
        self.assertEqual(first.shape, (900, 4))
        self.assertTrue(first.equals(second))

    def test_uploaded_csv_limits(self):
        self.assertEqual(load_uploaded_csv(b"a,b\\n" + b"1,2\\n" * 300).shape, (300, 2))
        with self.assertRaisesRegex(ValueError, "300"):
            load_uploaded_csv(b"a,b\\n1,2\\n")
        with self.assertRaises(ValueError):
            validated_frame(example_data(900).iloc[:50])

    def test_analysis_uses_existing_l5_engine(self):
        completed, errors = analyze(
            example_data(), ["robust-maxz", "pca-q"], ["temperature_C", "pressure_kPa"], 0.4
        )
        self.assertEqual(errors, {})
        self.assertEqual(set(completed), {"robust-maxz", "pca-q"})
        self.assertEqual(len(completed["robust-maxz"]["scores"]), 540)
        self.assertGreater(completed["robust-maxz"]["threshold"], 0)
        self.assertGreater(completed["robust-maxz"]["summary"]["flaggedSamples"], 0)

    def test_published_tep_result_table(self):
        for configuration in ("A", "B", "C"):
            table = tep_table(configuration)
            self.assertEqual(len(table), 9)
            self.assertTrue((table["Normal samples"] == 4800).all())
        faults = tep_faults("A", "pca-q")
        self.assertEqual(len(faults), 20)
        self.assertTrue((faults["Runs"] == 3).all())


if __name__ == "__main__":
    unittest.main()
