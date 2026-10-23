"""Run all retained Braatz studies from one frozen, hash-checked data cache.

This command performs no downloads. Use benchmarks.fetch_reference explicitly
first. Each study runs in a fresh process; logs and derived reports are retained.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys

from .fetch_reference import reference_filenames, validate_reference_hash

STUDIES = (
    ('baseline', 'evaluate', ()), ('robustness', 'robustness', ()),
    ('coverage', 'coverage', ()), ('sensitivity', 'sensitivity', ()),
    ('temporal', 'temporal_evaluate', ()), ('bounded', 'bounded_evaluate', ()),
    ('bounded-coverage', 'coverage', ('--methods','window-cusum-12','window-cusum-24','--scenarios','clean','random-missing-05','blackout-15samples')),
    ('drift-recovery', 'drift_recovery', ()), ('dynamic-pca', 'dynamic_pca_evaluate', ()),
    ('dpca-coverage', 'coverage', ('--methods','dpca-q-lag2','dpca-t2-lag2','--scenarios','clean','random-missing-05','blackout-15samples')),
    ('forward-budget', 'normal_budget_validation', ()),
)


def run_suite(data: Path, output: Path):
    for name in reference_filenames(): validate_reference_hash(name,(data/name).read_bytes())
    output.mkdir(parents=True,exist_ok=True)
    manifest={'python':sys.version.split()[0], 'numpy':importlib.metadata.version('numpy'), 'studies':[]}
    env={**os.environ,'PYTHONUTF8':'1','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1'}
    for name,module,extra in STUDIES:
        destination=output/name
        log=output/(name+'.log')
        command=[sys.executable,'-m','benchmarks.'+module,str(data),'--output-dir',str(destination),*extra]
        with log.open('w',encoding='utf-8') as stream:
            result=subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT,env=env)
        manifest['studies'].append({'study':name,'module':module,'arguments':list(extra),'exit_code':result.returncode})
        (output/'suite_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
        if result.returncode:
            raise RuntimeError(f'{name} failed; see {log}')
        print(f'PASS {name}',flush=True)
    manifest['reports']={str(p.relative_to(output)):hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in sorted(output.rglob('*')) if p.is_file() and p.suffix in ('.json','.md','.csv') and p.name!='suite_manifest.json'}
    (output/'suite_manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('data_dir',type=Path)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    run_suite(args.data_dir,args.output_dir)


if __name__=='__main__': main()
