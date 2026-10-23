"""Source-aware signal contracts shared by adapters and research boundaries.

Numerical monitors may consume matrices internally. Public adapters retain the
source, ordered schema, units, clock and sequence identity alongside those matrices.
Unknown units stay unknown; width or a similar signal name is never a mapping.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real


@dataclass(frozen=True)
class Signal:
    key: str
    unit: str | None = None
    meaning: str | None = None


@dataclass(frozen=True)
class SignalSchema:
    id: str
    source: str
    signals: tuple[Signal, ...]
    sample_interval_seconds: float | None

    def __post_init__(self):
        object.__setattr__(self, 'signals', tuple(self.signals))
        keys = self.keys
        if not self.id or not self.source or not keys or any(not k for k in keys) or len(set(keys)) != len(keys):
            raise ValueError('A schema requires source identity and distinct ordered signal keys.')
        interval = self.sample_interval_seconds
        if interval is not None and (isinstance(interval, bool) or not math.isfinite(interval) or interval <= 0):
            raise ValueError('A known sample interval must be finite and positive.')

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(signal.key for signal in self.signals)

    def require_compatible(self, other: SignalSchema):
        if self != other:
            raise ValueError(f'Incompatible signal spaces: {self.id} / {other.id}; an explicit verified adapter is required.')

    def metadata(self) -> dict:
        return dict(id=self.id, source=self.source,
                    signals=[dict(key=s.key, unit=s.unit, meaning=s.meaning) for s in self.signals],
                    sample_interval_seconds=self.sample_interval_seconds,
                    time_unit='seconds' if self.sample_interval_seconds is not None else 'sample_index')


@dataclass(frozen=True)
class ObservationBatch:
    schema: SignalSchema
    sequence_id: str
    timestamps: tuple[float, ...]
    values: tuple[tuple[float | None, ...], ...]
    partition: str = 'unlabeled'
    operating_mode: str | None = None

    def __post_init__(self):
        object.__setattr__(self, 'timestamps', tuple(self.timestamps))
        object.__setattr__(self, 'values', tuple(tuple(row) for row in self.values))
        if not self.sequence_id or not self.values or len(self.timestamps) != len(self.values):
            raise ValueError('Sequence identity, timestamps and samples must be present and aligned.')
        previous = -math.inf
        for timestamp, row in zip(self.timestamps, self.values):
            if isinstance(timestamp, bool) or not isinstance(timestamp, Real) or not math.isfinite(timestamp) or timestamp <= previous:
                raise ValueError('Timestamps must be finite and strictly increasing.')
            previous = timestamp
            if len(row) != len(self.schema.signals):
                raise ValueError('Each observation must match the ordered signal schema.')
            if any(v is not None and (isinstance(v, bool) or not isinstance(v, Real) or not math.isfinite(v)) for v in row):
                raise ValueError('Measurements must be finite numbers or explicitly missing.')

    @property
    def observed_mask(self) -> tuple[tuple[bool, ...], ...]:
        return tuple(tuple(v is not None for v in row) for row in self.values)

    def __len__(self):
        return len(self.values)

    def complete_values(self):
        if any(v is None for row in self.values for v in row):
            raise ValueError('Missing observations require an explicit coverage/imputation policy.')
        return self.values


TEP_CLASSIC_SCHEMA = SignalSchema(
    'tep-classic-52-v1', 'Russell/Chiang/Braatz TEP representation (also Rieth mode 1)',
    tuple(Signal(key) for key in ([f'xmeas_{i}' for i in range(1, 42)] + [f'xmv_{i}' for i in range(1, 12)])),
    180,
)
TEP_MULTIMODE_SCHEMA = SignalSchema(
    'thufdd-tep-native-53-v1', 'Lichen0102/THUFDD MMFDD-TEP 09c194f78281bb495da6669cae7a726515f4a4cb',
    tuple(Signal(f'source_col_{i:02d}') for i in range(53)), None,
)
