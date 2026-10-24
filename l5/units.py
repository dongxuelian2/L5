"""Small explicit engineering-unit registry, including affine temperature scales."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Unit:
    dimension: str
    scale: float = 1
    offset: float = 0


UNITS = {
    '°C': Unit('temperature', 1, 273.15), 'K': Unit('temperature'),
    '°F': Unit('temperature', 5 / 9, 273.15 - 32 * 5 / 9),
    'Δ°C': Unit('temperature-difference'), 'ΔK': Unit('temperature-difference'),
    'Δ°F': Unit('temperature-difference', 5 / 9),
    'Pa': Unit('pressure'), 'kPa': Unit('pressure', 1000),
    'MPa': Unit('pressure', 1e6), 'bar': Unit('pressure', 1e5),
    'm³/s': Unit('flow'), 'm³/h': Unit('flow', 1 / 3600), 'L/min': Unit('flow', 1 / 60000),
    'W': Unit('power'), 'kW': Unit('power', 1000), 'MW': Unit('power', 1e6),
    'V': Unit('voltage'), 'kV': Unit('voltage', 1000),
    'A': Unit('current'), 'mA': Unit('current', .001),
    's': Unit('time'), 'ms': Unit('time', .001), 'min': Unit('time', 60), 'h': Unit('time', 3600),
    'rpm': Unit('rotation', 1 / 60), 'Hz': Unit('rotation'), '1': Unit('dimensionless'),
}
ALIASES = {'C': '°C', 'degC': '°C', 'degF': '°F', 'F': '°F', 'm3/s': 'm³/s', 'm3/h': 'm³/h',
           'delta_degC': 'Δ°C', 'delta_K': 'ΔK', 'delta_degF': 'Δ°F', '': '1'}


def resolve(unit):
    key = canonical(unit)
    if key in UNITS:
        return UNITS[key]
    if key.endswith('/s'):
        base = UNITS.get(canonical(key[:-2]))
        if base and base.dimension != 'temperature':
            return Unit(base.dimension + '-rate', base.scale)
    return None


def canonical(unit):
    if not isinstance(unit, str) or len(unit) > 160:
        raise ValueError('Unit must be text of at most 160 characters.')
    return ALIASES.get(unit.strip(), unit.strip())


def dimension(unit):
    entry = resolve(unit)
    return entry.dimension if entry else None


def difference_unit(unit):
    return {'°C': 'Δ°C', 'K': 'ΔK', '°F': 'Δ°F'}.get(canonical(unit), unit)


def conversion(source, target, *, rotational=False):
    source, target = canonical(source), canonical(target)
    if source == target:
        return dict(source=source, target=target, scale=1., offset=0.)
    a, b = resolve(source), resolve(target)
    if not a or not b or a.dimension != b.dimension:
        raise ValueError(f'No explicit conversion from {source} to {target}. Custom units can only be preserved.')
    if a.dimension.startswith('rotation') and not rotational:
        raise ValueError('rpm / Hz conversion requires an explicit rotational-speed meaning.')
    return dict(source=source, target=target, scale=a.scale / b.scale, offset=(a.offset - b.offset) / b.scale)


def convert(values, source, target, *, rotational=False):
    relation = conversion(source, target, rotational=rotational)
    with np.errstate(over='ignore', invalid='ignore'):
        result = np.asarray(values, dtype=float) * relation['scale'] + relation['offset']
    if np.any(np.isfinite(values) & ~np.isfinite(result)):
        raise ValueError('Unit conversion overflowed; check signal magnitudes.')
    return result


def choices(source, *, rotational=False):
    key = canonical(source)
    group = dimension(key)
    if not group or group == 'rotation' and not rotational:
        return [source]
    return [name for name, unit in UNITS.items() if unit.dimension == group] or [source]


def catalog():
    return [dict(name=name, dimension=u.dimension, scale=u.scale, offset=u.offset,
                 requiresRotationalMeaning=u.dimension == 'rotation') for name, u in UNITS.items()]
