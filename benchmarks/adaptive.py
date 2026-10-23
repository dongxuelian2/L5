"""Conservative causal baseline adaptation for industrial channel residuals.

This is an experimental, *predeclared* detector, not a validated plant
operating-state estimator. Each new record starts from normal-training
robust medians; every sample is scored BEFORE updating the reference.

An adaptation guard freezes updates on large individual channel deviations
but does NOT prevent a slowly developing physical fault being learned away.
That failure mode is explicitly audited in the companion benchmark.
"""
from __future__ import annotations

from typing import Sequence

import numpy as np

from .monitoring import as_matrix


class AdaptiveMaxZMonitor:
    name = "adaptive-maxz"
    history_dependent = True

    def __init__(
        self, rate: float = 0.02,
        guard_z: float = 2.5,
        max_center_shift_z: float = 1.5,
    ):
        if not np.isfinite(rate) or not 0 < rate < 1:
            raise ValueError("Adaptation rate must be finite and in (0,1).")
        if not np.isfinite(guard_z) or guard_z <= 0:
            raise ValueError("Adaptation guard must be positive and finite.")
        if not np.isfinite(max_center_shift_z) or max_center_shift_z <= 0:
            raise ValueError("Center displacement cap must be positive and finite.")
        self.rate = float(rate)
        self.guard_z = float(guard_z)
        self.max_center_shift_z = float(max_center_shift_z)

    def fit(self, train: np.ndarray) -> None:
        x = as_matrix(train)
        if len(x) < 3:
            raise ValueError('Adaptive scale fitting requires at least three normal observations.')
        self.center = np.median(x, axis=0)
        mad = 1.4826 * np.median(np.abs(x - self.center), axis=0)
        std = np.std(x, axis=0, ddof=1)
        self.scale = np.maximum(mad, np.maximum(std * .05, 1e-10))
        self.features = x.shape[1]

    def _contributions(self, samples: np.ndarray) -> np.ndarray:
        if not hasattr(self, "center"):
            raise ValueError("Fit the adaptive monitor before scoring.")
        data = as_matrix(samples, features=self.features)
        center = self.center.copy()
        bounds = self.max_center_shift_z * self.scale
        contributions = np.empty_like(data)
        for i, row in enumerate(data):
            z = (row - center) / self.scale
            contributions[i] = np.abs(z)
            # Never adapt a gross channel departure; each feature is gated
            # separately to avoid corrupting all centers on a single outlier.
            eligible = np.abs(z) <= self.guard_z
            proposal = center + self.rate * (row - center) * eligible
            center = np.clip(proposal, self.center - bounds, self.center + bounds)
        if not np.isfinite(contributions).all():
            raise ValueError("Non-finite adaptive detector scores.")
        return contributions

    def score(self, samples: np.ndarray) -> np.ndarray:
        return np.max(self._contributions(samples), axis=1)

    def explain_at(
        self, samples: np.ndarray, index: int,
        feature_names: Sequence[str], count: int = 5,
    ) -> list[str]:
        if not 0 <= index < len(samples):
            raise ValueError("Explanation index must lie within the observed prefix.")
        if len(feature_names) != self.features:
            raise ValueError("Feature names must match model dimensions.")
        contributions = self._contributions(samples[:index + 1])[-1]
        order = sorted(range(self.features), key=lambda i: (-float(contributions[i]), i))
        return [feature_names[i] for i in order[:count]]

    def explain(self, sample: np.ndarray, feature_names: Sequence[str], count: int = 5) -> list[str]:
        raise ValueError("Adaptive attribution requires observed history via explain_at().")

    def metadata(self) -> dict:
        if not hasattr(self, "center"):
            raise ValueError("Fit the adaptive monitor before metadata.")
        return {
            "name": self.name,
            "features": self.features,
            "statistic": "max per-channel residual to causal gated adaptive center",
            "rate": self.rate,
            "guard_z": self.guard_z,
            "max_center_shift_z": self.max_center_shift_z,
            "score_before_update": True,
            "history_reset": "file boundary and observations requiring abstention",
            "parameters": "precommitted; no tuning on held-out faults",
        }
