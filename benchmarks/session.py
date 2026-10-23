"""Schema-aware fit/calibration/score boundary around research-only monitors."""
from __future__ import annotations

from dataclasses import dataclass
import math
import numpy as np

from l5.contracts import ObservationBatch, SignalSchema
from .monitoring import Monitor, as_matrix, build_monitor, calibrate


def observed_matrix(observations: ObservationBatch):
    interval = observations.schema.sample_interval_seconds or 1
    if any(not math.isclose(b-a, interval, rel_tol=0, abs_tol=1e-7)
           for a,b in zip(observations.timestamps, observations.timestamps[1:])):
        raise ValueError('Sequence gaps require an explicit observation-reset/abstention policy.')
    return as_matrix(observations.complete_values())


def batch(values, schema: SignalSchema, sequence_id: str, partition: str, *, start: int = 0, operating_mode=None):
    data = as_matrix(values, features=len(schema.signals))
    interval = schema.sample_interval_seconds or 1
    return ObservationBatch(schema, sequence_id, tuple((start+i)*interval for i in range(len(data))),
                            tuple(tuple(float(v) for v in row) for row in data), partition, operating_mode)


@dataclass(frozen=True)
class ResearchSession:
    schema: SignalSchema
    monitor: Monitor
    threshold: float
    fit_sequence: str
    calibration_sequence: str

    @classmethod
    def fit(cls, method: str, fit: ObservationBatch, calibration: ObservationBatch, *, alpha: float = .01):
        fit.schema.require_compatible(calibration.schema)
        if fit.partition != 'normal_fit' or calibration.partition != 'normal_calibration':
            raise ValueError('Only explicit normal fit/calibration partitions may train a research session.')
        if fit.sequence_id == calibration.sequence_id and fit.timestamps[-1] >= calibration.timestamps[0]:
            raise ValueError('Chronological fit/calibration partitions must not overlap or reverse time.')
        model = build_monitor(method)
        model.fit(observed_matrix(fit))
        threshold = calibrate(model, observed_matrix(calibration), alpha)
        return cls(fit.schema, model, threshold, fit.sequence_id, calibration.sequence_id)

    def score(self, observations: ObservationBatch) -> np.ndarray:
        self.schema.require_compatible(observations.schema)
        return self.monitor.score(observed_matrix(observations))

    def metadata(self):
        return {**self.monitor.metadata(), 'signal_schema_id': self.schema.id,
                'fit_sequence': self.fit_sequence, 'calibration_sequence': self.calibration_sequence,
                'deployment_status': 'research-only'}
