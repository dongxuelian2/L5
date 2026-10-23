"""Recompute both complete simulator artifacts and compare with numerical tolerance."""
from __future__ import annotations
import json
import math
from pathlib import Path
from .generate import build_scenario
from .platform import build_platform

def compare(actual, expected, location='root'):
    if isinstance(actual,(int,float)) and not isinstance(actual,bool) and isinstance(expected,(int,float)) and not isinstance(expected,bool):
        if not math.isclose(actual,expected,rel_tol=1e-12,abs_tol=1e-8):
            raise AssertionError(f'{location}: numerical difference {actual} / {expected}')
    elif isinstance(actual,dict) and isinstance(expected,dict):
        if actual.keys()!=expected.keys(): raise AssertionError(f'{location}: different fields')
        for key in actual: compare(actual[key],expected[key],f'{location}.{key}')
    elif isinstance(actual,(list,tuple)) and isinstance(expected,(list,tuple)):
        if len(actual)!=len(expected): raise AssertionError(f'{location}: different lengths')
        for index,(a,b) in enumerate(zip(actual,expected)): compare(a,b,f'{location}[{index}]')
    elif actual!=expected:
        raise AssertionError(f'{location}: {actual!r} / {expected!r}')

def main():
    root=Path(__file__).resolve().parents[1]/'src/data'
    for name,generate in (('scenario.json',build_scenario),('platform.json',build_platform)):
        compare(generate(),json.loads((root/name).read_text(encoding='utf-8')),name)
        print(f'PASS complete {name}: all observations, snapshots, fits and branches')

if __name__=='__main__': main()
