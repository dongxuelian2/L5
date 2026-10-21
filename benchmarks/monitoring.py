"""Dataset-neutral anomaly monitors and chronological evaluation for industrial time series.

All fitting and empirical threshold selection must use normal TRAINING records.
Test-set labels and fault onset are consumed only by evaluate_case().
NumPy is an explicit benchmark-only dependency; TripLens runtime remains stdlib.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
from typing import Protocol, Sequence

import numpy as np


def as_matrix(rows: Sequence[Sequence[float]], *, features: int | None = None) -> np.ndarray:
    data = np.asarray(rows, dtype=np.float64)
    if data.ndim != 2 or len(data) < 1 or data.shape[1] < 2:
        raise ValueError("Expected a nonempty, two-dimensional multivariate time series.")
    if features is not None and data.shape[1] != features:
        raise ValueError(f"Expected {features} variables; received {data.shape[1]}.")
    if not np.isfinite(data).all():
        raise ValueError("Monitor inputs must contain only finite measurements.")
    return data


def split_normal_training(rows: Sequence[Sequence[float]], fit_fraction: float = 0.7):
    """Chronological fit/calibration partition; zero test examples are used."""
    data = as_matrix(rows)
    if not 0.5 <= fit_fraction <= 0.9:
        raise ValueError("fit_fraction must be between 0.5 and 0.9.")
    position = int(len(data) * fit_fraction)
    if position < 30 or len(data) - position < 30:
        raise ValueError("Need at least 30 fit and 30 calibration observations.")
    return data[:position].copy(), data[position:].copy()


class Monitor(Protocol):
    name: str

    def fit(self, train: np.ndarray) -> None: ...
    def score(self, samples: np.ndarray) -> np.ndarray: ...
    def explain(self, sample: np.ndarray, feature_names: Sequence[str], count: int = 5) -> list[str]: ...
    def metadata(self) -> dict: ...


def _top_names(weights: np.ndarray, feature_names: Sequence[str], count: int) -> list[str]:
    if len(weights) != len(feature_names):
        raise ValueError("Incorrect number of feature names.")
    # Stable ties: use variable index as secondary sort key.
    order = sorted(range(len(weights)), key=lambda i: (-float(weights[i]), i))
    return [feature_names[i] for i in order[:count]]


class MaxZMonitor:
    name = "robust-maxz"

    def fit(self, train: np.ndarray) -> None:
        data = as_matrix(train)
        self.center = np.median(data, axis=0)
        mad = 1.4826 * np.median(np.abs(data - self.center), axis=0)
        std = np.std(data, axis=0, ddof=1)
        # MAD can vanish on quantized or constant channels.
        self.scale = np.maximum(mad, np.maximum(std * 0.05, 1e-10))
        self.features = data.shape[1]

    def _standardize(self, samples: np.ndarray) -> np.ndarray:
        return (as_matrix(samples, features=self.features) - self.center) / self.scale

    def score(self, samples: np.ndarray) -> np.ndarray:
        return np.max(np.abs(self._standardize(samples)), axis=1)

    def explain(self, sample: np.ndarray, feature_names: Sequence[str], count: int = 5) -> list[str]:
        return _top_names(np.abs(self._standardize(np.asarray([sample]))[0]), feature_names, count)

    def metadata(self) -> dict:
        return {"statistic": "maximum absolute robust z-score", "features": self.features}


class PCAMonitor:
    def __init__(self, mode: str = "q", variance: float = 0.90, max_components: int = 20):
        if mode not in ("q", "t2"):
            raise ValueError("PCA mode must be q or t2.")
        if not 0.5 <= variance < 1:
            raise ValueError("variance must be in [0.5,1).")
        if max_components < 1:
            raise ValueError("max_components must be positive.")
        self.mode, self.variance, self.max_components = mode, variance, max_components
        self.name = f"pca-{mode}"

    def fit(self, train: np.ndarray) -> None:
        data = as_matrix(train)
        if len(data) < 3:
            raise ValueError("PCA needs at least three observations.")
        self.center = data.mean(axis=0)
        self.scale = np.maximum(data.std(axis=0, ddof=1), 1e-10)
        standardized = (data - self.center) / self.scale
        _, singular, vt = np.linalg.svd(standardized, full_matrices=False)
        eigenvalues = (singular ** 2) / (len(data) - 1)
        total = float(eigenvalues.sum())
        if not np.isfinite(total) or total <= 1e-12:
            raise ValueError("PCA requires nonconstant training data.")
        count = int(np.searchsorted(np.cumsum(eigenvalues) / total, self.variance)) + 1
        k = max(1, min(count, self.max_components, data.shape[1] - 1, len(eigenvalues)))
        self.components = vt[:k]
        self.eigenvalues = np.maximum(eigenvalues[:k], 1e-10)
        self.retained_variance = float(eigenvalues[:k].sum() / total)
        self.features = data.shape[1]

    def _decompose(self, samples: np.ndarray):
        z = (as_matrix(samples, features=self.features) - self.center) / self.scale
        projected = z @ self.components.T
        residual = z - projected @ self.components
        return z, projected, residual

    def score(self, samples: np.ndarray) -> np.ndarray:
        _, projected, residual = self._decompose(samples)
        if self.mode == "q":
            return np.einsum("ij,ij->i", residual, residual)
        return np.sum((projected ** 2) / self.eigenvalues, axis=1)

    def explain(self, sample: np.ndarray, feature_names: Sequence[str], count: int = 5) -> list[str]:
        _, projected, residual = self._decompose(np.asarray([sample]))
        if self.mode == "q":
            weights = residual[0] ** 2
        else:
            # Descriptive leverage, not a causally valid root-cause attribution.
            weights = np.abs(self.components.T @ (projected[0] / np.sqrt(self.eigenvalues)))
        return _top_names(weights, feature_names, count)

    def metadata(self) -> dict:
        return {
            "statistic": "squared prediction error (Q)" if self.mode == "q" else "Hotelling T-squared",
            "features": self.features,
            "components": len(self.components),
            "retained_training_variance": round(self.retained_variance, 6),
            "target_training_variance": self.variance,
            "max_components": self.max_components,
        }


def build_monitor(name: str) -> Monitor:
    if name == MaxZMonitor.name:
        return MaxZMonitor()
    if name in ("pca-q", "pca-t2"):
        return PCAMonitor(mode=name.split("-")[1])
    if name in ("cusum-maxz", "ewma-maxz"):
        from .temporal import CUSUMMonitor, EWMAMonitor
        return CUSUMMonitor() if name == "cusum-maxz" else EWMAMonitor()
    if name in ("window-cusum-12", "window-cusum-24"):
        from .window_cusum import WindowCUSUMMonitor
        return WindowCUSUMMonitor(window=int(name.rsplit("-", 1)[-1]))
    if name == "adaptive-maxz":
        from .adaptive import AdaptiveMaxZMonitor
        return AdaptiveMaxZMonitor()
    if name in ("dpca-q-lag2", "dpca-t2-lag2"):
        from .dynamic_pca import DynamicPCAMonitor
        return DynamicPCAMonitor(mode="q" if name == "dpca-q-lag2" else "t2", lags=2)
    raise ValueError(f"Unknown method {name!r}.")


def calibrate(monitor: Monitor, calibration: np.ndarray, alpha: float) -> float:
    """Fixed empirical threshold; calibration data must be healthy train only.

    Higher order statistic, strict > comparison. Not a statistical guarantee of
    false-alarm probability (serial correlation and distribution shift matter).
    """
    if not 0 < alpha < 0.5:
        raise ValueError("alpha must be in (0, 0.5).")
    scores = monitor.score(calibration)
    if scores.ndim != 1 or len(scores) < 30 or not np.isfinite(scores).all():
        raise ValueError("Need 30+ finite calibration scores.")
    index = int(math.ceil((len(scores) - 1) * (1 - alpha)))
    return float(np.sort(scores)[index])


def persistent_alarms(scores: Sequence[float], threshold: float, consecutive: int) -> tuple[bool, ...]:
    if consecutive < 1:
        raise ValueError("consecutive must be positive.")
    if not math.isfinite(threshold):
        raise ValueError("threshold must be finite.")
    run = 0
    alarms = []
    for score in scores:
        if not math.isfinite(float(score)):
            raise ValueError("Scores must be finite.")
        run = run + 1 if float(score) > threshold else 0
        alarms.append(run >= consecutive)
    return tuple(alarms)


@dataclass(frozen=True)
class CaseMetrics:
    source: str
    fault_id: int
    samples: int
    onset_sample: int | None
    false_alarm_samples: int
    normal_samples: int
    false_alarm_rate: float
    detected_after_onset: bool | None
    detected_within_early_window: bool | None
    detection_delay_samples: int | None
    detection_delay_minutes: int | None
    detection_fraction_post_onset: float | None
    first_post_onset_alarm_sample: int | None
    first_post_onset_alarm_variables: list[str]


def evaluate_case(
    *,
    source: str,
    fault_id: int,
    samples: np.ndarray,
    monitor: Monitor,
    threshold: float,
    consecutive: int,
    feature_names: Sequence[str],
    onset_sample: int | None,
    seconds_per_sample: int,
    early_window_samples: int = 20,
) -> CaseMetrics:
    data = as_matrix(samples, features=len(feature_names))
    if onset_sample is not None and not 0 < onset_sample < len(data):
        raise ValueError("Fault onset must be within the test sequence.")
    if seconds_per_sample < 1:
        raise ValueError("Sampling interval must be positive.")
    if early_window_samples < 1:
        raise ValueError("Early window must contain at least one sample.")
    scores = monitor.score(data)
    alarms = persistent_alarms(scores, threshold, consecutive)
    normal_count = len(data) if onset_sample is None else onset_sample
    false_count = sum(alarms[:normal_count])
    # Do not call a continuously active pre-fault false alarm a newly detected fault.
    first = next((i for i in range(normal_count, len(data)) if alarms[i] and (i == 0 or not alarms[i - 1])), None) if onset_sample is not None else None
    fraction = None
    if onset_sample is not None:
        fraction = sum(alarms[onset_sample:]) / (len(data) - onset_sample)
    return CaseMetrics(
        source=source,
        fault_id=fault_id,
        samples=len(data),
        onset_sample=onset_sample,
        false_alarm_samples=false_count,
        normal_samples=normal_count,
        false_alarm_rate=round(false_count / normal_count, 6),
        detected_after_onset=first is not None if onset_sample is not None else None,
        detected_within_early_window=(first is not None and first - onset_sample <= early_window_samples) if onset_sample is not None else None,
        detection_delay_samples=first - onset_sample if first is not None else None,
        detection_delay_minutes=(first - onset_sample) * seconds_per_sample // 60 if first is not None else None,
        detection_fraction_post_onset=round(fraction, 6) if fraction is not None else None,
        first_post_onset_alarm_sample=first,
        first_post_onset_alarm_variables=(
            (monitor.explain_at(data, first, feature_names)
             if hasattr(monitor, "explain_at")
             else monitor.explain(data[first], feature_names))
            if first is not None else []
        ),
    )


def summarize_cases(cases: Sequence[CaseMetrics]) -> dict:
    normals = [case for case in cases if case.onset_sample is None]
    faults = [case for case in cases if case.onset_sample is not None]
    if not normals or not faults:
        raise ValueError("Need a healthy test and at least one fault test.")
    healthy = normals[0]
    delays = [c.detection_delay_samples for c in faults if c.detection_delay_samples is not None]
    early = sum(c.detected_within_early_window is True for c in faults)
    pre_fault = sum(c.normal_samples for c in faults)
    pre_false = sum(c.false_alarm_samples for c in faults)
    return {
        "healthy_test_false_alarm_rate": healthy.false_alarm_rate,
        "healthy_test_false_alarm_samples": healthy.false_alarm_samples,
        "fault_test_pre_onset_false_alarm_rate": round(pre_false / pre_fault, 6),
        "faults_evaluated": len(faults),
        "faults_detected": len(delays),
        "fault_detection_fraction": round(len(delays) / len(faults), 6),
        "faults_detected_early": early,
        "early_detection_fraction": round(early / len(faults), 6),
        "mean_detected_delay_samples": round(sum(delays) / len(delays), 3) if delays else None,
        "mean_detected_delay_minutes": round(sum(c.detection_delay_minutes for c in faults if c.detection_delay_minutes is not None) / len(delays), 3) if delays else None,
        "undetected_faults": [c.fault_id for c in faults if c.detection_delay_samples is None],
    }


def checksum(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
