"""User-maintained investigations in the Workspace SQLite database.

Detection intervals and runtime experiments remain owned by their existing stores.
An incident collects references to them and editable investigation records.
"""
from __future__ import annotations

from datetime import datetime
import json
import math
from uuid import uuid4

from .workspace import now
from .safety import EVIDENCE_KINDS


STATUSES = ('open', 'investigating', 'resolved', 'archived')
KINDS = ('note', 'evidence', 'hypothesis')


def text(value, label, limit=50000):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f'{label} must be text with at most {limit} characters.')
    return value.strip()


def seconds(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Time must be a finite number of seconds.')
    return value


class IncidentService:
    def __init__(self, store):
        self.store = store
        # Additive migration: existing datasets, results and simulation files stay in place.
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS incidents (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
                    start_time REAL, end_time REAL, time_origin TEXT,
                    status TEXT NOT NULL DEFAULT 'open', conclusion TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS incidents_workspace ON incidents(workspace_id, updated_at);
                CREATE TABLE IF NOT EXISTS incident_links (
                    id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL, reference_id TEXT NOT NULL, selector TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(incident_id, kind, reference_id, selector));
                CREATE TABLE IF NOT EXISTS incident_entries (
                    id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL, title TEXT NOT NULL, content TEXT NOT NULL DEFAULT '',
                    hypothesis_id TEXT REFERENCES incident_entries(id) ON DELETE SET NULL,
                    stance TEXT NOT NULL DEFAULT 'neutral',
                    source_link_id TEXT REFERENCES incident_links(id) ON DELETE SET NULL,
                    model_hypothesis TEXT,
                    observed_at REAL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS incident_entries_owner ON incident_entries(incident_id, created_at);
                CREATE TABLE IF NOT EXISTS incident_history (
                    id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
                    changes TEXT NOT NULL, recorded_at TEXT NOT NULL);
            ''')
            if 'model_hypothesis' not in {r['name'] for r in db.execute('PRAGMA table_info(incident_entries)')}:
                db.execute('ALTER TABLE incident_entries ADD COLUMN model_hypothesis TEXT')
            incident_columns = {r['name'] for r in db.execute('PRAGMA table_info(incidents)')}
            if 'time_axis_key' not in incident_columns:
                db.execute('ALTER TABLE incidents ADD COLUMN time_axis_key TEXT')
            if 'time_axis_snapshot' not in incident_columns:
                db.execute('ALTER TABLE incidents ADD COLUMN time_axis_snapshot TEXT')
            if 'observed_axis_key' not in {r['name'] for r in db.execute('PRAGMA table_info(incident_entries)')}:
                db.execute('ALTER TABLE incident_entries ADD COLUMN observed_axis_key TEXT')

    def row(self, identity):
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM incidents WHERE id=?', (identity,)).fetchone()
        if row is None:
            raise KeyError('Incident not found.')
        return self.decode_row(row)

    @staticmethod
    def decode_row(row):
        result = dict(row)
        if snapshot := result.pop('time_axis_snapshot'):
            result['time_axis_snapshot'] = json.loads(snapshot)
        return result

    def list(self, workspace_id, *, status=None, start=None, end=None, q=''):
        self.store.workspace(workspace_id)
        where, args = ['i.workspace_id=?'], [workspace_id]
        if status:
            if status not in STATUSES:
                raise ValueError('Unknown investigation status.')
            where.append('i.status=?'); args.append(status)
        if start is not None:
            where.append('i.end_time>=?'); args.append(seconds(start))
        if end is not None:
            where.append('i.start_time<=?'); args.append(seconds(end))
        if start is not None and end is not None and start > end:
            raise ValueError('Set the search end at or after the start.')
        if q:
            where.append("(instr(lower(i.title),lower(?))>0 OR instr(lower(i.description),lower(?))>0)")
            args.extend([q, q])
        with self.store.connect() as db:
            return [self.decode_row(r) for r in db.execute(f'''SELECT i.*,
                (SELECT COUNT(DISTINCT reference_id) FROM incident_links
                 WHERE incident_id=i.id AND kind IN ('analysis','interval')) AS analysis_count,
                (SELECT COUNT(*) FROM incident_links WHERE incident_id=i.id AND kind='interval') AS interval_count
                FROM incidents i WHERE {' AND '.join(where)} ORDER BY i.updated_at DESC, i.id''', args)]

    def fields(self, body, previous=None):
        allowed = ('title', 'description', 'start_time', 'end_time', 'time_origin', 'status', 'conclusion', 'time_axis_key')
        result = {k: body.get(k, (previous or {}).get(k)) for k in allowed}
        result['title'] = self.store.name(result['title'])
        for key in ('description', 'conclusion'):
            result[key] = text(result[key] if result[key] is not None else '', key)
        for key in ('start_time', 'end_time'):
            result[key] = seconds(result[key])
        if result['start_time'] is not None and result['end_time'] is not None and result['start_time'] > result['end_time']:
            raise ValueError('Set the incident end at or after the start.')
        origin = result['time_origin']
        if origin:
            parsed = datetime.fromisoformat(text(origin, 'Time origin', 100).replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                raise ValueError('The time origin must include a timezone, for example 2026-10-24T08:00:00Z.')
            result['time_origin'] = parsed.isoformat()
        else:
            result['time_origin'] = None
        result['status'] = result['status'] or 'open'
        if result['status'] not in STATUSES:
            raise ValueError('Unknown investigation status.')
        return result

    @staticmethod
    def touch(db, identity, workspace_id):
        stamp = now()
        db.execute('UPDATE incidents SET updated_at=? WHERE id=?', (stamp, identity))
        db.execute('UPDATE workspaces SET updated_at=? WHERE id=?', (stamp, workspace_id))

    def create(self, workspace_id, body, *, identity=None, sources=()):
        self.store.workspace(workspace_id)
        source = body.get('source')
        if source is not None:
            sources = (source, *sources)
        prepared = [self.prepare_link(workspace_id, source) for source in sources]
        values = self.fields(body)
        if prepared and not values['time_axis_key']:
            values['time_axis_key'] = self.prepared_axis(prepared[0])
        self.validate_axis(workspace_id, values['time_axis_key'])
        with self.store.connect() as db:
            identity = self.insert_incident(db, workspace_id, values, identity=identity)
            for link in prepared:
                self.insert_link(db, identity, link)
            self.touch(db, identity, workspace_id)
        return self.get(identity)

    def insert_incident(self, db, workspace_id, values, *, time_axis_snapshot=None, identity=None):
        identity, stamp = identity or uuid4().hex, now()
        db.execute('''INSERT INTO incidents
            (id,workspace_id,title,description,start_time,end_time,time_origin,status,conclusion,time_axis_key,time_axis_snapshot,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''', (identity, workspace_id, *values.values(),
                json.dumps(time_axis_snapshot, ensure_ascii=False) if time_axis_snapshot else None, stamp, stamp))
        self.record_change(db, identity, {'status': {'before': None, 'after': values['status']}})
        return identity

    def update(self, identity, body):
        incident = self.row(identity)
        values = self.fields(body, incident)
        self.validate_axis(incident['workspace_id'], values['time_axis_key'])
        with self.store.connect() as db:
            db.execute(f"UPDATE incidents SET {','.join(k+'=?' for k in values)} WHERE id=?", (*values.values(), identity))
            changes = {k: {'before': incident.get(k), 'after': v} for k, v in values.items() if incident.get(k) != v}
            if incident.get('time_axis_snapshot') and changes.keys() & {'time_origin', 'time_axis_key'}:
                db.execute('UPDATE incidents SET time_axis_snapshot=NULL WHERE id=?', (identity,))
            if changes:
                self.record_change(db, identity, changes)
            self.touch(db, identity, incident['workspace_id'])
        return self.get(identity)

    @staticmethod
    def record_change(db, identity, changes):
        db.execute('INSERT INTO incident_history VALUES (?,?,?,?)',
                   (uuid4().hex, identity, json.dumps(changes, ensure_ascii=False), now()))

    def history(self, identity):
        self.row(identity)
        with self.store.connect() as db:
            return [{**dict(r), 'changes': json.loads(r['changes'])} for r in db.execute(
                'SELECT * FROM incident_history WHERE incident_id=? ORDER BY recorded_at,id', (identity,))]

    def prepared_axis(self, source):
        kind, reference = source['kind'], source['reference_id']
        if kind == 'sensor-health':
            reference = self.store.sensor_health.get(reference)['datasetId']
        if kind in EVIDENCE_KINDS:
            return source['clockKey'] if kind == 'safety-observed' else None
        if kind in ('simulation', 'run'):
            return 'simulation:' + reference
        if kind == 'prognostic':
            return 'dataset:' + source['datasetId']
        did = self.store.result(reference)['datasetId'] if kind in ('analysis', 'interval') else reference
        dataset = self.store.dataset(did)
        simulation = dataset['metadata'].get('model', {}).get('simulationId')
        return 'simulation:' + simulation if simulation else 'dataset:' + did

    def validate_axis(self, workspace_id, key):
        if not key:
            return
        if not isinstance(key, str):
            raise ValueError('Choose a source for the incident time axis.')
        if key.startswith('dataset:'):
            if self.store.dataset(key.split(':', 1)[1])['workspace_id'] != workspace_id:
                raise ValueError('Choose a timeline dataset from this workspace.')
        elif key.startswith('simulation:'):
            self.simulation(workspace_id, key.split(':', 1)[1])
        else:
            raise ValueError('Choose a dataset or simulation time axis.')

    def simulation(self, workspace_id, identity):
        session = self.store.runtime.get(identity)
        if session.get('workspaceId') != workspace_id and not any(
            d['metadata'].get('model', {}).get('simulationId') == identity for d in self.store.datasets(workspace_id)
        ):
            raise ValueError('Save the dataset and process model to this workspace before linking the simulation.')
        return session

    def prepare_link(self, workspace_id, body):
        if not isinstance(body, dict):
            raise ValueError('Choose an existing record to link.')
        kind, selector = body.get('kind'), ''
        prognostic_dataset = None
        if kind == 'sensor-health':
            identity = body.get('diagnosticId', '')
            result = self.store.sensor_health.get(identity)
            if result['workspaceId'] != workspace_id:
                raise ValueError('Sensor diagnostic belongs to a different workspace.')
            index = body.get('episodeIndex')
            if index is not None:
                if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(result['episodes']):
                    raise ValueError('Choose an existing diagnostic fault interval.')
                selector = str(index)
        elif kind == 'dataset':
            identity = body.get('datasetId', '')
            dataset = self.store.dataset(identity)
            if dataset['workspace_id'] != workspace_id:
                raise ValueError('Choose a dataset from this workspace.')
        elif kind in ('analysis', 'interval'):
            identity = body.get('analysisId', '')
            result = self.store.result(identity)
            if result['workspaceId'] != workspace_id:
                raise ValueError('Choose an analysis from this workspace.')
            if body.get('datasetId', result['datasetId']) != result['datasetId']:
                raise ValueError('Choose the dataset used for the analysis.')
            if kind == 'interval':
                index = body.get('intervalIndex')
                if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(result['intervals']):
                    raise ValueError('Choose an anomaly interval present in this analysis.')
                selector = str(index)
        elif kind in ('simulation', 'run'):
            identity = body.get('simulationId', '')
            self.simulation(workspace_id, identity)
            if kind == 'run':
                selector = body.get('runId', '')
                self.store.runtime.run(identity, selector)
        elif kind == 'prognostic':
            identity = body.get('sessionId', '')
            prognostic_dataset = self.store.prognostics.get(workspace_id, identity)['config']['datasetId']
        elif kind in EVIDENCE_KINDS:
            identity = body.get('assessmentId', '')
            assessment = self.store.safety.get_assessment(workspace_id, identity)
            constraint_id, index = body.get('constraintId'), body.get('intervalIndex')
            raw = body.get('raw', False)
            detail = self.store.safety.evidence(assessment, kind, constraint_id, index, raw)
            selector = json.dumps(dict(intervalIndex=index, **detail), ensure_ascii=False, sort_keys=True, allow_nan=False)
            return dict(kind=kind, reference_id=identity, selector=selector, clockKey=detail['clock']['key'])
        else:
            raise ValueError('Unknown incident link type.')
        hypothesis = body.get('hypothesis')
        if hypothesis:
            faults = self.store.runtime.get(identity)['modelDescriptor']['faults'] if kind in ('simulation', 'run') else {}
            if hypothesis not in faults or hypothesis == 'healthy':
                raise ValueError('Choose a hypothesis supported by this process model.')
            if kind == 'run' and self.store.runtime.run(identity, selector)['request'].get('hypothesis') != hypothesis:
                raise ValueError('Choose the hypothesis saved with this experiment.')
        if kind == 'simulation' and ('asOf' in body or 'windowStart' in body):
            _, rows = self.store.runtime.window(identity, body)
            selector = json.dumps(dict(windowStart=rows[0]['t'], asOf=rows[-1]['t'], hypothesis=hypothesis), sort_keys=True)
        return dict(kind=kind, reference_id=identity, selector=selector, hypothesis=hypothesis, datasetId=prognostic_dataset,
                    hypothesisTitle=faults[hypothesis] if hypothesis else None)

    @staticmethod
    def insert_link(db, identity, prepared):
        kind, reference, selector = (prepared[k] for k in ('kind', 'reference_id', 'selector'))
        existing = db.execute('''SELECT id FROM incident_links
            WHERE incident_id=? AND kind=? AND reference_id=? AND selector=?''', (identity, kind, reference, selector)).fetchone()
        link_id, stamp = (existing['id'] if existing else uuid4().hex), now()
        if not existing:
            db.execute('INSERT INTO incident_links VALUES (?,?,?,?,?,?)', (link_id, identity, kind, reference, selector, stamp))
        if prepared.get('hypothesis'):
            title = prepared['hypothesisTitle']
            if not db.execute("SELECT id FROM incident_entries WHERE incident_id=? AND kind='hypothesis' AND model_hypothesis=?",
                              (identity, prepared['hypothesis'])).fetchone():
                db.execute('''INSERT INTO incident_entries
                    (id,incident_id,kind,title,content,source_link_id,model_hypothesis,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?)''', (uuid4().hex, identity, 'hypothesis', title,
                    f"Working hypothesis from the process model: {prepared['hypothesis']}. Record evidence that supports or challenges this hypothesis.", link_id, prepared['hypothesis'], stamp, stamp))
        return link_id

    def add_link(self, identity, body):
        incident = self.row(identity)
        prepared = self.prepare_link(incident['workspace_id'], body)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self.insert_link(db, identity, prepared)
            self.touch(db, identity, incident['workspace_id'])
        return self.get(identity)

    def remove_link(self, identity, link_id):
        incident = self.row(identity)
        source = next((link for link in self.links(identity) if link['id'] == link_id), None)
        with self.store.connect() as db:
            if source:
                from .incident_timeline import source_clock
                db.execute('''UPDATE incident_entries SET observed_axis_key=?
                    WHERE incident_id=? AND source_link_id=? AND observed_at IS NOT NULL AND observed_axis_key IS NULL''',
                    (source_clock(self.store, source)['key'], identity, link_id))
            if not db.execute('DELETE FROM incident_links WHERE id=? AND incident_id=?', (link_id, identity)).rowcount:
                raise KeyError('Incident link not found.')
            self.touch(db, identity, incident['workspace_id'])
        return self.get(identity)

    def entries(self, identity):
        self.row(identity)
        with self.store.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM incident_entries WHERE incident_id=? ORDER BY created_at,id', (identity,))]

    def save_entry(self, identity, body, entry_id=None):
        incident = self.row(identity)
        entries = {e['id']: e for e in self.entries(identity)}
        if entry_id and entry_id not in entries:
            raise KeyError('Investigation record not found.')
        previous = entries.get(entry_id, {})
        fields = ('kind', 'title', 'content', 'hypothesis_id', 'stance', 'source_link_id', 'observed_at')
        values = {k: body.get(k, previous.get(k)) for k in fields}
        values['kind'] = values['kind'] or 'note'
        if values['kind'] not in KINDS or (entry_id and values['kind'] != previous['kind']):
            raise ValueError('Choose a note, evidence item, or hypothesis. Saved entries retain their original type.')
        values['title'] = self.store.name(values['title'])
        values['content'] = text(values['content'] or '', 'Investigation content')
        values['observed_at'] = seconds(values['observed_at'])
        values['stance'] = values['stance'] or 'neutral'
        if values['stance'] not in ('neutral', 'support', 'oppose'):
            raise ValueError('Unknown evidence stance.')
        hypothesis = entries.get(values['hypothesis_id'])
        if values['hypothesis_id'] and (not hypothesis or hypothesis['kind'] != 'hypothesis' or values['kind'] != 'evidence'):
            raise ValueError('Evidence can only link hypotheses in this incident.')
        if values['stance'] != 'neutral' and not values['hypothesis_id']:
            raise ValueError('First choose the hypothesis this evidence supports or opposes.')
        with self.store.connect() as db:
            if values['source_link_id'] and not db.execute('SELECT id FROM incident_links WHERE incident_id=? AND id=?',
                                                         (identity, values['source_link_id'])).fetchone():
                raise ValueError('Evidence sources must belong to this incident.')
            # Retain the clock even if its source link is subsequently removed.
            source = next((l for l in self.links(identity) if l['id'] == values['source_link_id']), None)
            from .incident_timeline import source_clock, incident_clock
            clock = source_clock(self.store, source) if source else incident_clock(self.store, incident)
            values['observed_axis_key'] = (previous.get('observed_axis_key') if entry_id
                and previous.get('source_link_id') == values['source_link_id']
                and previous.get('observed_at') == values['observed_at'] else None) or clock['key']
            if entry_id:
                db.execute(f"UPDATE incident_entries SET {','.join(k+'=?' for k in values)},updated_at=? WHERE id=? AND incident_id=?",
                           (*values.values(), now(), entry_id, identity))
            else:
                self.insert_entry(db, identity, **values)
            self.touch(db, identity, incident['workspace_id'])
        return self.get(identity)

    @staticmethod
    def insert_entry(db, identity, *, kind, title, content, hypothesis_id=None, stance='neutral',
                     source_link_id=None, observed_at=None, observed_axis_key=None):
        stamp = now()
        db.execute('''INSERT INTO incident_entries
            (id,incident_id,kind,title,content,hypothesis_id,stance,source_link_id,observed_at,observed_axis_key,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''', (uuid4().hex, identity, kind, title, content, hypothesis_id, stance,
                                                 source_link_id, observed_at, observed_axis_key, stamp, stamp))

    def remove_entry(self, identity, entry_id):
        incident = self.row(identity)
        with self.store.connect() as db:
            # A removed hypothesis leaves its evidence as unassigned observations.
            db.execute("UPDATE incident_entries SET hypothesis_id=NULL,stance='neutral',updated_at=? WHERE incident_id=? AND hypothesis_id=?",
                       (now(), identity, entry_id))
            if not db.execute('DELETE FROM incident_entries WHERE id=? AND incident_id=?', (entry_id, identity)).rowcount:
                raise KeyError('Investigation record not found.')
            self.touch(db, identity, incident['workspace_id'])
        return self.get(identity)

    def links(self, identity):
        incident = self.row(identity)
        with self.store.connect() as db:
            rows = [dict(r) for r in db.execute('SELECT * FROM incident_links WHERE incident_id=? ORDER BY created_at,id', (identity,))]
        results, sessions = {}, {}
        datasets = None
        for link in rows:
            kind, reference = link['kind'], link['reference_id']
            if kind == 'sensor-health':
                result = self.store.sensor_health.get(reference)
                link['details'] = dict(diagnosticId=reference, datasetId=result['datasetId'], title=result['name'],
                    signals=result['config']['signals'], analysisRange=result['config']['analysisRange'])
                if link['selector']:
                    link['details'].update(episodeIndex=int(link['selector']), episode=result['episodes'][int(link['selector'])])
            elif kind == 'dataset':
                dataset = self.store.dataset(reference)
                link['details'] = dict(datasetId=reference, title=dataset['name'])
                if dataset['metadata'].get('resilience'):
                    link['details']['resilience'] = dataset['metadata']['resilience']
            elif kind in ('analysis', 'interval'):
                if reference not in results:
                    results[reference] = self.store.result(reference)
                result = results[reference]
                link['details'] = dict(analysisId=reference, datasetId=result['datasetId'], title=result['name'],
                                       algorithmLabel=result['algorithmLabel'], analysisRange=result['config']['analysisRange'],
                                       signals=result['relatedSignals'], contributionMetric=result.get('contributionMetric'))
                if result.get('experiment'):
                    link['details']['experiment'] = result['experiment']
                if kind == 'interval':
                    index = int(link['selector'])
                    link['details'].update(intervalIndex=index, interval=result['intervals'][index])
            elif kind == 'prognostic':
                session = self.store.prognostics.get(incident['workspace_id'], reference)
                forecast, config = session['forecast'], session['config']
                link['details'] = dict(sessionId=reference, datasetId=config['datasetId'], title=session['name'],
                                       assetName=config['assetName'], cutoff=forecast['cutoff'], status=forecast['status'],
                                       rulMedian=forecast['rul']['median'], method=forecast['method'], horizon=forecast['horizon'],
                                       trainingStart=config['start'])
            elif kind in EVIDENCE_KINDS:
                link['details'] = json.loads(link['selector'])
            else:
                if reference not in sessions:
                    sessions[reference] = self.store.runtime.get(reference)
                session = sessions[reference]
                if datasets is None:
                    datasets = self.store.datasets(incident['workspace_id'])
                dataset = next((d for d in datasets if d['metadata'].get('model', {}).get('simulationId') == reference), None)
                link['details'] = dict(simulationId=reference, title=session['title'], datasetId=dataset['id'] if dataset else None,
                    modelId=session['modelId'], modelVersion=session['modelVersion'], modelName=session['modelDescriptor']['name'],
                    scenarioId=session['scenarioId'], scenarioVersion=session['scenarioVersion'], config=session['config'],
                    signals=[s['key'] for s in session['modelDescriptor']['signals']],
                    signalDefinitions=session['modelDescriptor']['signals'])
                if kind == 'run':
                    link['details']['run'] = self.store.runtime.run(reference, link['selector'])
                elif link['selector']:
                    link['details']['observationWindow'] = json.loads(link['selector'])
        return rows

    def get(self, identity):
        return {**self.row(identity), 'links': self.links(identity), 'entries': self.entries(identity)}
