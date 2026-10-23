"""Causal temporal anomaly baselines for multivariate process signals.

CUSUM is a two-sided Page recurrence per channel, NOT a trained fault classifier.
EWMA is a causal exponentially weighted standardized observation deviation.
All state starts fresh per record (the evaluation file boundary), and a score
at time t depends only on fit statistics and observations through time t.

Parameters k=0.5 (CUSUM reference drift) and lambda=0.25 (EWMA smoothing)
are fixed *a priori*: fault-test outcomes may not tune them.
"""
from __future__ import annotations

from typing import Sequence

import numpy as np


class TemporalMaxMonitor:
    """Base for causal history-sensitive maximum-of-channel statistics."""
    history_dependent = True

    def __init__(self, mode: str, *, reference: float = 0.5, smoothing: float = 0.25):
        if mode not in ("cusum", "ewma"):
            raise ValueError("Temporal mode must be 'cusum' or 'ewma'.")
        if not np.isfinite(reference) or reference <= 0:
            raise ValueError("CUSUM reference drift must be positive and finite.")
        if not np.isfinite(smoothing) or not 0 < smoothing <= 1:
            raise ValueError("EWMA smoothing parameter must be in (0,1].")
        self.mode = mode
        self.reference = float(reference)
        self.smoothing = float(smoothing)
        self.name = f"{mode}-maxz"

    def fit(self, train: np.ndarray) -> None:
        from .monitoring import as_matrix

        x = as_matrix(train)
        if len(x) < 3:
            raise ValueError("Temporal monitors need at least three normal training samples.")
        self.center = np.median(x, axis=0)
        mad = 1.4826 * np.median(np.abs(x - self.center), axis=0)
        std = np.std(x, axis=0, ddof=1)
        self.scale = np.maximum(mad, np.maximum(std * 0.05, 1e-10))
        self.features = x.shape[1]

    def _features_at_each_time(self, samples: np.ndarray) -> np.ndarray:
        """Return nonnegative channel contributions using no future samples."""
        from .monitoring import as_matrix

        if not hasattr(self, "center"):
            raise ValueError("Fit the temporal monitor before scoring.")
        x = as_matrix(samples, features=self.features)
        z = (x - self.center) / self.scale
        state = np.zeros(self.features, dtype=np.float64)
        pos = np.zeros(self.features, dtype=np.float64)
        neg = np.zeros(self.features, dtype=np.float64)
        contributions = np.empty_like(z)
        for i, observation in enumerate(z):
            if self.mode == "cusum":
                # Standard two-sided Page CUSUM; history accumulates until
                # evidence dissipates. It does not reset at an alarm.
                pos = np.maximum(0.0, pos + observation - self.reference)
                neg = np.maximum(0.0, neg - observation - self.reference)
                contributions[i] = np.maximum(pos, neg)
            else:
                # A fresh record starts at the healthy reference state 0.
                state = (1.0 - self.smoothing) * state + self.smoothing * observation
                contributions[i] = np.abs(state)
        if not np.isfinite(contributions).all():
            raise ValueError("Temporal statistic overflowed; evidence is not reportable.")
        return contributions

    def score(self, samples: np.ndarray) -> np.ndarray:
        return np.max(self._features_at_each_time(samples), axis=1)

    def explain_at(
        self, samples: np.ndarray, index: int,
        feature_names: Sequence[str], count: int = 5
    ) -> list[str]:
        """Feature-level statistical contributions at a timestamp, not causes.

        A single sample cannot explain history-dependent detectors. Explicit
        sequence + index is mandatory and evaluation never passes future rows.
        """
        if not 0 <= index < len(samples):
            raise ValueError("Explanation index is outside the observed sequence.")
        if len(feature_names) != self.features:
            raise ValueError("Feature labels do not match the monitor.")
        weights = self._features_at_each_time(samples[:index + 1])[-1]
        order = sorted(range(len(weights)), key=lambda j: (-float(weights[j]), j))
        return [feature_names[j] for j in order[:count]]

    def explain(self, sample: np.ndarray, feature_names: Sequence[str], count: int = 5) -> list[str]:
        # Single-timestamp attribution would silently discard the integrated
        # history and invent a false "why". Require explicit explain_at().
        raise ValueError("Temporal attribution requires full observed prefix via explain_at().")

    def metadata(self) -> dict:
        if not hasattr(self, "center"):
            raise ValueError("Fit the temporal monitor before requesting metadata.")
        return {
            "name": self.name,
            "features": self.features,
            "statistic": "two-sided Page CUSUM max across channels"
            if self.mode == "cusum" else "causal EWMA max absolute deviation across channels",
            "reference_drift": self.reference if self.mode == "cusum" else None,
            "smoothing": self.smoothing if self.mode == "ewma" else None,
            "state_reset": "on each evaluation/calibration file boundary",
            "attribution": "history-based statistical contribution, not physical causality",
        }


class CUSUMMonitor(TemporalMaxMonitor):
    def __init__(self, reference: float = 0.5):
        super().__init__("cusum", reference=reference)


class EWMAMonitor(TemporalMaxMonitor):
    def __init__(self, smoothing: float = 0.25):
        super().__init__("ewma", smoothing=smoothing)
