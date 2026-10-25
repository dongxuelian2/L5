"""CSV ingestion without a predefined process schema."""
from __future__ import annotations

from io import StringIO
import csv

import numpy as np
import pandas as pd

from .data_quality import cadence, segment_ids, summarize

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
        frame = pd.read_csv(StringIO(source), sep=separator, skip_blank_lines=False, float_precision='round_trip')
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
        if kind not in ('auto', 'numeric', 'datetime', 'unix'):
            raise ValueError('Choose numeric, Unix or date/time timestamps.')
        if kind in ('numeric', 'unix') or (kind == 'auto' and numeric.notna().sum() >= max(1, len(frame) / 2)):
            unit = options.get('timeUnit', 'seconds')
            if unit not in TIME_UNITS:
                raise ValueError('Unknown time unit.')
            times = numeric.to_numpy(dtype=float) * TIME_UNITS[unit]
            time = {'kind': 'numeric', 'column': column, 'sourceUnit': unit, 'origin': None}
            if kind == 'unix':
                valid = times[np.isfinite(times)]
                if not len(valid):
                    raise ValueError('Time column needs at least one valid timestamp.')
                origin = pd.to_datetime(float(valid.min()), unit='s', utc=True)
                times = times - float(valid.min())
                time.update(kind='unix', origin=origin.isoformat())
        else:
            zone = options.get('timezone', 'UTC')
            try:
                pd.Timestamp('2000-01-01').tz_localize(zone)
            except (ValueError, TypeError, KeyError) as error:
                raise ValueError('Enter a valid timezone, such as UTC or Asia/Shanghai.') from error
            def parse_date(value):
                try:
                    stamp = pd.Timestamp(value)
                    return stamp.tz_localize(zone, ambiguous='NaT', nonexistent='NaT').tz_convert('UTC') if stamp.tzinfo is None else stamp.tz_convert('UTC')
                except (ValueError, TypeError, OverflowError):
                    return pd.NaT
            dates = pd.to_datetime(frame[column], errors='coerce', utc=True, format='mixed') if zone == 'UTC' else pd.to_datetime(frame[column].map(parse_date), utc=True)
            if dates.isna().all():
                raise ValueError('Time column needs at least one valid date. Choose numeric time or generated time instead.')
            origin = dates.min()
            times = (dates - origin).dt.total_seconds().to_numpy()
            time = {'kind': 'datetime', 'column': column, 'origin': origin.isoformat(), 'naiveTimezone': zone}
    valid_time = np.isfinite(times)
    if not valid_time.any():
        raise ValueError('Time column needs at least one valid timestamp.')
    invalid_times = [dict(row=int(i) + 2, raw=str(frame.iloc[i][column])) for i in np.flatnonzero(~valid_time)]
    source_times = times.copy()
    times = times[valid_time]
    order = np.argsort(times, kind='stable')
    if not np.array_equal(order, np.arange(len(frame))):
        times = times[order]
        notes.append('Rows were sorted by time before saving.')
    columns, arrays, ignored = [], [], []
    for name in frame:
        if name == column:
            continue
        values = pd.to_numeric(frame[name], errors='coerce').to_numpy(dtype=float)
        values[~np.isfinite(values)] = np.nan
        valid = values[np.isfinite(values)]
        if not len(valid) and frame[name].dtype.kind not in 'fiu':
            ignored.append(name)
            continue
        columns.append({'name': name, 'missing': int(np.isnan(values).sum()),
                        'min': float(valid.min()) if len(valid) else None, 'max': float(valid.max()) if len(valid) else None})
        arrays.append(values)
    if not arrays:
        raise ValueError('CSV needs at least one numeric signal besides the time column.')
    source_data = np.column_stack(arrays)
    data = source_data[valid_time][order]
    missing = int(np.isnan(source_data).sum())
    if missing:
        notes.append(f'{missing} missing / nonnumeric measurements will use baseline medians during analysis.')
    time.update({'start': float(times[0]), 'end': float(times[-1]), 'unit': 'seconds'})
    if invalid_times:
        notes.append(f'{len(invalid_times)} rows have invalid / missing time. They remain in the original CSV and quality counts; timed plots and analysis omit them.')
        for issue in invalid_times:
            row = issue['row'] - 2
            neighbors = np.flatnonzero(np.isfinite(source_times[:row]))
            issue['nearbyTime'] = float(source_times[neighbors[-1]]) if len(neighbors) else float(times[0])
    quality = summarize(times, data, [c['name'] for c in columns], source_values=source_data, invalid_times=invalid_times)
    time.update({k: quality[k] for k in ('typicalInterval', 'irregularCount', 'duplicateCount', 'invalidTimeCount', 'gapCount')})
    metadata = {'rowCount': len(frame), 'columns': columns, 'sourceColumns': list(frame.columns),
                'ignoredColumns': ignored, 'time': time, 'missingCount': missing, 'notes': notes, 'quality': quality}
    boundary = min(len(times) - 2, max(99, int(len(times) * .2) - 1))
    if boundary >= 0:
        metadata['suggestedRanges'] = {'baselineRange': [float(times[0]), float(times[boundary])],
                                       'analysisRange': [float(times[boundary + 1]), float(times[-1])]}
    return metadata, times, data


def series_preview(times: np.ndarray, data: np.ndarray, names: list[str], limit: int = 1600, *, gap_threshold=None) -> dict:
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
    gap_threshold = gap_threshold or cadence(times)['gapThreshold']
    return {'times': times[indexes].tolist(), 'segmentIds': {
        name: segment_ids(times, data[:, i], gap_threshold)[indexes].tolist() for i, name in enumerate(names)
    }, 'values': {
        name: [float(v) if np.isfinite(v) else None for v in data[indexes, i]] for i, name in enumerate(names)
    }, 'sourceRows': len(times), 'displayRows': len(indexes)}
