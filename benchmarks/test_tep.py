"""Unit tests for external TEP ingestion. No network or third-party fixtures needed."""
from __future__ import annotations

import csv
import json
import math
import tempfile
import unittest
from pathlib import Path

from benchmarks.tep import SAMPLE_SECONDS, VARIABLES, export_csv, main, read_tep_dat


class TEPImportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        # Each synthetic channel has a distinct value, exposing transpose bugs.
        self.rows = [
            tuple(index * 1000.0 + feature / 10 for feature in range(52))
            for index in range(3)
        ]

    def make_file(self, name="d14_te.dat", *, rows=None, transpose=False):
        matrix = self.rows if rows is None else rows
        if transpose:
            matrix = list(zip(*matrix))
        path = self.directory / name
        path.write_text(
            "\n".join("  ".join(str(value) for value in row) for row in matrix)
            + "\n",
            encoding="ascii",
        )
        return path

    def test_samples_first_preserves_all_features_and_metadata(self):
        dataset = read_tep_dat(self.make_file())
        self.assertEqual(dataset.rows, tuple(self.rows))
        self.assertEqual(dataset.fault_id, 14)
        self.assertEqual(dataset.split, "testing")
        self.assertEqual(dataset.layout, "samples-first")
        self.assertEqual(dataset.summary()["sample_interval_seconds"], 180)
        self.assertEqual(dataset.summary()["last_timestamp_seconds"], 360)
        self.assertEqual(len(VARIABLES), 52)
        self.assertEqual(VARIABLES[0], "xmeas_1")
        self.assertEqual(VARIABLES[-1], "xmv_11")
        self.assertNotIn("fault_id", VARIABLES)

    def test_variables_first_is_transposed_not_reordered(self):
        file = self.make_file("d00.dat", transpose=True)
        dataset = read_tep_dat(file)
        self.assertEqual(dataset.rows, tuple(self.rows))
        self.assertEqual(dataset.fault_id, 0)
        self.assertEqual(dataset.split, "training")
        self.assertEqual(dataset.layout, "variables-first")

    def test_export_has_timestamp_and_original_52_channels(self):
        dataset = read_tep_dat(self.make_file())
        path = self.directory / "tep.csv"
        export_csv(dataset, path)
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))
        self.assertEqual(rows[0], ["t", *VARIABLES])
        self.assertEqual(len(rows), 4)
        self.assertEqual([int(row[0]) for row in rows[1:]], [0, 180, 360])
        self.assertEqual([float(x) for x in rows[2][1:]], list(self.rows[1]))

    def test_non_rectangular_input_rejected(self):
        path = self.make_file()
        with path.open("a", encoding="ascii") as handle:
            handle.write("1 2 3\n")
        with self.assertRaisesRegex(ValueError, "Line 4"):
            read_tep_dat(path)

    def test_non_finite_values_rejected(self):
        for bad in ("nan", "inf", "-inf"):
            path = self.make_file()
            path.write_text(path.read_text().replace("0.0", bad, 1))
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "non-finite"):
                read_tep_dat(path)

    def test_wrong_dimensions_and_ambiguous_shapes_rejected(self):
        path = self.make_file(rows=[tuple(range(51)) for _ in range(3)])
        with self.assertRaisesRegex(ValueError, "Expected N x 52"):
            read_tep_dat(path)
        ambiguous = self.make_file(rows=[tuple(range(52)) for _ in range(52)])
        with self.assertRaisesRegex(ValueError, "Ambiguous 52x52"):
            read_tep_dat(ambiguous)
        self.assertEqual(len(read_tep_dat(ambiguous, layout="samples-first").rows), 52)

    def test_explicit_layout_checked(self):
        path = self.make_file()
        with self.assertRaisesRegex(ValueError, "Expected 52 variable rows"):
            read_tep_dat(path, layout="variables-first")
        with self.assertRaisesRegex(ValueError, "layout must be"):
            read_tep_dat(path, layout="upside-down")

    def test_labels_are_only_in_filenames_not_numeric_features(self):
        with self.assertRaisesRegex(ValueError, "Expected d00.dat"):
            read_tep_dat(self.make_file("fault_14.dat"))
        with self.assertRaisesRegex(ValueError, "Expected d00.dat"):
            read_tep_dat(self.make_file("d22.dat"))

    def test_empty_and_bad_numeric_files_rejected(self):
        empty = self.directory / "d00.dat"
        empty.write_text("  \n\n")
        with self.assertRaisesRegex(ValueError, "Empty"):
            read_tep_dat(empty)
        empty.write_text("3.0 nope\n")
        with self.assertRaisesRegex(ValueError, "Line 1"):
            read_tep_dat(empty)

    def test_fortran_d_exponents(self):
        path = self.make_file()
        path.write_text(path.read_text().replace("0.0", "0.0D+00", 1))
        self.assertEqual(read_tep_dat(path).rows[0][0], 0.0)

    def test_cli_summary_and_csv(self):
        from contextlib import redirect_stdout
        from io import StringIO
        file = self.make_file("d21.dat")
        output = self.directory / "out.csv"
        buffer = StringIO()
        with redirect_stdout(buffer):
            code = main([str(file), "--csv", str(output)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(buffer.getvalue())["fault_id"], 21)
        self.assertTrue(output.exists())


if __name__ == "__main__":
    unittest.main()
