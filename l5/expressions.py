"""Bounded AST interpreter for arrays; no Python evaluation, attributes or indexing."""
from __future__ import annotations

import ast
import math
from dataclasses import dataclass

import numpy as np

from .units import canonical, convert, difference_unit, dimension


@dataclass
class Quantity:
    values: np.ndarray
    unit: str | None
    observed: np.ndarray
    scalar: bool = False
    rotational: bool = False


FUNCTIONS = ('abs', 'sqrt', 'log', 'exp', 'sin', 'cos', 'minimum', 'maximum', 'clip', 'diff', 'rate')


def parse(expression, keys):
    if not isinstance(expression, str) or not expression.strip() or len(expression) > 2000:
        raise ValueError('Enter an expression of 1–2000 characters.')
    try:
        tree = ast.parse(expression, mode='eval')
    except (SyntaxError, RecursionError) as error:
        raise ValueError('Invalid signal expression.') from error
    nodes = list(ast.walk(tree))
    if len(nodes) > 200:
        raise ValueError('Expression has too many operations.')
    allowed = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Call, ast.Name, ast.Load, ast.Constant,
               ast.Add, ast.Sub, ast.Mult, ast.Div, ast.USub, ast.UAdd)
    for node in nodes:
        if not isinstance(node, allowed):
            raise ValueError('Only arithmetic, selected signal keys and documented numeric functions are allowed.')
        if isinstance(node, ast.Constant):
            try:
                valid = not isinstance(node.value, bool) and isinstance(node.value, (float, int)) and math.isfinite(float(node.value))
            except (ValueError, OverflowError):
                valid = False
            if not valid:
                raise ValueError('Expression constants must be finite numbers.')
        if isinstance(node, ast.Call) and (not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS or node.keywords):
            raise ValueError('Unknown function or keyword argument in signal expression.')
        if isinstance(node, ast.Name) and node.id not in keys and node.id not in FUNCTIONS:
            raise ValueError(f'Unknown signal key: {node.id}. Choose an explicitly selected source or earlier derived signal.')
    references = list(dict.fromkeys(n.id for n in nodes if isinstance(n, ast.Name) and n.id in keys))
    return tree, references


def combine(a, b, operation):
    ua, ub = a.unit, b.unit
    da, db = dimension(ua) if ua is not None else None, dimension(ub) if ub is not None else None
    left, right = a.values, b.values
    unit = ua
    if ua is None or ub is None:
        raise ValueError('Give an intermediate complex expression an explicit unit before adding or subtracting it.')
    if da == db == 'temperature':
        if operation != 'sub':
            raise ValueError('Adding absolute temperatures is ambiguous. Use a temperature difference or convert the formula explicitly.')
        right = convert(right, ub, ua)
        unit = difference_unit(ua)
    elif da == 'temperature' and db == 'temperature-difference':
        right = convert(right, ub, difference_unit(ua))
    elif da == 'temperature-difference' and db == 'temperature':
        if operation == 'sub':
            raise ValueError('Cannot subtract an absolute temperature from a temperature difference.')
        left = convert(left, ua, difference_unit(ub))
        unit = ub
    else:
        right = convert(right, ub, ua, rotational=a.rotational and b.rotational)
    return Quantity(left + right if operation == 'add' else left - right, unit, a.observed & b.observed,
                    a.scalar and b.scalar, a.rotational and b.rotational)


def evaluate(expression, quantities, times, output_unit=None):
    tree, references = parse(expression, quantities)
    def visit(node):
        if isinstance(node, ast.Constant):
            return Quantity(np.full(len(times), float(node.value)), '1', np.ones(len(times), dtype=bool), True)
        if isinstance(node, ast.Name):
            if node.id not in quantities:
                raise ValueError('A function name cannot be used as a signal.')
            return quantities[node.id]
        if isinstance(node, ast.UnaryOp):
            a = visit(node.operand)
            if isinstance(node.op, ast.USub) and a.unit is not None and dimension(a.unit) == 'temperature':
                raise ValueError('Negation of an absolute temperature is ambiguous.')
            return Quantity(-a.values if isinstance(node.op, ast.USub) else a.values, a.unit, a.observed, a.scalar, a.rotational)
        if isinstance(node, ast.BinOp):
            a, b = visit(node.left), visit(node.right)
            if isinstance(node.op, (ast.Add, ast.Sub)):
                return combine(a, b, 'add' if isinstance(node.op, ast.Add) else 'sub')
            if any(u is not None and dimension(u) == 'temperature' for u in (a.unit, b.unit)):
                raise ValueError('Products and ratios of absolute temperatures are ambiguous. Use a temperature difference.')
            dividing = isinstance(node.op, ast.Div)
            right = b.values
            if dividing and a.unit is not None and b.unit is not None and (canonical(a.unit) == canonical(b.unit) or dimension(a.unit) and dimension(a.unit) == dimension(b.unit)):
                right = convert(right, b.unit, a.unit, rotational=a.rotational and b.rotational)
                unit = '1'
            elif b.unit is not None and canonical(b.unit) == '1':
                unit = a.unit
            elif not dividing and a.unit is not None and canonical(a.unit) == '1':
                unit = b.unit
            else:
                unit = None
            rotation = a.rotational if b.unit is not None and canonical(b.unit) == '1' else b.rotational if not dividing and a.unit is not None and canonical(a.unit) == '1' else False
            return Quantity(a.values / right if dividing else a.values * right, unit, a.observed & b.observed, a.scalar and b.scalar, rotation)
        if isinstance(node, ast.Call):
            name = node.func.id
            args = [visit(arg) for arg in node.args]
            count = 3 if name == 'clip' else 2 if name in ('minimum', 'maximum') else 1
            if len(args) != count:
                raise ValueError(f'{name} needs {count} argument(s).')
            a = args[0]
            if name in ('diff', 'rate'):
                values = np.r_[np.nan, np.diff(a.values)]
                observed = np.r_[False, a.observed[:-1] & a.observed[1:]]
                unit = difference_unit(a.unit) if a.unit is not None else None
                if name == 'rate':
                    steps = np.diff(times)
                    if np.any(steps <= 0):
                        raise ValueError('rate requires strictly increasing sample times.')
                    values[1:] /= steps
                    unit = unit + '/s' if unit and canonical(unit) != '1' else '1/s' if unit else None
                return Quantity(values, unit, observed, rotational=a.rotational)
            if name in ('minimum', 'maximum', 'clip'):
                converted = [a.values]
                for b in args[1:]:
                    if a.unit is None or b.unit is None:
                        raise ValueError('Numeric bounds need known compatible units.')
                    converted.append(b.values if b.scalar and canonical(b.unit) == '1' else convert(b.values, b.unit, a.unit, rotational=a.rotational and b.rotational))
                return Quantity(getattr(np, name)(*converted), a.unit, np.logical_and.reduce([v.observed for v in args]), rotational=a.rotational)
            if name in ('log', 'exp', 'sin', 'cos') and (a.unit is None or canonical(a.unit) != '1'):
                raise ValueError(f'{name} requires a dimensionless argument.')
            if name == 'abs' and a.unit is not None and dimension(a.unit) == 'temperature':
                raise ValueError('abs requires a temperature difference rather than an absolute temperature.')
            unit = a.unit if name == 'abs' else '1' if a.unit and canonical(a.unit) == '1' else None
            return Quantity(getattr(np, name)(a.values), unit, a.observed, rotational=a.rotational if name == 'abs' else False)
        raise ValueError('Unsupported expression operation.')
    with np.errstate(all='ignore'):
        computed = visit(tree.body)
    # A direct reference must never let output conversion mutate its input quantity.
    quantity = Quantity(computed.values.copy(), computed.unit, computed.observed.copy(), rotational=computed.rotational)
    inferred = quantity.unit
    if inferred is None:
        if not output_unit or not output_unit.strip():
            raise ValueError('This complex expression needs an explicit output unit; its numeric inputs keep the displayed units.')
        quantity.unit = output_unit.strip()
    elif output_unit:
        quantity.values = convert(quantity.values, inferred, output_unit, rotational=quantity.rotational)
        quantity.unit = output_unit.strip()
    quantity.values = np.where(np.isfinite(quantity.values), quantity.values, np.nan)
    quantity.observed = quantity.observed & np.isfinite(quantity.values)
    return quantity, references, inferred
