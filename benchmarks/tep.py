"""Strict, dependency-free reader for the Russell/Chiang/Braatz Tennessee Eastman .dat files.

This module is deliberately separate from L5's synthetic-process diagnostic engine:
TEP XMEAS/XMV channels are not interchangeable with its 18 engineering signals.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

SAMPLE_SECONDS = 180  # 3-minute intervals in the reference data.
VARIABLES = tuple(
    [f"xmeas_{i}" for i in range(1, 42)]
    + [f"xmv_{i}" for i in range(1, 12)]
)
FILE_PATTERN = re.compile(r"d(0[0-9]|1[0-9]|2[01])(_te)?\.dat", re.IGNORECASE)


@dataclass(frozen=True)
class TEPDataset:
    """File-level metadata and samples; labels are NEVER included in feature rows."""

    source: str
    fault_id: int
    split: str
    layout: str
    rows: tuple[tuple[float, ...], ...]

    def summary(self) -> dict:
        return {
            "source": self.source,
            "fault_id": self.fault_id,
            "split": self.split,
            "layout": self.layout,
            "samples": len(self.rows),
            "features": len(VARIABLES),
            "sample_interval_seconds": SAMPLE_SECONDS,
            "first_timestamp_seconds": 0,
            "last_timestamp_seconds": (len(self.rows) - 1) * SAMPLE_SECONDS,
            "status": "ingested_only_no_diagnostic_metrics",
        }


def read_tep_dat(path: str | Path, *, layout: str = "auto") -> TEPDataset:
    """Load canonical d00.dat..d21_te.dat; handle the transposed d00.dat.

    'auto' intentionally rejects a 52x52 matrix (ambiguous). No normalization,
    fault onset or diagnostic interpretation is inferred here.
    """
    path = Path(path)
    match = FILE_PATTERN.fullmatch(path.name)
    if match is None:
        raise ValueError("Expected d00.dat..d21.dat or d00_te.dat..d21_te.dat.")
    if layout not in ("auto", "samples-first", "variables-first"):
        raise ValueError("layout must be auto, samples-first or variables-first.")

    matrix: list[tuple[float, ...]] = []
    width: int | None = None
    with path.open("r", encoding="ascii") as handle:
        for line_number, line in enumerate(handle, 1):
            parts = line.split()
            if not parts:
                continue
            try:
                values = tuple(float(p.replace("D", "E").replace("d", "e")) for p in parts)
            except ValueError as error:
                raise ValueError(f"Line {line_number}: nonnumeric value.") from error
            if not all(math.isfinite(value) for value in values):
                raise ValueError(f"Line {line_number}: non-finite value.")
            if width is None:
                width = len(values)
            elif len(values) != width:
                raise ValueError(
                    f"Line {line_number}: {len(values)} values; expected {width}."
                )
            matrix.append(values)

    if not matrix:
        raise ValueError("Empty TEP data file.")
    height = len(matrix)
    assert width is not None
    if layout == "auto":
        if width == 52 and height != 52:
            layout = "samples-first"
        elif height == 52 and width != 52:
            layout = "variables-first"
        elif height == 52 and width == 52:
            raise ValueError("Ambiguous 52x52 matrix; specify --layout.")
        else:
            raise ValueError(
                f"Expected N x 52 or 52 x N; found {height} x {width}."
            )

    if layout == "samples-first":
        if width != 52:
            raise ValueError(f"Expected 52 columns, found {width}.")
        rows = tuple(matrix)
    else:
        if height != 52:
            raise ValueError(f"Expected 52 variable rows, found {height}.")
        rows = tuple(tuple(column) for column in zip(*matrix))

    return TEPDataset(
        source=path.name,
        fault_id=int(match.group(1)),
        split="testing" if match.group(2) else "training",
        layout=layout,
        rows=rows,
    )


def export_csv(dataset: TEPDataset, path: str | Path) -> None:
    """Export time and all 52 original channels without mapping to L5 signals."""
    destination = Path(path)
    if destination.name == dataset.source:
        raise ValueError("CSV output must not overwrite the original DAT filename.")
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("t", *VARIABLES))
        for index, values in enumerate(dataset.rows):
            writer.writerow((index * SAMPLE_SECONDS, *values))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect/reference-export TEP DAT files")
    parser.add_argument("dat_file", type=Path, help="Local reference dXX[_te].dat file")
    parser.add_argument(
        "--layout", choices=("auto", "samples-first", "variables-first"),
        default="auto", help="Override the automatic file orientation check"
    )
    parser.add_argument(
        "--csv", type=Path, help="Optional destination for 53-column CSV export"
    )
    args = parser.parse_args(argv)
    try:
        dataset = read_tep_dat(args.dat_file, layout=args.layout)
        if args.csv:
            export_csv(dataset, args.csv)
    except (OSError, UnicodeError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(dataset.summary(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
