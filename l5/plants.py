"""Executable plant definitions and supported investigation settings."""
from dataclasses import dataclass
from hashlib import sha256
import json
from uuid import NAMESPACE_URL, uuid5

from simulation import cstr, tep


TEP_CHANNELS = [9, 21, 22, 51, 52]


@dataclass(frozen=True)
class Plant:
    id: str
    name: str
    version: str
    equipment: tuple[str, ...]
    connection: str
    mode: str
    sample: int
    channels: tuple[int, ...]
    signals: list[dict]
    references: dict
    fit_seed: int
    calibration_seed: int
    lookback: int
    followup: int
    limits: dict


TEP = Plant('tep', 'Tennessee Eastman', tep.MODEL,
    ('Feed system', 'Reactor', 'Separator and condenser', 'Recycle compressor', 'Stripper'),
    'Feeds enter the reactor. The condenser and separator split the reactor outlet between recycle and the stripper.',
    'Mode 1 · TEINIT and native velocity PI', 180, tuple(TEP_CHANNELS),
    [dict(s, logicalKey='tep.' + s['name']) for s in tep.SIGNALS],
    {'reactor-reference': (4, 4346024432), 'condenser-reference': (5, 5784921734)},
    4243534565, 1254545354, 1800, 3600,
    {'reactorPressureMaxKPaGauge': 3000, 'reactorTemperatureMaxC': 175,
     'reactorLiquidVolumeM3': [2, 24], 'separatorLiquidVolumeM3': [1, 12],
     'stripperLiquidVolumeM3': [1, 8], 'valvePercent': [0, 100]})
CSTR = Plant('cstr', 'Cascaded stirred-tank reactors', cstr.MODEL,
    ('Feed system', 'Reactor 1', 'Reactor 2'),
    'Feed enters Reactor 1. Its effluent feeds Reactor 2. Each vessel has a separate jacket temperature boundary.',
    'Cold stable equilibrium · once-through flow', cstr.SAMPLE, (1, 3, 4, 6), cstr.SIGNALS,
    {'warm-feed-reference': ('warm-feed', 907), 'lean-feed-reference': ('lean-feed', 709)},
    113, 313, 120, 180,
    {'reactorTemperatureReviewK': 335, 'jacketCommandK': [285, 305], 'concentrationMinimumMolM3': 0})


@dataclass(frozen=True)
class Scenario:
    id: str
    plant: Plant
    title: str
    mechanism: str
    fault: int | str
    seed: int
    duration: int
    onset: int
    intervention: int
    comparison: str


SCENARIOS = {s.id: s for s in (
    Scenario('reactor-cooling', TEP, 'Reactor cooling-water inlet step',
             'Reactor coolant warms by 5 °C. Reactor temperature and cooling valve respond.',
             4, 4598956239, 86400, 28800, 28800, 'Half reactor cooling-loop gain'),
    Scenario('condenser-cooling', TEP, 'Condenser cooling-water inlet step',
             'Condenser coolant warms by 5 °C. Separator cooling and downstream measurements respond.',
             5, 5658678765, 86400, 28800, 28800, 'Reduced condenser cooling-loop gain'),
    Scenario('cstr-feed-warming', CSTR, 'Warm feed to Reactor 1',
             'Feed temperature rises by 6 K. The thermal and reaction transient propagates to Reactor 2.',
             'warm-feed', 659, 1800, 600, 660, 'Bounded Reactor 1 jacket PI'),
    Scenario('cstr-feed-dilution', CSTR, 'Lean feed to Reactor 1',
             'Feed reactant concentration drops by 8%. Reactant, product and reaction heat change in both reactors.',
             'lean-feed', 857, 1800, 600, 660, 'Bounded Reactor 1 jacket PI'),
)}


def settings(scenario, supplied=None):
    supplied = supplied or {}
    defaults = dict(durationSeconds=scenario.duration, onsetSeconds=scenario.onset,
                    interventionSeconds=scenario.intervention, seed=scenario.seed)
    if scenario.plant is TEP:
        defaults['gain'] = .5
    if set(supplied) - defaults.keys():
        raise ValueError('Unknown run setting for this plant.')
    config = defaults | supplied
    duration, onset, intervention, seed = (config[k] for k in
        ('durationSeconds', 'onsetSeconds', 'interventionSeconds', 'seed'))
    p = scenario.plant
    if (any(type(t) is not int or t % p.sample for t in (duration, onset, intervention))
            or not p.sample * 101 <= duration <= (172800 if p is TEP else 7200)
            or not p.lookback + p.sample <= onset <= duration - p.followup
            or not onset <= intervention <= duration - p.sample):
        raise ValueError(f'Use {p.sample}-second ticks and leave the required observation windows before and after the event.')
    if (type(seed) is not int or not 0 < seed < 2**53
            or seed in {p.fit_seed, p.calibration_seed, *(value[1] for value in p.references.values())}):
        raise ValueError('Choose a positive integer evaluation seed below 2⁵³, distinct from the fit, calibration and diagnosis seeds.')
    if p is TEP and (type(config['gain']) not in (int, float) or not .1 <= config['gain'] <= 1.5):
        raise ValueError('Choose a reactor cooling-gain multiplier from 0.1 to 1.5.')
    return config


def run_key(scenario, config):
    return sha256(json.dumps([scenario.id, scenario.plant.version, config], sort_keys=True).encode()).hexdigest()


def run_id(key):
    return uuid5(NAMESPACE_URL, 'l5:plant:' + key).hex


def catalog():
    return [dict(id=p.id, name=p.name, equipment=p.equipment, connection=p.connection,
                 version=p.version, mode=p.mode, sampleSeconds=p.sample, limits=p.limits,
                 signals=[p.signals[i-1] for i in p.channels],
                 scenarios=[dict(id=s.id, title=s.title, mechanism=s.mechanism, comparison=s.comparison,
                                 settings=settings(s)) for s in SCENARIOS.values() if s.plant is p])
            for p in (TEP, CSTR)]
