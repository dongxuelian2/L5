"""Coverage-aware decision interface for held-out Tennessee Eastman stress tests.

Three possible observations: normal, alarm and abstain. An imputed sample
must *never* acquire a seemingly valid normal classification when required
channels are missing. Abstentions reset alarm persistence.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path

import numpy as np

from .evaluate import DEFAULT_METHODS, run_benchmark
from .monitoring import (
    as_matrix, build_monitor, calibrate, evaluate_case,
    persistent_alarms, split_normal_training,
)
from .robustness import SCENARIOS, Perturbed, apply_stress
from .tep import SAMPLE_SECONDS, VARIABLES, read_tep_dat

NORMAL = "normal"
ALARM = "alarm"
ABSTAIN = "abstain"
DEFAULT_SCENARIOS = SCENARIOS + ("blackout-15samples",)
VERSION = "tep-coverage-gate-v1"


@dataclass(frozen=True)
class CoveragePolicy:
    min_observed_fraction: float = 0.90
    required_channels: tuple[str, ...] = ("xmeas_7", "xmeas_9")

    def __post_init__(self):
        if not math.isfinite(self.min_observed_fraction) or not 0 < self.min_observed_fraction <= 1:
            raise ValueError("min_observed_fraction must be in (0, 1].")
        if len(set(self.required_channels)) != len(self.required_channels):
            raise ValueError("Required channels must be unique.")
        if any(name not in VARIABLES for name in self.required_channels):
            raise ValueError("Required channels must use canonical TEP feature names.")

    def public_metadata(self) -> dict:
        # JSON round-trips should retain stable types rather than a tuple.
        return {
            "min_observed_fraction": self.min_observed_fraction,
            "required_channels": list(self.required_channels),
        }


def decide(
    scores: np.ndarray,
    observed_mask: np.ndarray,
    *,
    threshold: float,
    consecutive: int,
    policy: CoveragePolicy,
) -> tuple[str, ...]:
    """Gate score interpretation by original validity, not imputed values.

    On loss of coverage return ABSTAIN and reset pending consecutive alarms.
    On restoration the persistence counter starts from zero, avoiding stale
    alarm state before the observation gap.
    """
    scores = np.asarray(scores, dtype=float)
    mask = np.asarray(observed_mask)
    if scores.ndim != 1 or mask.ndim != 2 or len(scores) != len(mask):
        raise ValueError("Expected one score and one observed-feature mask per sample.")
    if mask.shape[1] != len(VARIABLES) or mask.dtype != np.bool_:
        raise ValueError("Observation mask must be Boolean with exactly 52 TEP features.")
    if not np.isfinite(scores).all() or not math.isfinite(threshold):
        raise ValueError("Scores and decision threshold must be finite.")
    if not isinstance(consecutive, int) or isinstance(consecutive, bool) or consecutive < 1:
        raise ValueError("consecutive must be positive.")
    critical = [VARIABLES.index(name) for name in policy.required_channels]
    states: list[str] = []
    run = 0
    for score, row in zip(scores, mask):
        valid = row.mean() >= policy.min_observed_fraction and all(row[i] for i in critical)
        if not valid:
            run = 0
            states.append(ABSTAIN)
        else:
            run = run + 1 if score > threshold else 0
            states.append(ALARM if run >= consecutive else NORMAL)
    return tuple(states)


def score_with_observation_resets(
    monitor,
    values: np.ndarray,
    original_mask: np.ndarray,
    policy: CoveragePolicy,
) -> np.ndarray:
    """Restart temporal history after abstained rows, never on imputed data.

    Static detectors can still score all imputed rows, but the decision gate
    makes invalid rows abstentions. Temporal detectors must *not* ingest a
    missing row as a valid zero-ish value or carry history across it.
    """
    data = as_matrix(values, features=len(VARIABLES))
    observed = np.asarray(original_mask)
    if observed.dtype != np.bool_ or observed.shape != data.shape:
        raise ValueError("Observation mask must be Boolean and feature-aligned.")
    if not getattr(monitor, 'history_dependent', False):
        return monitor.score(data)
    required = [VARIABLES.index(name) for name in policy.required_channels]
    valid = np.mean(observed, axis=1) >= policy.min_observed_fraction
    if required:
        valid &= np.all(observed[:, required], axis=1)
    scores = np.zeros(len(data), dtype=float)
    start = 0
    while start < len(data):
        if not valid[start]:
            start += 1
            continue
        end = start + 1
        while end < len(data) and valid[end]:
            end += 1
        scores[start:end] = monitor.score(data[start:end])
        start = end
    return scores


def observation_summary(
    states: tuple[str, ...],
    *,
    onset_sample: int | None,
    early_window_samples: int = 20,
) -> dict:
    """Report both alarm workload and observation coverage; never count abstain as normal."""
    if not states or any(s not in (NORMAL, ALARM, ABSTAIN) for s in states):
        raise ValueError("Decision stream must contain only valid three-state decisions.")
    if onset_sample is not None and not 0 < onset_sample < len(states):
        raise ValueError("Fault onset must lie within the decision stream.")
    if early_window_samples < 1:
        raise ValueError("Early window must contain at least one sample.")
    normal_end = len(states) if onset_sample is None else onset_sample
    normal = states[:normal_end]
    available = sum(s != ABSTAIN for s in normal)
    false_alarms = sum(s == ALARM for s in normal)
    episodes = sum(
        state == ALARM and (i == 0 or states[i - 1] != ALARM)
        for i, state in enumerate(normal)
    )
    starts = [i for i in range(normal_end, len(states))
              if states[i] == ALARM and states[i - 1] != ALARM] if onset_sample is not None else []
    first = starts[0] if starts else None
    early = states[onset_sample:min(len(states), onset_sample + early_window_samples + 1)] \
        if onset_sample is not None else ()
    early_valid = sum(s != ABSTAIN for s in early)
    post = states[onset_sample:] if onset_sample is not None else ()
    return {
        "normal_samples": normal_end,
        "normal_observed_samples": available,
        "normal_abstained_samples": normal_end - available,
        "normal_coverage_fraction": round(available / normal_end, 6),
        "normal_false_alarm_active_samples": false_alarms,
        "false_alarm_active_fraction_all_samples": round(false_alarms / normal_end, 6),
        "false_alarm_active_fraction_observed_samples": (
            round(false_alarms / available, 6) if available else None
        ),
        "normal_false_alarm_episodes": episodes,
        "normal_false_alarm_episodes_per_24h": round(
            24 * episodes / (normal_end * SAMPLE_SECONDS / 3600), 6
        ),
        "post_onset_samples": len(post) if onset_sample is not None else None,
        "post_onset_observed_samples": sum(s != ABSTAIN for s in post)
        if onset_sample is not None else None,
        "early_window_observed_samples": early_valid if onset_sample is not None else None,
        "early_window_total_samples": len(early) if onset_sample is not None else None,
        "early_window_coverage_fraction": round(early_valid / len(early), 6)
        if onset_sample is not None else None,
        "first_new_post_onset_alarm_sample": first,
        "detected_after_onset": first is not None if onset_sample is not None else None,
        "detected_within_early_window": (
            first is not None and first - onset_sample <= early_window_samples
        ) if onset_sample is not None else None,
        "delay_minutes": (first - onset_sample) * SAMPLE_SECONDS // 60
        if first is not None else None,
    }


def _get_stressed(
    data: np.ndarray,
    scenario: str,
    name: str,
    median: np.ndarray,
    scale: np.ndarray,
    seed: int,
) -> Perturbed:
    if scenario != "blackout-15samples":
        return apply_stress(data, scenario, name, median, scale, seed)
    # A deliberately severe gap around the test fault onset. Keep the same
    # window in the healthy test; this is a *sensor* interruption, not a fault
    # label generated by the benchmark.
    baseline = apply_stress(data, "clean", name, median, scale, seed)
    observed = baseline.observed_mask.copy()
    measurements = baseline.data.copy()
    observed[155:170] = False
    measurements[155:170] = median[None, :]
    return Perturbed(
        measurements, int(np.count_nonzero(~observed)),
        int(observed.size), observed,
    )


def run_coverage(
    data_dir: str | Path, *,
    faults: tuple[int, ...] = tuple(range(1, 22)),
    methods: tuple[str, ...] = DEFAULT_METHODS,
    scenarios: tuple[str, ...] = DEFAULT_SCENARIOS,
    policy: CoveragePolicy = CoveragePolicy(),
    seed: int = 20261021,
    fit_fraction: float = 0.7,
    alpha: float = 0.01,
    persistence: int = 3,
    onset_sample: int = 160,
    early_window_samples: int = 20,
) -> dict:
    if not scenarios or "clean" not in scenarios or len(set(scenarios)) != len(scenarios):
        raise ValueError("Scenarios must be unique and contain clean.")
    if any(name not in DEFAULT_SCENARIOS for name in scenarios):
        raise ValueError("Unsupported coverage stress scenario.")
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        raise ValueError("seed must be a nonnegative integer.")
    reference = run_benchmark(
        data_dir, faults=faults, methods=methods, fit_fraction=fit_fraction,
        alpha=alpha, persistence=persistence, onset_sample=onset_sample,
        early_window_samples=early_window_samples,
    )
    directory = Path(data_dir)
    fit, calibration = split_normal_training(read_tep_dat(directory / "d00.dat").rows, fit_fraction)
    medians = np.median(fit, axis=0)
    scales = np.maximum(fit.std(axis=0, ddof=1), 1e-10)
    names = ["d00_te.dat", *[f"d{i:02d}_te.dat" for i in sorted(faults)]]
    originals = {name: as_matrix(read_tep_dat(directory / name).rows, features=52)
                 for name in names}

    trained = {}
    for method in methods:
        model = build_monitor(method)
        model.fit(fit)
        limit = calibrate(model, calibration, alpha)
        if round(limit, 10) != reference["methods"][method]["threshold"]:
            raise AssertionError("Monitor calibration differs from frozen reference baseline.")
        trained[method] = (model, limit)
    report = {
        "schema_version": 1,
        "benchmark": VERSION,
        "policy": policy.public_metadata(),
        "seed": seed,
        "normal_fit_and_calibration_only": True,
        "fixed_model_and_threshold_for_all_scenarios": True,
        "reference_input_files": reference["input_files"],
        "base_evaluation_protocol": reference["evaluation_protocol"],
        "scenarios": {},
        "limitations": [
            "The required XMEAS(7) and XMEAS(9) channels are an illustrative conservative gate, not a validated plant safety requirement.",
            "Imputed values are used for computational continuity, never to bypass missing-data abstention.",
            "Sensor blackout and offsets are artificial stressors; real-world prevalence is unknown.",
            "All abstained windows remain in detection denominators: missing evidence cannot inflate measured success.",
            "Anomaly decisions are not root-cause identification or safe plant actuation.",
        ],
    }
    for scenario in scenarios:
        transformed = {
            name: _get_stressed(originals[name], scenario, name, medians, scales, seed)
            for name in names
        }
        results = {}
        for method, (monitor, limit) in trained.items():
            cases = []
            for name in names:
                perturbed = transformed[name]
                onset = None if name == "d00_te.dat" else onset_sample
                scores = score_with_observation_resets(
                    monitor, perturbed.data, perturbed.observed_mask, policy,
                )
                states = decide(
                    scores, perturbed.observed_mask, threshold=limit,
                    consecutive=persistence, policy=policy,
                )
                summary = observation_summary(
                    states, onset_sample=onset,
                    early_window_samples=early_window_samples,
                )
                case = {
                    "source": name,
                    "fault_id": int(name[1:3]),
                    "missing_cells": perturbed.missing_cells,
                    "missing_fraction": perturbed.missing_fraction,
                    "decisions": {
                        NORMAL: states.count(NORMAL),
                        ALARM: states.count(ALARM),
                        ABSTAIN: states.count(ABSTAIN),
                    },
                    **summary,
                }
                if scenario == "clean":
                    original = next(c for c in reference["methods"][method]["cases"] if c["source"] == name)
                    if case["detected_after_onset"] != original["detected_after_onset"] \
                            or case["detected_within_early_window"] != original["detected_within_early_window"] \
                            or case["normal_false_alarm_active_samples"] != original["false_alarm_samples"]:
                        raise AssertionError("Clean tri-state decisions diverge from prior evaluation.")
                cases.append(case)
            results[method] = {
                "threshold": round(limit, 10),
                "faults_evaluated": len(faults),
                "early_detected": sum(c["detected_within_early_window"] is True for c in cases[1:]),
                "eventually_detected": sum(c["detected_after_onset"] is True for c in cases[1:]),
                "healthy_coverage_fraction": cases[0]["normal_coverage_fraction"],
                "healthy_abstained_samples": cases[0]["normal_abstained_samples"],
                "healthy_false_alarm_episodes": cases[0]["normal_false_alarm_episodes"],
                "healthy_false_alarm_active_samples": cases[0]["normal_false_alarm_active_samples"],
                "mean_fault_early_window_coverage": round(sum(
                    c["early_window_coverage_fraction"] for c in cases[1:]
                ) / len(faults), 6),
                "cases": cases,
            }
        report["scenarios"][scenario] = results
    clean = report["scenarios"]["clean"]
    for results in report["scenarios"].values():
        for method, metrics in results.items():
            metrics["delta_early_vs_clean"] = metrics["early_detected"] - clean[method]["early_detected"]
            metrics["delta_healthy_episodes_vs_clean"] = (
                metrics["healthy_false_alarm_episodes"]
                - clean[method]["healthy_false_alarm_episodes"]
            )
    return report


def render_markdown(report: dict) -> str:
    lines = [
        "# Tennessee Eastman: coverage-aware three-state evaluation",
        "",
        "Outputs are NORMAL / ALARM / ABSTAIN; any insufficiently observed sample abstains.",
        "All models and thresholds are frozen from normal training/calibration.",
        "Artificial stress settings are not estimated field failure probabilities.",
        "",
        "## Abstention policy",
        "",
        f"- Minimum feature observation: {report['policy']['min_observed_fraction']:.0%}",
        "- Required channels: " + ", ".join(report["policy"]["required_channels"]),
        "",
        "| Scenario | Monitor | Early faults | Healthy coverage | Fault early coverage | False episodes | Delta early |",
        "|:--|:--|--:|--:|--:|--:|--:|",
    ]
    for scenario, methods in report["scenarios"].items():
        for name, result in methods.items():
            lines.append(
                f"| {scenario} | {name} | {result['early_detected']}/{result['faults_evaluated']} | "
                f"{result['healthy_coverage_fraction']:.1%} | "
                f"{result['mean_fault_early_window_coverage']:.1%} | "
                f"{result['healthy_false_alarm_episodes']} | "
                f"{result['delta_early_vs_clean']:+d} |"
            )
    lines += [
        "",
        "Abstentions count in the timeline and in fault denominators. Changes in hit",
        "rates cannot be read without simultaneously inspecting coverage and nuisance alarms.",
        "Alarm streaks reset at every abstention; no stale previous alarm is retained.",
        "XMEAS(7) and XMEAS(9) are illustrative coverage-critical signals, not",
        "a verified industrial safety policy.",
        "",
        "## Reference input SHA-256",
        "",
    ]
    for file in report["reference_input_files"]:
        lines.append(f"- {file['source']}: {file['sha256']}")
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict, output_dir: str | Path) -> tuple[Path, Path]:
    folder = Path(output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    json_path = folder / "tep_coverage_report.json"
    md_path = folder / "tep_coverage_scoreboard.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run TEP coverage-aware abstention stress audit")
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--faults", type=int, nargs="+", default=list(range(1, 22)))
    parser.add_argument("--methods", nargs="+", choices=DEFAULT_METHODS + ("window-cusum-12", "window-cusum-24", "dpca-q-lag2", "dpca-t2-lag2"), default=list(DEFAULT_METHODS))
    parser.add_argument("--scenarios", nargs="+", choices=DEFAULT_SCENARIOS, default=list(DEFAULT_SCENARIOS))
    parser.add_argument("--seed", type=int, default=20261021)
    parser.add_argument("--min-observed-fraction", type=float, default=0.90)
    parser.add_argument("--required-channels", nargs="*", default=["xmeas_7", "xmeas_9"])
    args = parser.parse_args(argv)
    try:
        result = run_coverage(
            args.data_dir,
            faults=tuple(args.faults), methods=tuple(args.methods),
            scenarios=tuple(args.scenarios), seed=args.seed,
            policy=CoveragePolicy(args.min_observed_fraction, tuple(args.required_channels)),
        )
        if args.output_dir:
            paths = write_report(result, args.output_dir)
            print("Reports: " + " and ".join(str(path) for path in paths))
    except (OSError, ValueError) as error:
        parser.error(str(error))
    for scenario, methods in result["scenarios"].items():
        print(scenario)
        for name, row in methods.items():
            print(
                f"  {name}: early {row['early_detected']}/{row['faults_evaluated']}, "
                f"healthy coverage {row['healthy_coverage_fraction']:.3f}, "
                f"false episodes {row['healthy_false_alarm_episodes']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
