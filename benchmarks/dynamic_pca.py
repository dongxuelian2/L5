"""Causal lag-augmented PCA baselines on multivariate industrial time series.

At time t the feature vector is [x_t, x_{t-1}, x_{t-2}] (fixed two past
lags). At the start of *each* independent record, nonexistent past
observations are replaced with the feature-wise mean of normal FIT data,
never the first test observation or a future value.

The lag-augmented eigenspace, standardized feature centers/scales, and
lag padding are learned exclusively on the normal-fit partition; thresholds
are calibrated exclusively on the chronological healthy-calibration partition.
No fault labels or held-out test series participate in either step.
"""
from __future__ import annotations

from typing import Sequence
import numpy as np

from .monitoring import as_matrix


class DynamicPCAMonitor:
    """Q residual or Hotelling T² over causally lagged measurements."""
    history_dependent = True

    def __init__(
        self, mode: str = "q", *, lags: int = 2,
        variance: float = 0.90, max_components: int = 20,
    ):
        if mode not in ("q", "t2"):
            raise ValueError("Dynamic PCA mode must be q or t2.")
        if not isinstance(lags, int) or isinstance(lags, bool) or lags < 1 or lags > 8:
            raise ValueError("Number of historical lags must be an integer in [1,8].")
        if not np.isfinite(variance) or not 0.5 <= variance < 1:
            raise ValueError("Target training variance must be in [0.5,1).")
        if not isinstance(max_components, int) or isinstance(max_components, bool) or max_components < 1:
            raise ValueError("Maximum PCA components must be positive.")
        self.mode, self.lags = mode, lags
        self.variance, self.max_components = float(variance), max_components
        self.name = f"dpca-{mode}-lag{lags}"

    def _lag_matrix(self, samples: np.ndarray) -> np.ndarray:
        """Causal feature windows; reset lagged state at every record boundary."""
        if not hasattr(self, "pad_center"):
            raise ValueError("Fit Dynamic PCA before scoring.")
        data = as_matrix(samples, features=self.features)
        padded = np.concatenate(
            [np.broadcast_to(self.pad_center, (self.lags, self.features)), data],
            axis=0,
        )
        # Block zero is current, block k is k observations into the past.
        return np.concatenate([
            padded[self.lags - lag:self.lags - lag + len(data)]
            for lag in range(self.lags + 1)
        ], axis=1)

    def fit(self, train: np.ndarray) -> None:
        data = as_matrix(train)
        if len(data) < max(30, self.lags + 3):
            raise ValueError("Dynamic PCA requires at least 30 normal fit observations.")
        self.features = data.shape[1]
        self.pad_center = data.mean(axis=0)
        expanded = self._lag_matrix(data)
        self.center = expanded.mean(axis=0)
        self.scale = np.maximum(expanded.std(axis=0, ddof=1), 1e-10)
        z = (expanded - self.center) / self.scale
        _, singular, vt = np.linalg.svd(z, full_matrices=False)
        eigenvalues = singular**2 / (len(z) - 1)
        total = float(eigenvalues.sum())
        if not np.isfinite(total) or total <= 1e-12:
            raise ValueError("Dynamic PCA requires varying normal training measurements.")
        count = int(np.searchsorted(np.cumsum(eigenvalues) / total, self.variance)) + 1
        k = max(1, min(count, self.max_components, expanded.shape[1] - 1, len(eigenvalues)))
        self.components = vt[:k]
        self.eigenvalues = np.maximum(eigenvalues[:k], 1e-10)
        self.retained_variance = float(eigenvalues[:k].sum() / total)

    def _decompose(self, samples: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        if not hasattr(self, "components"):
            raise ValueError("Fit Dynamic PCA before scoring.")
        z = (self._lag_matrix(samples) - self.center) / self.scale
        projected = z @ self.components.T
        residual = z - projected @ self.components
        return projected, residual

    def score(self, samples: np.ndarray) -> np.ndarray:
        projected, residual = self._decompose(samples)
        if self.mode == "q":
            scores = np.einsum("ij,ij->i", residual, residual)
        else:
            scores = np.sum(projected**2 / self.eigenvalues, axis=1)
        if not np.isfinite(scores).all():
            raise ValueError("Non-finite dynamic PCA statistics.")
        return scores

    def explain_at(
        self, samples: np.ndarray, index: int,
        feature_names: Sequence[str], count: int = 5,
    ) -> list[str]:
        """History-aware statistical contributions aggregated across time lags.

        These are descriptive feature weights, not causal fault attribution.
        """
        if not 0 <= index < len(samples):
            raise ValueError("Explanation index must be in the observed prefix.")
        if len(feature_names) != self.features:
            raise ValueError("Wrong number of feature names.")
        projected, residual = self._decompose(np.asarray(samples[:index + 1]))
        if self.mode == "q":
            weights = (residual[-1]**2).reshape(self.lags + 1, self.features).sum(axis=0)
        else:
            # Descriptive leverage only; no additive causal decomposition.
            leverage = np.abs(self.components.T @ (projected[-1] / np.sqrt(self.eigenvalues)))
            weights = leverage.reshape(self.lags + 1, self.features).sum(axis=0)
        order = sorted(range(self.features), key=lambda i: (-float(weights[i]), i))
        return [feature_names[i] for i in order[:count]]

    def explain(
        self, sample: np.ndarray, feature_names: Sequence[str], count: int = 5,
    ) -> list[str]:
        raise ValueError("Dynamic PCA attribution requires the observed prefix via explain_at().")

    def metadata(self) -> dict:
        if not hasattr(self, "components"):
            raise ValueError("Fit Dynamic PCA before requesting metadata.")
        return {
            "statistic": "lagged PCA squared prediction error Q"
            if self.mode == "q" else "lagged PCA Hotelling T-squared",
            "features": self.features,
            "lagged_features": self.features * (self.lags + 1),
            "causal_past_lags": self.lags,
            "padded_history": "normal-fit per-feature mean at each record start",
            "components": len(self.components),
            "retained_training_variance": round(self.retained_variance, 6),
            "target_training_variance": self.variance,
            "max_components": self.max_components,
            "history_reset": "independent file and observation abstention boundary",
            "attribution": "descriptive feature weights summed across time lags",
        }
