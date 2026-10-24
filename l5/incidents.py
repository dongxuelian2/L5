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


STATUSES = ('open', 'investigating', 'resolved', 'archived')
KINDS = ('note', 'evidence', 'hypothesis')


def text(value, label, limit=50000):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f'{label}必须是文本，最多 {limit} 个字符。')
    return value.strip()


def seconds(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('时间必须是有限的秒数。')
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
            if 'time_axis_key' not in {r['name'] for r in db.execute('PRAGMA table_info(incidents)')}:
                db.execute('ALTER TABLE incidents ADD COLUMN time_axis_key TEXT')
            if 'observed_axis_key' not in {r['name'] for r in db.execute('PRAGMA table_info(incident_entries)')}:
                db.execute('ALTER TABLE incident_entries ADD COLUMN observed_axis_key TEXT')

    def row(self, identity):
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM incidents WHERE id=?', (identity,)).fetchone()
        if row is None:
            raise KeyError('事件不存在。')
        return dict(row)

    def list(self, workspace_id, *, status=None, start=None, end=None, q=''):
        self.store.workspace(workspace_id)
        where, args = ['i.workspace_id=?'], [workspace_id]
        if status:
            if status not in STATUSES:
                raise ValueError('未知的调查状态。')
            where.append('i.status=?'); args.append(status)
        if start is not None:
            where.append('i.end_time>=?'); args.append(seconds(start))
        if end is not None:
            where.append('i.start_time<=?'); args.append(seconds(end))
        if start is not None and end is not None and start > end:
            raise ValueError('查找的结束时间不能早于开始时间。')
        if q:
            where.append("(instr(lower(i.title),lower(?))>0 OR instr(lower(i.description),lower(?))>0)")
            args.extend([q, q])
        with self.store.connect() as db:
            return [dict(r) for r in db.execute(f'''SELECT i.*,
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
            raise ValueError('事件结束时间不能早于开始时间。')
        origin = result['time_origin']
        if origin:
            parsed = datetime.fromisoformat(text(origin, '时间轴起点', 100).replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                raise ValueError('时间轴起点必须带有时区，例如 2026-10-24T08:00:00Z。')
            result['time_origin'] = parsed.isoformat()
        else:
            result['time_origin'] = None
        result['status'] = result['status'] or 'open'
        if result['status'] not in STATUSES:
            raise ValueError('未知的调查状态。')
        return result

    @staticmethod
    def touch(db, identity, workspace_id):
        stamp = now()
        db.execute('UPDATE incidents SET updated_at=? WHERE id=?', (stamp, identity))
        db.execute('UPDATE workspaces SET updated_at=? WHERE id=?', (stamp, workspace_id))

    def create(self, workspace_id, body):
        self.store.workspace(workspace_id)
        source = body.get('source')
        prepared = self.prepare_link(workspace_id, source) if source is not None else None
        values = self.fields(body)
        if prepared and not values['time_axis_key']:
            values['time_axis_key'] = self.prepared_axis(prepared)
        self.validate_axis(workspace_id, values['time_axis_key'])
        identity, stamp = uuid4().hex, now()
        with self.store.connect() as db:
            db.execute('''INSERT INTO incidents
                (id,workspace_id,title,description,start_time,end_time,time_origin,status,conclusion,time_axis_key,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                (identity, workspace_id, *values.values(), stamp, stamp))
            if prepared:
                self.insert_link(db, identity, prepared)
            self.record_change(db, identity, {'status': {'before': None, 'after': values['status']}})
            self.touch(db, identity, workspace_id)
        return self.get(identity)

    def update(self, identity, body):
        incident = self.row(identity)
        values = self.fields(body, incident)
        self.validate_axis(incident['workspace_id'], values['time_axis_key'])
        with self.store.connect() as db:
            db.execute(f"UPDATE incidents SET {','.join(k+'=?' for k in values)} WHERE id=?", (*values.values(), identity))
            changes = {k: {'before': incident.get(k), 'after': v} for k, v in values.items() if incident.get(k) != v}
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
        if kind in ('simulation', 'run'):
            return 'simulation:' + reference
        did = self.store.result(reference)['datasetId'] if kind in ('analysis', 'interval') else reference
        dataset = self.store.dataset(did)
        simulation = dataset['metadata'].get('model', {}).get('simulationId')
        return 'simulation:' + simulation if simulation else 'dataset:' + did

    def validate_axis(self, workspace_id, key):
        if not key:
            return
        if not isinstance(key, str):
            raise ValueError('请选择事件时间轴的来源。')
        if key.startswith('dataset:'):
            if self.store.dataset(key.split(':', 1)[1])['workspace_id'] != workspace_id:
                raise ValueError('时间轴数据集不属于此 Workspace。')
        elif key.startswith('simulation:'):
            self.simulation(workspace_id, key.split(':', 1)[1])
        else:
            raise ValueError('请选择数据集或模拟会话的时间轴。')

    def simulation(self, workspace_id, identity):
        session = self.store.runtime.get(identity)
        if session.get('workspaceId') != workspace_id and not any(
            d['metadata'].get('model', {}).get('simulationId') == identity for d in self.store.datasets(workspace_id)
        ):
            raise ValueError('模拟会话不属于此 Workspace，请先保存数据和过程模型到此项目。')
        return session

    def prepare_link(self, workspace_id, body):
        if not isinstance(body, dict):
            raise ValueError('请选择要关联的已有记录。')
        kind, selector = body.get('kind'), ''
        if kind == 'dataset':
            identity = body.get('datasetId', '')
            dataset = self.store.dataset(identity)
            if dataset['workspace_id'] != workspace_id:
                raise ValueError('数据集不属于此 Workspace。')
        elif kind in ('analysis', 'interval'):
            identity = body.get('analysisId', '')
            result = self.store.result(identity)
            if result['workspaceId'] != workspace_id:
                raise ValueError('分析不属于此 Workspace。')
            if body.get('datasetId', result['datasetId']) != result['datasetId']:
                raise ValueError('数据集与分析不匹配。')
            if kind == 'interval':
                index = body.get('intervalIndex')
                if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(result['intervals']):
                    raise ValueError('请选择该分析实际存在的异常区间。')
                selector = str(index)
        elif kind in ('simulation', 'run'):
            identity = body.get('simulationId', '')
            self.simulation(workspace_id, identity)
            if kind == 'run':
                selector = body.get('runId', '')
                self.store.runtime.run(identity, selector)
        else:
            raise ValueError('未知的事件关联类型。')
        hypothesis = body.get('hypothesis')
        if hypothesis:
            from simulation.platform import FAULTS
            if kind not in ('simulation', 'run') or hypothesis not in FAULTS:
                raise ValueError('请选择此过程模型支持的候选解释。')
            if kind == 'run' and self.store.runtime.run(identity, selector)['request'].get('hypothesis') != hypothesis:
                raise ValueError('候选解释与实验记录不匹配。')
        if kind == 'simulation' and ('asOf' in body or 'windowStart' in body):
            _, rows = self.store.runtime.window(identity, body)
            selector = json.dumps(dict(windowStart=rows[0]['t'], asOf=rows[-1]['t'], hypothesis=hypothesis), sort_keys=True)
        return dict(kind=kind, reference_id=identity, selector=selector, hypothesis=hypothesis)

    @staticmethod
    def insert_link(db, identity, prepared):
        kind, reference, selector = (prepared[k] for k in ('kind', 'reference_id', 'selector'))
        existing = db.execute('''SELECT id FROM incident_links
            WHERE incident_id=? AND kind=? AND reference_id=? AND selector=?''', (identity, kind, reference, selector)).fetchone()
        link_id, stamp = (existing['id'] if existing else uuid4().hex), now()
        if not existing:
            db.execute('INSERT INTO incident_links VALUES (?,?,?,?,?,?)', (link_id, identity, kind, reference, selector, stamp))
        if prepared.get('hypothesis'):
            from simulation.platform import FAULTS
            title = FAULTS[prepared['hypothesis']]
            if not db.execute("SELECT id FROM incident_entries WHERE incident_id=? AND kind='hypothesis' AND model_hypothesis=?",
                              (identity, prepared['hypothesis'])).fetchone():
                db.execute('''INSERT INTO incident_entries
                    (id,incident_id,kind,title,content,source_link_id,model_hypothesis,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?)''', (uuid4().hex, identity, 'hypothesis', title,
                    f"来自过程模型的工作假设：{prepared['hypothesis']}。可继续记录支持与反对证据。", link_id, prepared['hypothesis'], stamp, stamp))
        return link_id

    def add_link(self, identity, body):
        incident = self.row(identity)
        prepared = self.prepare_link(incident['workspace_id'], body)
        with self.store.connect() as db:
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
                raise KeyError('事件关联不存在。')
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
            raise KeyError('调查记录不存在。')
        previous = entries.get(entry_id, {})
        fields = ('kind', 'title', 'content', 'hypothesis_id', 'stance', 'source_link_id', 'observed_at')
        values = {k: body.get(k, previous.get(k)) for k in fields}
        values['kind'] = values['kind'] or 'note'
        if values['kind'] not in KINDS or (entry_id and values['kind'] != previous['kind']):
            raise ValueError('请选择笔记、证据或候选解释；已有记录的类型不可更改。')
        values['title'] = self.store.name(values['title'])
        values['content'] = text(values['content'] or '', '调查内容')
        values['observed_at'] = seconds(values['observed_at'])
        values['stance'] = values['stance'] or 'neutral'
        if values['stance'] not in ('neutral', 'support', 'oppose'):
            raise ValueError('未知的证据关系。')
        hypothesis = entries.get(values['hypothesis_id'])
        if values['hypothesis_id'] and (not hypothesis or hypothesis['kind'] != 'hypothesis' or values['kind'] != 'evidence'):
            raise ValueError('证据只能关联本事件中的候选解释。')
        if values['stance'] != 'neutral' and not values['hypothesis_id']:
            raise ValueError('请先选择证据所支持或反对的候选解释。')
        with self.store.connect() as db:
            if values['source_link_id'] and not db.execute('SELECT id FROM incident_links WHERE incident_id=? AND id=?',
                                                         (identity, values['source_link_id'])).fetchone():
                raise ValueError('证据来源必须属于本事件。')
            # Retain the clock even if its source link is subsequently removed.
            source = next((l for l in self.links(identity) if l['id'] == values['source_link_id']), None)
            from .incident_timeline import source_clock, incident_clock
            clock = source_clock(self.store, source) if source else incident_clock(self.store, incident)
            values['observed_axis_key'] = (previous.get('observed_axis_key') if entry_id
                and previous.get('source_link_id') == values['source_link_id']
                and previous.get('observed_at') == values['observed_at'] else None) or clock['key']
            stamp = now()
            if entry_id:
                db.execute(f"UPDATE incident_entries SET {','.join(k+'=?' for k in values)},updated_at=? WHERE id=? AND incident_id=?",
                           (*values.values(), stamp, entry_id, identity))
            else:
                db.execute('''INSERT INTO incident_entries
                    (id,incident_id,kind,title,content,hypothesis_id,stance,source_link_id,observed_at,observed_axis_key,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''', (uuid4().hex, identity, *values.values(), stamp, stamp))
            self.touch(db, identity, incident['workspace_id'])
        return self.get(identity)

    def remove_entry(self, identity, entry_id):
        incident = self.row(identity)
        with self.store.connect() as db:
            # A removed hypothesis leaves its evidence as unassigned observations.
            db.execute("UPDATE incident_entries SET hypothesis_id=NULL,stance='neutral',updated_at=? WHERE incident_id=? AND hypothesis_id=?",
                       (now(), identity, entry_id))
            if not db.execute('DELETE FROM incident_entries WHERE id=? AND incident_id=?', (entry_id, identity)).rowcount:
                raise KeyError('调查记录不存在。')
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
            if kind == 'dataset':
                dataset = self.store.dataset(reference)
                link['details'] = dict(datasetId=reference, title=dataset['name'])
            elif kind in ('analysis', 'interval'):
                if reference not in results:
                    results[reference] = self.store.result(reference)
                result = results[reference]
                link['details'] = dict(analysisId=reference, datasetId=result['datasetId'], title=result['name'],
                                       algorithmLabel=result['algorithmLabel'], analysisRange=result['config']['analysisRange'],
                                       signals=result['relatedSignals'], contributionMetric=result.get('contributionMetric'))
                if kind == 'interval':
                    index = int(link['selector'])
                    link['details'].update(intervalIndex=index, interval=result['intervals'][index])
            else:
                if reference not in sessions:
                    sessions[reference] = self.store.runtime.get(reference)
                session = sessions[reference]
                if datasets is None:
                    datasets = self.store.datasets(incident['workspace_id'])
                dataset = next((d for d in datasets if d['metadata'].get('model', {}).get('simulationId') == reference), None)
                link['details'] = dict(simulationId=reference, title=session['title'], datasetId=dataset['id'] if dataset else None)
                if kind == 'run':
                    link['details']['run'] = self.store.runtime.run(reference, link['selector'])
                elif link['selector']:
                    link['details']['observationWindow'] = json.loads(link['selector'])
        return rows

    def get(self, identity):
        return {**self.row(identity), 'links': self.links(identity), 'entries': self.entries(identity)}
