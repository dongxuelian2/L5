"""Predetermined alpha and perturbation-seed audit of TEP coverage decisions.

This is a *sensitivity analysis on one fixed public reference dataset*, not
independent plant replication, hyperparameter search or uncertainty estimation
from independently observed faults. Never rank and select a test-optimal alpha.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
from statistics import median

from .coverage import CoveragePolicy, run_coverage
from .evaluate import DEFAULT_METHODS

VERSION = "tep-sensitivity-v1"
DEFAULT_SEEDS = (20261021, 20261022, 20261023, 20261024, 20261025)
DEFAULT_ALPHAS = (0.005, 0.01, 0.05)
DEFAULT_SCENARIOS = ("clean", "random-missing-05", "noise-20pct")


def _validate(
    seeds: tuple[int, ...],
    alphas: tuple[float, ...],
    scenarios: tuple[str, ...],
) -> None:
    if len(seeds) < 2 or len(set(seeds)) != len(seeds) or any(
        not isinstance(s, int) or isinstance(s, bool) or s < 0 for s in seeds
    ):
        raise ValueError("At least two distinct nonnegative integer seeds are required.")
    if len(alphas) < 2 or any(
        not isinstance(a, (int, float)) or not math.isfinite(a) or not 0 < a < 0.5
        for a in alphas
    ) or len(set(alphas)) != len(alphas):
        raise ValueError("At least two distinct finite alphas in (0, 0.5) are required.")
    if not scenarios or "clean" not in scenarios or len(set(scenarios)) != len(scenarios):
        raise ValueError("Scenarios must be distinct and include clean.")
    if any(s not in DEFAULT_SCENARIOS for s in scenarios):
        raise ValueError("Only clean, random-missing-05 and noise-20pct are allowed in this sweep.")


def _range(values: list[float | int]) -> dict:
    if not values:
        raise ValueError("Cannot summarize an empty set of runs.")
    return {
        "min": min(values),
        "median": median(values),
        "max": max(values),
    }


def run_sensitivity(
    data_dir: str | Path, *,
    faults: tuple[int, ...] = tuple(range(1, 22)),
    methods: tuple[str, ...] = DEFAULT_METHODS,
    seeds: tuple[int, ...] = DEFAULT_SEEDS,
    alphas: tuple[float, ...] = DEFAULT_ALPHAS,
    scenarios: tuple[str, ...] = DEFAULT_SCENARIOS,
    policy: CoveragePolicy = CoveragePolicy(),
    persistence: int = 3,
    onset_sample: int = 160,
    early_window_samples: int = 20,
    fit_fraction: float = 0.7,
) -> dict:
    _validate(seeds, alphas, scenarios)
    # The sweep is declared before any held-out outcomes are examined.
    # Each run_coverage call uses the unmodified normal train and calibration,
    # and leaves the threshold frozen for that particular alpha.
    per_seed = []
    summary_inputs: dict[tuple[float, str, str], list[dict]] = defaultdict(list)
    checksums = None
    protocol = None
    for alpha in alphas:
        frozen_thresholds = {}
        clean_reference = {}
        for seed in seeds:
            report = run_coverage(
                data_dir, faults=faults, methods=methods,
                scenarios=scenarios, seed=seed, policy=policy,
                alpha=alpha, persistence=persistence,
                onset_sample=onset_sample, early_window_samples=early_window_samples,
                fit_fraction=fit_fraction,
            )
            if checksums is None:
                checksums = report["reference_input_files"]
                protocol = report["base_evaluation_protocol"]
            elif report["reference_input_files"] != checksums:
                raise AssertionError("Reference source files changed during the sweep.")
            row = {"alpha": alpha, "seed": seed, "results": {}}
            for scenario in scenarios:
                row["results"][scenario] = {}
                for method in methods:
                    measured = report["scenarios"][scenario][method]
                    threshold = measured["threshold"]
                    if method in frozen_thresholds and frozen_thresholds[method] != threshold:
                        raise AssertionError("Normal-trained threshold changed across perturbation seeds.")
                    frozen_thresholds[method] = threshold
                    cases = measured["cases"][1:]
                    early_flags = {
                        str(case["fault_id"]): bool(case["detected_within_early_window"])
                        for case in cases
                    }
                    item = {
                        "threshold": threshold,
                        "early_detected": measured["early_detected"],
                        "eventually_detected": measured["eventually_detected"],
                        "healthy_coverage_fraction": measured["healthy_coverage_fraction"],
                        "healthy_false_alarm_episodes": measured["healthy_false_alarm_episodes"],
                        "healthy_false_alarm_active_samples": measured["healthy_false_alarm_active_samples"],
                        "fault_early_hit_flags": early_flags,
                    }
                    row["results"][scenario][method] = item
                    summary_inputs[(alpha, scenario, method)].append(item)
                    if scenario == "clean":
                        comparable = (
                            item["early_detected"], item["eventually_detected"],
                            item["healthy_false_alarm_episodes"], item["healthy_false_alarm_active_samples"],
                        )
                        if method in clean_reference and clean_reference[method] != comparable:
                            raise AssertionError("Clean results changed with a seed that should not affect data.")
                        clean_reference[method] = comparable
            per_seed.append(row)

    # No "best alpha" output: the point is sensitivity at *predeclared*
    # threshold targets, not tuning a detector against held-out faults.
    aggregated = {}
    for alpha in alphas:
        key = format(alpha, ".12g")
        by_scenario = {}
        for scenario in scenarios:
            by_method = {}
            for method in methods:
                group = summary_inputs[(alpha, scenario, method)]
                matched_clean = summary_inputs[(alpha, "clean", method)]
                if len(group) != len(seeds) or len(matched_clean) != len(seeds):
                    raise AssertionError("Expected one paired run for every declared seed.")
                fault_names = sorted(group[0]["fault_early_hit_flags"], key=int)
                by_method[method] = {
                    "threshold": group[0]["threshold"],
                    "early_detected": _range([r["early_detected"] for r in group]),
                    "eventually_detected": _range([r["eventually_detected"] for r in group]),
                    "healthy_coverage_fraction": _range([r["healthy_coverage_fraction"] for r in group]),
                    "healthy_false_alarm_episodes": _range([r["healthy_false_alarm_episodes"] for r in group]),
                    "healthy_false_alarm_active_samples": _range(
                        [r["healthy_false_alarm_active_samples"] for r in group]
                    ),
                    "paired_delta_early_vs_clean": _range([
                        r["early_detected"] - c["early_detected"]
                        for r, c in zip(group, matched_clean)
                    ]),
                    "paired_delta_false_episodes_vs_clean": _range([
                        r["healthy_false_alarm_episodes"] - c["healthy_false_alarm_episodes"]
                        for r, c in zip(group, matched_clean)
                    ]),
                    "fault_early_hits_across_seeds": {
                        fault: sum(r["fault_early_hit_flags"][fault] for r in group)
                        for fault in fault_names
                    },
                }
            by_scenario[scenario] = by_method
        aggregated[key] = by_scenario

    for method in methods:
        limits = [
            aggregated[format(alpha, ".12g")]["clean"][method]["threshold"]
            for alpha in sorted(alphas)
        ]
        if any(limits[i] < limits[i + 1] for i in range(len(limits) - 1)):
            raise AssertionError("Threshold must be non-increasing as alpha rises.")

    return {
        "schema_version": 1,
        "benchmark": VERSION,
        "data_provenance": checksums,
        "reference_protocol": protocol,
        "policy": policy.public_metadata(),
        "methods": list(methods),
        "declared_seeds": list(seeds),
        "declared_alphas": list(alphas),
        "declared_scenarios": list(scenarios),
        "faults": list(sorted(faults)),
        "per_seed": per_seed,
        "summary_by_alpha": aggregated,
        "interpretation_limits": [
            "All repeated runs reuse one fixed TEP reference dataset: seeds create noise/missing masks, not independent plant realizations.",
            "The different alpha settings are a predeclared threshold-sensitivity sweep, NOT test-selected optimized operating points.",
            "Min/median/max are descriptive across artificial perturbation seeds, not sampling-confidence intervals.",
            "Clean reference data are deterministic and must be identical across all seeds at a fixed alpha.",
            "Alarm episodes and timely detections must be considered together; rising hit count alone is not better quality.",
            "No fault classification, causal inference, uncertainty guarantee, or plant actuation is established.",
        ],
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# TEP — sensitivity to normal-calibrated thresholds and perturbation seeds",
        "",
        "These are **one dataset with repeated synthetic stress masks**; not independent",
        "plant replications or confidence intervals. No test-optimal alpha is selected.",
        "",
        "| Alpha | Scenario | Method | Early faults min / median / max | Δ early vs clean min / median / max | Healthy false episodes min / median / max |",
        "|:--|:--|:--|:--|:--|:--|",
    ]
    def tri(item):
        return f"{item['min']} / {item['median']} / {item['max']}"
    for alpha, scenarios in report["summary_by_alpha"].items():
        for scenario, methods in scenarios.items():
            for method, row in methods.items():
                lines.append(
                    f"| {alpha} | {scenario} | {method} | {tri(row['early_detected'])} | "
                    f"{tri(row['paired_delta_early_vs_clean'])} | {tri(row['healthy_false_alarm_episodes'])} |"
                )
    lines.extend([
        "",
        "The full JSON includes each seed, calibrated threshold, normal coverage",
        "and per-fault early-hit flags. No result is omitted for poor performance.",
        "",
        "## Test input provenance",
        "",
    ])
    for source in report["data_provenance"]:
        lines.append(f"- {source['source']}: {source['sha256']}")
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict, output_dir: str | Path) -> tuple[Path, Path]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    js = root / "tep_sensitivity_report.json"
    md = root / "tep_sensitivity_scoreboard.md"
    js.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    md.write_text(render_markdown(report), encoding="utf-8")
    return js, md


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Predetermined TEP alpha and seed sensitivity audit")
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--faults", type=int, nargs="+", default=list(range(1, 22)))
    parser.add_argument("--methods", nargs="+", choices=DEFAULT_METHODS, default=list(DEFAULT_METHODS))
    parser.add_argument("--seeds", type=int, nargs="+", default=list(DEFAULT_SEEDS))
    parser.add_argument("--alphas", type=float, nargs="+", default=list(DEFAULT_ALPHAS))
    parser.add_argument("--scenarios", nargs="+", choices=DEFAULT_SCENARIOS, default=list(DEFAULT_SCENARIOS))
    args = parser.parse_args(argv)
    try:
        report = run_sensitivity(
            args.data_dir, faults=tuple(args.faults), methods=tuple(args.methods),
            seeds=tuple(args.seeds), alphas=tuple(args.alphas),
            scenarios=tuple(args.scenarios),
        )
        if args.output_dir:
            paths = write_report(report, args.output_dir)
            print("Reports: " + " and ".join(str(file) for file in paths))
        print(render_markdown(report))
    except (ValueError, OSError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
