"""Small runtime contract shared by two concrete physical models."""
from __future__ import annotations

from copy import deepcopy
import math
from typing import Protocol


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def field(key, label, default, low, high, *, group='Model parameters', unit='', integer=False, nullable=False):
    return dict(key=key, label=label, default=default, min=low, max=high, group=group,
                unit=unit, type='integer' if integer else 'number', nullable=nullable)


def validate_fields(raw, fields, defaults, faults):
    if not isinstance(raw, dict) or set(raw) - defaults.keys():
        raise ValueError('Unknown model configuration parameters.')
    config = {**deepcopy(defaults), **raw}
    if not isinstance(config.get('fault'), str) or config['fault'] not in faults:
        raise ValueError('Choose a fault supported by this model.')
    for spec in fields:
        key, value = spec['key'], config[spec['key']]
        if value is None and spec['nullable']:
            continue
        if not finite(value) or not spec['min'] <= value <= spec['max']:
            raise ValueError(f"{spec['label']} must be between {spec['min']} and {spec['max']} {spec['unit']}.")
        if spec['type'] == 'integer' and int(value) != value:
            raise ValueError(f"{spec['label']} must be an integer.")
        if spec['type'] == 'integer':
            config[key] = int(value)
    return config


def ground_truth(config):
    """Half-open fault intervals on the simulation clock; never detector output."""
    actual_end = config['start'] + config['fault_duration'] if config.get('fault_duration') is not None else math.inf
    end = min(config['duration'], actual_end)
    intervals = [] if config['fault'] == 'healthy' or config['start'] > end else [
        dict(start=config['start'], end=end, endExclusive=actual_end <= config['duration'], kind='anomaly', category=config['fault'])]
    return dict(timeBasis='simulation-seconds', coverage=[0, config['duration']],
                intervals=intervals, postFault='unknown: residual dynamics are not labelled healthy', source='configured-simulation-fault')


class ProcessModel(Protocol):
    """Operations beyond describe/validate are required only when advertised.

    The runtime checks capabilities before invoking optional operations. Models
    without tools, interventions or ground truth need not provide those methods.
    """
    id: str
    version: str

    def describe(self) -> dict: ...
    def validate(self, config: dict, *, randomize: bool = False) -> dict: ...
    def simulate(self, config: dict) -> list[dict]: ...
    def truth(self, config: dict) -> dict: ...
    def observe(self, session: dict, rows: list[dict]) -> dict: ...
    def tools(self, session: dict, rows: list[dict], body: dict) -> dict: ...
    def intervene(self, session: dict, rows: list[dict], body: dict) -> dict: ...
