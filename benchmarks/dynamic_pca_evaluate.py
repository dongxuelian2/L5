"""Held-out, same-protocol TEP comparison of dynamic and static PCA monitors.

Dynamic PCA parameters (past lags=2, variance target=.90, components<=20)
are fixed *before* running any fault tests; this module never selects a
"winning" lag/threshold based on the observed fault labels.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .evaluate import run_benchmark
from .monitoring import build_monitor, calibrate, persistent_alarms, split_normal_training
from .robustness import alarm_episodes
from .tep import read_tep_dat

VERSION = "tep-dynamic-pca-v1"
METHODS = ("robust-maxz", "pca-q", "pca-t2", "dpca-q-lag2", "dpca-t2-lag2")


def run_comparison(
    data_dir: str | Path, *,
    faults: tuple[int, ...] = tuple(range(1, 22)),
    alpha: float = .01,
    persistence: int = 3,
    onset_sample: int = 160,
    early_window_samples: int = 20,
    fit_fraction: float = .7,
) -> dict:
    """Train and calibrate on normal data only; evaluate the same reference files."""
    canonical = run_benchmark(
        data_dir, faults=faults, methods=METHODS, alpha=alpha,
        persistence=persistence, onset_sample=onset_sample,
        early_window_samples=early_window_samples,
        fit_fraction=fit_fraction,
    )
    root = Path(data_dir)
    fit, normal_cal = split_normal_training(read_tep_dat(root / "d00.dat").rows, fit_fraction)
    heldout_normal = read_tep_dat(root / "d00_te.dat").rows
    rows = []
    for method in METHODS:
        monitor = build_monitor(method)
        monitor.fit(fit)
        limit = calibrate(monitor, normal_cal, alpha)
        baseline = canonical["methods"][method]
        if round(limit, 10) != baseline["threshold"]:
            raise AssertionError("Normal-only threshold changed from canonical benchmark.")
        alarms = persistent_alarms(monitor.score(heldout_normal), limit, persistence)
        episodes = alarm_episodes(alarms, len(alarms))
        agg = baseline["aggregate"]
        if episodes["active_samples"] != agg["healthy_test_false_alarm_samples"]:
            raise AssertionError("Held-out normal alarm-active samples do not match canonical.")
        rows.append({
            "method": method,
            "kind": "dynamic-lag2" if method.startswith("dpca-") else "static",
            "early_detected": agg["faults_detected_early"],
            "eventually_detected": agg["faults_detected"],
            "faults_evaluated": agg["faults_evaluated"],
            "healthy_false_alarm_episodes": episodes["count"],
            "healthy_alarm_active_samples": episodes["active_samples"],
            "healthy_episodes_per_24h": episodes["per_24h"],
            "mean_delay_minutes_given_detection": agg["mean_detected_delay_minutes"],
            "missed_fault_ids": agg["undetected_faults"],
            "normal_calibration_threshold": baseline["threshold"],
            "training_model_metadata": baseline["model"],
            "per_case": baseline["cases"],
        })
    return {
        "schema_version": 1,
        "benchmark": VERSION,
        "methods": list(METHODS),
        "fit_and_test_protocol": canonical["evaluation_protocol"],
        "source_files": canonical["input_files"],
        "parameters_precommitted": {
            "dynamic_lags": 2, "variance_target": .90,
            "maximum_components": 20, "normal_calibration_alpha": alpha,
            "consecutive_alarm_samples": persistence,
            "padding": "normal-fit per-channel mean, no future data",
        },
        "rows": rows,
        "interpretation_limits": [
            "Every model fits and calibrates exclusively on chronological normal d00.dat.",
            "Test trajectory histories are causal, with no future measurements or preceding other-file state.",
            "Lag-augmented Q and T2 scores do not classify fault IDs or establish physical causal root causes.",
            "The same nominal empirical alpha does not equalize false alarm episodes across monitors.",
            "Detection over 800 post-onset samples (~40 h) is not equivalent to detection in 60 minutes.",
            "Result-based method tuning on held-out fault tests is prohibited; negative results are retained.",
            "A single reference dataset is not statistically independent replication of plant operations.",
        ],
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# Tennessee Eastman: causal dynamic PCA vs static baseline", "",
        "Prespecified two-lag DPCA-Q / DPCA-T² against conventional PCA and Max-Z.",
        "Fit/calibration uses healthy training only. No fault-based tuning or selection.", "",
        "| Detector | Kind | Early (60min) | Eventual | Healthy false episodes | Healthy alarm-active samples | Mean detected delay |",
        "|:--|:--|--:|--:|--:|--:|--:|",
    ]
    for row in report["rows"]:
        delay = row["mean_delay_minutes_given_detection"]
        lines.append(
            f"| {row['method']} | {row['kind']} | "
            f"{row['early_detected']}/{row['faults_evaluated']} | "
            f"{row['eventually_detected']}/{row['faults_evaluated']} | "
            f"{row['healthy_false_alarm_episodes']} | "
            f"{row['healthy_alarm_active_samples']} | "
            f"{delay if delay is not None else 'N/A'} min |"
        )
    lines += [
        "", "## Evaluation boundaries", "",
        "The 60-minute hit count should be assessed together with nuisance false",
        "alarm episodes and active samples, not only with eventual detections.",
        "Healthy training uses a chronological fit/calibration split and each",
        "independent test file starts with normal-fit mean history padding.",
        "History-aware statistical feature contributions are not root causes.",
        "", "## Original source checksums", "",
    ]
    for f in report["source_files"]:
        lines.append(f"- {f['source']}: {f['sha256']}")
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict, output_dir: str | Path) -> tuple[Path, Path]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    js, md = target / "tep_dynamic_pca_report.json", target / "tep_dynamic_pca_scoreboard.md"
    js.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    md.write_text(render_markdown(report), encoding="utf-8")
    return js, md


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare fixed causal lag2 DPCA vs reference TEP baselines")
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--faults", type=int, nargs="+", default=list(range(1, 22)))
    parser.add_argument("--alpha", type=float, default=.01)
    parser.add_argument("--persistence", type=int, default=3)
    args = parser.parse_args(argv)
    try:
        report = run_comparison(
            args.data_dir, faults=tuple(args.faults),
            alpha=args.alpha, persistence=args.persistence,
        )
        if args.output_dir:
            paths = write_report(report, args.output_dir)
            print("Reports: " + " and ".join(str(p) for p in paths))
        print(render_markdown(report))
    except (ValueError, OSError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
