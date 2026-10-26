"""Small, stateless data adapters for the public L5 Streamlit demonstration."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MIN_ROWS = 300
MAX_ROWS = 3000
MAX_SIGNALS = 12
MAX_UPLOAD_BYTES = 2_000_000


def example_data(samples: int = 900) -> pd.DataFrame:
    """Reproducible synthetic process measurements; not Tennessee Eastman data."""
    if not MIN_ROWS <= samples <= MAX_ROWS:
        raise ValueError("Sample count is outside the demonstration budget.")
    rng = np.random.default_rng(2026)
    t = np.arange(samples, dtype=float)
    fault = np.maximum(t - samples * 0.65, 0)
    cycle = np.sin(t / 47)
    return pd.DataFrame({
        "temperature_C": 120 + 0.35 * cycle + rng.normal(0, 0.22, samples) + 0.027 * fault,
        "pressure_kPa": 2700 + 3.8 * cycle + rng.normal(0, 2.4, samples) + 0.36 * fault,
        "cooling_flow_pct": 100 - 0.8 * cycle + rng.normal(0, 0.6, samples) - 0.038 * fault,
        "vibration_mm_s": 1.0 + rng.normal(0, 0.028, samples) + 0.0025 * fault,
    })


def validated_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if not MIN_ROWS <= len(frame) <= MAX_ROWS:
        raise ValueError(f"Use {MIN_ROWS}–{MAX_ROWS} rows for this online demonstration.")
    numeric = frame.select_dtypes(include="number").copy()
    if numeric.empty or numeric.shape[1] > MAX_SIGNALS:
        raise ValueError(f"Choose a CSV with 1–{MAX_SIGNALS} numeric signals.")
    numeric = numeric.replace([np.inf, -np.inf], np.nan)
    if any(numeric[column].notna().sum() == 0 for column in numeric):
        raise ValueError("Every numeric signal must contain at least one finite measurement.")
    return numeric.astype(np.float64)


def load_uploaded_csv(contents: bytes) -> pd.DataFrame:
    if not contents or len(contents) > MAX_UPLOAD_BYTES:
        raise ValueError("The CSV must be nonempty and at most 2 MB.")
    try:
        data = pd.read_csv(BytesIO(contents), nrows=MAX_ROWS + 1)
    except (UnicodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise ValueError("Unable to read a UTF-8 CSV with a header row.") from exc
    return validated_frame(data)


def analyze(frame: pd.DataFrame, algorithms: list[str], signals: list[str], normal_fraction: float) -> tuple[dict, dict]:
    """Call the same numerical implementation used by the full L5 workspace."""
    from l5.analysis import ALGORITHMS, run_analysis

    if not algorithms or any(algorithm not in ALGORITHMS for algorithm in algorithms):
        raise ValueError("Select at least one available L5 detector.")
    if not signals or any(signal not in frame.columns for signal in signals):
        raise ValueError("Select one or more numeric signals.")
    if not 0.35 <= normal_fraction <= 0.60:
        raise ValueError("Normal baseline fraction must be between 35% and 60%.")
    numeric = validated_frame(frame)
    split = int(len(numeric) * normal_fraction)
    config = {
        "signals": signals,
        "baselineRange": [0.0, float(split - 1)],
        "analysisRange": [float(split), float(len(numeric) - 1)],
        "alpha": 0.01,
        "fitFraction": 0.7,
    }
    times = np.arange(len(numeric), dtype=np.float64)
    matrix = numeric.to_numpy(dtype=np.float64)
    completed, errors = {}, {}
    for algorithm in algorithms:
        try:
            completed[algorithm] = run_analysis(times, matrix, list(numeric.columns), {
                **config, "algorithm": algorithm
            })
        except (ValueError, TypeError, FloatingPointError, np.linalg.LinAlgError) as exc:
            errors[algorithm] = str(exc)
    return completed, errors


def tep_table(configuration: str = "A") -> pd.DataFrame:
    """Summarize existing official TEP test results without launching calculations."""
    if configuration not in ("A", "B", "C"):
        raise ValueError("Unknown TEP training configuration.")
    path = ROOT / "examples" / "tep" / "robustness_per_run.csv"
    source = pd.read_csv(path)
    required = {
        "configuration", "algorithm", "status", "faultNumber",
        "detected30m", "detectedEventually", "normalAlarmSamples", "normalSamples",
    }
    if not required.issubset(source.columns):
        raise ValueError("The committed TEP results lack required metric columns.")
    rows = source[(source["configuration"] == configuration) & (source["status"] == "succeeded")]
    faults = rows[rows["faultNumber"] > 0]
    healthy = rows[rows["faultNumber"] == 0]
    detected = faults.groupby("algorithm")[["detected30m", "detectedEventually"]].sum()
    background = healthy.groupby("algorithm")[["normalAlarmSamples", "normalSamples"]].sum()
    summary = detected.join(background, how="inner").reset_index()
    summary = summary.rename(columns={
        "algorithm": "Detector",
        "detected30m": "Detected within 30 min",
        "detectedEventually": "Eventually detected",
        "normalAlarmSamples": "Alarm samples on normal runs",
        "normalSamples": "Normal samples",
    })
    if summary.empty:
        raise ValueError("No verified TEP results for this configuration.")
    return summary.sort_values("Detected within 30 min", ascending=False).reset_index(drop=True)


def tep_faults(configuration: str, algorithm: str) -> pd.DataFrame:
    path = ROOT / "examples" / "tep" / "robustness_per_run.csv"
    source = pd.read_csv(path)
    selected = source[
        (source["configuration"] == configuration)
        & (source["algorithm"] == algorithm)
        & (source["faultNumber"] > 0)
        & (source["status"] == "succeeded")
    ]
    if selected.empty:
        return pd.DataFrame()
    return selected.groupby("faultNumber", as_index=False).agg(
        runs=("detected30m", "size"),
        detected_30m=("detected30m", "sum"),
        detected_eventually=("detectedEventually", "sum"),
    ).rename(columns={"faultNumber": "Fault", "runs": "Runs", "detected_30m": "Detected in 30 min", "detected_eventually": "Eventually detected"})
