"""Cross-operating-mode NORMAL transfer audit for the six-mode TEP release.

Source: Lichen0102 / THUFDD MMFDD-TEP v1.0 (2023).
Pinned GitHub commit 09c194f78281bb495da6669cae7a726515f4a4cb.
This is NOT Reinartz et al.'s 133GB DTU dataset or Rieth's Dataverse.

The six m{1..6}d00.mat files contain SINGLE normal trajectories per
mode, in columns 0..52 of an 81-column MATLAB matrix. Remaining
28 disturbance columns are never used. Original README describes 41
measurements and 12 input variables; exact channel equivalence to the
older canonical 52-variable Braatz/Rieth representation is NOT assumed.

This tests cross-mode nuisance alarms only, NOT new fault-detection scores.
Every model is fitted/calibrated on one mode's early/medium normal period,
and scored on strictly future portions of ALL six normal mode trajectories.
The target-mode sequence never influences training or calibration.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from statistics import median
import urllib.error
import urllib.request

import numpy as np

from .monitoring import as_matrix, build_monitor, calibrate, persistent_alarms
from .robustness import alarm_episodes

VERSION = "tep-multimode-normal-transfer-v1"
SOURCE_REPO = "Lichen0102/Multi-mode-Fault-Diagnosis-Datasets-with-TE-process"
SOURCE_COMMIT = "09c194f78281bb495da6669cae7a726515f4a4cb"
MODE_IDS = (1, 2, 3, 4, 5, 6)
METHODS = ("robust-maxz", "pca-q", "pca-t2", "dpca-q-lag2", "dpca-t2-lag2")
# Verified against GitHub's original file tree (Git blob SHA-1; not SHA-256).
GIT_BLOB_SHA1 = {
    1: "2da4f7051e7c3ee91781e18c46da100a00a628ce",
    2: "442921f8389d2fa38d9030d1aa33fb73ad5769cf",
    3: "2b3cf641c2bde12cbb23969422f9e6da0b1f0c92",
    4: "e2b98451f0c20647064ea719d85aafa85d2c144e",
    5: "518d664049d89b67fce3fe42d39c435bda4cf734",
    6: "4c98917eb064a3efb558240b8b0acc895f01b331",
}
FEATURES = 53
TOTAL_COLUMNS = 81
FIT_END, CAL_END = 720, 1080
MAX_SOURCE_BYTES = 4_000_000
ALPHA = .01
PERSISTENCE = 3


def source_url(mode: int) -> str:
    if mode not in MODE_IDS:
        raise ValueError("Unknown TEP operating mode.")
    return (f"https://raw.githubusercontent.com/{SOURCE_REPO}/"
            f"{SOURCE_COMMIT}/M{mode}/m{mode}d00.mat")


def original_git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def download_mode_data(directory: Path, *, modes: tuple[int, ...] = MODE_IDS,
                       allow_network: bool = True) -> dict:
    """Only six 1.6 MB normal source files; fail closed on changed content."""
    if not modes or len(set(modes)) != len(modes) or any(i not in MODE_IDS for i in modes):
        raise ValueError("Choose distinct official operating modes 1..6.")
    directory.mkdir(parents=True, exist_ok=True)
    provenance = {}
    for mode in modes:
        filename = f"m{mode}d00.mat"
        destination = directory / filename
        if not destination.exists():
            if not allow_network:
                raise ValueError(f"Missing cached source: {destination}")
            request = urllib.request.Request(
                source_url(mode), headers={"User-Agent": "L5-TEP-normal-transfer/1.0"},
            )
            temp = directory / (filename + ".partial")
            try:
                with urllib.request.urlopen(request, timeout=70) as response, temp.open("wb") as out:
                    length = 0
                    while True:
                        block = response.read(1 << 20)
                        if not block:
                            break
                        length += len(block)
                        if length > MAX_SOURCE_BYTES:
                            raise ValueError("Unexpectedly large upstream MATLAB source.")
                        out.write(block)
                temp.replace(destination)
            finally:
                temp.unlink(missing_ok=True)
        data = destination.read_bytes()
        if not 500_000 < len(data) <= MAX_SOURCE_BYTES:
            raise ValueError(f"Invalid mode {mode} MATLAB file size.")
        git_sha = original_git_blob_sha(data)
        if git_sha != GIT_BLOB_SHA1[mode]:
            raise ValueError(f"Mode {mode} binary differs from pinned GitHub blob: {git_sha}")
        provenance[str(mode)] = {
            "mode": mode, "source_url": source_url(mode),
            "source_repo": SOURCE_REPO, "source_commit": SOURCE_COMMIT,
            "file_bytes": len(data), "git_blob_sha1": git_sha,
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    return provenance


def parse_normal_matrix(values: np.ndarray, *, name: str) -> np.ndarray:
    """Strict, raw data-order preservation; never infer canonical 52 sensors."""
    x = np.asarray(values)
    if x.ndim != 2 or x.shape[1] != TOTAL_COLUMNS or len(x) < 1200:
        raise ValueError(f"{name}: expected >=1200 rows and exactly 81 raw columns.")
    if not np.issubdtype(x.dtype, np.number) or np.iscomplexobj(x):
        raise ValueError(f"{name}: original MATLAB matrix must be real numeric.")
    if not np.isfinite(x).all():
        raise ValueError(f"{name}: nonfinite process/disturbance data.")
    data = as_matrix(x[:, :FEATURES], features=FEATURES).copy()
    if not np.isfinite(data).all():
        raise ValueError(f"{name}: nonfinite monitoring inputs.")
    return data


def read_mode_data(directory: Path, *, modes: tuple[int, ...] = MODE_IDS) -> dict[int, np.ndarray]:
    try:
        from scipy.io import loadmat
    except ImportError as error:
        raise RuntimeError("Install scipy==1.16.2 for reading original MATLAB files.") from error
    runs = {}
    for mode in modes:
        name = f"m{mode}d00"
        content = loadmat(directory / (name + ".mat"))
        if name not in content:
            raise ValueError(f"Missing expected MATLAB object {name}.")
        runs[mode] = parse_normal_matrix(content[name], name=name)
    return runs


def _workload(model, data: np.ndarray, threshold: float) -> dict:
    scores = model.score(data)
    alarms = persistent_alarms(scores, threshold, PERSISTENCE)
    stats = alarm_episodes(alarms, len(alarms))
    return {
        "episodes": stats["count"], "active_samples": stats["active_samples"],
        "longest_active_run": stats["longest_duration_samples"],
        "observations": len(alarms),
        "fraction_active": round(stats["active_samples"]/len(alarms), 6),
    }


def run_transfer(
    mode_data: dict[int, np.ndarray], *, modes: tuple[int, ...] = MODE_IDS,
    methods: tuple[str, ...] = METHODS,
) -> dict:
    """The six source trajectories have one fixed, untouched test tail each.

    FIT=first 720, CAL=next 360, EVAL=all later samples, for EVERY mode.
    No target-mode observations enter the source-mode fitted model/threshold.
    This is not cross-run independence within a mode; only ONE run/mode.
    """
    if not modes or len(set(modes)) != len(modes) or any(i not in MODE_IDS for i in modes):
        raise ValueError("Expected unique declared mode IDs 1..6.")
    if not methods or len(set(methods)) != len(methods) or any(m not in METHODS for m in methods):
        raise ValueError("Expected unique fixed monitor names.")
    data = {mode: as_matrix(mode_data[mode], features=FEATURES) for mode in modes}
    if any(len(x) < 1200 for x in data.values()):
        raise ValueError("Each normal mode requires at least 1200 time samples.")
    # Cross-mode only tests after an identical logical time boundary.
    # The tails remain untouched by fitting and threshold selection.
    report = {
        "schema_version": 1, "benchmark": VERSION,
        "source": SOURCE_REPO, "source_commit": SOURCE_COMMIT,
        "mode_ids": list(modes), "methods": list(methods),
        "features": FEATURES, "raw_columns": TOTAL_COLUMNS,
        "source_column_mapping": "original columns 0..52, generic 53 features; never assume canonical 52",
        "fit_samples": FIT_END, "calibration_samples": CAL_END-FIT_END,
        "normal_validation_start": CAL_END,
        "calibration_alpha": ALPHA, "alarm_persistence": PERSISTENCE,
        "rows": [], "comparison": [],
        "limitations": [
            "Single normal trajectory per operating mode; these are not independently seeded replicates within a mode.",
            "All six mode files come from a different publication/repository than Reinartz DTU or Rieth Dataverse.",
            "Raw 53-feature ordering comes from the source README and is not equated with previous 52-channel TEP.",
            "A different healthy operating point can trigger the old mode's anomaly detector without any fault.",
            "Cross-mode test tails are never used for fit/threshold selection.",
            "An out-of-mode alarm is a NORMAL-domain-shift false alarm, not a fault detection.",
            "Samples are likely temporally correlated; no population confidence intervals are claimed.",
            "Results are descriptive diagnostics, not evidence of reliable automatic mode recognition.",
        ],
    }
    for source_mode in modes:
        source = data[source_mode]
        for method in methods:
            model = build_monitor(method)
            model.fit(source[:FIT_END])
            threshold = calibrate(model, source[FIT_END:CAL_END], ALPHA)
            if not np.isfinite(threshold):
                raise ValueError("Normal-calibration threshold must remain finite.")
            for target_mode in modes:
                target = data[target_mode]
                workload = _workload(model, target[CAL_END:], threshold)
                report["rows"].append({
                    "train_mode": source_mode, "test_mode": target_mode,
                    "same_mode": source_mode == target_mode,
                    "method": method, "threshold": round(threshold, 10),
                    "fit_metadata": model.metadata(),
                    "test": workload,
                })
    for source_mode in modes:
        for target_mode in modes:
            base = next(r for r in report["rows"] if r["train_mode"]==source_mode
                        and r["test_mode"]==target_mode and r["method"]=="robust-maxz") if "robust-maxz" in methods else None
            if base is None:
                continue
            for row in report["rows"]:
                if row["train_mode"] != source_mode or row["test_mode"] != target_mode or row["method"]=="robust-maxz":
                    continue
                report["comparison"].append({
                    "train_mode": source_mode, "test_mode": target_mode, "method": row["method"],
                    "difference_from_maxz_episodes": row["test"]["episodes"]-base["test"]["episodes"],
                    "difference_from_maxz_active_samples": row["test"]["active_samples"]-base["test"]["active_samples"],
                })
    # Aggregates are descriptive over the SAME six trajectories reused
    # across 36 source/target pairs; do not treat as independent trials.
    for method in methods:
        per_method = [r for r in report["rows"] if r["method"] == method]
        for same in (True, False):
            selected = [r for r in per_method if r["same_mode"] is same]
            total = sum(r["test"]["observations"] for r in selected)
            active = sum(r["test"]["active_samples"] for r in selected)
            report.setdefault("descriptive_summary", []).append({
                "method": method,
                "subset": "diagonal_same_mode" if same else "off_diagonal_normal_shift",
                "cells": len(selected),
                "healthy_normal_observations": total,
                "false_alarm_episodes": sum(r["test"]["episodes"] for r in selected),
                "alarm_active_samples": active,
                "alarm_active_fraction": round(active / total, 6),
            })
    return report


def render_markdown(report: dict) -> str:
    lines = [
        "# TEP: six-mode healthy cross-operating-mode transfer audit", "",
        "Single normal trajectory **per mode**; no fault records or mode-label classifier.",
        "53 original source columns are NOT assumed to match the older 52-channel dataset.", "",
        "Fit [0,720), calibrate [720,1080), score normal tails [1080,end).",
        "Same-mode cells estimate held-out in-mode nuisance alarms; off-diagonal cells",
        "quantify NORMAL mode shift mistaken for anomalies.", "",
        "## Descriptive same-mode vs cross-mode summary", "",
        "| Detector | Normal subset | Cells | Total confirmed false-alarm episodes | Alarm-active samples / normal samples | Active fraction |",
        "|:--|:--|--:|--:|--:|--:|",
    ]
    for summary in report["descriptive_summary"]:
        lines.append(
            f"| {summary['method']} | {summary['subset']} | {summary['cells']} | "
            f"{summary['false_alarm_episodes']} | "
            f"{summary['alarm_active_samples']}/{summary['healthy_normal_observations']} | "
            f"{summary['alarm_active_fraction']:.2%} |"
        )
    lines += [
        "", "## Full fixed protocol transfer matrix", "",
        "| Trained mode | Test mode | Detector | Same mode? | Normal false-alarm episodes | Normal alarm-active samples | Evaluation samples |",
        "|:--|:--|:--|:--|--:|--:|--:|",
    ]
    for r in report["rows"]:
        t=r["test"]
        lines.append(
            f"| {r['train_mode']} | {r['test_mode']} | {r['method']} | "
            f"{'yes' if r['same_mode'] else 'no'} | {t['episodes']} | "
            f"{t['active_samples']} | {t['observations']} |"
        )
    lines += ["", "## Limitations", ""]
    lines.extend("- "+v for v in report["limitations"])
    if "original_sources" in report:
        lines+=["", "## Original MATLAB source checksums (SHA-256)", ""]
        for p in report["original_sources"].values():
            lines.append(f"- Mode {p['mode']}: {p['sha256']}, Git blob {p['git_blob_sha1']}")
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict, directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    js=directory/"tep_six_mode_normal_report.json"
    md=directory/"tep_six_mode_normal_scoreboard.md"
    js.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False)+"\n",encoding="utf-8")
    md.write_text(render_markdown(report),encoding="utf-8")
    return js,md


def main(argv: list[str] | None = None) -> int:
    parser=argparse.ArgumentParser(description="Pinned six-mode TEP NORMAL-only domain shift audit")
    parser.add_argument("data_dir",type=Path)
    parser.add_argument("--output-dir",type=Path)
    parser.add_argument("--local-only",action="store_true")
    args=parser.parse_args(argv)
    try:
        sources=download_mode_data(args.data_dir, allow_network=not args.local_only)
        runs=read_mode_data(args.data_dir)
        result=run_transfer(runs)
        result["original_sources"]=sources
        if args.output_dir:
            files=write_report(result,args.output_dir)
            print("Reports: "+", ".join(str(f) for f in files))
        print(render_markdown(result))
    except (ValueError, OSError, RuntimeError, urllib.error.URLError) as error:
        parser.error(str(error))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
