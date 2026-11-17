"""Run the Braatz studies in separate processes with verified reference inputs."""
from __future__ import annotations

import argparse
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
    env = {**os.environ, 'PYTHONUTF8': '1', 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1'}
    for name, module, extra in STUDIES:
        print(f'Running {name}', flush=True)
        command = [sys.executable, '-m', 'benchmarks.' + module, str(data),
                   '--output-dir', str(output / name), *extra]
        subprocess.run(command, env=env, check=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('data_dir',type=Path)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    run_suite(args.data_dir,args.output_dir)


if __name__=='__main__': main()
