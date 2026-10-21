"""Frozen-model TEP stress audit: no fault data or stressors affect training.

Stress perturbations are deterministic artificial challenge settings; their
prevalence and magnitude are not estimates of real industrial disturbances.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path

import numpy as np

from .evaluate import DEFAULT_METHODS, run_benchmark
from .monitoring import as_matrix, build_monitor, calibrate, evaluate_case, persistent_alarms, split_normal_training
from .tep import SAMPLE_SECONDS, VARIABLES, read_tep_dat

VERSION = "tep-robustness-v1"
SCENARIOS = (
    "clean", "loss-xmeas7", "loss-xmeas9",
    "random-missing-05", "noise-20pct", "offset-half-sigma",
)
DESCRIPTIONS = {
    "clean": "Original held-out records",
    "loss-xmeas7": "Entire XMEAS(7) missing; frozen healthy-training median fill",
    "loss-xmeas9": "Entire XMEAS(9) missing; frozen healthy-training median fill",
    "random-missing-05": "5% independently missing cells; frozen healthy-training median fill",
    "noise-20pct": "Added Gaussian noise with std=20% of healthy-training channel std",
    "offset-half-sigma": "All channels shifted by +0.5 healthy-training std",
}


@dataclass(frozen=True)
class Perturbed:
    data: np.ndarray
    missing_cells: int
    total_cells: int
    observed_mask: np.ndarray

    @property
    def missing_fraction(self) -> float:
        return round(self.missing_cells / self.total_cells, 6)


def stable_seed(seed: int, scenario: str, filename: str) -> int:
    material = f"L5/tep-stress-v1/{seed}/{scenario}/{filename}".encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


def apply_stress(
    data: np.ndarray, scenario: str, filename: str, median: np.ndarray, scale: np.ndarray, seed: int
) -> Perturbed:
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown stress scenario: {scenario}")
    measurements = as_matrix(data, features=52).copy()
    if median.shape != (52,) or scale.shape != (52,) or not np.isfinite(median).all():
        raise ValueError("Healthy-fit imputation metadata must contain 52 finite channel medians.")
    if not np.isfinite(scale).all() or np.any(scale <= 0):
        raise ValueError("Healthy-fit channel scales must be positive and finite.")
    missing = np.zeros(measurements.shape, dtype=bool)
    if scenario == "loss-xmeas7":
        missing[:, 6] = True
    elif scenario == "loss-xmeas9":
        missing[:, 8] = True
    elif scenario == "random-missing-05":
        rng = np.random.default_rng(stable_seed(seed, scenario, filename))
        missing = rng.random(measurements.shape) < 0.05
    elif scenario == "noise-20pct":
        rng = np.random.default_rng(stable_seed(seed, scenario, filename))
        measurements += rng.standard_normal(measurements.shape) * (scale * 0.20)
    elif scenario == "offset-half-sigma":
        measurements += scale * 0.5

    if np.any(missing.all(axis=1)):
        raise ValueError("Entirely unobserved rows require explicit abstention, never a healthy prediction.")
    count = int(missing.sum())
    if count:
        measurements[missing] = np.broadcast_to(median, missing.shape)[missing]
    # Preserve original observation validity even after numerical imputation.
    # Consumers making decisions must gate on this mask BEFORE interpreting
    # an imputed statistic as a normal or alarm outcome.
    return Perturbed(measurements, count, int(measurements.size), ~missing)


def alarm_episodes(alarms: tuple[bool, ...], normal_end: int) -> dict:
    """Rising edges in healthy interval; continuous nuisance alarm counts once."""
    if not 0 < normal_end <= len(alarms):
        raise ValueError("Healthy interval must contain at least one sample.")
    starts = [i for i in range(normal_end) if alarms[i] and (i == 0 or not alarms[i-1])]
    lengths = []
    for start in starts:
        end = start + 1
        while end < normal_end and alarms[end]:
            end += 1
        lengths.append(end - start)
    hours = normal_end * SAMPLE_SECONDS / 3600
    return {
        "count": len(starts),
        "per_24h": round(24 * len(starts) / hours, 6),
        "active_samples": int(sum(alarms[:normal_end])),
        "longest_duration_samples": max(lengths, default=0),
    }


def run_robustness(
    data_dir: str | Path, *,
    faults: tuple[int, ...] = tuple(range(1, 22)),
    methods: tuple[str, ...] = DEFAULT_METHODS,
    scenarios: tuple[str, ...] = SCENARIOS,
    seed: int = 20261021,
    fit_fraction: float = 0.7,
    alpha: float = 0.01,
    persistence: int = 3,
    onset_sample: int = 160,
    early_window_samples: int = 20,
) -> dict:
    if not scenarios or len(set(scenarios)) != len(scenarios):
        raise ValueError("Scenarios must be nonempty and distinct.")
    if any(scenario not in SCENARIOS for scenario in scenarios) or "clean" not in scenarios:
        raise ValueError("Scenarios must be supported and must contain clean.")
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        raise ValueError("Stress seed must be a nonnegative integer.")

    # Canonical validation and clean metrics remain the source of truth.
    baseline = run_benchmark(
        data_dir, faults=faults, methods=methods, fit_fraction=fit_fraction,
        alpha=alpha, persistence=persistence, onset_sample=onset_sample,
        early_window_samples=early_window_samples,
    )
    directory = Path(data_dir)
    fit, calibration = split_normal_training(read_tep_dat(directory / "d00.dat").rows, fit_fraction)
    median = np.median(fit, axis=0)
    std = np.maximum(fit.std(axis=0, ddof=1), 1e-10)
    filenames = ["d00_te.dat", *[f"d{i:02d}_te.dat" for i in sorted(faults)]]
    originals = {
        name: as_matrix(read_tep_dat(directory / name).rows, features=52)
        for name in filenames
    }
    fitted = {}
    for name in methods:
        model = build_monitor(name)
        model.fit(fit)
        threshold = calibrate(model, calibration, alpha)
        if round(threshold, 10) != baseline["methods"][name]["threshold"]:
            raise AssertionError("Frozen threshold differs from the canonical clean baseline.")
        fitted[name] = (model, threshold)

    report = {
        "schema_version": 1,
        "benchmark": VERSION,
        "baseline_benchmark": baseline["benchmark"],
        "base_protocol": baseline["evaluation_protocol"],
        "input_files": baseline["input_files"],
        "seed": seed,
        "conditions": {name: DESCRIPTIONS[name] for name in scenarios},
        "imputation": "median from normal fit partition; no calibration or test data",
        "thresholds": "frozen, calibrated on unmodified normal calibration partition",
        "scenario_results": {},
        "limitations": [
            "Stressors are artificial, not measured plant disturbance distributions.",
            "Perturbations affect both healthy and fault tests, never training/calibration.",
            "No test-time retuning, labels in features, or sensor adaptation.",
            "Median imputation can mask real faults and distort multivariate relationships.",
            "Wholly unobserved samples fail rather than masquerading as healthy observations.",
            "Anomaly detection is not fault-type diagnosis or safe actuation.",
        ],
    }
    for scenario in scenarios:
        transformed = {
            name: apply_stress(originals[name], scenario, name, median, std, seed)
            for name in filenames
        }
        results = {}
        for method, (monitor, threshold) in fitted.items():
            cases = []
            for name in filenames:
                item = transformed[name]
                fault_id = int(name[1:3])
                onset = None if fault_id == 0 else onset_sample
                metrics = evaluate_case(
                    source=name, fault_id=fault_id, samples=item.data,
                    monitor=monitor, threshold=threshold, consecutive=persistence,
                    feature_names=VARIABLES, onset_sample=onset,
                    seconds_per_sample=SAMPLE_SECONDS,
                    early_window_samples=early_window_samples,
                )
                alarms = persistent_alarms(monitor.score(item.data), threshold, persistence)
                episodes = alarm_episodes(alarms, len(item.data) if onset is None else onset)
                cases.append({
                    **asdict(metrics),
                    "normal_false_alarm_episodes": episodes["count"],
                    "normal_false_alarm_episodes_per_24h": episodes["per_24h"],
                    "normal_longest_false_alarm_episode_samples": episodes["longest_duration_samples"],
                    "missing_cells": item.missing_cells,
                    "missing_fraction": item.missing_fraction,
                })
            if scenario == "clean":
                for expected, actual in zip(baseline["methods"][method]["cases"], cases):
                    if any(actual[key] != value for key, value in expected.items()):
                        raise AssertionError("Clean stress-case metrics differ from the canonical benchmark.")
            normal = cases[0]
            results[method] = {
                "threshold": round(threshold, 10),
                "faults_evaluated": len(faults),
                "early_detected": sum(c["detected_within_early_window"] is True for c in cases[1:]),
                "eventually_detected": sum(c["detected_after_onset"] is True for c in cases[1:]),
                "healthy_false_alarm_active_sample_fraction": normal["false_alarm_rate"],
                "healthy_false_alarm_episodes": normal["normal_false_alarm_episodes"],
                "healthy_false_alarm_episodes_per_24h": normal["normal_false_alarm_episodes_per_24h"],
                "cases": cases,
            }
        report["scenario_results"][scenario] = results
    clean = report["scenario_results"]["clean"]
    for methods_result in report["scenario_results"].values():
        for method, metrics in methods_result.items():
            metrics["delta_early_vs_clean"] = metrics["early_detected"] - clean[method]["early_detected"]
            metrics["delta_healthy_episodes_vs_clean"] = (
                metrics["healthy_false_alarm_episodes"] - clean[method]["healthy_false_alarm_episodes"]
            )
    return report


def render_markdown(report: dict) -> str:
    lines = [
        "# Tennessee Eastman: frozen-model robustness audit", "",
        "Artificial test-time perturbations; no retuning on faults or stressed tests.", "",
        "| Scenario | Method | Early detected | Delta early | Healthy false episodes | Delta episodes | Episodes/24h |",
        "|:--|:--|--:|--:|--:|--:|--:|",
    ]
    for scenario, results in report["scenario_results"].items():
        for method, stats in results.items():
            lines.append(
                f"| {scenario} | {method} | {stats['early_detected']}/{stats['faults_evaluated']} | "
                f"{stats['delta_early_vs_clean']:+d} | {stats['healthy_false_alarm_episodes']} | "
                f"{stats['delta_healthy_episodes_vs_clean']:+d} | "
                f"{stats['healthy_false_alarm_episodes_per_24h']} |"
            )
    lines.extend([
        "", "Each episode is one alarm rising edge in the healthy test interval.",
        "The active-sample false-alarm fraction and per-fault results are in JSON.",
        "An eventual alert within 40 hours is not equivalent to early detection.",
        "", "## Synthetic stress definitions", "",
    ])
    for name, description in report["conditions"].items():
        lines.append(f"- {name}: {description}")
    lines.extend(["", "## Original reference data SHA-256", ""])
    for item in report["input_files"]:
        lines.append(f"- {item['source']}: {item['sha256']}")
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict, output_dir: str | Path) -> tuple[Path, Path]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    js, md = target / "tep_robustness_report.json", target / "tep_robustness_scoreboard.md"
    js.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    md.write_text(render_markdown(report), encoding="utf-8")
    return js, md


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Frozen-model TEP corruption stress evaluation")
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--faults", type=int, nargs="+", default=list(range(1, 22)))
    parser.add_argument("--methods", nargs="+", choices=DEFAULT_METHODS, default=list(DEFAULT_METHODS))
    parser.add_argument("--scenarios", nargs="+", choices=SCENARIOS, default=list(SCENARIOS))
    parser.add_argument("--seed", type=int, default=20261021)
    args = parser.parse_args(argv)
    try:
        report = run_robustness(
            args.data_dir, faults=tuple(args.faults), methods=tuple(args.methods),
            scenarios=tuple(args.scenarios), seed=args.seed,
        )
        if args.output_dir:
            paths = write_report(report, args.output_dir)
            print("Reports: " + " and ".join(str(path) for path in paths))
    except (OSError, ValueError) as error:
        parser.error(str(error))
    for scenario, results in report["scenario_results"].items():
        print(scenario)
        for name, stats in results.items():
            print(
                f"  {name}: early {stats['early_detected']}/{stats['faults_evaluated']}, "
                f"healthy false episodes {stats['healthy_false_alarm_episodes']}, "
                f"delta early {stats['delta_early_vs_clean']:+d}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
