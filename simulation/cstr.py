"""Two constant-volume, well-mixed exothermic reactors in a once-through cascade."""
from hashlib import sha256
from pathlib import Path
from time import perf_counter

import numpy as np
from scipy.optimize import brentq

MODEL = sha256(Path(__file__).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
VOLUME = .1  # m³ per reactor
FLOW = .1 / 60  # m³/s
VOLUMETRIC_HEAT_CAPACITY = 239000.  # J/(m³ K)
REACTION_HEAT = 50000.  # J/mol, released
ACTIVATION = 8750.  # E/R in K
PREFACTOR = 7.2e10 / 60  # 1/s
UA = 50000. / 60  # W/K
FEED = np.array([1000., 0., 350.])  # mol/m³, mol/m³, K
COOLANT = 300.
SAMPLE = 10
NOISE = np.array([.5, .5, .025] * 2)
SIGNALS = [
    dict(name=f'{key}_{i}', logicalKey=f'cstr.{key}_{i}', displayName=label, unit=unit,
         device=f'Reactor {i}', category=category)
    for key, label, unit, category in (
        ('a', 'Reactant A', 'mol/m³', 'Simulated measurement'),
        ('b', 'Product B', 'mol/m³', 'Simulated measurement'),
        ('temperature', 'Liquid temperature', 'K', 'Simulated measurement'),
        ('jacket', 'Jacket boundary temperature', 'K', 'Manipulated variable'))
    for i in (1, 2)
]
SIGNALS = [SIGNALS[i] for i in (0, 2, 4, 1, 3, 5, 6, 7)]


def reaction(temperature):
    return PREFACTOR * np.exp(-ACTIVATION / temperature)


def derivative(state, feed, jacket):
    first, second = state.reshape(2, 3)
    rate1, rate2 = reaction(state[2::3]) * state[0::3]
    dilution = FLOW / VOLUME
    thermal = REACTION_HEAT / VOLUMETRIC_HEAT_CAPACITY
    cooling = UA / (VOLUME * VOLUMETRIC_HEAT_CAPACITY)
    t1, t2 = state[2::3]
    return np.concatenate((
        dilution * (feed - first) + [-rate1, rate1, thermal * rate1 + cooling * (jacket[0] - t1)],
        dilution * (first - second) + [-rate2, rate2, thermal * rate2 + cooling * (jacket[1] - t2)]))


def equilibria(inlet, jacket=COOLANT):
    """Solve the reduced scalar heat balance, including all sign-crossing roots."""
    def concentrations(temperature):
        reactant = inlet[0] / (1 + VOLUME / FLOW * reaction(temperature))
        return reactant, inlet[0] + inlet[1] - reactant

    def heat(temperature):
        return (VOLUMETRIC_HEAT_CAPACITY * FLOW * (inlet[2] - temperature)
                + REACTION_HEAT * VOLUME * reaction(temperature) * concentrations(temperature)[0]
                + UA * (jacket - temperature))

    # The no-reaction and full-conversion heat balances bound every possible root.
    conductance = VOLUMETRIC_HEAT_CAPACITY * FLOW + UA
    low = (VOLUMETRIC_HEAT_CAPACITY * FLOW * inlet[2] + UA * jacket) / conductance
    high = low + REACTION_HEAT * FLOW * inlet[0] / conductance
    grid = np.linspace(low, high, 257)
    rates = [heat(t) for t in grid]
    roots = {t for t, rate in zip(grid, rates) if abs(rate) < 1e-9}
    roots.update(brentq(heat, a, b) for a, b, fa, fb in zip(grid[:-1], grid[1:], rates[:-1], rates[1:])
                 if fa * fb < 0 and abs(fa) >= 1e-9 and abs(fb) >= 1e-9)
    return [np.array([*concentrations(t), t]) for t in sorted(roots)]


def initial_state():
    first = equilibria(FEED)[0]
    second = equilibria(first)[0]
    return np.concatenate((first, second))


def linearization(state):
    """Analytic continuous-time state, jacket-input and temperature-output matrices."""
    dilution = FLOW / VOLUME
    cooling = UA / (VOLUME * VOLUMETRIC_HEAT_CAPACITY)
    thermal = REACTION_HEAT / VOLUMETRIC_HEAT_CAPACITY
    a = np.zeros((6, 6))
    b = np.zeros((6, 2))
    c = np.zeros((2, 6))
    a[3:, :3] = dilution * np.eye(3)
    for reactor, offset in enumerate((0, 3)):
        concentration, _, temperature = state[offset:offset + 3]
        k = reaction(temperature)
        dk = concentration * k * ACTIVATION / temperature**2
        a[offset:offset+3, offset:offset+3] = [
            [-dilution - k, 0, -dk], [k, -dilution, dk],
            [thermal * k, 0, -dilution - cooling + thermal * dk]]
        b[offset + 2, reactor] = cooling
        c[reactor, offset + 2] = 1
    return a, b, c


def simulate(fault, seed, *, duration=1800, onset=600, intervention_at=660, control=False,
             step=1, observe=None, check=None):
    if (fault not in ('normal', 'warm-feed', 'lean-feed') or type(step) is not int
            or step < 1 or SAMPLE % step or any(type(t) is not int or t % SAMPLE for t in
                                               (duration, onset, intervention_at))
            or not 0 <= onset <= intervention_at <= duration):
        raise ValueError('CSTR events and duration must align with the ten-second observation clock.')
    start = perf_counter()
    initial = initial_state()
    state = initial.copy()
    target = state[2]
    rng = np.random.default_rng(seed)
    rows, states = [], []
    feed = FEED.copy()
    jacket = np.full(2, COOLANT)
    integral = 0.
    for at in range(0, duration + 1, SAMPLE):
        if check:
            check()
        values = state + rng.normal(scale=NOISE)
        if fault == 'warm-feed' and at >= onset:
            feed[2] = FEED[2] + 6.
        elif fault == 'lean-feed' and at >= onset:
            feed[0] = .92 * FEED[0]
        if control and at >= intervention_at:
            error = values[2] - target
            output = COOLANT - 1.25 * error - .025 * integral
            jacket[0] = np.clip(output, 285., 305.)
            if output == jacket[0] or (error > 0 and output > 305.) or (error < 0 and output < 285.):
                integral += SAMPLE * error
        row = np.r_[at, values, jacket]
        rows.append(row)
        states.append(state.copy())
        if observe:
            observe(row)
        if at == duration:
            break
        for _ in range(SAMPLE // step):
            k1 = derivative(state, feed, jacket)
            k2 = derivative(state + step / 2 * k1, feed, jacket)
            k3 = derivative(state + step / 2 * k2, feed, jacket)
            k4 = derivative(state + step * k3, feed, jacket)
            state += step / 6 * (k1 + 2*k2 + 2*k3 + k4)
        if not np.isfinite(state).all() or np.any(state[[0, 1, 3, 4]] < 0) or np.any(state[2::3] <= 0):
            raise ValueError('CSTR integration left the physical state domain.')
    return np.asarray(rows), dict(runtimeSeconds=perf_counter() - start,
                                  nominalReactorTemperatureK=initial[2::3].tolist()), np.asarray(states)
