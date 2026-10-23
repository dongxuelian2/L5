"""TEP normal-only temporal validation and predeclared alarm-workload budgets.

This is NOT a new independent process dataset. Both chronological folds
reuse overlapping segments of the SAME d00.dat normal trajectory. The
external d00_te.dat is a separate reference *file*, not verified to be an
independent plant realization. Fault labels and both held-out test file
families cannot influence model fitting, thresholding or budget selection.

The primary budget is fixed before examining any fault outcomes:
at most one confirmed normal-calibration alarm episode and at most 2%
normal-calibration alarm-active samples, with three-sample persistence.
Choose the LEAST restrictive observed calibration-score threshold
satisfying both constraints. It does not guarantee matching held-out
healthy nuisance alarms; always report that measured burden separately.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path

import numpy as np

from .monitoring import (
    as_matrix, build_monitor, calibrate, checksum, evaluate_case,
    persistent_alarms,
)
from .robustness import alarm_episodes
from .tep import SAMPLE_SECONDS, VARIABLES, read_tep_dat

VERSION = "tep-normal-only-budget-validation-v1"
METHODS = ("robust-maxz", "pca-q", "pca-t2", "dpca-q-lag2", "dpca-t2-lag2")
POLICIES = ("fixed-alpha-01", "calibration-1episode-2pct-active")
# Nested, overlapping forward-chronological folds, NOT independent samples.
# With a 480-point dataset, final fold validation ends at index 480.
FOLDS = (
    ("forward-A", 250, 350, 425),
    ("forward-B", 300, 400, 500),
)
CALIBRATION_MAX_EPISODES = 1
CALIBRATION_MAX_ACTIVE_FRACTION = .02


def calibration_budget_threshold(
    scores: np.ndarray, *, persistence: int = 3,
    max_episodes: int = CALIBRATION_MAX_EPISODES,
    max_active_fraction: float = CALIBRATION_MAX_ACTIVE_FRACTION,
) -> float:
    """Normal-calibration-only deterministic constrained threshold.

    Return the smallest score level such that strict > threshold gives
    <=max_episodes confirmed alarm *starts* and <=floor(N*fraction)
    confirmed alarm-active points. This is an observed-score candidate
    selection, not interpolation or test-set optimization.
    """
    series = np.asarray(scores, dtype=float)
    if series.ndim != 1 or len(series) < 30 or not np.isfinite(series).all():
        raise ValueError("Need a finite one-dimensional normal calibration series of at least 30.")
    if not isinstance(persistence, int) or isinstance(persistence, bool) or persistence < 1:
        raise ValueError("Persistence must be a positive integer.")
    if not isinstance(max_episodes, int) or isinstance(max_episodes, bool) or max_episodes < 0:
        raise ValueError("Episode budget must be a nonnegative integer.")
    if not math.isfinite(max_active_fraction) or not 0 <= max_active_fraction < 1:
        raise ValueError("Active-sample budget fraction must be finite and in [0,1).")
    max_active = math.floor(len(series) * max_active_fraction)
    for threshold in np.unique(series):
        alarms = persistent_alarms(series, float(threshold), persistence)
        episodes = alarm_episodes(alarms, len(series))
        if episodes["count"] <= max_episodes and episodes["active_samples"] <= max_active:
            return float(threshold)
    raise AssertionError("No feasible normal-only budget threshold; maximum must always have zero exceedances.")


def _alarm_workload(scores: np.ndarray, threshold: float, persistence: int) -> dict:
    alarms = persistent_alarms(scores, threshold, persistence)
    episode = alarm_episodes(alarms, len(alarms))
    return {
        "episodes": episode["count"],
        "alarm_active_samples": episode["active_samples"],
        "longest_alarm_run_samples": episode["longest_duration_samples"],
        "observations": len(alarms),
        "alarm_active_fraction": round(episode["active_samples"] / len(alarms), 6),
        "episodes_per_24h": episode["per_24h"],
    }


def _normal_folds(length: int) -> list[tuple[str, int, int, int]]:
    if length not in (480, 500):
        raise ValueError("Normal training reference must contain exactly 480 or 500 observations.")
    return [(name, fit, cal, min(stop, length)) for name, fit, cal, stop in FOLDS]


def run_validation(
    data_dir: str | Path, *,
    faults: tuple[int, ...] = tuple(range(1, 22)),
    methods: tuple[str, ...] = METHODS,
    policies: tuple[str, ...] = POLICIES,
    persistence: int = 3,
    alpha: float = .01,
    onset_sample: int = 160,
    early_window_samples: int = 20,
) -> dict:
    if not faults or len(set(faults)) != len(faults) or any(
        not isinstance(i, int) or isinstance(i, bool) or i < 1 or i > 21 for i in faults
    ):
        raise ValueError("Use distinct fault IDs in 1..21.")
    if not methods or len(set(methods)) != len(methods) or any(x not in METHODS for x in methods):
        raise ValueError("Use distinct prespecified monitors.")
    if not policies or len(set(policies)) != len(policies) or any(x not in POLICIES for x in policies):
        raise ValueError("Use distinct prespecified calibration policies.")
    if persistence < 1 or not 0 < alpha < .5 or not 0 < onset_sample < 960 or early_window_samples < 1:
        raise ValueError("Invalid predeclared evaluation protocol.")
    directory = Path(data_dir)
    filenames = ["d00.dat", "d00_te.dat", *[f"d{i:02d}_te.dat" for i in sorted(faults)]]
    if any(not (directory / filename).is_file() for filename in filenames):
        raise ValueError("Missing required TEP DAT input file.")
    datasets = {name: read_tep_dat(directory / name) for name in filenames}
    normal_fit = as_matrix(datasets["d00.dat"].rows, features=52)
    folds = _normal_folds(len(normal_fit))
    for name in filenames[1:]:
        if len(datasets[name].rows) != 960:
            raise ValueError(f"Expected 960 held-out test samples in {name}.")
    tests = {name: as_matrix(datasets[name].rows, features=52) for name in filenames[1:]}
    inputs = [{
        **datasets[name].summary(),
        "sha256": checksum(directory / name),
        "usage": "nested_forward_normal_fit_calibration_validation" if name == "d00.dat"
                 else "read_only_external_evaluation",
    } for name in filenames]
    report = {
        "schema_version": 1,
        "benchmark": VERSION,
        "data_provenance": inputs,
        "folds": [{
            "name": name,
            "fit": [0, fit_end],
            "calibration": [fit_end, cal_end],
            "normal_validation": [cal_end, val_end],
        } for name, fit_end, cal_end, val_end in folds],
        "methods": list(methods),
        "policies": list(policies),
        "budget": {
            "maximum_calibration_confirmed_episodes": CALIBRATION_MAX_EPISODES,
            "maximum_calibration_alarm_active_fraction": CALIBRATION_MAX_ACTIVE_FRACTION,
            "threshold_selection": "smallest observed calibration score satisfying both caps",
            "fixed_quantile_alpha": alpha,
            "confirmed_alarm_consecutive_samples": persistence,
        },
        "assumed_fault_onset": onset_sample,
        "early_window_samples": early_window_samples,
        "sample_seconds": SAMPLE_SECONDS,
        "rows": [],
        "paired_vs_maxz": [],
        "limitations": [
            "Two forward chronological folds overlap in the same normal-training trajectory; they are not independent replicates.",
            "d00_te.dat is a separate external normal test FILE, not evidence of independent plant trajectories or operating regimes.",
            "An equal cap on healthy CALIBRATION episodes/active samples does not imply equal realized held-out healthy-test workload.",
            "The short calibration sections (~100 observations) provide weak guarantees about the 960-sample normal test.",
            "DPCA uses normal-fit-only lag padding and resets per separate calibration, validation or test sequence.",
            "All threshold parameters and fold boundaries were set before examining any fault labels.",
            "The same set of 21 held-out fault trajectories is reused in both folds; no independent confidence interval follows.",
            "Mean delay conditional on detection can improve when difficult cases are missed; compare full fault hit counts.",
            "Alarm episodes and active sample burden both matter. No superiority or deployment safety claim follows.",
        ],
    }
    for fold_name, fit_end, cal_end, val_end in folds:
        fit = normal_fit[:fit_end]
        cal = normal_fit[fit_end:cal_end]
        validation = normal_fit[cal_end:val_end]
        if len(cal) < 30 or len(validation) < 30:
            raise AssertionError("Insufficient chronological normal-only calibration/validation observations.")
        for method in methods:
            detector = build_monitor(method)
            detector.fit(fit)
            calibration_scores = detector.score(cal)
            fixed_threshold = calibrate(detector, cal, alpha)
            budget_threshold = calibration_budget_threshold(
                calibration_scores, persistence=persistence
            )
            if not np.isfinite(fixed_threshold) or not np.isfinite(budget_threshold):
                raise AssertionError("Non-finite normal-only calibration thresholds.")
            for policy in policies:
                threshold = (fixed_threshold if policy == "fixed-alpha-01" else budget_threshold)
                cal_workload = _alarm_workload(calibration_scores, threshold, persistence)
                if policy != "fixed-alpha-01":
                    if cal_workload["episodes"] > CALIBRATION_MAX_EPISODES or cal_workload["alarm_active_fraction"] > CALIBRATION_MAX_ACTIVE_FRACTION:
                        raise AssertionError("Normal-calibration budget exceeded.")
                val_workload = _alarm_workload(detector.score(validation), threshold, persistence)
                healthy_workload = _alarm_workload(detector.score(tests["d00_te.dat"]), threshold, persistence)
                cases = [
                    asdict(evaluate_case(
                        source=name, fault_id=int(name[1:3]), samples=tests[name],
                        monitor=detector, threshold=threshold,
                        consecutive=persistence, feature_names=VARIABLES,
                        onset_sample=onset_sample, seconds_per_sample=SAMPLE_SECONDS,
                        early_window_samples=early_window_samples,
                    ))
                    for name in filenames[2:]
                ]
                early_ids = [case["fault_id"] for case in cases if case["detected_within_early_window"] is True]
                eventual_ids = [case["fault_id"] for case in cases if case["detected_after_onset"] is True]
                delays = [case["detection_delay_minutes"] for case in cases if case["detection_delay_minutes"] is not None]
                report["rows"].append({
                    "fold": fold_name,
                    "method": method,
                    "policy": policy,
                    "threshold": round(threshold, 10),
                    "training_metadata": detector.metadata(),
                    "normal_calibration_workload": cal_workload,
                    "normal_forward_validation_workload": val_workload,
                    "external_healthy_test_workload": healthy_workload,
                    "early_detected": len(early_ids),
                    "eventually_detected": len(eventual_ids),
                    "faults_evaluated": len(faults),
                    "early_hit_fault_ids": early_ids,
                    "eventually_hit_fault_ids": eventual_ids,
                    "mean_detected_delay_minutes": round(sum(delays) / len(delays), 3) if delays else None,
                    "per_fault": cases,
                })
    # Post-hoc descriptive pairing on identical fault IDs. No parameter
    # selection, winner announcement, or optimization derives from this.
    for fold_name, *_ in folds:
        for policy in policies:
            baseline = next((r for r in report["rows"]
                             if r["fold"] == fold_name and r["policy"] == policy
                             and r["method"] == "robust-maxz"), None)
            if baseline is None:
                continue
            reference_hits = set(baseline["early_hit_fault_ids"])
            for row in report["rows"]:
                if row["fold"] != fold_name or row["policy"] != policy or row["method"] == "robust-maxz":
                    continue
                hits = set(row["early_hit_fault_ids"])
                report["paired_vs_maxz"].append({
                    "fold": fold_name,
                    "policy": policy,
                    "method": row["method"],
                    "early_hit_gained_fault_ids": sorted(hits - reference_hits),
                    "early_hit_lost_fault_ids": sorted(reference_hits - hits),
                    "early_hit_net_delta": len(hits) - len(reference_hits),
                    "external_healthy_episode_delta": row["external_healthy_test_workload"]["episodes"] -
                                                     baseline["external_healthy_test_workload"]["episodes"],
                    "external_healthy_active_sample_delta": row["external_healthy_test_workload"]["alarm_active_samples"] -
                                                           baseline["external_healthy_test_workload"]["alarm_active_samples"],
                })
    return report


def render_markdown(report: dict) -> str:
    lines = [
        "# TEP: predeclared normal-only calibration workload and forward validation",
        "",
        "Two **overlapping folds from one normal trajectory**. External d00_te.dat",
        "is a distinct file, not verified independent plant operation. No test-based tuning.",
        "",
        "The workload caps (<=1 calibration event, <=2% calibration active samples)",
        "are NOT claimed to hold on the separate normal test file.",
        "",
        "| Forward fold | Cal policy | Detector | Cal episodes / active | Validation episodes / active | External healthy episodes / active | Faults early / total |",
        "|:--|:--|:--|:--|:--|:--|--:|",
    ]
    for row in report["rows"]:
        def fmt(k):
            work = row[k]
            return f"{work['episodes']} / {work['alarm_active_samples']}"
        lines.append(
            f"| {row['fold']} | {row['policy']} | {row['method']} | "
            f"{fmt('normal_calibration_workload')} | "
            f"{fmt('normal_forward_validation_workload')} | "
            f"{fmt('external_healthy_test_workload')} | "
            f"{row['early_detected']}/{row['faults_evaluated']} |"
        )
    lines.extend([
        "",
        "## Per-fault paired early detections vs Max-Z",
        "",
        "| Fold | Policy | Detector | Gained fault IDs | Lost fault IDs | Early hit net difference |",
        "|:--|:--|:--|:--|:--|--:|",
    ])
    for row in report["paired_vs_maxz"]:
        lines.append(
            f"| {row['fold']} | {row['policy']} | {row['method']} | "
            f"{','.join(map(str,row['early_hit_gained_fault_ids'])) or '-'} | "
            f"{','.join(map(str,row['early_hit_lost_fault_ids'])) or '-'} | "
            f"{row['early_hit_net_delta']:+d} |"
        )
    lines += ["", "## Source SHA-256", ""]
    for file in report["data_provenance"]:
        lines.append(f"- {file['source']}: {file['sha256']}")
    lines += ["", "## Limits", ""]
    for limit in report["limitations"]:
        lines.append("- " + limit)
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict, output_dir: str | Path) -> tuple[Path, Path]:
    folder = Path(output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    js = folder / "tep_normal_budget_validation.json"
    md = folder / "tep_normal_budget_scoreboard.md"
    js.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    md.write_text(render_markdown(report), encoding="utf-8")
    return js, md


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Normal-only forward TEP validation and predeclared calibration alarm budgets")
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--faults", nargs="+", type=int, default=list(range(1, 22)))
    parser.add_argument("--methods", nargs="+", choices=METHODS, default=list(METHODS))
    parser.add_argument("--policies", nargs="+", choices=POLICIES, default=list(POLICIES))
    args = parser.parse_args(argv)
    try:
        report = run_validation(
            args.data_dir, faults=tuple(args.faults),
            methods=tuple(args.methods), policies=tuple(args.policies),
        )
        if args.output_dir:
            paths = write_report(report, args.output_dir)
            print("Reports: " + " and ".join(str(p) for p in paths))
        print(render_markdown(report))
    except (OSError, ValueError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
