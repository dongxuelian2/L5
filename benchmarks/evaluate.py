"""Reproducible, train-normal-only TEP detection benchmark.

Usage:
  python3 -m benchmarks.evaluate /path/to/tep-data --output-dir /tmp/l5-tep
No benchmark data is downloaded or bundled by this script.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from .monitoring import (
    as_matrix, build_monitor, calibrate, checksum, evaluate_case,
    split_normal_training, summarize_cases,
)
from .tep import SAMPLE_SECONDS, VARIABLES, read_tep_dat

DEFAULT_METHODS = ("robust-maxz", "pca-q", "pca-t2")
BENCHMARK_VERSION = "tep-detection-v1"


def run_benchmark(
    data_dir: str | Path,
    *,
    faults: tuple[int, ...] = tuple(range(1, 22)),
    methods: tuple[str, ...] = DEFAULT_METHODS,
    fit_fraction: float = 0.7,
    alpha: float = 0.01,
    persistence: int = 3,
    onset_sample: int = 160,
    early_window_samples: int = 20,
) -> dict:
    """Fit and calibrate only on d00.dat; never fit on *_te or fault data."""
    folder = Path(data_dir)
    if not folder.is_dir():
        raise ValueError(f"Not a directory: {folder}")
    if not faults or len(set(faults)) != len(faults) or any(i not in range(1, 22) for i in faults):
        raise ValueError("Fault IDs must be distinct integers from 1 to 21.")
    if not methods or len(set(methods)) != len(methods):
        raise ValueError("Choose at least one distinct monitor.")
    if persistence < 1:
        raise ValueError("persistence must be positive.")
    if onset_sample < 1:
        raise ValueError("onset_sample must be positive.")
    if early_window_samples < 1:
        raise ValueError("early_window_samples must be positive.")

    expected = ["d00.dat", "d00_te.dat", *[f"d{i:02d}_te.dat" for i in sorted(faults)]]
    absent = [name for name in expected if not (folder / name).is_file()]
    if absent:
        raise ValueError(f"Missing required reference files: {', '.join(absent)}")

    datasets = {name: read_tep_dat(folder / name) for name in expected}
    train = datasets["d00.dat"]
    if len(train.rows) not in (480, 500):
        raise ValueError(f"Unexpected d00.dat length {len(train.rows)} (expected 480 or 500).")
    for name in expected[1:]:
        if len(datasets[name].rows) != 960:
            raise ValueError(f"{name}: expected exactly 960 reference samples.")
    if onset_sample >= 960:
        raise ValueError("onset_sample must precede the end of reference test files.")

    fit, calibration = split_normal_training(train.rows, fit_fraction)
    # No fault training files are ever read or consulted, even if present.
    inputs = [
        {
            **datasets[name].summary(),
            "sha256": checksum(folder / name),
            "usage": "healthy_fit_and_calibration" if name == "d00.dat" else "evaluation_only",
        }
        for name in expected
    ]
    result = {
        "schema_version": 1,
        "benchmark": BENCHMARK_VERSION,
        "dataset": "Russell-Chiang-Braatz Tennessee Eastman reference DAT",
        "evaluation_protocol": {
            "fit_source": "d00.dat",
            "fit_samples": len(fit),
            "calibration_samples": len(calibration),
            "split": "chronological_no_shuffle",
            "test_normal_source": "d00_te.dat",
            "fault_test_sources": [f"d{i:02d}_te.dat" for i in sorted(faults)],
            "fault_onset_zero_based_sample": onset_sample,
            "fault_onset_is_protocol_assumption": True,
            "early_detection_window_samples": early_window_samples,
            "early_detection_window_minutes": early_window_samples * SAMPLE_SECONDS // 60,
            "fault_training_used": False,
            "threshold_from": "held_out_normal_training_only",
            "threshold_alpha_target": alpha,
            "threshold_rule": "higher_empirical_quantile_strict_greater_than",
            "persistence_consecutive_samples": persistence,
            "sample_interval_seconds": SAMPLE_SECONDS,
            "notes": [
                "A sample above threshold is not an automatically validated real process fault.",
                "Calibration quantiles are empirical, not guaranteed test false-alarm bounds.",
                "The fault onset of 160 is a conventional TEP test protocol, not inferred from samples.",
                "Post-onset detection and attribution are not a claim of accurate fault classification.",
                "Temporal correlations, split selection and dataset edition affect results.",
            ],
        },
        "input_files": inputs,
        "features": list(VARIABLES),
        "methods": {},
    }

    # Numeric matrices are created once. Labels/IDs are never passed to fit.
    cases = [(datasets["d00_te.dat"], None)]
    cases += [(datasets[f"d{i:02d}_te.dat"], onset_sample) for i in sorted(faults)]
    for method_name in methods:
        model = build_monitor(method_name)
        model.fit(fit)
        threshold = calibrate(model, calibration, alpha=alpha)
        metrics = [
            evaluate_case(
                source=dataset.source,
                fault_id=dataset.fault_id,
                samples=as_matrix(dataset.rows, features=len(VARIABLES)),
                monitor=model,
                threshold=threshold,
                consecutive=persistence,
                feature_names=VARIABLES,
                onset_sample=onset,
                seconds_per_sample=SAMPLE_SECONDS,
                early_window_samples=early_window_samples,
            )
            for dataset, onset in cases
        ]
        # Explicit conversion avoids mutating frozen CaseMetrics.
        from dataclasses import asdict
        result["methods"][method_name] = {
            "threshold": round(threshold, 10),
            "model": model.metadata(),
            "aggregate": summarize_cases(metrics),
            "cases": [asdict(metric) for metric in metrics],
        }
    return result


def render_markdown(report: dict) -> str:
    """Human-readable, reproducible benchmark scoreboard (not a scientific comparison claim)."""
    protocol = report["evaluation_protocol"]
    window = protocol["early_detection_window_minutes"]
    lines = [
        "# Tennessee Eastman: external anomaly-detection baseline",
        "",
        "**Scope:** 21 known TEP test scenarios; this is anomaly detection, not",
        "fault-ID classification, causal diagnosis, or validated plant control.",
        "",
        f"- Train: normal \`d00.dat\`; chronological {protocol['fit_samples']} fit + "
        f"{protocol['calibration_samples']} calibration samples",
        f"- Test: healthy \`d00_te.dat\`; faulty \`d01_te.dat\` ... \`d21_te.dat\`",
        f"- Assumed fault onset: zero-based sample {protocol['fault_onset_zero_based_sample']}; "
        f"alarm persistence: {protocol['persistence_consecutive_samples']} consecutive samples",
        f"- **Early detection horizon: {window} minutes**; later alarms are not early successes",
        "",
        "| Method | Early faults | Eventual faults | Healthy false-alarm samples | Mean detected delay |",
        "|:--|--:|--:|--:|--:|",
    ]
    for name, result in report["methods"].items():
        aggr = result["aggregate"]
        n = aggr["faults_evaluated"]
        delay = aggr["mean_detected_delay_minutes"]
        lines.append(
            f"| {name} | {aggr['faults_detected_early']}/{n} | "
            f"{aggr['faults_detected']}/{n} | "
            f"{aggr['healthy_test_false_alarm_samples']}/960 | "
            f"{delay if delay is not None else 'N/A'} min |"
        )
    lines += [
        "",
        "## Per-fault delay (minutes from onset; * indicates early detection)",
        "",
        "| Fault ID | " + " | ".join(report["methods"]) + " |",
        "|:--|" + "|".join("--:" for _ in report["methods"]) + "|",
    ]
    faulty = sorted(
        case["fault_id"]
        for case in next(iter(report["methods"].values()))["cases"]
        if case["fault_id"] != 0
    )
    for fault in faulty:
        cells = []
        for method in report["methods"].values():
            case = next(c for c in method["cases"] if c["fault_id"] == fault)
            delay = case["detection_delay_minutes"]
            if delay is None:
                cells.append("missed")
            else:
                cells.append(f"{delay}{'*' if case['detected_within_early_window'] else ''}")
        lines.append(f"| IDV({fault}) | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## Limits and reproducibility",
        "",
        "- Eventual detection over 800 post-fault samples (~40 hours) is not rapid detection.",
        "- False alarm fraction measures alarm-active samples, not statistically",
        "  independent false alarm episodes.",
        "- Mean delay excludes undetected faults, so it must be read alongside",
        "  detected counts and the early-horizon metric.",
        "- Calibration is healthy training-only; the threshold is an empirical",
        "  quantile and does not establish a guaranteed deployment false-alarm rate.",
        "- The highlighted variables are descriptive signal deviations, not",
        "  verified physical or causal root causes.",
        "",
        "### Input provenance (SHA-256)",
        "",
    ]
    for item in report["input_files"]:
        lines.append(f"- \`{item['source']}\`: \`{item['sha256']}\`")
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict, output_dir: str | Path) -> tuple[Path, Path, Path]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    json_path = destination / "tep_detection_report.json"
    csv_path = destination / "tep_detection_cases.csv"
    markdown_path = destination / "tep_detection_scoreboard.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    fields = [
        "method", "source", "fault_id", "samples", "onset_sample",
        "false_alarm_samples", "normal_samples", "false_alarm_rate",
        "detected_after_onset", "detected_within_early_window", "detection_delay_samples", "detection_delay_minutes",
        "detection_fraction_post_onset", "first_post_onset_alarm_sample",
        "first_post_onset_alarm_variables",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for method, metrics in report["methods"].items():
            for case in metrics["cases"]:
                writer.writerow({
                    **case,
                    "method": method,
                    "first_post_onset_alarm_variables": ";".join(
                        case["first_post_onset_alarm_variables"]
                    ),
                })
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, csv_path, markdown_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Normal-only TEP anomaly benchmark (not fault classification)")
    parser.add_argument("data_dir", type=Path, help="Directory containing the original TEP DAT reference files")
    parser.add_argument("--faults", type=int, nargs="+", default=list(range(1, 22)),
                        help="Fault IDs to evaluate (default: all 1..21, with normal test)")
    parser.add_argument("--methods", nargs="+", choices=DEFAULT_METHODS, default=list(DEFAULT_METHODS))
    parser.add_argument("--fit-fraction", type=float, default=0.7)
    parser.add_argument("--alpha", type=float, default=0.01)
    parser.add_argument("--persistence", type=int, default=3)
    parser.add_argument("--onset-sample", type=int, default=160)
    parser.add_argument("--early-window-samples", type=int, default=20)
    parser.add_argument("--output-dir", type=Path, help="Write JSON + CSV result artifacts here")
    args = parser.parse_args(argv)

    try:
        report = run_benchmark(
            args.data_dir,
            faults=tuple(args.faults),
            methods=tuple(args.methods),
            fit_fraction=args.fit_fraction,
            alpha=args.alpha,
            persistence=args.persistence,
            onset_sample=args.onset_sample,
            early_window_samples=args.early_window_samples,
        )
        if args.output_dir:
            json_path, csv_path, markdown_path = write_report(report, args.output_dir)
            print(f"Reports: {json_path}, {csv_path} and {markdown_path}")
        for name, result in report["methods"].items():
            summary = result["aggregate"]
            print(
                f"{name}: {summary['faults_detected']}/{summary['faults_evaluated']} eventual, "
                f"{summary['faults_detected_early']}/{summary['faults_evaluated']} early; held-out normal FPR {summary['healthy_test_false_alarm_rate']:.4f}; "
                f"mean delay {summary['mean_detected_delay_minutes']} min (detected faults)"
            )
    except (ValueError, OSError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
