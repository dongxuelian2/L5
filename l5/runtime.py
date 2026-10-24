"""Runtime process sessions, prefix analysis and persistent user experiments."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import asdict
import json
from pathlib import Path
import re
import secrets
from threading import RLock
from uuid import uuid4

from simulation.platform import (
    ACTIONS, ACTION_PARAMETERS, Config, EDGES, FAULTS, KEYS, META, SYNTHETIC_SCHEMA,
    THRESHOLD, action_parameters, analyze_rows, finite, fit_hypothesis, interventions, run_tools, simulate,
)

MODEL_ID = SYNTHETIC_SCHEMA.id
TOOLS = ['inspect_signal_window', 'analyze_window', 'find_change_point', 'inspect_controller',
         'trace_downstream', 'inspect_alarm_history', 'compare_hypotheses', 'sensor_consistency',
         'recommend_next_measurement', 'query_sop', 'simulate_fault']


def catalog():
    return dict(modelId=MODEL_ID, model='TripLens coupled process model',
                faults={'healthy': 'Healthy operation', **FAULTS}, defaults=asdict(Config()),
                signals=list(META.values()), edges=[dict(source=a, target=b, kind=k) for a,b,k in EDGES],
                actions=ACTIONS, actionParameters={k: dict(default=v[0], min=v[1], max=v[2]) for k,v in ACTION_PARAMETERS.items()}, tools=TOOLS,
                capabilities=['simulation', 'diagnosis', 'topology', 'alarms', 'interventions'])


class SimulationService:
    def __init__(self, store):
        self.store = store
        self.root = store.root / 'simulations'
        self.root.mkdir(exist_ok=True)
        self.cache = OrderedDict()
        self.lock = RLock()

    def folder(self, identity):
        if not isinstance(identity, str) or not re.fullmatch('[a-f0-9]{32}', identity):
            raise KeyError('Simulation not found.')
        return self.root / identity

    @staticmethod
    def write(path: Path, value):
        temporary = path.with_name(f'{path.stem}.{uuid4().hex}.tmp')
        temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        temporary.replace(path)

    def get(self, identity):
        path = self.folder(identity) / 'session.json'
        if not path.exists():
            raise KeyError('Simulation not found.')
        return json.loads(path.read_text(encoding='utf-8'))

    def list(self, workspace_id=None):
        if workspace_id:
            self.store.workspace(workspace_id)
        sessions = []
        for path in self.root.glob('*/session.json'):
            session = json.loads(path.read_text(encoding='utf-8'))
            if workspace_id is None or session.get('workspaceId') == workspace_id:
                sessions.append({k:v for k,v in session.items() if k != 'rows'})
        return sorted(sessions, key=lambda s:s['createdAt'], reverse=True)

    def create(self, body):
        raw = body.get('config', {})
        if not isinstance(raw, dict) or set(raw) - Config.__dataclass_fields__.keys():
            raise ValueError('Unknown simulation parameters.')
        config = Config(**{**raw, 'seed': raw.get('seed') if raw.get('seed') is not None else secrets.randbelow(2**31)})
        workspace_id = body.get('workspaceId')
        if workspace_id:
            self.store.workspace(workspace_id)
        from .workspace import now
        session = dict(id=uuid4().hex, title=self.store.name(body.get('title') or f"{catalog()['faults'][config.fault]} experiment"),
                       modelId=MODEL_ID, config=asdict(config), rows=simulate(config),
                       createdAt=now(), workspaceId=workspace_id, datasetId=None)
        folder = self.folder(session['id'])
        folder.mkdir()
        self.write(folder / 'session.json', session)
        return session

    def window(self, identity, body):
        session = self.get(identity)
        end = body.get('asOf', session['config']['duration'])
        start = body.get('windowStart', 0)
        if not finite(end) or not finite(start) or not 0 <= start <= end <= session['config']['duration']:
            raise ValueError('Choose a window inside this simulation.')
        rows = [r for r in session['rows'] if start <= r['t'] <= end]
        if len(rows) < 2:
            raise ValueError('This window has fewer than two observations.')
        return session, rows

    def analysis(self, identity, body):
        session, rows = self.window(identity, body)
        key = (identity, rows[0]['t'], rows[-1]['t'])
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                return {**self.cache[key], 'asOf':body.get('asOf', rows[-1]['t'])}
        result = dict(**analyze_rows(rows, source_id=identity), asOf=body.get('asOf', rows[-1]['t']),
                      observedThrough=rows[-1]['t'], windowStart=rows[0]['t'], samples=len(rows))
        with self.lock:
            self.cache[key] = result
            while len(self.cache) > 128:
                self.cache.popitem(last=False)
        return result

    def record(self, identity, kind, body, result):
        from .workspace import now
        record = dict(id=uuid4().hex, kind=kind, request=body, result=result, createdAt=now())
        folder = self.folder(identity) / 'runs'
        folder.mkdir(exist_ok=True)
        self.write(folder / f"{record['id']}.json", record)
        return record

    def runs(self, identity):
        self.get(identity)
        return sorted([json.loads(p.read_text(encoding='utf-8')) for p in (self.folder(identity)/'runs').glob('*.json')], key=lambda r:r['createdAt'], reverse=True)

    def run(self, identity, run_id):
        self.get(identity)
        if not isinstance(run_id, str) or not re.fullmatch('[a-f0-9]{32}', run_id):
            raise KeyError('Simulation experiment not found.')
        path = self.folder(identity) / 'runs' / f'{run_id}.json'
        if not path.exists():
            raise KeyError('Simulation experiment not found.')
        return json.loads(path.read_text(encoding='utf-8'))

    def tools(self, identity, body):
        _, rows = self.window(identity, body)
        result = dict(asOf=rows[-1]['t'], trace=run_tools(rows, body.get('calls')))
        return self.record(identity, 'tools', body, result)

    def intervene(self, identity, body):
        session, rows = self.window(identity, body)
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
        return self.record(identity, 'intervention', body, result)

    def save(self, identity, body):
        session = self.get(identity)
        workspace_id = body.get('workspaceId') or session.get('workspaceId')
        self.store.workspace(workspace_id)
        if session.get('datasetId') and session.get('workspaceId') == workspace_id:
            return self.store.dataset(session['datasetId'])
        columns = ['t', *KEYS]
        text = ','.join(columns) + '\n' + '\n'.join(','.join(str(r[k]) for k in columns) for r in session['rows'])
        dataset = self.store.import_dataset(workspace_id, dict(csv=text, name=body.get('name') or session['title'], filename=f'{identity}.csv'),
                                            model=dict(id=MODEL_ID, simulationId=identity, capabilities=catalog()['capabilities']))
        session.update(workspaceId=workspace_id, datasetId=dataset['id'])
        self.write(self.folder(identity) / 'session.json', session)
        return dataset
