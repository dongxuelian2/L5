"""Compare derived numerical regressions, never select models from test outcomes.

The checked-in snapshot records the audited 2026-10-23 rerun of the retained
protocols. It is software regression evidence, not an independent validation set.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

SKIP = {'cases','per_case','per_fault','baseline_report','input_files','source_files','data_provenance',
        'reference_input_files','model','fit_metadata','training_metadata','training_model_metadata',
        'limitations','caveats','interpretation_limits'}


def projection(value):
    if isinstance(value,dict): return {k:projection(v) for k,v in value.items() if k not in SKIP}
    if isinstance(value,list): return [projection(v) for v in value]
    return value


def report_projection(directory: Path):
    return {str(p.relative_to(directory)).replace('\\','/'):projection(json.loads(p.read_text(encoding='utf-8')))
            for p in sorted(directory.rglob('*.json')) if p.name!='suite_manifest.json'}


def compare(actual, expected, location='report'):
    if isinstance(actual,(int,float)) and not isinstance(actual,bool) and isinstance(expected,(int,float)) and not isinstance(expected,bool):
        if not math.isclose(actual,expected,rel_tol=1e-10,abs_tol=1e-8):
            raise AssertionError(f'{location}: numeric regression {actual} / {expected}')
    elif isinstance(actual,dict) and isinstance(expected,dict):
        if actual.keys()!=expected.keys(): raise AssertionError(f'{location}: different report fields')
        for key in actual: compare(actual[key],expected[key],location+'.'+key)
    elif isinstance(actual,list) and isinstance(expected,list):
        if len(actual)!=len(expected): raise AssertionError(f'{location}: different report lengths')
        for i,(a,b) in enumerate(zip(actual,expected)): compare(a,b,f'{location}[{i}]')
    elif type(actual) is not type(expected) or actual!=expected:
        raise AssertionError(f'{location}: {actual!r} / {expected!r}')


def verify(kind: str, directory: Path):
    snapshot=json.loads(Path(__file__).with_name('numeric_reference.json').read_text(encoding='utf-8'))
    actual=report_projection(directory)
    if not actual: raise ValueError('No executed reports found.')
    compare(actual,snapshot['reports'][kind])
    print(f'PASS {kind}: {len(actual)} numerical report projections match the audited snapshot.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind',choices=('reference','rieth','six-mode'))
    parser.add_argument('report_dir',type=Path)
    args=parser.parse_args()
    verify(args.kind,args.report_dir)


if __name__=='__main__': main()
