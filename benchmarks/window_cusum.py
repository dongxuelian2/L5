"""Predeclared finite-lookback, two-sided Page-style CUSUM.

At timestamp t and channel j:
  S+(t,j) = max(0, max_{1<=h<=W} sum_{i=t-h+1}^t (z(i,j)-k))
  S-(t,j) = max(0, max_{1<=h<=W} sum_{i=t-h+1}^t (-z(i,j)-k)).
Only the observed prefix matters; unlike unbounded Page CUSUM, old drift
cannot remain in the accumulator beyond the trailing W observations.

This is a maximum-over-recent-suffixes statistic, not a mechanical CUSUM
alarm reset. W=12 / 24 and k=0.5 are fixed before looking at fault tests.
"""
from __future__ import annotations

import numpy as np

from .monitoring import as_matrix
from .temporal import TemporalMaxMonitor


class WindowCUSUMMonitor(TemporalMaxMonitor):
    def __init__(self, window: int = 12, reference: float = 0.5):
        if not isinstance(window, int) or isinstance(window, bool) or window < 2:
            raise ValueError("Window must be an integer of at least two observations.")
        super().__init__("cusum", reference=reference)
        self.window = window
        self.name = f"window-cusum-{window}"

    def _features_at_each_time(self, samples: np.ndarray) -> np.ndarray:
        if not hasattr(self, "center"):
            raise ValueError("Fit before scoring.")
        x = as_matrix(samples, features=self.features)
        z = (x - self.center) / self.scale
        # Pair of prefix sums. At time t, enumerate only suffixes ending
        # at t of at most 'window' observations. Never inspect future data.
        positive = z - self.reference
        negative = -z - self.reference
        pos_prefix = np.vstack((np.zeros((1, self.features)), np.cumsum(positive, axis=0)))
        neg_prefix = np.vstack((np.zeros((1, self.features)), np.cumsum(negative, axis=0)))
        contributions = np.empty_like(z)
        for t in range(len(z)):
            begin = max(0, t + 1 - self.window)
            best_pos = pos_prefix[t + 1] - np.min(pos_prefix[begin:t + 1], axis=0)
            best_neg = neg_prefix[t + 1] - np.min(neg_prefix[begin:t + 1], axis=0)
            contributions[t] = np.maximum(0, np.maximum(best_pos, best_neg))
        if not np.isfinite(contributions).all():
            raise ValueError("Window CUSUM statistic overflowed.")
        return contributions

    def metadata(self) -> dict:
        result = super().metadata()
        result.update({
            "statistic": "max trailing-window two-sided Page-style suffix sum",
            "window_samples": self.window,
            "bounded_lookback": True,
            "reference_drift": self.reference,
            "state_reset": "per-file and after the specified trailing window",
        })
        return result
