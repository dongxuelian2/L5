"""Pinned, auditable download of publicly mirrored original TEP reference files.

Use only in an explicit benchmark run; no runtime or unit test downloads.
Original reference files are never committed to this repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .tep import read_tep_dat

# Reference commit (not floating 'master'): verified as the mirror's master
# on 2026-10-21. All benchmark reports include per-file SHA-256 checksums.
REFERENCE_REVISION = "9a6c8e5fcef4a2850778704e7793c87b0a187005"
SOURCE_BASE = (
    "https://raw.githubusercontent.com/jkitchin/"
    f"tennessee-eastman-profbraatz/{REFERENCE_REVISION}/data/"
)
MAX_REFERENCE_BYTES = 2_000_000
REFERENCE_SOURCES = json.loads(Path(__file__).with_name('reference_sources.json').read_text(encoding='utf-8'))
if REFERENCE_SOURCES['source_revision'] != REFERENCE_REVISION:
    raise RuntimeError('Reference checksum manifest does not match the pinned source revision.')


def validate_reference_hash(name: str, payload: bytes):
    expected = REFERENCE_SOURCES['files'][name]
    if len(payload) != expected['bytes'] or hashlib.sha256(payload).hexdigest() != expected['sha256']:
        raise ValueError(f'{name}: content differs from the pinned source SHA-256 (including cached files).')


def reference_filenames(faults: tuple[int, ...] = tuple(range(1, 22))) -> list[str]:
    if len(set(faults)) != len(faults) or any(i not in range(1, 22) for i in faults):
        raise ValueError("Fault IDs must be distinct integers between 1 and 21.")
    return ["d00.dat", "d00_te.dat", *(f"d{i:02d}_te.dat" for i in sorted(faults))]


def fetch_reference(
    destination: str | Path,
    *,
    faults: tuple[int, ...] = tuple(range(1, 22)),
    retries: int = 3,
) -> list[Path]:
    if not 1 <= retries <= 5:
        raise ValueError("retries must be between 1 and 5.")
    dest = Path(destination)
    dest.mkdir(parents=True, exist_ok=True)
    outputs = []
    for name in reference_filenames(faults):
        target = dest / name
        if target.exists():
            validate_reference_hash(name, target.read_bytes())
            # Existing files must pass structural and expected-size checks.
            dataset = read_tep_dat(target)
            size = len(dataset.rows)
            if size != (500 if name == "d00.dat" else 960):
                raise ValueError(f"{name} unexpected cached sample count: {size}")
            outputs.append(target)
            continue
        request = Request(SOURCE_BASE + name, headers={"User-Agent": "TripLens-TEP-Benchmark/0.3"})
        for attempt in range(retries):
            try:
                with urlopen(request, timeout=40) as response:
                    payload = response.read(MAX_REFERENCE_BYTES + 1)
                if len(payload) > MAX_REFERENCE_BYTES:
                    raise ValueError(f"{name}: reference payload exceeded size limit")
                validate_reference_hash(name, payload)
                # Commit the download atomically; delete invalid payloads.
                temp = dest / f".{name}.part"
                try:
                    temp.write_bytes(payload)
                    temp.replace(target)
                    try:
                        dataset = read_tep_dat(target)
                        size = len(dataset.rows)
                        expected = 500 if name == "d00.dat" else 960
                        if size != expected:
                            raise ValueError(f"{name}: expected {expected} rows, found {size}")
                    except (ValueError, OSError):
                        target.unlink(missing_ok=True)
                        raise
                finally:
                    temp.unlink(missing_ok=True)
                break
            except (HTTPError, URLError, TimeoutError, OSError):
                if attempt + 1 == retries:
                    raise
                time.sleep(0.5 * (attempt + 1))
        outputs.append(target)
    return outputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download pinned public TEP reference files")
    parser.add_argument("--dest", type=Path, required=True)
    parser.add_argument("--faults", type=int, nargs="+", default=list(range(1, 22)))
    args = parser.parse_args(argv)
    try:
        files = fetch_reference(args.dest, faults=tuple(args.faults))
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(f"Validated {len(files)} pinned TEP reference files from {REFERENCE_REVISION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
