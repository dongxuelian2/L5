"""Predeclared fixed-calibration workload comparison of classical and bounded CUSUM.

Comparisons are made under two *predeclared* calibration policies:
  1. original healthy-calibration 99th-percentile threshold (alpha=.01),
  2. a threshold admitting ZERO confirmed alarm episodes in the held-out
     *healthy training calibration* segment, not on the test set.

Neither policy guarantees matching nuisance episodes on the separate 960-
sample healthy reference test. There is no test-optimal threshold selection.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path

import numpy as np

from .evaluate import run_benchmark
from .monitoring import (
    as_matrix, build_monitor, calibrate, evaluate_case, persistent_alarms,
    split_normal_training,
)
from .robustness import alarm_episodes
from .tep import SAMPLE_SECONDS, VARIABLES, read_tep_dat

VERSION = "tep-bounded-cusum-v1"
METHODS = (
    "robust-maxz", "pca-q", "pca-t2",
    "cusum-maxz", "ewma-maxz", "window-cusum-12", "window-cusum-24",
)


def zero_episode_calibration(
    scores: np.ndarray, base_threshold: float, persistence: int
) -> float:
    """Raise an empirical threshold using *healthy calibration only*.

    For confirmed alarms to be impossible in this normal-calibration segment,
    threshold >= max over all length-persistence rolling minimum scores.
    Strict > is used for alarms. A short normal sample offers no guarantee
    on an independent, longer test segment or under distribution shift.
    """
    s = np.asarray(scores, dtype=float)
    if s.ndim != 1 or len(s) < 30 or not np.isfinite(s).all():
        raise ValueError("Need a finite one-dimensional 30+ sample calibration score series.")
    if persistence < 1 or persistence > len(s):
        raise ValueError("Persistence must be positive and no longer than calibration.")
    if not math.isfinite(base_threshold):
        raise ValueError("Base calibration threshold must be finite.")
    rolling_low = max(
        float(np.min(s[i + 1 - persistence:i + 1]))
        for i in range(persistence - 1, len(s))
    )
    threshold = max(float(base_threshold), rolling_low)
    if any(persistent_alarms(s, threshold, persistence)):
        raise AssertionError("Calibration workload policy failed on healthy data.")
    return threshold


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
        data_dir, faults=faults, methods=METHODS, alpha=alpha,
        persistence=persistence, onset_sample=onset_sample,
        early_window_samples=early_window_samples, fit_fraction=fit_fraction,
    )
    root = Path(data_dir)
    fit, cal = split_normal_training(read_tep_dat(root / "d00.dat").rows, fit_fraction)
    sources = ["d00_te.dat", *(f"d{i:02d}_te.dat" for i in sorted(faults))]
    samples = {name: as_matrix(read_tep_dat(root / name).rows, features=len(VARIABLES))
               for name in sources}
    rows = []
    for method in METHODS:
        monitor = build_monitor(method)
        monitor.fit(fit)
        calibration_scores = monitor.score(cal)
        threshold_quantile = calibrate(monitor, cal, alpha)
        threshold_budget = zero_episode_calibration(calibration_scores, threshold_quantile, persistence)
        original = baseline["methods"][method]
        if round(threshold_quantile, 10) != original["threshold"]:
            raise AssertionError("Quantile threshold differs from previous unchanged benchmark.")
        for policy, threshold in (
            ("quantile-alpha-01", threshold_quantile),
            ("healthy-calibration-zero-episodes", threshold_budget),
        ):
            individual = []
            for name, data in samples.items():
                fault_id = int(name[1:3])
                onset = None if fault_id == 0 else onset_sample
                metrics = evaluate_case(
                    source=name, fault_id=fault_id, samples=data,
                    monitor=monitor, threshold=threshold,
                    consecutive=persistence, feature_names=VARIABLES,
                    onset_sample=onset, seconds_per_sample=SAMPLE_SECONDS,
                    early_window_samples=early_window_samples,
                )
                alarm = persistent_alarms(monitor.score(data), threshold, persistence)
                episodes = alarm_episodes(alarm, len(data) if onset is None else onset)
                individual.append({
                    **asdict(metrics),
                    "false_alarm_episodes_in_healthy_prefix": episodes["count"],
                    "false_alarm_episodes_per_24h": episodes["per_24h"],
                    "false_alarm_longest_run_samples": episodes["longest_duration_samples"],
                })
                if policy == "quantile-alpha-01":
                    original_case = next(x for x in original["cases"] if x["source"] == name)
                    for key, value in original_case.items():
                        if individual[-1][key] != value:
                            raise AssertionError("Quantile policy changed established reference metrics.")
            healthy = individual[0]
            faulty = individual[1:]
            rows.append({
                "method": method,
                "threshold_policy": policy,
                "calibration_threshold": round(threshold, 10),
                "healthy_calibration_episodes": alarm_episodes(
                    persistent_alarms(calibration_scores, threshold, persistence),
                    len(calibration_scores),
                )["count"],
                "healthy_test_false_alarm_episodes": healthy["false_alarm_episodes_in_healthy_prefix"],
                "healthy_test_alarm_active_samples": healthy["false_alarm_samples"],
                "healthy_test_longest_false_alarm_run_samples": healthy["false_alarm_longest_run_samples"],
                "early_detected": sum(x["detected_within_early_window"] is True for x in faulty),
                "eventually_detected": sum(x["detected_after_onset"] is True for x in faulty),
                "faults_evaluated": len(faulty),
                "missed_fault_ids": [x["fault_id"] for x in faulty if not x["detected_after_onset"]],
                "per_fault": individual,
            })
    return {
        "schema_version": 1,
        "benchmark": VERSION,
        "source_files": baseline["input_files"],
        "evaluation_protocol": baseline["evaluation_protocol"],
        "precommitted_windows_samples": [12, 24],
        "precommitted_reference_drift": 0.5,
        "healthy_calibration_episode_target": 0,
        "baseline_alpha": alpha,
        "methods": list(METHODS),
        "rows": rows,
        "caveats": [
            "Both threshold policies use the healthy calibration segment only; neither uses test fault labels.",
            "Zero episodes in the short healthy calibration segment is not an independent healthy-test workload guarantee.",
            "Nominally equal calibration alarm budgets do not imply equal realized healthy-test episodes.",
            "CUSUM's long-held alarm state is counted in active alarm samples, not hidden by episode counts.",
            "Windowed CUSUM observes at most the previous 12/24 samples (36/72 min) and restarts at each file boundary.",
            "Models and candidate windows were predeclared before inspecting the held-out fault scores.",
            "No test-set-tuned winner is selected; monitoring alarms are not fault diagnosis or safe physical actuation.",
        ],
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# Tennessee Eastman: bounded-history CUSUM and calibration workload", "",
        "Same normal-only train/calibration files and 21 held-out fault records;",
        "two precommitted thresholds per monitor. No choice of a held-out winner.", "",
        "| Calibration policy | Detector | Early / faults | Eventual / faults | Calibration episodes | Healthy test episodes | Healthy test alarm-active samples |",
        "|:--|:--|--:|--:|--:|--:|--:|",
    ]
    for row in report["rows"]:
        lines.append(
            f"| {row['threshold_policy']} | {row['method']} | "
            f"{row['early_detected']}/{row['faults_evaluated']} | "
            f"{row['eventually_detected']}/{row['faults_evaluated']} | "
            f"{row['healthy_calibration_episodes']} | "
            f"{row['healthy_test_false_alarm_episodes']} | "
            f"{row['healthy_test_alarm_active_samples']} |"
        )
    lines.extend([
        "", "Zero calibration alarm episodes do not ensure zero held-out normal",
        "episodes. Longer healthy-test sequences may expose shifts and",
        "temporal accumulation invisible in the brief calibration set.",
        "See JSON for all source hashes, thresholds and per-fault outcomes.",
        "", "## Input SHA-256", "",
    ])
    for item in report["source_files"]:
        lines.append(f"- {item['source']}: {item['sha256']}")
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict, output_dir: str | Path) -> tuple[Path, Path]:
    dest = Path(output_dir)
    dest.mkdir(parents=True, exist_ok=True)
    js = dest / "tep_bounded_cusum_report.json"
    md = dest / "tep_bounded_cusum_scoreboard.md"
    js.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    md.write_text(render_markdown(report), encoding="utf-8")
    return js, md


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare finite-window CUSUM under fixed normal calibration budgets")
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--faults", type=int, nargs="+", default=list(range(1, 22)))
    parser.add_argument("--alpha", type=float, default=0.01)
    args = parser.parse_args(argv)
    try:
        result = run_comparison(args.data_dir, faults=tuple(args.faults), alpha=args.alpha)
        if args.output_dir:
            output = write_report(result, args.output_dir)
            print("Reports: " + ", ".join(str(x) for x in output))
        print(render_markdown(result))
    except (OSError, ValueError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
