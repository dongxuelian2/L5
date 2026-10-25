"""Bounded reader for the pinned Rieth RDX2 numeric data.frames.

This is deliberately a narrow data adapter, not a general R deserializer. No R
code is evaluated. Only metadata needed for row selection is retained while
numeric columns are decompressed in 64K-row chunks. Names and attributes are
validated before any selected rows are returned.
"""
from __future__ import annotations

import gzip
import struct
import zlib
from pathlib import Path

import numpy as np

from .tep import VARIABLES

CHUNK_ROWS = 65536
MAX_RUNS = 64
MAX_ROWS = 20 * 500 * 960
COLUMNS = ('faultNumber', 'simulationRun', 'sample', *VARIABLES)


class Reader:
    def __init__(self, stream):
        self.stream, self.refs = stream, []

    def read(self, size):
        data = self.stream.read(size)
        if len(data) != size:
            raise ValueError('Incomplete Rieth RData: unexpected end of file.')
        return data

    def integer(self):
        return struct.unpack('>i', self.read(4))[0]

    def small(self, depth=0):
        if depth > 100:
            raise ValueError('Unsupported nested RData metadata.')
        flags = self.integer()
        kind = flags & 255
        if kind == 254:  # NILVALUE_SXP
            return None
        if kind == 255:  # REFSXP, only interned symbols in this format
            index = flags >> 8 or self.integer()
            if not 1 <= index <= len(self.refs):
                raise ValueError('Invalid RData symbol reference.')
            return self.refs[index-1]
        if kind == 1:  # SYMSXP
            name = self.small(depth+1)
            self.refs.append(name)
            return name
        if kind == 9:  # CHARSXP
            size = self.integer()
            if not 0 <= size <= 4096:
                raise ValueError('Unsupported RData string length.')
            return self.read(size).decode('utf-8')
        if kind == 2:  # tagged pairlist; attributes precede tag/car/cdr
            if flags & 512:
                self.small(depth+1)
            tag = self.small(depth+1) if flags & 1024 else None
            value = self.small(depth+1)
            rest = self.small(depth+1)
            if rest is not None and not isinstance(rest, dict):
                raise ValueError('Unsupported RData attribute list.')
            return {tag: value, **(rest or {})}
        if kind in (13, 14, 16):
            size = self.integer()
            if not 0 <= size <= 1000:
                raise ValueError('Overlarge RData attribute vector.')
            if kind == 16:
                value = [self.small(depth+1) for _ in range(size)]
            else:
                value = np.frombuffer(self.read(size * (4 if kind == 13 else 8)), dtype='>i4' if kind == 13 else '>f8').tolist()
            if flags & 512:
                self.small(depth+1)
            return value
        raise ValueError(f'Unsupported RData metadata type {kind}; expected the official Rieth RDX2 data.frame.')

    def vector(self, expected_size=None):
        flags, size = self.integer(), self.integer()
        if flags not in (13, 14) or not 1 <= size <= MAX_ROWS or (expected_size is not None and size != expected_size):
            raise ValueError('Rieth columns must be equal-length plain integer/double vectors.')
        return size, np.dtype('>i4' if flags == 13 else '>f8')


def read_selected(path: str | Path, selections, *, object_name: str, samples_per_run: int):
    """Return {(faultNumber, simulationRun): N x 52} with explicit boundaries.

    Up to 64 requested runs; the only O(source rows) allocation is the uint8
    fault selector (9.6 MB for Faulty Testing). Feature columns are never held
    in full. The compressed stream is consumed to EOF to check gzip integrity.
    """
    keys = tuple(tuple(key) for key in selections)
    if not 1 <= len(keys) <= MAX_RUNS or len(set(keys)) != len(keys):
        raise ValueError(f'Select 1–{MAX_RUNS} distinct fault/run pairs.')
    if any(len(k) != 2 or any(isinstance(v, bool) or not isinstance(v, int) for v in k) or not 0 <= k[0] <= 20 or not 1 <= k[1] <= 500 for k in keys):
        raise ValueError('Fault must be 0–20 and simulationRun 1–500.')
    try:
        with gzip.open(path, 'rb') as stream:
            reader = Reader(stream)
            if reader.read(7) != b'RDX2\nX\n' or reader.integer() != 2:
                raise ValueError('Expected official XDR RDX2 serialization.')
            reader.integer(), reader.integer()  # writer/minimum reader versions
            if reader.integer() != 1026 or reader.small() != object_name:
                raise ValueError(f'RData object mismatch: expected {object_name}.')
            if reader.integer() != 787 or reader.integer() != 55:
                raise ValueError('Expected a 55-column R data.frame.')
            n, dtype = reader.vector()
            faults = np.empty(n, dtype=np.uint8)
            for begin in range(0, n, CHUNK_ROWS):
                end = min(n, begin+CHUNK_ROWS)
                block = np.frombuffer(reader.read((end-begin)*dtype.itemsize), dtype=dtype)
                if not np.isfinite(block).all() or np.any(block != np.floor(block)) or np.any((block < 0) | (block > 20)):
                    raise ValueError('Invalid faultNumber metadata.')
                faults[begin:end] = block
            _, dtype = reader.vector(n)
            indexes, identities = [], []
            for begin in range(0, n, CHUNK_ROWS):
                end = min(n, begin+CHUNK_ROWS)
                block = np.frombuffer(reader.read((end-begin)*dtype.itemsize), dtype=dtype)
                if not np.isfinite(block).all() or np.any(block != np.floor(block)) or np.any((block < 1) | (block > 500)):
                    raise ValueError('Invalid simulationRun metadata.')
                keep = np.zeros(len(block), dtype=bool)
                for fault, run in keys:
                    keep |= (faults[begin:end] == fault) & (block == run)
                local = np.flatnonzero(keep)
                indexes.extend((local+begin).tolist())
                identities.extend(zip(faults[begin:end][local].tolist(), block[local].astype(int).tolist()))
                if len(indexes) > len(keys)*samples_per_run:
                    raise ValueError('Requested runs contain too many samples or duplicate identities.')
            del faults
            indexes = np.asarray(indexes, dtype=np.int64)
            if len(indexes) != len(keys)*samples_per_run:
                raise ValueError('Missing or incomplete requested simulation runs.')
            selected = np.empty((len(indexes), 53), dtype=np.float64)
            for column in range(53):  # sample metadata, then 52 features
                _, dtype = reader.vector(n)
                for begin in range(0, n, CHUNK_ROWS):
                    end = min(n, begin+CHUNK_ROWS)
                    block = np.frombuffer(reader.read((end-begin)*dtype.itemsize), dtype=dtype)
                    lo, hi = np.searchsorted(indexes, [begin, end])
                    selected[lo:hi, column] = block[indexes[lo:hi]-begin]
            attrs = reader.small()
            if not isinstance(attrs, dict) or attrs.get('names') != list(COLUMNS) or attrs.get('class') != ['data.frame']:
                raise ValueError('Original Rieth column names/order or data.frame class differ from the verified schema.')
            if reader.small() is not None or stream.read(1):
                raise ValueError('Unexpected additional RData objects or trailing data.')
    except (EOFError, gzip.BadGzipFile, struct.error, UnicodeError, zlib.error) as error:
        raise ValueError(f'Corrupt or incomplete Rieth RData: {error}') from error
    if not np.isfinite(selected).all():
        raise ValueError('Selected TEP samples contain nonfinite measurements.')
    result = {}
    for key in keys:
        rows = selected[[identity == key for identity in identities]]
        rows = rows[np.argsort(rows[:, 0], kind='stable')]
        if len(rows) != samples_per_run or not np.array_equal(rows[:, 0], np.arange(1, samples_per_run+1)):
            raise ValueError(f'Run {key} lacks unique contiguous sample indices 1–{samples_per_run}.')
        result[key] = rows[:, 1:].copy()
    return result
