"""Finite reachability and controlled invariance for the L5 coupled tanks.

Heads are metres. Pump commands are percentage points and valve commands are
fractions. The graph state is (head grid point, previous pump/valve command).
"""
from __future__ import annotations

import math
from time import perf_counter

import numpy as np

from .models import resolve
from .models.base import finite
from .models.tanks import donor_stage, hydraulic_flows

MODEL = 'coupled-tanks'
LEVEL_TOLERANCE = 1e-10
PLANT_KEYS = ('area1', 'area2', 'connection', 'outlet', 'pumpRate', 'outletValve', 'tankHeight')
DISTURBANCES = {
    'nominal': {},
    'pump-loss': {'pump': .85},
    'valve-restriction': {'valve': .86},
    'leakage': {'leak': .003},
    'input-low': {'inflow': -.002},
    'input-high': {'inflow': .002},
    'hydraulic-mismatch': {'connection': .90, 'outlet': 1.05},
}


def defaults():
    model = resolve(MODEL).describe()
    return dict(modelId=MODEL, plant={key: model['defaults'][key] for key in PLANT_KEYS},
                safe=[[.3, 2.35], [.25, 2.35]], target=[[1.4, 1.8], [.85, 1.15]],
                pump=[0, 150], valve=[.2, 1], slew=[6, .05], actionCounts=[4, 3],
                grid=[29, 29], horizon=16, controlSeconds=10, integrationStep=.1,
                mode='nominal', disturbances=list(DISTURBANCES)[1:])


def vector(value, size):
    return isinstance(value, (tuple, list)) and len(value) == size and all(finite(v) for v in value)


def validate(raw):
    config = defaults()
    if not isinstance(raw, dict) or raw.keys() - config.keys() or raw.get('modelId', MODEL) != MODEL:
        raise ValueError('Choose a supported coupled-tank reachability configuration.')
    config.update(raw)
    plant = config['plant']
    if not isinstance(plant, dict) or plant.keys() - set(PLANT_KEYS):
        raise ValueError('Choose supported hydraulic parameters.')
    validated_plant = resolve(MODEL).validate(plant)
    config['plant'] = {key: validated_plant[key] for key in PLANT_KEYS}
    maximum = validated_plant['tankHeight']
    for key in ('safe', 'target'):
        region = config[key]
        if not isinstance(region, (tuple, list)) or len(region) != 2 or any(
                not vector(bounds, 2) or not 0 <= bounds[0] < bounds[1] <= maximum for bounds in region):
            # Keep field names in a separate error so clients can localize the message.
            raise ValueError('Use increasing tank level limits within the model overflow height.')
        config[key] = [list(bounds) for bounds in region]
    if any(not lo <= tlo < thi <= hi for (lo, hi), (tlo, thi) in zip(config['safe'], config['target'])):
        raise ValueError('The recovery target must lie entirely inside the operating region.')
    for key, low, high in [('pump', 0, 150), ('valve', .01, 1)]:
        bounds = config[key]
        if not vector(bounds, 2) or not low <= bounds[0] <= bounds[1] <= high:
            raise ValueError('Use valid pump and valve command bounds.')
    if not vector(config['slew'], 2) or any(not 0 <= v <= high for v, high in zip(config['slew'], (150, 1))):
        raise ValueError('Use slew limits of 0–150 percentage points/s and 0–1 fraction/s.')
    for key, low, high in [('grid', 7, 61), ('actionCounts', 2, 5)]:
        values = config[key]
        if not vector(values, 2) or any(int(v) != v or not low <= v <= high for v in values):
            raise ValueError('Use 7–61 level points per axis and 2–5 samples per actuator.')
        config[key] = list(map(int, values))
    for key, low, high in [('horizon', 1, 40), ('controlSeconds', 1, 30), ('integrationStep', .02, .25)]:
        v = config[key]
        if not finite(v) or not low <= v <= high or (key == 'horizon' and int(v) != v):
            raise ValueError('Use 1–40 control steps, 1–30 s per step and 0.02–0.25 s for integration.')
    config['horizon'] = int(config['horizon'])
    declared = config['disturbances']
    if (config['mode'] not in ('nominal', 'robust') or not isinstance(declared, list)
            or len(declared) > len(DISTURBANCES)-1 or any(
                not isinstance(v, str) or v == 'nominal' or v not in DISTURBANCES for v in declared)
            or len(set(declared)) != len(declared) or (config['mode'] == 'robust' and not declared)):
        raise ValueError('Choose unique modeled disturbances for robust analysis.')
    config['disturbances'] = [key for key in DISTURBANCES if key in declared]
    return config


def margin(heads, bounds):
    """Signed distance to the nearest tank limit in metres, including overflow."""
    return np.minimum(np.minimum(heads[0]-bounds[0][0], bounds[0][1]-heads[0]),
                      np.minimum(heads[1]-bounds[1][0], bounds[1][1]-heads[1]))


def disturbed_plant(plant, disturbance):
    return {**plant, 'connection': plant['connection']*disturbance.get('connection', 1.),
            'outlet': plant['outlet']*disturbance.get('outlet', 1.)}


def physical_step(config, heads, action, disturbance, max_step, *, trace=False):
    """Advance one constant command interval on the shared conservative solver.

    Check all accepted substep states. The output trace, when requested, uses
    local times and includes t=0 and the exact next switching boundary.
    """
    plant = disturbed_plant(config['plant'], disturbance)
    duration = config['controlSeconds']
    count = math.ceil(duration / max_step)
    dt = duration / count
    pump, opening = action
    opening *= disturbance.get('valve', 1.)
    safety = margin(heads, config['safe'])
    mass = 0.

    def stage(state):
        flux = hydraulic_flows(plant, state, pump, opening, disturbance.get('pump', 1.),
                               disturbance.get('leak', 0.), disturbance.get('inflow', 0.), ops=np)
        return donor_stage(plant, state, flux, dt, ops=np)

    path = [(0., *heads, float(safety))] if trace else None
    for i in range(count):
        left, fa = stage(heads)
        right, fb = stage(left)
        heads = ((heads[0]+right[0])*.5, (heads[1]+right[1])*.5)
        safety = np.minimum(safety, margin(heads, config['safe']))
        if trace:
            mass += dt*.5*sum(f[0]-sum(f[2:]) for f in (fa, fb))
            path.append((duration if i+1 == count else dt*(i+1), *map(float, heads),
                         float(margin(heads, config['safe']))))
    return heads, safety, path, mass


def predecessor(edges, members):
    """Edges are [state, action, disturbance]; -1 is a rejected transition."""
    return np.all((edges >= 0) & members[edges], axis=-1)


def reach(edges, target, horizon, movement):
    """Synchronous backward layers, with one witness for each earliest rank."""
    rank = np.where(target, 0, -1)
    witness = np.full(len(target), -1, dtype=np.int16)
    for step in range(1, horizon+1):
        allowed = predecessor(edges, rank >= 0)
        new = (rank < 0) & allowed.any(axis=1)
        if not new.any():
            break
        rank[new] = step
        witness[new] = np.where(allowed[new], movement[new], np.inf).argmin(axis=1)
    return rank, witness


def viability(edges, safe):
    """Greatest fixed point via parallel removals and reverse outcome edges."""
    n, actions, outcomes = edges.shape
    flat = edges.ravel()
    positions = np.flatnonzero(flat >= 0)
    positions = positions[np.argsort(flat[positions])]
    offsets = np.r_[0, np.cumsum(np.bincount(flat[positions], minlength=n))]
    valid = predecessor(edges, safe)
    counts = valid.sum(axis=1)
    valid = valid.ravel()
    members = safe.copy()
    removed = np.flatnonzero(safe & (counts == 0))
    iterations = 1  # includes the final fixed-point comparison
    while removed.size:
        iterations += 1
        members[removed] = False
        starts = offsets[removed]
        lengths = offsets[removed+1] - starts
        indices = np.repeat(starts - (lengths.cumsum() - lengths), lengths)
        affected = np.unique(positions[indices + np.arange(lengths.sum())] // outcomes)
        disabled = affected[valid[affected]]
        valid[disabled] = False
        sources = disabled // actions
        np.subtract.at(counts, sources, 1)
        removed = np.unique(sources[members[sources] & (counts[sources] == 0)])
    return members, iterations


class Study:
    def __init__(self, raw):
        start = perf_counter()
        self.config = config = validate(raw)
        axes = [np.linspace(0, config['plant']['tankHeight']*1.08, n) for n in config['grid']]
        self.axes = axes
        self.spacing = [float(axis[1]-axis[0]) for axis in axes]
        self.centers = np.stack(np.meshgrid(*axes, indexing='ij'), axis=-1).reshape(-1, 2)
        self.safe = margin(self.centers.T, config['safe']) >= -LEVEL_TOLERANCE
        self.target = margin(self.centers.T, config['target']) >= -LEVEL_TOLERANCE
        if not self.target.any():
            raise ValueError('The target contains no grid points. Refine the grid or widen the target.')
        levels = [np.unique(np.linspace(*config[key], num=n)) for key, n in
                  zip(('pump', 'valve'), config['actionCounts'])]
        self.actions = np.stack(np.meshgrid(*levels, indexing='ij'), axis=-1).reshape(-1, 2)
        a = len(self.actions)
        self.scenarios = ['nominal', *config['disturbances']] if config['mode'] == 'robust' else ['nominal']
        d = len(self.scenarios)
        physical_steps = int(self.safe.sum()) * a * d * math.ceil(config['controlSeconds']/config['integrationStep'])
        if len(self.centers)*a*a*d > 5_000_000 or physical_steps > 80_000_000:
            raise ValueError('This study exceeds the graph or integration budget. Reduce the grid, actions or disturbances.')

        difference = abs(self.actions[:, None, :] - self.actions[None, :, :])
        self.slew = np.all(difference <= np.array(config['slew'])*config['controlSeconds'] + 1e-12, axis=2)
        movement = (difference / [150., 1.]).sum(axis=2)
        destinations = np.full((len(self.centers), a, d), -1, dtype=np.int32)
        for s, name in enumerate(self.scenarios):
            for j, action in enumerate(self.actions):
                endpoints, minimum, _, _ = physical_step(config, tuple(self.centers[self.safe].T), action,
                                                         DISTURBANCES[name], config['integrationStep'])
                cells = self.project(endpoints)
                accepted = (minimum >= -LEVEL_TOLERANCE) & np.isfinite(minimum) & self.safe[cells]
                destinations[self.safe, j, s] = np.where(accepted, cells*a + j, -1)
        graph = np.where(self.slew[None, :, :, None], destinations[:, None, :, :], -1)
        nominal = graph[..., :1].reshape(-1, a, 1)
        self.edges = graph.reshape(-1, a, d)
        safe = np.repeat(self.safe, a)
        target = np.repeat(self.target, a)
        tie_break = np.tile(movement, (len(self.centers), 1))
        self.rank, self.witness = reach(self.edges, target, config['horizon'], tie_break)
        self.viable, self.iterations = viability(self.edges, safe)
        self.viable_target_rank, _ = reach(self.edges, target & self.viable, config['horizon'], tie_break)
        if d > 1:
            self.nominal_rank, _ = reach(nominal, target, config['horizon'], tie_break)
            self.nominal_viable, self.nominal_iterations = viability(nominal, safe)
        else:
            self.nominal_rank, self.nominal_viable, self.nominal_iterations = self.rank, self.viable, self.iterations
        self.duration = perf_counter()-start

    def project(self, heads):
        nx, ny = self.config['grid']
        i = np.clip(np.floor(heads[0]/self.spacing[0]+.5).astype(int), 0, nx-1)
        j = np.clip(np.floor(heads[1]/self.spacing[1]+.5).astype(int), 0, ny-1)
        return i*ny+j

    def boundary_mask(self):
        """Flags cells at physical limits or touching differing graph outcomes."""
        config = self.config
        half = np.array(self.spacing)*.5
        geometric = np.zeros(len(self.centers), dtype=bool)
        for key in ('safe', 'target'):
            box = np.array(config[key])
            heads = self.centers
            intersects = np.all((heads + half >= box[:, 0]) & (heads - half <= box[:, 1]), axis=1)
            contained = np.all((heads - half > box[:, 0]) & (heads + half < box[:, 1]), axis=1)
            geometric |= intersects & ~contained
        nx, ny = config['grid']
        flags = np.broadcast_to(geometric[:, None], (len(self.centers), len(self.actions))).copy()
        comparison = ((self.rank >= 0).astype(np.int8) + 2*self.viable + 4*(self.rank == 0)
                      + 8*(self.nominal_rank >= 0) + 16*self.nominal_viable
                      + 32*(self.viable_target_rank >= 0)).reshape(nx, ny, -1)
        grid_flags = flags.reshape(nx, ny, -1)
        grid_flags[:-1] |= comparison[:-1] != comparison[1:]
        grid_flags[1:] |= comparison[:-1] != comparison[1:]
        grid_flags[:, :-1] |= comparison[:, :-1] != comparison[:, 1:]
        grid_flags[:, 1:] |= comparison[:, :-1] != comparison[:, 1:]
        return flags

    def result(self):
        a = len(self.actions)
        by_head = lambda array: array.reshape(-1, a).tolist()
        flags = self.boundary_mask()
        return dict(format='l5-reachability-v1', config=self.config, modelVersion=resolve(MODEL).version,
                    numerical=dict(axes=[axis.tolist() for axis in self.axes], spacing=self.spacing,
                                   actions=self.actions.tolist(), scenarios={key: DISTURBANCES[key] for key in self.scenarios},
                                   horizonSeconds=self.config['controlSeconds']*self.config['horizon'],
                                   convergence=True, viabilityIterations=self.iterations,
                                   nominalViabilityIterations=self.nominal_iterations,
                                   seconds=self.duration, graphBytes=self.edges.nbytes,
                                   safeAugmentedStates=int(self.safe.sum())*a,
                                   acceptedActions=int(np.sum(np.all(self.edges >= 0, axis=-1))),
                                   boundaryAugmentedStates=int(flags.sum()),
                                   levelTolerance=LEVEL_TOLERANCE,
                                   projection='nearest-point-ties-up', slewSemantics='sampled-command',
                                   targetSemantics='checked-at-command-boundaries',
                                   integration='donor-limited-ssprk2', scope='representative-point-approximation'),
                    safe=self.safe.tolist(), target=self.target.tolist(), ranks=by_head(self.rank),
                    policy=by_head(self.witness), viable=by_head(self.viable),
                    viableTargetRanks=by_head(self.viable_target_rank),
                    nominalRanks=by_head(self.nominal_rank), nominalViable=by_head(self.nominal_viable),
                    boundary=flags.tolist())

    def inspect(self, heads, previous):
        cell = int(self.project(heads))
        node = cell*len(self.actions)+previous
        safe = margin(heads, self.config['safe']) >= -LEVEL_TOLERANCE
        if not safe:
            category = 'unsafe'
        elif margin(heads, self.config['target']) >= -LEVEL_TOLERANCE:
            category = 'target'
        elif (not self.safe[cell] or self.target[cell] or
              (not np.allclose(self.centers[cell], heads, atol=1e-10, rtol=0) and self.boundary_mask()[cell, previous])):
            category = 'uncertain'
        else:
            category = 'recoverable' if self.rank[node] >= 0 else 'nonrecoverable'
        return dict(category=category, cell=cell, rank=int(self.rank[node]) if safe else -1,
                    viable=bool(self.viable[node] and safe))

    def replay(self, heads, previous, strategy='policy', realization='nominal', advance=None):
        """Re-evaluate the stored feedback map on unsnapped physical states."""
        config = self.config
        if not vector(heads, 2) or any(not 0 <= v <= 10.8 for v in heads):
            raise ValueError('Enter two physical heads between 0 and 10.8 m.')
        if not finite(previous) or int(previous) != previous or not 0 <= previous < len(self.actions):
            raise ValueError('Choose a previous pump and valve command from the action grid.')
        if strategy not in ('policy', 'hold', 'drain', 'fill'):
            raise ValueError('Choose a supported recovery strategy.')
        if advance is None:
            def advance(heads, action, disturbance):
                return physical_step(config, heads, action, disturbance, config['integrationStep']*.5, trace=True)

        initial = list(heads)
        previous = int(previous)
        initial_previous = previous
        safety = float(margin(heads, config['safe']))
        rows = [dict(t=0., level1=heads[0], level2=heads[1], safetyMargin=safety,
                     pump=float(self.actions[previous, 0]), valve=float(self.actions[previous, 1]))]
        actions, violations = [], []
        motion = np.zeros(2)
        effort = np.zeros(2)
        elapsed = 0.
        status = 'horizonExpired'
        for k in range(config['horizon']+1):
            if safety < -LEVEL_TOLERANCE:
                status = 'unsafe'
                violations = [dict(t=r['t'], margin=r['safetyMargin']) for r in rows
                              if r['safetyMargin'] < -LEVEL_TOLERANCE]
                break
            if margin(heads, config['target']) >= -LEVEL_TOLERANCE:
                status = 'recovered'
                break
            if k == config['horizon']:
                break
            if strategy == 'policy':
                node = int(self.project(heads))*len(self.actions)+previous
                selected = int(self.witness[node])
                if selected < 0 or self.rank[node] > config['horizon']-k:
                    status = 'no-policy'
                    break
            elif strategy == 'hold':
                selected = previous
            else:
                # Fixed emergency targets, approached on the same slew-limited alphabet.
                desired = np.array([config['pump'][strategy == 'fill'], config['valve'][1]])
                distance = (abs(self.actions-desired)/[150., 1.]).sum(axis=1)
                selected = int(np.where(self.slew[previous], distance, np.inf).argmin())
            pump, valve = map(float, self.actions[selected])
            name = realization(k) if callable(realization) else realization
            disturbance = DISTURBANCES[name]
            if not self.slew[previous, selected]:
                raise RuntimeError('Invalid finite policy witness.')
            motion += abs(self.actions[selected]-self.actions[previous])
            effort += self.actions[selected]*config['controlSeconds']
            actions.append(dict(t=elapsed, pump=pump, valve=valve, disturbance=name))
            heads, interval_margin, points, _ = advance(heads, (pump, valve), disturbance)
            rows[-1].update(pump=pump, valve=valve)
            rows.extend(dict(t=elapsed+t, level1=h1, level2=h2, safetyMargin=m, pump=pump, valve=valve)
                        for t, h1, h2, m in points[1:])
            safety = min(safety, float(interval_margin))
            elapsed = (k+1)*config['controlSeconds']
            previous = selected
        return dict(strategy=strategy, status=status, initial=initial, previousAction=initial_previous,
                    elapsedSeconds=elapsed, recoverySeconds=elapsed if status == 'recovered' else None,
                    minimumMargin=safety, movement=motion.tolist(), effort=effort.tolist(),
                    actions=actions, trajectory=rows, violations=violations)
