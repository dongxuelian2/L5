"""Predeclared causal baseline drift and alarm-recovery evaluation on TEP.

Competing decisions:
  - ordinary 3-consecutive-exceedance alert (legacy policy);
  - latch an alert until 3 consecutive *observed* readings return below
    75% of the same healthy-calibrated trigger threshold.

Recovery does NOT silence an ongoing fault merely because an incident has
been raised, and abstention resets both the temporal detector and alarm state.
The adaptive model is not guaranteed to distinguish benign drift from a
slowly evolving fault: testing must explicitly report this limitation.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

from .coverage import ALARM, NORMAL, ABSTAIN, CoveragePolicy, decide, observation_summary, score_with_observation_resets
from .evaluate import run_benchmark
from .monitoring import as_matrix, build_monitor, calibrate, split_normal_training
from .tep import SAMPLE_SECONDS, VARIABLES, read_tep_dat

VERSION = "tep-drift-recovery-v1"
METHODS = ("robust-maxz", "ewma-maxz", "adaptive-maxz")
SCENARIOS = ("clean", "slow-drift-1sigma", "transient-offset-2sigma", "blackout-15samples")
POLICIES = ("legacy-persistence", "recovery-hysteresis")
TRANSIENT_START, TRANSIENT_END = 240, 260


def recovery_decisions(
    scores: np.ndarray, observed_mask: np.ndarray, *, threshold: float,
    persistence: int, release_fraction: float, release_count: int,
    policy: CoveragePolicy,
) -> tuple[str, ...]:
    """Evidence-based release; no timed alarm suppression or test-label input."""
    scores = np.asarray(scores, dtype=float)
    mask = np.asarray(observed_mask)
    if scores.ndim != 1 or mask.shape != (len(scores), len(VARIABLES)) or mask.dtype != np.bool_:
        raise ValueError("Scores and 52-channel Boolean observation mask must align.")
    if not np.isfinite(scores).all() or not math.isfinite(threshold) or threshold < 0:
        raise ValueError("Scores/trigger threshold must be finite and nonnegative.")
    if not 0 < release_fraction < 1 or persistence < 1 or release_count < 1:
        raise ValueError("Recovery parameters must have 0<release_fraction<1 and positive run lengths.")
    if not isinstance(policy, CoveragePolicy):
        raise ValueError("Expected a coverage policy.")
    required = [VARIABLES.index(name) for name in policy.required_channels]
    release_threshold = threshold * release_fraction
    result: list[str] = []
    armed = False
    high_run = 0
    quiet_run = 0
    for score, observed in zip(scores, mask):
        valid = observed.mean() >= policy.min_observed_fraction and all(observed[i] for i in required)
        if not valid:
            armed, high_run, quiet_run = False, 0, 0
            result.append(ABSTAIN)
        elif not armed:
            high_run = high_run + 1 if score > threshold else 0
            if high_run >= persistence:
                armed = True
                quiet_run = 0
                result.append(ALARM)
            else:
                result.append(NORMAL)
        else:
            quiet_run = quiet_run + 1 if score <= release_threshold else 0
            if quiet_run >= release_count:
                armed = False
                high_run = 0
                quiet_run = 0
                result.append(NORMAL)
            else:
                result.append(ALARM)
    return tuple(result)


def stress_case(
    rows: np.ndarray, name: str, median: np.ndarray, std: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Perturb identical time indexes in healthy and fault tests, no test fitting."""
    x = as_matrix(rows, features=len(VARIABLES)).copy()
    if name not in SCENARIOS:
        raise ValueError(f"Unknown drift scenario: {name}")
    if median.shape != (52,) or std.shape != (52,) or not np.isfinite(std).all() or np.any(std <= 0):
        raise ValueError("Training feature scales must be positive and finite.")
    observed = np.ones(x.shape, dtype=bool)
    if name == "slow-drift-1sigma":
        x += np.linspace(0, 1, len(x))[:, None] * std[None, :]
    elif name == "transient-offset-2sigma":
        x[TRANSIENT_START:TRANSIENT_END] += 2.0 * std[None, :]
    elif name == "blackout-15samples":
        observed[155:170, :] = False
        x[155:170, :] = median
    return x, observed


def transient_recovery_metric(states: tuple[str, ...]) -> dict:
    """For held-out healthy experiment, report clearance only if alarm ongoing."""
    if len(states) <= TRANSIENT_END:
        raise ValueError("Transient analysis needs an observed post-intervention window.")
    active = states[TRANSIENT_END - 1] == ALARM
    end = next((i for i in range(TRANSIENT_END, len(states)) if states[i] == NORMAL), None) if active else None
    return {
        "alarm_active_at_transient_end": active,
        "clearance_delay_minutes": (end - TRANSIENT_END) * SAMPLE_SECONDS // 60
        if end is not None else None,
        "clearance_censored": bool(active and end is None),
        "clearance_not_applicable": not active,
    }


def run_experiment(
    data_dir: str | Path, *,
    faults: tuple[int, ...] = tuple(range(1, 22)),
    methods: tuple[str, ...] = METHODS,
    scenarios: tuple[str, ...] = SCENARIOS,
    policies: tuple[str, ...] = POLICIES,
    alpha: float = 0.01,
    persistence: int = 3,
    release_fraction: float = 0.75,
    release_count: int = 3,
    fit_fraction: float = 0.7,
    onset_sample: int = 160,
    early_window_samples: int = 20,
    coverage_policy: CoveragePolicy = CoveragePolicy(),
) -> dict:
    if not scenarios or "clean" not in scenarios or len(set(scenarios)) != len(scenarios) or any(s not in SCENARIOS for s in scenarios):
        raise ValueError("Scenarios must be distinct, supported and include clean.")
    if not policies or len(set(policies)) != len(policies) or any(p not in POLICIES for p in policies):
        raise ValueError("Alarm policies must be distinct and supported.")
    if not methods or len(set(methods)) != len(methods) or any(m not in METHODS for m in methods):
        raise ValueError("Monitors must be distinct and predeclared.")
    if not 0 < release_fraction < 1 or release_count < 1:
        raise ValueError("Release hysteresis parameters are invalid.")
    base = run_benchmark(
        data_dir, faults=faults, methods=methods, fit_fraction=fit_fraction,
        alpha=alpha, persistence=persistence, onset_sample=onset_sample,
        early_window_samples=early_window_samples,
    )
    root = Path(data_dir)
    fit, cal = split_normal_training(read_tep_dat(root / "d00.dat").rows, fit_fraction)
    median = np.median(fit, axis=0)
    std = np.maximum(fit.std(axis=0, ddof=1), 1e-10)
    names = ["d00_te.dat", *[f"d{i:02d}_te.dat" for i in sorted(faults)]]
    original = {name: as_matrix(read_tep_dat(root / name).rows, features=52) for name in names}
    frozen = {}
    for method in methods:
        monitor = build_monitor(method)
        monitor.fit(fit)
        threshold = calibrate(monitor, cal, alpha)
        if round(threshold, 10) != base["methods"][method]["threshold"]:
            raise AssertionError("Normal calibration threshold drifted.")
        frozen[method] = (monitor, threshold)

    report = {
        "schema_version": 1,
        "benchmark": VERSION,
        "base_protocol": base["evaluation_protocol"],
        "source_files": base["input_files"],
        "fit_partition_only_for_drift_scales": True,
        "policy_parameters_predeclared": {
            "adaptation_rate": 0.02,
            "adaptation_guard_z": 2.5,
            "adaptation_max_shift_z": 1.5,
            "trigger_persistence": persistence,
            "release_fraction": release_fraction,
            "release_count": release_count,
            "transient_start_index": TRANSIENT_START,
            "transient_end_index_exclusive": TRANSIENT_END,
            "sampling_seconds": SAMPLE_SECONDS,
            "coverage": coverage_policy.public_metadata(),
        },
        "methods": list(methods),
        "scenarios": list(scenarios),
        "alarm_policies": list(policies),
        "rows": [],
        "limitations": [
            "Synthetic, equal-channel offsets and ramps are not physical plant operating modes.",
            "A gradual genuine fault may be absorbed into an adaptive baseline, reducing fault sensitivity.",
            "Frozen adaptation parameters come from predeclared engineering choices, not independent fault-free validation.",
            "All nuisance-alarm rates are measured on the same held-out healthy test trajectory.",
            "Holding an alarm during recovery increases active-alarm time; it never creates a timed suppression.",
            "An unobservable sample abstains and resets detector and decision history.",
            "A monitor's empirical alpha does not guarantee equal realized false-alarm episode workloads.",
            "This is statistical monitoring, not certified fault classification, root-cause explanation or closed-loop control.",
        ],
    }
    for scenario in scenarios:
        cases = {name: stress_case(data, scenario, median, std) for name, data in original.items()}
        for method, (monitor, threshold) in frozen.items():
            scored = {
                name: score_with_observation_resets(monitor, x, mask, coverage_policy)
                for name, (x, mask) in cases.items()
            }
            for policy_name in policies:
                evaluations = []
                for name in names:
                    _, mask = cases[name]
                    scores = scored[name]
                    if policy_name == "legacy-persistence":
                        decisions = decide(
                            scores, mask, threshold=threshold,
                            consecutive=persistence, policy=coverage_policy,
                        )
                    else:
                        decisions = recovery_decisions(
                            scores, mask, threshold=threshold,
                            persistence=persistence, release_fraction=release_fraction,
                            release_count=release_count, policy=coverage_policy,
                        )
                    onset = None if name == "d00_te.dat" else onset_sample
                    summary = observation_summary(
                        decisions, onset_sample=onset,
                        early_window_samples=early_window_samples,
                    )
                    record = {
                        "source": name,
                        "fault_id": int(name[1:3]),
                        **summary,
                        "state_counts": {
                            NORMAL: decisions.count(NORMAL),
                            ALARM: decisions.count(ALARM),
                            ABSTAIN: decisions.count(ABSTAIN),
                        },
                    }
                    if scenario == "transient-offset-2sigma" and onset is None:
                        record["transient_recovery"] = transient_recovery_metric(decisions)
                    if scenario == "clean" and policy_name == "legacy-persistence":
                        expected = next(c for c in base["methods"][method]["cases"] if c["source"] == name)
                        for key in ("detected_after_onset", "detected_within_early_window"):
                            if record[key] != expected[key]:
                                raise AssertionError("Unstressed persistence detection differs from canonical baseline.")
                        if record["normal_false_alarm_active_samples"] != expected["false_alarm_samples"]:
                            raise AssertionError("Clean healthy alarm-active samples diverge from canonical result.")
                    evaluations.append(record)
                healthy, faulty = evaluations[0], evaluations[1:]
                report["rows"].append({
                    "scenario": scenario,
                    "method": method,
                    "policy": policy_name,
                    "threshold": round(threshold, 10),
                    "faults_evaluated": len(faulty),
                    "early_detected": sum(c["detected_within_early_window"] is True for c in faulty),
                    "eventually_detected": sum(c["detected_after_onset"] is True for c in faulty),
                    "healthy_false_alarm_episodes": healthy["normal_false_alarm_episodes"],
                    "healthy_alarm_active_samples": healthy["normal_false_alarm_active_samples"],
                    "healthy_observed_fraction": healthy["normal_coverage_fraction"],
                    "healthy_transient_recovery": healthy.get("transient_recovery"),
                    "per_case": evaluations,
                })
    return report


def render_markdown(report: dict) -> str:
    lines = [
        "# TEP causal adaptation and recovery: predeclared diagnostic audit", "",
        "No fault-test model selection. All center scales, model fit and thresholds",
        "originate in normal training. Synthetic drifts do not model physical plant state.", "",
        "| Test condition | Detector | Alarm policy | Early / faults | Eventual / faults | Healthy false episodes | Healthy alarm-active samples |",
        "|:--|:--|:--|--:|--:|--:|--:|",
    ]
    for row in report["rows"]:
        lines.append(
            f"| {row['scenario']} | {row['method']} | {row['policy']} | "
            f"{row['early_detected']}/{row['faults_evaluated']} | "
            f"{row['eventually_detected']}/{row['faults_evaluated']} | "
            f"{row['healthy_false_alarm_episodes']} | {row['healthy_alarm_active_samples']} |"
        )
    lines.extend([
        "",
        "Recovery does not suppress an active incident on a timer: three observed",
        "sub-threshold readings are required for confirmed clearance.",
        "JSON additionally records post-transient clearance delay or censoring",
        "when the healthy test was in an alarm at intervention end.",
        "An adaptive center can absorb gradual *fault* evidence; unchanged fault",
        "denominators and early-hit counts expose rather than conceal this risk.",
        "", "## Original input SHA-256", "",
    ])
    for file in report["source_files"]:
        lines.append(f"- {file['source']}: {file['sha256']}")
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict, output_dir: str | Path) -> tuple[Path, Path]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    js = destination / "tep_drift_recovery_report.json"
    md = destination / "tep_drift_recovery_scoreboard.md"
    js.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    md.write_text(render_markdown(report), encoding="utf-8")
    return js, md


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Normal-trained drift adaptation and evidence-based alarm recovery on TEP")
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--faults", nargs="+", type=int, default=list(range(1, 22)))
    parser.add_argument("--scenarios", nargs="+", choices=SCENARIOS, default=list(SCENARIOS))
    parser.add_argument("--methods", nargs="+", choices=METHODS, default=list(METHODS))
    parser.add_argument("--policies", nargs="+", choices=POLICIES, default=list(POLICIES))
    args = parser.parse_args(argv)
    try:
        report = run_experiment(
            args.data_dir, faults=tuple(args.faults),
            scenarios=tuple(args.scenarios), methods=tuple(args.methods),
            policies=tuple(args.policies),
        )
        if args.output_dir:
            files = write_report(report, args.output_dir)
            print("Reports: " + ", ".join(str(file) for file in files))
        print(render_markdown(report))
    except (ValueError, OSError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
