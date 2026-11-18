"""Adapter to the Russell–Chiang–Braatz closed-loop Fortran plant."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

import numpy as np

SOURCE = Path(__file__).with_name('tennessee_eastman')
SIGNALS = json.loads((SOURCE / 'signals.json').read_text())
FILES = [SOURCE / name for name in ('closed_loop.f', 'teprob.f')]
MODEL = hashlib.sha256(b''.join(f.read_bytes().replace(b'\r\n', b'\n') for f in FILES)).hexdigest()


def describe_columns(columns):
    for column, signal in zip(columns, SIGNALS, strict=True):
        if column['name'] != signal['name']:
            raise ValueError('The dataset does not match the classic 52-channel Tennessee Eastman schema.')
        column.update(signal, logicalKey='tep.' + signal['name'])


def executable(cache):
    compiler = shutil.which('gfortran')
    if not compiler:
        raise ValueError('Install GNU Fortran (gfortran) and restart the L5 server to run the plant.')
    version = subprocess.check_output([compiler, '--version'], text=True).splitlines()[0]
    build = hashlib.sha256((MODEL + version).encode()).hexdigest()[:20]
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / (build + ('.exe' if os.name == 'nt' else ''))
    if not target.is_file():
        with tempfile.TemporaryDirectory(dir=cache) as tmp:
            output = Path(tmp) / target.name
            result = subprocess.run([compiler, '-std=legacy', '-O2', '-fno-automatic', *FILES, '-o', output],
                                    capture_output=True, text=True, timeout=120)
            if result.returncode:
                raise ValueError('Compiling the Tennessee Eastman plant failed: ' + result.stderr[-800:])
            os.replace(output, target)
    return target, version


def simulate(binary, fault, seed, gain=1., subdivisions=1, hours=24, state_offset=(0, 0.)):
    state, offset = state_offset
    if state not in (0, 37, 38) or not np.isfinite(offset):
        raise ValueError('Choose an initial cooling-water temperature offset.')
    args = f'{hours * 3600} {fault} {gain} {subdivisions} {state} {offset}\n{seed}\n'
    start = time.perf_counter()
    result = subprocess.run([binary], input=args, capture_output=True, text=True, timeout=120, check=True)
    rows = np.loadtxt(io.StringIO(result.stdout), ndmin=2)
    if (rows.shape != (hours * 20, 53) or not np.isfinite(rows).all()
            or not np.array_equal(rows[:, 0], np.arange(1, len(rows) + 1) * 180)):
        raise ValueError('The plant returned an incomplete or invalid trajectory.')
    initial_pressure, initial_temperature, initial_coolant, balance = map(float, result.stderr.split())
    return rows, dict(runtimeSeconds=time.perf_counter() - start, componentBalanceMaxLbmolPerHour=balance,
                      initialPressureKPaGauge=initial_pressure, initialTemperatureC=initial_temperature,
                      initialReactorCoolantOutletC=initial_coolant)
