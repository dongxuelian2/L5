"""Dataset-neutral monitors shared by workspaces and research benchmarks."""
from __future__ import annotations

import math
from typing import Protocol, Sequence

import numpy as np


def as_matrix(rows: Sequence[Sequence[float]], *, features: int | None = None) -> np.ndarray:
    data = np.asarray(rows, dtype=np.float64)
    if data.ndim != 2 or len(data) < 1 or data.shape[1] < 1:
        raise ValueError("Expected a nonempty, two-dimensional numeric time series.")
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
    history_dependent = False

    def fit(self, train: np.ndarray) -> None:
        data = as_matrix(train)
        if len(data) < 3:
            raise ValueError('Robust scale fitting requires at least three normal observations.')
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
    history_dependent = False
    def __init__(self, mode: str = "q", variance: float = 0.90, max_components: int = 20):
        if mode not in ("q", "t2"):
            raise ValueError("PCA mode must be q or t2.")
        if not 0.5 <= variance < 1:
            raise ValueError("variance must be in [0.5,1).")
        if not isinstance(max_components, int) or isinstance(max_components, bool) or max_components < 1:
            raise ValueError("max_components must be positive.")
        self.mode, self.variance, self.max_components = mode, variance, max_components
        self.name = f"pca-{mode}"

    def fit(self, train: np.ndarray) -> None:
        data = as_matrix(train)
        if len(data) < 3:
            raise ValueError("PCA needs at least three observations.")
        if data.shape[1] < 2:
            raise ValueError("PCA needs at least two signals; use Max-Z for one signal.")
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
    if not isinstance(consecutive, int) or isinstance(consecutive, bool) or consecutive < 1:
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
