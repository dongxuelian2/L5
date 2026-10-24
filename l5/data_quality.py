"""Measured-data summaries and display segments; no interpolation or resampling."""
from __future__ import annotations

import numpy as np


def cadence(times):
    steps = np.diff(times)
    positive = steps[steps > 0]
    typical = float(np.median(positive)) if len(positive) else None
    # A gap is an explicit display policy, distinct from ordinary irregularity.
    threshold = 5 * typical if typical else None
    gaps = [dict(start=float(times[i]), end=float(times[i+1]), duration=float(step))
            for i, step in enumerate(steps) if threshold and step > threshold]
    irregular = int(np.sum((positive <= threshold) & (np.abs(positive - typical) > max(1e-9, typical * .05)))) if typical else 0
    unique, counts = np.unique(times, return_counts=True)
    duplicates = [dict(time=float(t), count=int(c)) for t, c in zip(unique, counts) if c > 1]
    return dict(typicalInterval=typical, gapThreshold=threshold, gaps=gaps, gapCount=len(gaps),
                irregularCount=irregular, irregular=bool(irregular), duplicates=duplicates,
                duplicateCount=int(np.sum(counts - 1)))


def segment_ids(times, values, gap_threshold=None):
    """IDs survive display sampling, so no sampled path bridges a hidden hole."""
    finite = np.isfinite(values)
    breaks = np.ones(len(times), dtype=bool)
    if len(times) > 1:
        breaks[1:] = ~finite[1:] | ~finite[:-1]
        if gap_threshold:
            breaks[1:] |= np.diff(times) > gap_threshold
    return np.cumsum(breaks)


def runs(times, mask, gap_threshold=None):
    spans, first, last, count = [], None, None, 0
    for t, active in zip(times, mask):
        if first is not None and (not active or (gap_threshold and t - last > gap_threshold)):
            spans.append(dict(start=float(first), end=float(last), count=count))
            first, count = None, 0
        if active:
            if first is None:
                first = t
            last, count = t, count + 1
    if first is not None:
        spans.append(dict(start=float(first), end=float(last), count=count))
    return spans


def summarize(times, values, names, *, source_values=None, invalid_times=()):
    source_values = values if source_values is None else source_values
    sampling = cadence(times)
    signals = {}
    for i, name in enumerate(names):
        raw = source_values[:, i]
        valid = raw[np.isfinite(raw)]
        measured = np.isfinite(values[:, i])
        missing = int(np.sum(~np.isfinite(raw)))
        signals[name] = dict(totalCount=len(raw), validCount=int(measured.sum()), finiteCount=len(valid),
            missing=missing, missingFraction=missing / len(raw) if len(raw) else 0,
            invalidTimeMeasurements=int(len(valid) - measured.sum()),
            min=float(valid.min()) if len(valid) else None, max=float(valid.max()) if len(valid) else None,
            mean=float(valid.mean()) if len(valid) else None, std=float(valid.std()) if len(valid) else None,
            missingSpans=runs(times, ~measured, sampling['gapThreshold']),
            availableSpans=runs(times, measured, sampling['gapThreshold']))
    return dict(totalCount=len(source_values), timedCount=len(times), invalidTimeCount=len(invalid_times),
                invalidTimes=list(invalid_times), start=float(times[0]), end=float(times[-1]),
                **sampling, signals=signals)
