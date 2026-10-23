"""CSV ingestion without a predefined process schema."""
from __future__ import annotations

from io import StringIO
import csv

import numpy as np
import pandas as pd

TIME_NAMES = {'time', 'timestamp', 'datetime', 'date', 't', '时间', '日期'}
TIME_UNITS = {'seconds': 1, 'milliseconds': .001, 'minutes': 60, 'hours': 3600}


def prepare_csv(text: str, options: dict) -> tuple[dict, np.ndarray, np.ndarray]:
    if not isinstance(text, str) or not text.strip():
        raise ValueError('Choose a nonempty CSV file.')
    try:
        source = text.lstrip('\ufeff')
        try:
            separator = csv.Sniffer().sniff(source[:65536], delimiters=',;\t|').delimiter
        except csv.Error:
            separator = ','
        frame = pd.read_csv(StringIO(source), sep=separator)
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeError) as error:
        raise ValueError(f'Unable to read CSV: {error}') from error
    frame.columns = [str(c).strip() for c in frame.columns]
    if not len(frame) or not frame.columns.is_unique or any(not c for c in frame.columns):
        raise ValueError('CSV needs data rows and unique, nonempty column names.')
    column = options.get('timeColumn', next((c for c in frame if c.lower() in TIME_NAMES), None))
    notes = []
    if column is None:
        interval = float(options.get('sampleInterval', 1))
        if not np.isfinite(interval) or interval <= 0:
            raise ValueError('Sampling interval must be a positive number of seconds.')
        times = np.arange(len(frame), dtype=float) * interval
        time = {'kind': 'generated', 'column': None, 'sampleInterval': interval, 'origin': None}
    else:
        if column not in frame:
            raise ValueError('Time column does not exist in this CSV.')
        numeric = pd.to_numeric(frame[column], errors='coerce')
        kind = options.get('timeKind', 'auto')
        if kind not in ('auto', 'numeric', 'datetime'):
            raise ValueError('Choose numeric time or a date/time column.')
        if kind == 'numeric' or (kind == 'auto' and numeric.notna().all()):
            unit = options.get('timeUnit', 'seconds')
            if unit not in TIME_UNITS:
                raise ValueError('Unknown time unit.')
            times = numeric.to_numpy(dtype=float) * TIME_UNITS[unit]
            if not np.isfinite(times).all():
                raise ValueError('Numeric time column contains missing or invalid values.')
            time = {'kind': 'numeric', 'column': column, 'sourceUnit': unit, 'origin': None}
        else:
            dates = pd.to_datetime(frame[column], errors='coerce', utc=True, format='mixed')
            if dates.isna().any():
                raise ValueError('Time column contains invalid dates. Choose numeric time or generated time instead.')
            origin = dates.min()
            times = (dates - origin).dt.total_seconds().to_numpy()
            time = {'kind': 'datetime', 'column': column, 'origin': origin.isoformat()}
    order = np.argsort(times, kind='stable')
    if not np.array_equal(order, np.arange(len(frame))):
        frame = frame.iloc[order].reset_index(drop=True)
        times = times[order]
        notes.append('Rows were sorted by time before saving.')
    columns, arrays, ignored = [], [], []
    for name in frame:
        if name == column:
            continue
        values = pd.to_numeric(frame[name], errors='coerce').to_numpy(dtype=float)
        values[~np.isfinite(values)] = np.nan
        valid = values[np.isfinite(values)]
        if not len(valid):
            ignored.append(name)
            continue
        columns.append({'name': name, 'missing': int(np.isnan(values).sum()),
                        'min': float(valid.min()), 'max': float(valid.max())})
        arrays.append(values)
    if not arrays:
        raise ValueError('CSV needs at least one numeric signal besides the time column.')
    data = np.column_stack(arrays)
    missing = int(np.isnan(data).sum())
    if missing:
        notes.append(f'{missing} missing / nonnumeric measurements will use baseline medians during analysis.')
    time.update({'start': float(times[0]), 'end': float(times[-1]), 'unit': 'seconds'})
    metadata = {'rowCount': len(frame), 'columns': columns, 'sourceColumns': list(frame.columns),
                'ignoredColumns': ignored, 'time': time, 'missingCount': missing, 'notes': notes}
    boundary = min(len(times) - 2, max(99, int(len(times) * .2) - 1))
    if boundary >= 0:
        metadata['suggestedRanges'] = {'baselineRange': [float(times[0]), float(times[boundary])],
                                       'analysisRange': [float(times[boundary + 1]), float(times[-1])]}
    return metadata, times, data


def series_preview(times: np.ndarray, data: np.ndarray, names: list[str], limit: int = 1600) -> dict:
    """Display downsampling only; analysis always uses all selected source rows."""
    # Keep per-channel extrema so short spikes survive an overview plot.
    if len(times) <= limit:
        indexes = np.arange(len(times))
    else:
        buckets = max(1, limit // (4 * len(names) + 2))
        keep = {0, len(times) - 1}
        for chunk in np.array_split(np.arange(len(times)), buckets):
            keep.update((int(chunk[0]), int(chunk[-1])))
            for col in range(data.shape[1]):
                missing = chunk[~np.isfinite(data[chunk, col])]
                if len(missing):
                    keep.update((int(missing[0]), int(missing[-1])))
                valid = chunk[np.isfinite(data[chunk, col])]
                if len(valid):
                    keep.update((int(valid[np.argmin(data[valid, col])]), int(valid[np.argmax(data[valid, col])])))
        indexes = np.array(sorted(keep))
    return {'times': times[indexes].tolist(), 'values': {
        name: [float(v) if np.isfinite(v) else None for v in data[indexes, i]] for i, name in enumerate(names)
    }, 'sourceRows': len(times), 'displayRows': len(indexes)}
