"""Independent normal-simulation TEP audit using Rieth et al. (2017) RData.

Data source: https://doi.org/10.7910/DVN/6C3JR1 (v1, published 2017).
Training and testing simulations use nonoverlapping random-number seeds per
the original data documentation. The data's simulationRun *index* may still
repeat between the two disjoint-seed datasets.

Only TWO fault-free RData files are downloaded. No fault labels are used to
select a model or a threshold. All monitor options/policies/run IDs are fixed
before observing the external normal-test trajectories.

The 10 external normal test files below are different simulated trajectories
of the SAME operating mode. They are not separate plant operating modes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import median
import urllib.parse
import urllib.request

import numpy as np

from .monitoring import as_matrix, build_monitor, calibrate, persistent_alarms
from .normal_budget_validation import calibration_budget_threshold
from .robustness import alarm_episodes
from .tep import VARIABLES, SAMPLE_SECONDS

VERSION = "tep-rieth-independent-normal-v1"
DOI = "doi:10.7910/DVN/6C3JR1"
DATA_FILES = {
    "train": ("TEP_FaultFree_Training.RData", "TMBUVJ", "fault_free_training", 500),
    "test": ("TEP_FaultFree_Testing.RData", "Q4NOFD", "fault_free_testing", 960),
}
METHODS = ("robust-maxz", "pca-q", "pca-t2", "dpca-q-lag2", "dpca-t2-lag2")
POLICIES = ("quantile-alpha-01", "normal-calibration-1episode-2pct")
FOLDS = (("A", 1, 2, 3), ("B", 4, 5, 6))
EXTERNAL_TEST_RUN_IDS = tuple(range(1, 11))
MAX_BYTES = 100 * 1024 * 1024


def source_url(file_id: str) -> str:
    persistent_id = f"{DOI}/{file_id}"
    return ("https://dataverse.harvard.edu/api/access/datafile/:persistentId?"
            + urllib.parse.urlencode({"persistentId": persistent_id}))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download_normal_data(directory: Path) -> dict:
    """Retrieve only 23MB train + 45MB test (never fault files or source code).

    Reject responses that look like error pages; keep data outside the repo.
    """
    directory.mkdir(parents=True, exist_ok=True)
    meta = {}
    for split, (filename, file_id, _, _) in DATA_FILES.items():
        target = directory / filename
        url = source_url(file_id)
        if not target.exists():
            tmp = directory / (filename + ".partial")
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "L5-TEP-research/1.0"})
                with urllib.request.urlopen(request, timeout=120) as response, tmp.open("wb") as out:
                    size = 0
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise ValueError(f"Unexpected overlarge response for {filename}.")
                        out.write(chunk)
                if not 1_000_000 <= tmp.stat().st_size <= MAX_BYTES:
                    raise ValueError(f"Bad download size for {filename}; Dataverse may have returned an error.")
                with tmp.open("rb") as handle:
                    magic = handle.read(32).lstrip()
                if magic.startswith((b"<!DOCTYPE", b"<html", b'{"status"', b'{"message"')):
                    raise ValueError(f"Dataverse returned an HTML/JSON error, not RData: {filename}.")
                tmp.replace(target)
            finally:
                tmp.unlink(missing_ok=True)
        if not target.is_file() or not 1_000_000 <= target.stat().st_size <= MAX_BYTES:
            raise ValueError(f"Invalid cached Rieth RData file: {target}")
        meta[split] = {
            "source_file": filename,
            "source_doi": DOI,
            "file_persistent_id": f"{DOI}/{file_id}",
            "direct_download_url": url,
            "downloaded_bytes": target.stat().st_size,
            "sha256": _sha256(target),
        }
    return meta


def extract_run_arrays(
    matrix: np.ndarray, columns: tuple[str, ...], *,
    run_ids: tuple[int, ...], samples_per_run: int,
) -> dict[int, np.ndarray]:
    """Validate the original 55-column schema and contiguous run sample order.

    Metadata cols are never passed to detectors. Refuse incomplete/mixed runs
    rather than silently reusing a different run or concatenating identities.
    """
    required = ("faultNumber", "simulationRun", "sample", *VARIABLES)
    if len(columns) != len(required) or set(columns) != set(required) or len(set(columns)) != len(columns):
        raise ValueError("Expected exactly the original 55 Rieth metadata+52 feature columns.")
    if not run_ids or len(set(run_ids)) != len(run_ids):
        raise ValueError("Request distinct simulationRun IDs.")
    x = np.asarray(matrix, dtype=np.float64)
    if x.ndim != 2 or x.shape[1] != len(columns) or not np.isfinite(x).all():
        raise ValueError("The Rieth original 55-column matrix must be rectangular and finite.")
    idx = {key: columns.index(key) for key in required}
    if np.any(x[:, idx["faultNumber"]] != 0):
        raise ValueError("Fault-containing records are never permitted in a fault-free dataset.")
    runs = {}
    for run_id in run_ids:
        if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id < 1:
            raise ValueError("Invalid simulation run ID.")
        selected = x[x[:, idx["simulationRun"]] == run_id]
        if len(selected) != samples_per_run:
            raise ValueError(f"Run {run_id} contains {len(selected)} rows, expected {samples_per_run}.")
        order = np.argsort(selected[:, idx["sample"]])
        ordered = selected[order]
        if not np.array_equal(ordered[:, idx["sample"]], np.arange(1, samples_per_run + 1)):
            raise ValueError(f"Run {run_id} lacks unique contiguous time indices.")
        runs[run_id] = as_matrix(ordered[:, [idx[name] for name in VARIABLES]], features=52).copy()
    return runs


def read_normal_rdata(directory: Path) -> tuple[dict[int, np.ndarray], dict[int, np.ndarray]]:
    """RData parser is an optional pinned CI dependency; no R interpreter."""
    try:
        import pyreadr
    except ImportError as error:
        raise RuntimeError("Install pyreadr==0.5.7 to read external Rieth RData.") from error
    matrices = []
    for split, (_, _, object_name, n) in DATA_FILES.items():
        filename = DATA_FILES[split][0]
        mapping = pyreadr.read_r(str(directory / filename))
        if object_name not in mapping or len(mapping) != 1:
            raise ValueError(f"RData object mismatch in {filename}: expected {object_name}.")
        frame = mapping[object_name]
        ids = tuple(sorted({v for fold in FOLDS for v in fold[1:]})) if split == "train" else EXTERNAL_TEST_RUN_IDS
        matrices.append(extract_run_arrays(
            frame.to_numpy(dtype=np.float64), tuple(frame.columns),
            run_ids=ids, samples_per_run=n,
        ))
    return matrices[0], matrices[1]


def _workload(model, data: np.ndarray, threshold: float, consecutive: int) -> dict:
    # Each independent normal trajectory gets its own causal state boundary.
    alarms = persistent_alarms(model.score(data), threshold, consecutive)
    counts = alarm_episodes(alarms, len(alarms))
    return {
        "episodes": counts["count"],
        "active_samples": counts["active_samples"],
        "longest_run_samples": counts["longest_duration_samples"],
        "total_samples": len(data),
    }


def _summary(values: list[int]) -> dict:
    if not values:
        raise ValueError("Cannot summarize empty experiment.")
    return {"minimum": min(values), "median": median(values), "maximum": max(values), "sum": sum(values)}


def run_independent_runs(
    training: dict[int, np.ndarray], external: dict[int, np.ndarray], *,
    methods: tuple[str, ...] = METHODS, policies: tuple[str, ...] = POLICIES,
    folds: tuple[tuple[str, int, int, int], ...] = FOLDS,
    external_ids: tuple[int, ...] = EXTERNAL_TEST_RUN_IDS,
    alpha: float = .01, persistence: int = 3,
) -> dict:
    if not methods or len(set(methods)) != len(methods) or any(n not in METHODS for n in methods):
        raise ValueError("Methods must be unique and fixed ahead of evaluation.")
    if not policies or len(set(policies)) != len(policies) or any(n not in POLICIES for n in policies):
        raise ValueError("Policies must be unique and fixed ahead of evaluation.")
    if not folds or not external_ids or len(set(external_ids)) != len(external_ids):
        raise ValueError("Use declared distinct forward validation and external test trajectories.")
    if not 0 < alpha < .5 or not isinstance(persistence, int) or persistence < 1:
        raise ValueError("Invalid healthy-only threshold protocol.")
    if any(len(set((fit,cal,val))) != 3 or fit not in training or cal not in training or val not in training
           for _,fit,cal,val in folds):
        raise ValueError("Fit, calibration and validation must be distinct normal runs.")
    ids_flat = [run_id for _,fit,cal,val in folds for run_id in (fit,cal,val)]
    if len(set(ids_flat)) != len(ids_flat):
        raise ValueError("Folds must use nonoverlapping fit/calibration/validation simulation runs.")
    if any(run_id not in external for run_id in external_ids):
        raise ValueError("Missing a predeclared external test simulation run.")
    train = {i: as_matrix(v, features=52) for i,v in training.items()}
    test = {i: as_matrix(v, features=52) for i,v in external.items()}
    report = {
        "schema_version": 1, "benchmark": VERSION,
        "training_source": "Rieth 2017 fault_free_training, distinct simulationRun RNG states",
        "external_source": "Rieth 2017 fault_free_testing, authors report non-overlapping RNG seeds",
        "same_plant_mode": "TEP mode 1", "sample_seconds": SAMPLE_SECONDS,
        "folds": [{"name": name, "fit_run":fit, "calibration_run":cal,
                   "validation_run":val} for name,fit,cal,val in folds],
        "external_normal_runs": list(external_ids),
        "methods": list(methods), "policies": list(policies),
        "budget": {"max_calibration_episodes": 1, "max_calibration_alarm_active_fraction": .02,
                   "persistence": persistence, "alpha": alpha},
        "rows": [],
        "paired_vs_maxz": [],
        "limitations": [
            "Independent simulation seed runs are not different plant modes; this evaluates TEP mode 1 only.",
            "Training and testing run index numbers can coincide while original random seeds do not overlap per the dataset authors.",
            "Neither held-out normal test nor an anomaly/fault label participates in model fitting or calibration.",
            "A normal-calibration alarm workload cap is not a guaranteed population false alarm limit.",
            "Only 10 predeclared external normal simulations are inspected; ranges are descriptive, not confidence intervals.",
            "This PR measures held-out NORMAL false alarms. It does not claim an independent fault-detection evaluation.",
        ],
    }
    for name,fit_id,cal_id,val_id in folds:
        for method in methods:
            model = build_monitor(method)
            model.fit(train[fit_id])
            cal = train[cal_id]
            q = calibrate(model, cal, alpha)
            work_threshold = calibration_budget_threshold(model.score(cal), persistence=persistence)
            for policy in policies:
                threshold = q if policy == "quantile-alpha-01" else work_threshold
                cal_result = _workload(model,cal,threshold,persistence)
                if policy != "quantile-alpha-01":
                    if cal_result["episodes"] > 1 or cal_result["active_samples"] > int(len(cal)*.02):
                        raise AssertionError("Predeclared calibration budget violated.")
                normal_val = _workload(model, train[val_id], threshold, persistence)
                out = {str(i): _workload(model, test[i], threshold, persistence) for i in external_ids}
                report["rows"].append({
                    "fold": name, "method":method, "policy":policy,
                    "threshold": round(threshold, 10), "fit_metadata":model.metadata(),
                    "calibration":cal_result, "untouched_training_normal_validation":normal_val,
                    "external_per_run":out,
                    "external_episodes":_summary([r["episodes"] for r in out.values()]),
                    "external_active_samples":_summary([r["active_samples"] for r in out.values()]),
                })
    for fold_name, *_ in folds:
        for policy in policies:
            ref = next((r for r in report["rows"] if r["fold"] == fold_name and r["policy"] == policy and r["method"] == "robust-maxz"), None)
            if not ref:
                continue
            for row in report["rows"]:
                if row["fold"] != fold_name or row["policy"] != policy or row["method"] == "robust-maxz":
                    continue
                report["paired_vs_maxz"].append({
                    "fold": fold_name, "method":row["method"], "policy":policy,
                    "per_run_delta_episodes": {key:row["external_per_run"][key]["episodes"]-ref["external_per_run"][key]["episodes"] for key in ref["external_per_run"]},
                    "per_run_delta_active_samples": {key:row["external_per_run"][key]["active_samples"]-ref["external_per_run"][key]["active_samples"] for key in ref["external_per_run"]},
                })
    return report


def run_external(directory: Path, *, download: bool = True) -> dict:
    provenance = download_normal_data(directory) if download else {
        split: {"source_file":filename, "source_doi":DOI,
                "file_persistent_id": f"{DOI}/{file_id}",
                "direct_download_url":source_url(file_id),
                "downloaded_bytes":(directory/filename).stat().st_size,
                "sha256":_sha256(directory/filename)}
        for split,(filename,file_id,_,_) in DATA_FILES.items()
    }
    train,test = read_normal_rdata(directory)
    report = run_independent_runs(train,test)
    report["source_files"] = provenance
    return report


def render_markdown(report: dict) -> str:
    lines = [
        "# Rieth TEP: independently seeded normal-run holdout", "",
        "Distinct training/calibration/validation simulation runs and 10 external",
        "**separately seeded normal test trajectories**. All runs remain TEP mode 1.",
        "No fault-based algorithm or threshold selection and no fault-test data.",
        "",
        "| Fold | Policy | Detector | Calibration episodes / active | Untouched normal validation episodes / active | External 10 runs: total episodes | Median episodes per run | External total active samples |",
        "|:--|:--|:--|:--|:--|--:|--:|--:|",
    ]
    for row in report["rows"]:
        lines.append(
            f"| {row['fold']} | {row['policy']} | {row['method']} | "
            f"{row['calibration']['episodes']}/{row['calibration']['active_samples']} | "
            f"{row['untouched_training_normal_validation']['episodes']}/{row['untouched_training_normal_validation']['active_samples']} | "
            f"{row['external_episodes']['sum']} | {row['external_episodes']['median']} | "
            f"{row['external_active_samples']['sum']} |"
        )
    lines += ["", "## Limitations", ""]
    lines.extend("- "+v for v in report["limitations"])
    if "source_files" in report:
        lines += ["", "## Harvard Dataverse original data SHA-256", ""]
        for p in report["source_files"].values():
            lines.append(f"- {p['file_persistent_id']}: {p['sha256']}")
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict, folder: Path) -> tuple[Path, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    js = folder/"tep_rieth_normal_report.json"
    md = folder/"tep_rieth_normal_scoreboard.md"
    js.write_text(json.dumps(report,indent=2,ensure_ascii=False,sort_keys=True)+"\n",encoding="utf-8")
    md.write_text(render_markdown(report),encoding="utf-8")
    return js,md


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Independently seeded Rieth TEP healthy-only monitor validation")
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--local-only", action="store_true", help="Use already downloaded original RData")
    args=parser.parse_args(argv)
    try:
        report=run_external(args.data_dir,download=not args.local_only)
        if args.output_dir:
            files=write_report(report,args.output_dir)
            print("Reports: "+", ".join(map(str,files)))
        print(render_markdown(report))
    except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
