"""Adapter to the Russell–Chiang–Braatz closed-loop Fortran plant."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from queue import Empty, Queue
from threading import Thread

import numpy as np

SOURCE = Path(__file__).with_name('tennessee_eastman')
SIGNALS = json.loads((SOURCE / 'signals.json').read_text())
FILES = [SOURCE / name for name in ('closed_loop.f', 'teprob.f')]
MODEL = hashlib.sha256(b''.join(f.read_bytes().replace(b'\r\n', b'\n')
                               for f in [*FILES, SOURCE / 'signals.json'])).hexdigest()


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


def simulate(binary, fault, seed, gain=1., subdivisions=1, hours=24, state_offset=(0, 0.), *,
             duration=None, onset=28800, intervention_at=28800, gain_loop=10, states=None,
             observe=None, check=None):
    """Read native controller samples as the executable advances through one run."""
    state, offset = state_offset
    if state not in (0, 37, 38) or not np.isfinite(offset):
        raise ValueError('Choose an initial cooling-water temperature offset.')
    duration = hours * 3600 if duration is None else duration
    if (type(duration) is not int or duration < 180 or duration % 180 or duration > 172800
            or type(subdivisions) is not int or not 1 <= subdivisions <= 16
            or type(fault) is not int or not 0 <= fault <= 20
            or type(seed) is not int or not 0 < seed < 2**53
            or not np.isfinite(gain) or not 0 < gain <= 2 or gain_loop not in (10, 11)
            or any(type(t) is not int or not 0 <= t <= 172800 for t in (onset, intervention_at))):
        raise ValueError('Invalid Tennessee Eastman integration configuration.')
    args = (f'{duration} {fault} {gain} {subdivisions} {state} {offset} {onset} {intervention_at} '
            f'{gain_loop} {int(states is not None)}\n{seed}\n')
    start = time.perf_counter()
    rows = np.empty((duration // 180, 53))
    width = 53 if states is None else 103
    received = 0
    queue = Queue()

    def read_samples(pipe):
        for line in pipe:
            queue.put(line)
        queue.put(None)

    try:
        with tempfile.TemporaryFile() as diagnostics, subprocess.Popen(
                [binary], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=diagnostics, text=True) as process:
            reader = Thread(target=read_samples, args=(process.stdout,), daemon=True)
            reader.start()
            try:
                process.stdin.write(args)
                process.stdin.close()
                while True:
                    if check:
                        check()
                    if time.perf_counter() - start > 120:
                        raise subprocess.TimeoutExpired(str(binary), 120)
                    try:
                        line = queue.get(timeout=.1)
                    except Empty:
                        continue
                    if line is None:
                        break
                    row = np.fromstring(line, sep=' ')
                    if (received >= len(rows) or row.shape != (width,) or not np.isfinite(row).all()
                            or row[0] != (received + 1) * 180):
                        raise ValueError('The plant returned an invalid observation.')
                    rows[received] = row[:53]
                    received += 1
                    if states is not None:
                        states.append(row[53:])
                    if observe:
                        observe(row[:53])
                if process.wait(timeout=5) or received != len(rows):
                    raise ValueError('The plant returned an incomplete trajectory.')
                diagnostics.seek(0)
                initial_pressure, initial_temperature, initial_coolant, balance = map(float, diagnostics.read().split())
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                reader.join()
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError(f'The Tennessee Eastman simulation failed. Retry the study. {error}') from error
    return rows, dict(runtimeSeconds=time.perf_counter() - start, componentBalanceMaxLbmolPerHour=balance,
                      initialPressureKPaGauge=initial_pressure, initialTemperatureC=initial_temperature,
                      initialReactorCoolantOutletC=initial_coolant)
