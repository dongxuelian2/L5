"""Local alarm sessions and operator history derived from saved analyses."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
from uuid import uuid4

from .alarms import extract_events, flood_metrics, group_alarms, normalize_policy
from .workspace import now


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def expiry(value):
    if isinstance(value, str):
        try:
            result = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if result.tzinfo is not None:
                return result.astimezone(timezone.utc)
        except (ValueError, OverflowError):
            pass
    raise ValueError('Shelving needs a valid expiration with a timezone.')


class AlarmService:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS alarm_sessions (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    name TEXT NOT NULL, analysis_ids TEXT NOT NULL, snapshot TEXT NOT NULL,
                    event_count INTEGER NOT NULL, group_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS alarm_sessions_workspace ON alarm_sessions(workspace_id, updated_at);
                CREATE TABLE IF NOT EXISTS alarm_actions (
                    sequence INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL,
                    session_id TEXT NOT NULL REFERENCES alarm_sessions(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL, actor TEXT NOT NULL, recorded_at TEXT NOT NULL,
                    details TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS alarm_actions_session ON alarm_actions(session_id, sequence);
            ''')

    @staticmethod
    def summary(row):
        return dict(id=row['id'], workspaceId=row['workspace_id'], name=row['name'],
                    createdAt=row['created_at'], updatedAt=row['updated_at'], analysisIds=json.loads(row['analysis_ids']),
                    eventCount=row['event_count'], groupCount=row['group_count'])

    @staticmethod
    def row(db, identity):
        row = db.execute('SELECT * FROM alarm_sessions WHERE id=?', (identity,)).fetchone()
        if row is None:
            raise KeyError('Alarm session not found.')
        return row

    def list(self, workspace_id):
        self.store.workspace(workspace_id)
        with self.store.connect() as db:
            return [self.summary(row) for row in db.execute('''SELECT id,workspace_id,name,analysis_ids,event_count,
                group_count,created_at,updated_at FROM alarm_sessions WHERE workspace_id=? ORDER BY updated_at DESC,id''',
                (workspace_id,))]

    def create(self, workspace_id, body):
        self.store.workspace(workspace_id)
        name = self.store.name(body.get('name'))
        identities = body.get('analysisIds')
        if not isinstance(identities, list) or not identities or any(not isinstance(i, str) or not i for i in identities):
            raise ValueError('Select saved analyses for the alarm session.')
        identities = sorted(set(identities))
        policy = normalize_policy(body.get('policy'))
        datasets, axes, events, sources = {}, {}, [], []

        def dataset(identity):
            if identity not in datasets:
                value = self.store.dataset(identity)
                if value['workspace_id'] != workspace_id:
                    raise ValueError('Alarm sources must belong to this workspace.')
                datasets[identity] = value
            return datasets[identity]

        references = [*policy['mappings'], *(r[side] for r in policy['relationships'] for side in ('left', 'right'))]
        for reference in references:
            try:
                columns = dataset(reference['datasetId'])['metadata']['columns']
            except KeyError as error:
                raise ValueError('Alarm policy references a missing dataset or signal.') from error
            if reference['signal'] not in {c['name'] for c in columns}:
                raise ValueError('Alarm policy references a missing dataset or signal.')

        for identity in identities:
            result = self.store.result(identity)
            if result['workspaceId'] != workspace_id:
                raise ValueError('Alarm sources must belong to this workspace.')
            source = dataset(result['datasetId'])
            clock = source['metadata']['clock']
            start, end = (result['times'][i] + clock['offset'] for i in (0, -1))
            axis = axes.setdefault(clock['axisId'], dict(id=clock['axisId'], label=clock['label'],
                origin='1970-01-01T00:00:00Z' if clock['axisId'] == 'utc' else None, start=start, end=end))
            axis.update(start=min(axis['start'], start), end=max(axis['end'], end))
            sources.append(dict(analysisId=identity, analysisName=result['name'], datasetId=source['id'],
                datasetName=source['name'], detector=result['config']['algorithm'], detectorLabel=result['algorithmLabel'],
                clock=clock, start=start, end=end, coverageFraction=result['summary'].get('coverageFraction'),
                abstainedSamples=result['summary'].get('abstainedSamples')))
            events.extend(extract_events(result, source, clock))

        grouping = group_alarms(events, policy)
        axes = [axes[k] for k in sorted(axes)]
        snapshot = dict(schemaVersion=1, policy=policy, axes=axes, sources=sources, **grouping)
        snapshot['flood'] = flood_metrics(grouping['events'], grouping['groups'], policy, axes=axes)
        identity, stamp = uuid4().hex, now()
        with self.store.connect() as db:
            db.execute('INSERT INTO alarm_sessions VALUES (?,?,?,?,?,?,?,?,?)',
                       (identity, workspace_id, name, encode(identities), encode(snapshot), len(grouping['events']),
                        len(grouping['groups']), stamp, stamp))
            db.execute('UPDATE workspaces SET updated_at=? WHERE id=?', (stamp, workspace_id))
        return self.get(identity)

    @staticmethod
    def actions(db, identity):
        return [dict(id=row['id'], kind=row['kind'], actor=row['actor'], recordedAt=row['recorded_at'],
                     **json.loads(row['details'])) for row in db.execute('''SELECT * FROM alarm_actions
                         WHERE session_id=? ORDER BY sequence''', (identity,))]

    @staticmethod
    def append(db, row, kind, actor, stamp, **details):
        db.execute('''INSERT INTO alarm_actions (id,session_id,kind,actor,recorded_at,details) VALUES (?,?,?,?,?,?)''',
                   (uuid4().hex, row['id'], kind, actor, stamp, encode(details)))
        db.execute('UPDATE alarm_sessions SET updated_at=? WHERE id=?', (stamp, row['id']))
        db.execute('UPDATE workspaces SET updated_at=? WHERE id=?', (stamp, row['workspace_id']))

    def get(self, identity):
        with self.store.connect() as db:
            db.execute('BEGIN')
            row, audit = self.row(db, identity), self.actions(db, identity)
        snapshot = json.loads(row['snapshot'])
        as_of = now()
        started, current = (datetime.fromisoformat(v) for v in (row['created_at'], as_of))
        age = (current - started).total_seconds()
        acknowledgements, shelves = {}, {}
        incidents_by_group, delays = defaultdict(list), defaultdict(list)
        for action in audit:
            kind = action['kind']
            if kind == 'acknowledge':
                acknowledgements.setdefault(action['eventId'], action['recordedAt'])
            elif kind in ('shelve', 'unshelve'):
                shelves[action['eventId']] = action.get('expiresAt')
            elif kind == 'incident':
                incidents_by_group[action['groupId']].append(action['incidentId'])
        incidents_by_event = {}
        for group in snapshot['groups']:
            group['incidentIds'] = incidents_by_group[group['id']]
            if group['incidentIds']:
                incidents_by_event.update((event_id, group['incidentIds']) for event_id in group['eventIds'])
        escalation = snapshot['policy']['escalationSeconds']
        for event in snapshot['events']:
            event_id = event['id']
            acknowledged, shelved = acknowledgements.get(event_id), shelves.get(event_id)
            if acknowledged:
                delays[event['axisId']].append(max(0, (datetime.fromisoformat(acknowledged) - started).total_seconds()))
            if shelved and datetime.fromisoformat(shelved) <= current:
                shelved = None
            event['operator'] = dict(acknowledgedAt=acknowledged, shelvedUntil=shelved,
                incidentIds=incidents_by_event.get(event_id, []), escalated=(escalation is not None and age >= escalation
                    and not acknowledged and event['measuredState'] == 'active' and event['policyEligible']))
        for axis in snapshot['flood']['axes']:
            values = delays[axis['axisId']]
            axis.update(acknowledgedCount=len(values), meanAcknowledgementDelaySeconds=sum(values) / len(values) if values else None)
        return {**self.summary(row), **snapshot, 'audit': audit, 'asOf': as_of}

    def event_action(self, identity, event_id, body):
        kind = body.get('kind')
        if kind not in ('acknowledge', 'shelve', 'unshelve', 'note'):
            raise ValueError('Choose an available alarm action.')
        actor = self.store.name(body.get('actor', 'operator'))
        note = body.get('note', '')
        if not isinstance(note, str) or len(note) > 2000 or (kind == 'note' and not note.strip()):
            raise ValueError('Enter an operator note of 1–2000 characters.')
        details = dict(eventId=event_id, **({'note': note.strip()} if note.strip() else {}))
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self.row(db, identity)
            snapshot = json.loads(row['snapshot'])
            if not any(e['id'] == event_id for e in snapshot['events']):
                raise KeyError('Alarm event not found.')
            stamp = now()
            if kind == 'shelve':
                expires = expiry(body.get('expiresAt'))
                seconds = (expires - datetime.fromisoformat(stamp)).total_seconds()
                if not 0 < seconds <= snapshot['policy']['maxShelveSeconds']:
                    raise ValueError('Shelve until a future time within the saved policy limit.')
                details['expiresAt'] = expires.isoformat()
            prior = [a for a in self.actions(db, identity) if a.get('eventId') == event_id]
            duplicate_ack = kind == 'acknowledge' and not details.get('note') and any(a['kind'] == kind for a in prior)
            shelf = next((a for a in reversed(prior) if a['kind'] in ('shelve', 'unshelve')), {})
            duplicate_shelf = kind == 'shelve' and not details.get('note') and shelf.get('expiresAt') == details['expiresAt']
            inactive_unshelve = kind == 'unshelve' and not details.get('note') and shelf.get('expiresAt', '') <= stamp
            if not (duplicate_ack or duplicate_shelf or inactive_unshelve):
                self.append(db, row, kind, actor, stamp, **details)
        return self.get(identity)

    def incident(self, identity, group_id, body):
        actor = self.store.name(body.get('actor', 'operator'))
        incident_id = body.get('incidentId')
        if incident_id is not None and (not isinstance(incident_id, str) or not incident_id):
            raise ValueError('Choose an existing incident from this workspace.')
        service = self.store.incidents
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self.row(db, identity)
            snapshot = json.loads(row['snapshot'])
            group = next((g for g in snapshot['groups'] if g['id'] == group_id), None)
            if group is None:
                raise KeyError('Alarm group not found.')
            audit = self.actions(db, identity)
            links = [a for a in audit if a['kind'] == 'incident' and a['groupId'] == group_id]
            duplicate = any(a['incidentId'] == incident_id if incident_id else a['createdIncident'] for a in links)
            if not duplicate:
                members = set(group['eventIds'])
                events = [e for e in snapshot['events'] if e['id'] in members]
                created = incident_id is None
                chinese = body.get('locale') == 'zh-CN'
                fixed_clock = None
                if created:
                    utc = group['axisId'] == 'utc'
                    axis = next(a for a in snapshot['axes'] if a['id'] == group['axisId'])
                    clocks = {e['clockKey']: dict(key=e['clockKey'], axisId=e['axisId'], offset=e['offset']) for e in events}
                    clock_snapshot = None if utc else dict(axisId=axis['id'], axisLabel=axis['label'],
                        label='报警会话时间快照' if chinese else 'Alarm session time snapshot', clocks=list(clocks.values()))
                    origin = '1970-01-01T00:00:00+00:00'
                    fields = service.fields(dict(title=body.get('title') or row['name'],
                        start_time=group['start'], end_time=group['end'], time_origin=origin if utc else None))
                    incident_id = service.insert_incident(db, row['workspace_id'], fields, time_axis_snapshot=clock_snapshot)
                    fixed_clock = ('origin:' + origin) if utc else ('alarm-snapshot:' + incident_id)
                elif not db.execute('SELECT id FROM incidents WHERE id=? AND workspace_id=?',
                                    (incident_id, row['workspace_id'])).fetchone():
                    raise ValueError('Choose an existing incident from this workspace.')
                self.attach_group(db, incident_id, row, group, events, audit, chinese, fixed_clock)
                service.touch(db, incident_id, row['workspace_id'])
                self.append(db, row, 'incident', actor, now(), groupId=group_id, incidentId=incident_id,
                            createdIncident=created)
        return self.get(identity)

    def attach_group(self, db, incident_id, row, group, events, audit, chinese, fixed_clock):
        from .alarm_reports import relationship_text

        service = self.store.incidents
        summary = '报警工作区分组证据' if chinese else 'Alarm workspace grouping evidence'
        explanation = '时间与信号关联用于调查。物理因果关系仍需验证。' if chinese else 'Temporal and signal associations guide investigation. Physical causality still requires verification.'
        content = f"{explanation}\n{row['name']} [{row['id']}]\n{group['id']} · {group['axisId']} · {group['start']} → {group['end']}"
        service.insert_entry(db, incident_id, kind='evidence', title=summary, content=content)
        for relation in group['relationships']:
            service.insert_entry(db, incident_id, kind='evidence', title=summary, content=relationship_text(relation, chinese))
        for dataset_id in sorted({e['datasetId'] for e in events}):
            service.insert_link(db, incident_id, dict(kind='dataset', reference_id=dataset_id, selector=''))
        notes = defaultdict(list)
        for action in audit:
            if action.get('note'):
                notes[action.get('eventId')].append(action)
        for event in events:
            index = event['intervalIndex']
            link = service.insert_link(db, incident_id, dict(kind='analysis' if index is None else 'interval',
                reference_id=event['analysisId'], selector='' if index is None else str(index)))
            title = '原始报警及测量来源' if chinese else 'Source alarm and measurements'
            content = json.dumps({key: event[key] for key in ('id', 'datasetId', 'analysisId', 'intervalIndex',
                'fragmentIndex', 'axisId', 'offset', 'start', 'end', 'nativeStart', 'nativeEnd', 'peakTime', 'peakScore',
                'threshold', 'signals', 'observedSpan', 'observedFraction', 'measuredState')}, ensure_ascii=False, indent=2)
            evidence = dict(source_link_id=link, observed_at=event['start'] if fixed_clock else event['nativeStart'],
                            observed_axis_key=fixed_clock or event['clockKey'])
            service.insert_entry(db, incident_id, kind='evidence', title=title, content=content, **evidence)
            for action in notes[event['id']]:
                service.insert_entry(db, incident_id, kind='note', title='操作员观察' if chinese else 'Operator observation',
                    content=f"{action['actor']} · {action['recordedAt']}\n{action['note']}", **evidence)
