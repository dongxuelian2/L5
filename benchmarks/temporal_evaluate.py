"""Head-to-head evaluation of fixed causal temporal and static TEP baselines.

This entry point reuses exactly the existing normal-only fit/calibration,
held-out test files and onset/persistence/early-window rules. No model or
threshold is chosen based on the results of these held-out faults.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from .evaluate import run_benchmark, write_report
from .monitoring import build_monitor, calibrate, persistent_alarms, split_normal_training
from .robustness import alarm_episodes
from .tep import read_tep_dat

VERSION = "tep-causal-temporal-v1"
METHODS = ("robust-maxz", "pca-q", "pca-t2", "cusum-maxz", "ewma-maxz")


def run_comparison(
    data_dir: str | Path, *,
    faults: tuple[int, ...] = tuple(range(1, 22)),
    alpha: float = 0.01,
    persistence: int = 3,
    onset_sample: int = 160,
    early_window_samples: int = 20,
    fit_fraction: float = 0.7,
) -> dict:
    baseline = run_benchmark(
        data_dir, faults=faults, methods=METHODS,
        alpha=alpha, persistence=persistence, onset_sample=onset_sample,
        early_window_samples=early_window_samples, fit_fraction=fit_fraction,
    )
    normal = read_tep_dat(Path(data_dir) / "d00_te.dat")
    fit, calibration = split_normal_training(
        read_tep_dat(Path(data_dir) / "d00.dat").rows, fit_fraction
    )
    rows = []
    for name in METHODS:
        model = build_monitor(name)
        model.fit(fit)
        limit = calibrate(model, calibration, alpha)
        reference = baseline["methods"][name]
        if round(limit, 10) != reference["threshold"]:
            raise AssertionError("Healthy-only recalibration mismatch.")
        scores = model.score(normal.rows)
        alarms = persistent_alarms(scores, limit, persistence)
        episodes = alarm_episodes(alarms, len(alarms))
        if episodes["active_samples"] != reference["aggregate"]["healthy_test_false_alarm_samples"]:
            raise AssertionError("Healthy false-alarm metrics disagree with canonical baseline.")
        agg = reference["aggregate"]
        rows.append({
            "method": name,
            "kind": "temporal" if name in ("cusum-maxz", "ewma-maxz") else "static",
            "early_detected": agg["faults_detected_early"],
            "eventually_detected": agg["faults_detected"],
            "faults_evaluated": agg["faults_evaluated"],
            "healthy_false_alarm_active_samples": episodes["active_samples"],
            "healthy_false_alarm_episodes": episodes["count"],
            "healthy_false_alarm_episodes_per_24h": episodes["per_24h"],
            "mean_delay_minutes_given_detection": agg["mean_detected_delay_minutes"],
            "undetected_fault_ids": agg["undetected_faults"],
            "threshold": reference["threshold"],
            "fit_metadata": reference["model"],
        })
    return {
        "schema_version": 1,
        "benchmark": VERSION,
        "comparison_protocol": baseline["evaluation_protocol"],
        "source_files": baseline["input_files"],
        "rows": rows,
        "baseline_report": baseline,
        "method_parameters_selected_before_held_out_evaluation": True,
        "caveats": [
            "Every monitor uses the same chronological healthy fit/calibration partition and identical test cases.",
            "The monitor-specific empirical threshold targets are not equalized nuisance-alarm episode rates.",
            "CUSUM may accumulate normal drift for long records; it is never reset on each alarm, only at file boundaries.",
            "Calibration and test windows have different lengths; no distribution-free false-alarm guarantee is implied.",
            "Mean detection delay includes detected faults only; early counts and nuisance alarms are essential.",
            "The study reports baseline performance, not optimized state-of-the-art scores or fault diagnosis.",
        ],
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# Tennessee Eastman: causal temporal vs static baseline monitors", "",
        "Fixed method parameters, same healthy-only fit/calibration and the same",
        "21 held-out fault scenarios. **No selection on held-out fault results.**", "",
        "| Monitor | Type | Faults early (60 min) | Eventual | Healthy nuisance episodes | Healthy alarm-active samples | Mean detected delay |",
        "|:--|:--|--:|--:|--:|--:|--:|",
    ]
    for row in report["rows"]:
        delay = row["mean_delay_minutes_given_detection"]
        lines.append(
            f"| {row['method']} | {row['kind']} | "
            f"{row['early_detected']}/{row['faults_evaluated']} | "
            f"{row['eventually_detected']}/{row['faults_evaluated']} | "
            f"{row['healthy_false_alarm_episodes']} | "
            f"{row['healthy_false_alarm_active_samples']} | "
            f"{delay if delay is not None else 'N/A'} min |"
        )
    lines += [
        "", "## Limitations", "",
        "New early detections must be read alongside nuisance-alarm episodes.",
        "A longer CUSUM trace can accumulate harmless nonstationarity; no",
        "automatic alarm reset or physical fault-ID explanation is assumed.",
        "A statistical channel contribution is **not** a validated causal root cause.",
        "The entire per-fault table and input hashes are included in JSON.", "",
        "## Reference source SHA-256", "",
    ]
    for item in report["source_files"]:
        lines.append(f"- {item['source']}: {item['sha256']}")
    lines.append("")
    return "\n".join(lines)


def write_comparison(report: dict, output_dir: str | Path) -> tuple[Path, Path]:
    folder = Path(output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    path_json = folder / "tep_temporal_comparison.json"
    path_md = folder / "tep_temporal_comparison.md"
    path_json.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    path_md.write_text(render_markdown(report), encoding="utf-8")
    return path_json, path_md


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate Page CUSUM/EWMA against fixed reference monitors")
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--faults", type=int, nargs="+", default=list(range(1, 22)))
    parser.add_argument("--alpha", type=float, default=0.01)
    parser.add_argument("--persistence", type=int, default=3)
    parser.add_argument("--early-window-samples", type=int, default=20)
    args = parser.parse_args(argv)
    try:
        report = run_comparison(
            args.data_dir, faults=tuple(args.faults), alpha=args.alpha,
            persistence=args.persistence,
            early_window_samples=args.early_window_samples,
        )
        if args.output_dir:
            path_json, path_md = write_comparison(report, args.output_dir)
            print(f"Reports: {path_json} and {path_md}")
        print(render_markdown(report))
    except (OSError, ValueError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
