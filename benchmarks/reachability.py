"""Frozen, deterministic held-out cases for reachability and nonlinear replay.

Run from the root with python -m benchmarks.reachability --output recovery.json.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from time import perf_counter
import tracemalloc

import numpy as np
from scipy.integrate import solve_ivp

from l5.reachability import DISTURBANCES, Study, margin
from l5.recovery_studies import STRATEGIES

GRIDS = (17, 41)
MODES = ('nominal', 'robust')
# Initial levels, previous command, repeating disturbance schedule, and known
# planning constraints are fixed independently of the resulting policies.
CASES = {
    'healthy-equilibrium': ((1.5625, 1.), (100, 1), ('nominal',), {}),
    'high-tank-1': ((2.27, .81), (100, 1), ('nominal',), {}),
    'high-tank-2': ((1.36, 2.26), (100, 1), ('nominal',), {}),
    'low-volume': ((.39, .34), (100, 1), ('nominal',), {}),
    'reduced-pump': ((1.18, .71), (100, 1), ('pump-loss',), {}),
    'restricted-valve': ((1.95, .78), (100, 1), ('valve-restriction',), {}),
    'leakage': ((1.13, .85), (100, 1), ('leakage',), {}),
    'limited-pump-authority': ((1.1, .58), (80, 1), ('nominal',), {'pump': [0, 80]}),
    'slow-actuation': ((2.22, .49), (50, .6), ('nominal',), {'slew': [1, .01], 'actionCounts': [4, 5]}),
    'undeclared-combination': ((1.65, .66), (100, 1), ('compound',), {}),
    'near-recovery-frontier-low': ((1.2, .57), (100, 1), ('nominal',), {'horizon': 2}),
    'near-recovery-frontier-high': ((1.31, .65), (100, 1), ('nominal',), {'horizon': 2}),
    'near-operating-limit': ((2.348, .31), (150, .2), ('nominal',), {}),
    'insufficient-volume-zero-inlet': ((.45, .35), (0, 1), ('nominal',), {'pump': [0, 0]}),
    'switching-disturbances': ((1.2, .7), (100, 1), ('input-low', 'pump-loss', 'input-high', 'leakage'), {}),
}
EVAL_DISTURBANCES = {**DISTURBANCES, 'compound': dict(pump=.70, valve=.72, leak=.005, outlet=1.10)}


def independent_transition(config, heads, action, disturbance):
    """Adaptive DOP853 integration of the physical ODE, independent of graph steps."""
    plant = config['plant']
    pump, valve = action
    feed = max(0, plant['pumpRate']*pump/100*disturbance.get('pump', 1) + disturbance.get('inflow', 0))
    connection = plant['connection']*disturbance.get('connection', 1)*valve*disturbance.get('valve', 1)
    outlet = plant['outlet']*disturbance.get('outlet', 1)*plant['outletValve']
    leak = disturbance.get('leak', 0)

    def rhs(_, state):
        h1, h2 = state
        delta = h1-h2
        transfer = connection*math.copysign(math.sqrt(abs(delta)), delta)
        lost1, lost2 = [.1*max(0, h-plant['tankHeight'])**1.5 for h in state]
        return [(feed-transfer-leak*math.sqrt(max(0, h1))-lost1)/plant['area1'],
                (transfer-outlet*math.sqrt(max(0, h2))-lost2)/plant['area2']]

    seconds = config['controlSeconds']
    times = np.linspace(0, seconds, math.ceil(seconds/.05)+1)
    solver = solve_ivp(rhs, (0, seconds), heads, method='DOP853', t_eval=times, rtol=5e-9, atol=1e-10, max_step=.3)
    if not solver.success or not np.all(np.isfinite(solver.y)) or np.min(solver.y) < -1e-8:
        raise RuntimeError('Independent ODE integration failed: ' + solver.message)
    margins = margin(solver.y, config['safe'])
    path = list(zip(times.tolist(), *solver.y.tolist(), margins.tolist()))
    return tuple(solver.y[:, -1]), float(np.min(margins)), path, None


def summarize(rows):
    def metrics(strategy):
        runs = [row['runs'][strategy] for row in rows if strategy in row['runs']]
        recovered = [run for run in runs if run['status'] == 'recovered']
        return dict(recovered=len(recovered), completed=len(runs), successRate=len(recovered)/len(runs) if runs else None,
                    safetyViolations=sum(bool(run['violations']) for run in runs),
                    medianRecoverySeconds=float(np.median([run['recoverySeconds'] for run in recovered])) if recovered else None,
                    meanEffort=np.mean([run['effort'] for run in runs], axis=0).tolist() if runs else None)
    return dict(strategies={key: metrics(key) for key in STRATEGIES},
                optimisticReplayFailures=sum(row['optimisticReplayFailure'] for row in rows),
                inModelOptimisticReplayFailures=sum(row['optimisticReplayFailure'] and row['inModel'] for row in rows),
                falseOptimisticWithImpossibilityProof=sum(row['falseOptimisticWithProof'] for row in rows),
                falsePessimisticWithWitness=sum(row['falsePessimisticWithWitness'] for row in rows),
                finiteNegativeWithRealizationWitness=sum(row['finiteNegativeWithRealizationWitness'] for row in rows),
                numericalFailures=sum(len(row['numericalErrors']) for row in rows))


def evaluate(include_trajectories=False):
    records, resources = [], []
    for grid in GRIDS:
        for mode in MODES:
            studies = {}
            for name, (heads, previous, schedule, changes) in CASES.items():
                key = json.dumps(changes, sort_keys=True)
                if key not in studies:
                    tracemalloc.start()
                    started = perf_counter()
                    try:
                        study = Study(dict(grid=[grid, grid], mode=mode, **changes))
                        peak = tracemalloc.get_traced_memory()[1]
                    finally:
                        tracemalloc.stop()
                    studies[key] = study
                    resources.append(dict(grid=grid, mode=mode, overrides=changes, seconds=perf_counter()-started,
                                          tracedPeakBytes=peak, graphBytes=study.edges.nbytes))
                study = studies[key]
                prev = int(np.flatnonzero(np.all(np.isclose(study.actions, previous), axis=1))[0])
                node = int(study.project(heads))*len(study.actions)+prev
                positive = bool(study.rank[node] >= 0)
                runs, errors = {}, {}
                started = perf_counter()
                for strategy in STRATEGIES:
                    current = ['nominal']

                    def select(k):
                        # The policy already selected its command when this is called.
                        current[0] = schedule[k % len(schedule)]
                        return current[0] if current[0] in DISTURBANCES else 'nominal'

                    def advance(state, action, _):
                        return independent_transition(study.config, state, action, EVAL_DISTURBANCES[current[0]])

                    try:
                        run = study.replay(heads, prev, strategy, select, advance=advance)
                    except RuntimeError as error:
                        errors[strategy] = str(error)
                        continue
                    for k, action in enumerate(run['actions']):
                        action['disturbance'] = schedule[k % len(schedule)]
                    if not include_trajectories:
                        run.pop('trajectory')
                    runs[strategy] = run
                witnessed = [k for k, run in runs.items() if run['status'] == 'recovered']
                # Zero pump authority. Even a worst-case positive bias over the
                # full horizon cannot supply the target's required volume.
                areas = [study.config['plant'][key] for key in ('area1', 'area2')]
                lower_target_volume = np.dot(areas, np.array(study.config['target'])[:, 0])
                max_bias = max(DISTURBANCES[key].get('inflow', 0.) for key in study.scenarios)
                max_volume = np.dot(areas, heads) + max_bias*study.config['horizon']*study.config['controlSeconds']
                proof = study.config['pump'][1] == 0 and bool(max_volume < lower_target_volume)
                finite_negative_with_witness = not positive and bool(witnessed)
                classification = study.inspect(heads, prev)
                clearance = dict(boundary=bool(study.boundary_mask()[node//len(study.actions), prev]),
                                 physicalMargin=float(margin(heads, study.config['safe'])))
                records.append(dict(grid=grid, mode=mode, case=name, heads=heads, previous=previous,
                                    disturbanceSchedule=schedule, config=study.config, finite=classification, **clearance,
                                    runs=runs, numericalErrors=errors, replaySeconds=perf_counter()-started,
                                    inModel=all(key in study.scenarios for key in schedule),
                                    optimisticReplayFailure=positive and 'policy' in runs and 'policy' not in witnessed,
                                    falseOptimisticWithProof=positive and proof,
                                    falsePessimisticWithWitness=finite_negative_with_witness and mode == 'nominal' and schedule == ('nominal',),
                                    finiteNegativeWithRealizationWitness=finite_negative_with_witness, witnessedBy=witnessed,
                                    reference=dict(maximumVolume=float(max_volume), minimumTargetVolume=float(lower_target_volume)) if proof else None))
    groups = {f'{mode}-{grid}': summarize([row for row in records if row['grid'] == grid and row['mode'] == mode])
              for grid in GRIDS for mode in MODES}
    sensitivity = {}
    for mode in MODES:
        coarse, fine = [[r for r in records if r['mode'] == mode and r['grid'] == grid] for grid in GRIDS]
        sensitivity[mode] = dict(rankSignChanges=[a['case'] for a, b in zip(coarse, fine)
                                                   if (a['finite']['rank'] >= 0) != (b['finite']['rank'] >= 0)],
                                 viabilityChanges=[a['case'] for a, b in zip(coarse, fine)
                                                   if a['finite']['viable'] != b['finite']['viable']])
    return dict(protocol='l5-recovery-held-out-v1', groups=groups, gridSensitivity=sensitivity,
                resources=resources, cases=records, disturbanceParameters=EVAL_DISTURBANCES,
                reference=dict(integrator='DOP853', maxStep=.3, marginSampleInterval=.05,
                               rtol=5e-9, atol=1e-10, memory='tracemalloc peak during graph construction'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--trajectories', action='store_true', help='Include all independent ODE samples in the JSON output.')
    options = parser.parse_args()
    result = evaluate(options.trajectories)
    if options.output:
        options.output.parent.mkdir(parents=True, exist_ok=True)
        options.output.write_text(json.dumps(result, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps({key: result[key] for key in ('groups', 'gridSensitivity', 'resources')}, indent=2))
