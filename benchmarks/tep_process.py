"""Reproduce the external-reference and local sensitivity comparisons."""
import argparse
import hashlib
import json
import os
import subprocess
from tempfile import TemporaryDirectory
from pathlib import Path

import numpy as np

from l5.industrial_study import CASES, CHANNELS, ONSET, diagnose
from simulation.tep import executable, simulate


def compare_driver(binary, reference):
    """Run the unedited upstream executable through its own output routine."""
    source = reference.resolve().parent / 'fortran'
    with TemporaryDirectory() as directory:
        work = Path(directory)
        data = work / '~'
        data.mkdir()
        exe = work / ('oracle.exe' if os.name == 'nt' else 'oracle')
        subprocess.run(['gfortran', '-std=legacy', '-O2', '-fno-automatic',
                        source/'temain_mod.f', source/'teprob.f', '-o', exe], check=True)
        subprocess.run([exe], cwd=work, stdout=subprocess.DEVNULL, check=True)
        files = [data/f'TE_data_me{i:02}.dat' for i in range(1, 12)]
        files += [data/f'TE_data_mv{i}.dat' for i in range(1, 4)]
        ref = np.column_stack([np.loadtxt(path, ndmin=2) for path in files])[:160, :52]
    rows = simulate(binary, 0, 4651207995, hours=8)[0][:, 1:]
    # E13.5 carries five significant decimal digits in the upstream files.
    rounded = np.array([float(format(x, '.5g')) for x in rows.flat]).reshape(rows.shape)
    return dict(samples=160, channels=52, differencesAtPublishedPrecision=int((rounded != ref).sum()))


def alignment_trials(binary, runs):
    """Stress the alarm trigger and reference clock on held-out simulator seeds."""
    fit = runs['fit'][:, CHANNELS]
    center, factor = fit.mean(axis=0), np.linalg.cholesky(np.cov(fit.T))
    rng = np.random.default_rng(91473)
    totals = {}
    roles = {0: 'normal', 4: 'reactor-reference', 5: 'condenser-reference'}
    for fault, truth in roles.items():
        correct, count = 0, 0
        max_error = 0
        for seed in (2112396789, 3549106923, 4126341789):
            rows = simulate(binary, fault, seed)[0]
            noise = rng.normal(size=(len(rows), len(CHANNELS))) * fit.std(axis=0)
            for delay in (180, 540, 1440):
                for duration in (900, 3600):
                    cutoff = ONSET + delay + duration
                    available = rows[:, 0] < cutoff
                    for sigma in (0, .5):
                        obs = rows[:, CHANNELS] + sigma * noise
                        for shift in (-180, 0, 180):
                            references = {role: (runs[role][:, 0] - ONSET - shift, runs[role][:, CHANNELS])
                                          for role in ('reactor-reference', 'condenser-reference')}
                            result = diagnose(rows[available, 0], obs[available], ONSET + delay, references, center, factor, duration)
                            count += 1
                            correct += result['hypothesis'] == truth
                            if fault:
                                max_error = max(max_error, abs(result['estimatedOnsets'][truth] - ONSET))
        totals[truth] = dict(correct=correct, comparisons=count, maxOnsetErrorSeconds=max_error if fault else None)
    return totals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference', type=Path, help='tep-rust/reference/data at the revision in the guide')
    args = parser.parse_args()
    binary, compiler = executable(Path('output/tep-build'))
    runs = {role: simulate(binary, *case)[0] for role, case in CASES.items()}
    fit = runs['fit'][:, CHANNELS]
    cov = np.cov(fit.T)
    scale = np.linalg.cholesky(cov)
    signatures = np.stack([runs[k][160:180, CHANNELS].mean(0) - fit.mean(0)
                           for k in ('reactor-reference', 'condenser-reference')], axis=1)
    result = dict(compiler=compiler, upstreamDriver=compare_driver(binary, args.reference), comparisons={},
                  temperatureOnlyRank=int(np.linalg.matrix_rank(signatures[:1])),
                  signatureSingularValues=np.linalg.svd(np.linalg.solve(scale, signatures), compute_uv=False).tolist())
    for fault, role in [(0, 'calibration'), (4, 'evaluation'), (5, 'condenser-reference')]:
        file = args.reference / f'd{fault:02}_te.dat'
        refs = np.loadtxt(file)[:480]
        generated = runs[role][:, 1:]
        effect = refs[160:180, np.array(CHANNELS)-1].mean(0) - fit.mean(0)
        dist = np.linalg.norm(np.linalg.solve(scale, signatures - effect[:, None]), axis=0)
        result['comparisons'][file.name] = dict(sha256=hashlib.sha256(file.read_bytes()).hexdigest(),
            medianAbsoluteStandardizedMeanDifference=float(np.median(abs(generated.mean(0)-refs.mean(0))/refs.std(0))),
            reactorAndCondenserDistances=dist.tolist())
    result['alignmentTrials'] = alignment_trials(binary, runs)
    result['refinement'] = {}
    for div in (1, 2, 4):
        rows, audit = simulate(binary, *CASES['evaluation'], subdivisions=div)
        result['refinement'][div] = dict(**audit, postTemperatureMAE=float(abs(rows[160:, 9]-120.4).mean()),
                                         meanValveCommand=float(rows[160:, 51].mean()))
    # Thermal-state subspace: one degree Celsius is the scale on each axis.
    # The first hour supplies 20 output vectors. Common random numbers isolate
    # the closed-loop response to a small change in each initial temperature.
    result['thermalObservability'] = {}
    for h in (.02, .01):
        derivatives = []
        for state in (37, 38):
            plus = simulate(binary, 0, CASES['fit'][1], hours=1, state_offset=(state, h))[0]
            minus = simulate(binary, 0, CASES['fit'][1], hours=1, state_offset=(state, -h))[0]
            derivatives.append((plus[:, CHANNELS] - minus[:, CHANNELS]) / (2*h))
        full = np.column_stack([np.linalg.solve(scale, d.T).ravel() for d in derivatives])
        temperature = np.column_stack([d[:, 0] / np.sqrt(cov[0, 0]) for d in derivatives])
        result['thermalObservability'][h] = {
            name:np.linalg.svd(matrix, compute_uv=False).tolist()
            for name, matrix in [('fiveSignals', full), ('temperatureOnly', temperature)]}
    # Paired central differences at the baseline gain multiplier; same seed for both perturbations.
    sensitivities = {}
    for h in (.02, .01):
        plus = simulate(binary, 4, CASES['evaluation'][1], 1+h)[0]
        minus = simulate(binary, 4, CASES['evaluation'][1], 1-h)[0]
        j = np.linalg.solve(scale, ((plus[:, CHANNELS]-minus[:, CHANNELS])/(2*h)).T)
        sensitivities[h] = dict(before=float(np.linalg.norm(j[:, :160])), after=float(np.linalg.norm(j[:, 160:])))
    result['whitenedGainSensitivityNorm'] = sensitivities
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
