"""TripLens adapter; the established evidence, tools and forecasts stay model-local."""
from dataclasses import asdict
import secrets
from .base import field, ground_truth, validate_fields

from simulation.platform import (
    ACTIONS, ACTION_PARAMETERS, Config, EDGES, FAULTS, KEYS, META, SYNTHETIC_SCHEMA,
    THRESHOLD, action_parameters, analyze_rows, finite, fit_hypothesis, interventions, run_tools, simulate,
)

MODEL_ID = SYNTHETIC_SCHEMA.id
TOOLS = ['inspect_signal_window', 'analyze_window', 'find_change_point', 'inspect_controller',
         'trace_downstream', 'inspect_alarm_history', 'compare_hypotheses', 'sensor_consistency',
         'recommend_next_measurement', 'query_sop', 'simulate_fault']


class TripLensModel:
    id = MODEL_ID
    version = '2.0.0'

    def describe(self):
        defaults = asdict(Config(step=.2))
        fields = [
            field('start', 'Fault onset', defaults['start'], 0, 100000, group='Fault configuration', unit='s'),
            field('severity', 'Fault severity multiplier', 1, 0, 100, group='Fault configuration'),
            field('fault_duration', 'Fault duration (blank = persistent)', None, .05, 100000, group='Fault configuration', unit='s', nullable=True),
            field('operating', 'Initial temperature offset', 0, -20, 20, group='Initial conditions', unit='°C'),
            field('noise', 'Measurement noise multiplier', 1, 0, 100, group='Noise and timing'),
            field('response', 'Controller response multiplier', 1, .05, 100),
            field('delay', 'Actuator delay', 5, 0, 100000, unit='s'),
            field('duration', 'Simulation duration', 240, .05, 100000, group='Noise and timing', unit='s'),
            field('step', 'Sampling / integration step', .2, .05, 1, group='Noise and timing', unit='s'),
            field('seed', 'Random seed (blank = generate per run)', 1, 0, 2147483647, group='Noise and timing', integer=True, nullable=True),
        ]
        return dict(modelId=self.id, model='TripLens coupled process model', name='TripLens', version=self.version,
            category='Coupled thermal process', description='Two control loops, actuator dynamics, thermal feedback and pressure propagation.',
            source=dict(name='L5 TripLens reduced-order simulator', path='simulation/platform.py'),
            limitations=['Reduced-order synthetic process; evidence scores are not probabilities.', 'Forecasts are conditional; model mismatch is not bounded.'],
            faults={'healthy': 'Healthy operation', **FAULTS}, defaults=defaults, configFields=fields,
            signals=list(META.values()), edges=[dict(source=a,target=b,kind=k) for a,b,k in EDGES],
            actions=[{**a, 'parameters': {'feed_reduce':['feedReduction'], 'setpoint':['setpointDrop'], 'bypass':['bypassFlow'], 'backup_pump':['pumpSpeed'], 'emergency':['emergencyFlow'], 'shutdown':[], 'combined':['feedReduction','bypassFlow']}[a['id']]} for a in ACTIONS],
            actionParameters={k:dict(default=v[0],min=v[1],max=v[2],label=k) for k,v in ACTION_PARAMETERS.items()},
            tools=TOOLS, toolDefinitions=[dict(id=t,name=t,fields=[]) for t in TOOLS],
            capabilities=['simulation','observation','diagnosis','investigation-tools','topology','alarms','interventions','forecast','ground-truth'])

    def validate(self, raw, *, randomize=False):
        if not isinstance(raw, dict) or set(raw) - Config.__dataclass_fields__.keys():
            raise ValueError('Unknown simulation parameters.')
        values = {**asdict(Config()), **raw, 'seed': raw.get('seed')}
        descriptor = self.describe()
        values = validate_fields(values, descriptor['configFields'], asdict(Config()), descriptor['faults'])
        if values.get('seed') is None:
            values['seed'] = secrets.randbelow(2**31) if randomize else None
        # A saved scenario may ask for a fresh seed. A session always fixes it.
        Config(**{**values, 'seed': 1 if values['seed'] is None else values['seed']})
        return values

    def simulate(self, config):
        return simulate(Config(**config))

    def observe(self, session, rows):
        return analyze_rows(rows, source_id=session['id'])

    def tools(self, session, rows, body):
        return dict(asOf=rows[-1]['t'], trace=run_tools(rows, body.get('calls')))

    truth = staticmethod(ground_truth)

    def intervene(self, session, rows, body):
        mode = body.get('mode', 'observed')
        hypothesis = body.get('hypothesis')
        if hypothesis not in FAULTS:
            raise ValueError('Choose a fault hypothesis, including a non-leading candidate if desired.')
        horizon = body.get('horizon', session['config']['duration'])
        at = body.get('at', rows[-1]['t'])
        if not finite(horizon) or not finite(at) or not rows[-1]['t'] <= at <= horizon:
            raise ValueError('Intervention must start at or after the current observations and within the prediction horizon.')
        if mode == 'known':
            if rows[0]['t'] != 0:
                raise ValueError('Known-model forecasts start at the simulation origin; set window start to zero.')
            config = Config(**{**session['config'], 'fault':hypothesis, 'duration':horizon})
            error, origin = None, 0
        elif mode == 'observed':
            origin = rows[0]['t']
            config, error = fit_hypothesis(rows, analyze_rows(rows)['diagnosis'], hypothesis=hypothesis, duration=horizon-origin)
        else:
            raise ValueError('Model mode must be observed or known.')
        actions = body.get('actions', ['bypass'])
        if not isinstance(actions, list) or not actions or len(set(actions)) != len(actions) or any(a not in {x['id'] for x in ACTIONS} for a in actions):
            raise ValueError('Choose one or more unique intervention actions.')
        parameters = action_parameters(body.get('parameters'))
        base = simulate(config, compact=True)
        branches = [dict(action=a, parameters=parameters, **simulate(config, a, at-origin, compact=True, parameters=parameters)) for a in actions]
        for path in [base, *branches]:
            path['times'] = [round(t+origin, 9) for t in path['times']]
            if path['trip'] is not None:
                path['trip'] += origin
            path['safe'] = path['trip'] is None
            path['margin'] = THRESHOLD - path['physicalPeak']
        result = dict(mode=mode, hypothesis=hypothesis, observedThrough=rows[-1]['t'], at=at,
                      horizon=horizon, threshold=THRESHOLD, fitError=error, fittedParameters=asdict(config),
                      baseline=base, branches=branches, scope='simulation-only',
                      uncertainty='Conditional reduced-order model forecast; model mismatch is not bounded.')
        if body.get('search'):
            search = body['search']
            if not isinstance(search, dict):
                raise ValueError('Search needs a resolution in seconds.')
            resolution = search.get('resolution', max(config.step, (horizon-at)/30))
            if not finite(resolution) or resolution <= 0:
                raise ValueError('Search resolution must be positive.')
            steps = (int((horizon-at)/resolution)+2) * len(actions) * (int(config.duration/config.step)+1)
            if steps > 3_000_000:
                raise ValueError('This search exceeds 3,000,000 integration steps. Increase the search resolution or shorten the prediction horizon.')
            recovery = interventions(config, fit_error=error, from_time=at-origin,
                                     resolution=resolution, parameters=parameters, actions=actions)
            for action in recovery['actions']:
                if action['latest'] is not None:
                    action['latest'] += origin
                action['intervals'] = [[round(a+origin,9),round(b+origin,9)] for a,b in action['intervals']]
                for trial in action['trials']:
                    trial['time'] += origin
            result['search'] = recovery
        return result
