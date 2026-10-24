"""Explicit duplicate, coverage, interpolation and fill policies on one time grid."""
from __future__ import annotations

import numpy as np


PROVENANCE = {0: 'missing', 1: 'measured', 2: 'interpolated', 3: 'held',
              4: 'aggregated', 5: 'fixed-fill', 6: 'statistic-fill', 7: 'derived', 8: 'nearest', 9: 'processed-source'}
METHODS = ('nearest', 'linear', 'previous', 'mean', 'min', 'max')
MISSING_METHODS = ('keep', 'linear', 'previous', 'fixed', 'statistic')
DUPLICATES = ('first', 'last', 'mean', 'error')


def deduplicate(times, values, observed, policy):
    unique, starts, counts = np.unique(times, return_index=True, return_counts=True)
    duplicates = int(np.sum(counts - 1))
    if duplicates and policy == 'error':
        raise ValueError('Duplicate timestamps conflict with the selected error policy.')
    if policy in ('first', 'error', 'last'):
        indexes = starts + counts - 1 if policy == 'last' else starts
        return unique, values[indexes], observed[indexes], duplicates
    result, masks = [], []
    for start, count in zip(starts, counts):
        group = values[start:start + count]
        valid = np.isfinite(group)
        result.append(float(group[valid].mean()) if valid.any() else np.nan)
        masks.append(bool(valid.any() and observed[start:start + count][valid].all()))
    return unique, np.asarray(result), np.asarray(masks), duplicates


def resample(times, values, observed, grid, *, method, interval, max_gap, tolerance=1e-8):
    result = np.full(len(grid), np.nan)
    codes = np.zeros(len(grid), dtype=np.uint8)
    measured = np.zeros(len(grid), dtype=bool)
    inside = (grid >= times[0] - tolerance) & (grid <= times[-1] + tolerance)
    right = np.searchsorted(times, grid)
    safe = np.minimum(right, len(times) - 1)
    previous = np.maximum(right - 1, 0)
    safe = np.where(np.abs(times[previous] - grid) < np.abs(times[safe] - grid), previous, safe)
    # All computations use seconds relative to the grid origin, avoiding Unix-sized tolerances.
    exact = inside & np.isclose(times[safe], grid, rtol=0, atol=tolerance)
    if method in ('mean', 'min', 'max'):
        # Left-closed windows [g, g + interval); never extend the source's coverage.
        lefts = np.searchsorted(times, grid, side='left')
        rights = np.searchsorted(times, grid + interval, side='left')
        for i in np.flatnonzero(inside):
            a, b = lefts[i], rights[i]
            valid = np.flatnonzero(np.isfinite(values[a:b])) + a
            if len(valid):
                result[i] = getattr(np, method)(values[valid])
                codes[i] = 4
                measured[i] = observed[valid].all()
        return result, codes, measured
    finite_exact = exact & np.isfinite(values[safe])
    result[finite_exact] = values[safe[finite_exact]]
    codes[finite_exact] = np.where(observed[safe[finite_exact]], 1, 9)
    measured[finite_exact] = observed[safe[finite_exact]]
    candidates = np.flatnonzero(inside & ~exact & (right > 0) & (right < len(times)))
    if not len(candidates):
        return result, codes, measured
    r = right[candidates]
    l = r - 1
    span = times[r] - times[l]
    age = grid[candidates] - times[l]
    if method == 'linear':
        valid = (span <= max_gap + tolerance) & np.isfinite(values[l]) & np.isfinite(values[r])
        idx = candidates[valid]
        result[idx] = values[l[valid]] + (values[r[valid]] - values[l[valid]]) * age[valid] / span[valid]
        codes[idx] = 2
    elif method == 'previous':
        valid = (age <= max_gap + tolerance) & np.isfinite(values[l])
        idx = candidates[valid]
        result[idx] = values[l[valid]]
        codes[idx] = 3
    else:
        nearest = np.where(age <= span - age, l, r)
        valid = (span <= max_gap + tolerance) & (np.abs(times[nearest] - grid[candidates]) <= max_gap + tolerance) & np.isfinite(values[nearest])
        idx = candidates[valid]
        result[idx] = values[nearest[valid]]
        codes[idx] = 8
    return result, codes, measured


def fill_missing(grid, values, codes, observed, *, policy, max_gap, coverage, statistic_values,
                 anchor_times=None, anchor_values=None, anchor_observed=None):
    result, codes, observed = values.copy(), codes.copy(), observed.copy()
    method = policy['method']
    inside = (grid >= coverage[0]) & (grid <= coverage[1])
    missing = ~np.isfinite(values) & inside
    effective = dict(policy)
    if method in ('linear', 'previous'):
        anchor_times = grid if anchor_times is None else anchor_times
        anchor_values = values if anchor_values is None else anchor_values
        anchor_observed = observed if anchor_observed is None else anchor_observed
        finite = np.isfinite(anchor_values)
        if finite.any():
            if method == 'previous':
                t, v = anchor_times[finite], anchor_values[finite]
                previous = np.searchsorted(t, grid, side='right') - 1
                take = missing & (previous >= 0) & (grid - t[np.maximum(previous, 0)] <= max_gap)
                result[take], codes[take] = v[previous[take]], 3
            else:
                filled, _, _ = resample(anchor_times[finite], anchor_values[finite], anchor_observed[finite], grid,
                    method=method, interval=1, max_gap=max_gap)
                take = missing & np.isfinite(filled)
                result[take], codes[take] = filled[take], 2
    elif method in ('fixed', 'statistic'):
        value = policy.get('value')
        if method == 'statistic':
            valid = statistic_values[np.isfinite(statistic_values)]
            value = float(getattr(np, policy['statistic'])(valid)) if len(valid) else None
            effective['computedValue'] = value
            effective['validSourceSamples'] = len(valid)
        if value is not None:
            result[missing], codes[missing] = value, 5 if method == 'fixed' else 6
    # No filled or interpolated value becomes an original observation.
    observed[missing] = False
    return result, codes, observed, effective
