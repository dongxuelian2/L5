"""Dataset-neutral anomaly monitors and chronological evaluation for industrial time series.

All fitting and empirical threshold selection must use normal TRAINING records.
Test-set labels and fault onset are consumed only by evaluate_case().
The generic monitors are shared with the L5 workspace engine.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
from typing import Sequence

import numpy as np


from l5.monitoring import (
    Monitor, MaxZMonitor, PCAMonitor, as_matrix, split_normal_training,
    calibrate, persistent_alarms,
)


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
    detection_delay_minutes: float | None
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
    if isinstance(seconds_per_sample, bool) or not math.isfinite(seconds_per_sample) or seconds_per_sample <= 0:
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
        detection_delay_minutes=(first - onset_sample) * seconds_per_sample / 60 if first is not None else None,
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
