"""Workspace OPC UA acquisition: session ownership and append-only evidence."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
import csv
from datetime import datetime, timezone
from io import StringIO
import json
import math
from threading import RLock, Thread
from uuid import NAMESPACE_URL, uuid4, uuid5

from .datasets import prepare_csv


def utc(value=None):
    if value is None:
        stamp = datetime.now(timezone.utc)
    else:
        if not isinstance(value, str):
            raise ValueError('Use an ISO timestamp with a timezone.')
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError('Use an ISO timestamp with a timezone.')
    return stamp.astimezone(timezone.utc).isoformat(timespec='microseconds')


def json_text(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def interval(start=None, end=None):
    start, end = utc(start) if start is not None else None, utc(end) if end is not None else None
    if start and end and start > end:
        raise ValueError('The interval start must precede the end.')
    return start, end


class LiveConflict(ValueError):
    pass


class LiveUnavailable(Exception):
    pass


class LiveGateway:
    """HTTP threads own control transitions; one asyncio loop owns all UA transports."""

    def __init__(self, store):
        self.store = store
        self.lock = RLock()
        self.preview = {}
        self.recording = {}
        self.errors = {}
        self.loop = self.thread = None
        self.closed = False
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS live_sessions (
                    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    name TEXT NOT NULL, state TEXT NOT NULL, config TEXT NOT NULL, mappings TEXT NOT NULL,
                    started_at TEXT NOT NULL, stopped_at TEXT);
                CREATE INDEX IF NOT EXISTS live_sessions_workspace
                    ON live_sessions(workspace_id, started_at);
                CREATE TABLE IF NOT EXISTS live_samples (
                    id INTEGER PRIMARY KEY, session_id TEXT NOT NULL REFERENCES live_sessions(id) ON DELETE CASCADE,
                    timestamp TEXT NOT NULL, signal_id TEXT NOT NULL, observation TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS live_samples_time ON live_samples(session_id, timestamp, id);
                CREATE INDEX IF NOT EXISTS live_samples_signal ON live_samples(session_id, signal_id, timestamp);
                CREATE INDEX IF NOT EXISTS live_samples_arrival ON live_samples(session_id, id);
                CREATE TABLE IF NOT EXISTS live_events (
                    id INTEGER PRIMARY KEY, session_id TEXT NOT NULL REFERENCES live_sessions(id) ON DELETE CASCADE,
                    timestamp TEXT NOT NULL, event TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS live_events_time ON live_events(session_id, timestamp, id);
                CREATE INDEX IF NOT EXISTS live_events_arrival ON live_events(session_id, id);
            ''')
            stamp = utc()
            for row in db.execute("SELECT id FROM live_sessions WHERE state='recording'").fetchall():
                self._event(db, row['id'], dict(kind='application_interruption', timestamp=stamp,
                    detail='The previous L5 process stopped before finalizing the session. Uncommitted loss is unknown.'))
            db.execute("UPDATE live_sessions SET state='interrupted', stopped_at=? WHERE state='recording'", (stamp,))

    def _run(self, coroutine):
        if self.loop is None:
            self.loop = asyncio.new_event_loop()

            def run():
                asyncio.set_event_loop(self.loop)
                try:
                    self.loop.run_forever()
                finally:
                    self.loop.run_until_complete(self.loop.shutdown_asyncgens())
                    self.loop.run_until_complete(self.loop.shutdown_default_executor())
                    self.loop.close()

            self.thread = Thread(target=run, name='l5-opc-ua', daemon=True)
            self.thread.start()
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop).result()

    def _check(self, workspace_id):
        self.store.workspace(workspace_id)
        if self.closed:
            raise LiveConflict('The live data gateway is shutting down.')

    @staticmethod
    def _public_status(**fields):
        return dict(connection_state='disconnected', last_error=None, config=None,
                    active_session_id=None) | fields

    def status(self, workspace_id):
        with self.lock:
            self._check(workspace_id)
            if workspace_id in self.recording:
                identity, collector = self.recording[workspace_id]
                async def snapshot():
                    return collector.status()
                return self._public_status(config=collector.config.public(), active_session_id=identity,
                                           **self._run(snapshot()))
            source = self.preview.get(workspace_id)
            if source is not None:
                try:
                    self._run(source.check_health())
                except Exception as error:
                    self._disconnect(workspace_id)
                    self.errors[workspace_id] = self._error('OPC UA connection', error)
                else:
                    return self._public_status(connection_state='connected', config=source.config.public(),
                                               last_error=self.errors.get(workspace_id))
            error = self.errors.get(workspace_id)
            return self._public_status(connection_state='error' if error else 'disconnected', last_error=error)

    @staticmethod
    def _error(action, error):
        from .live_opcua import opcua_error

        return f'{action} failed: {opcua_error(error)}'

    def connect(self, workspace_id, body):
        from .live_opcua import OpcUaConfig, OpcUaSource

        with self.lock:
            self._check(workspace_id)
            if workspace_id in self.recording:
                raise LiveConflict('Stop the acquisition before changing the connection.')
            config = OpcUaConfig.from_payload(body)
            self._disconnect(workspace_id)
            source = OpcUaSource(config)
            try:
                self._run(source.connect())
            except Exception as error:
                self.errors[workspace_id] = self._error('OPC UA connection', error)
                raise LiveUnavailable(self.errors[workspace_id]) from None
            self.preview[workspace_id] = source
            return self.status(workspace_id)

    def _disconnect(self, workspace_id):
        source = self.preview.pop(workspace_id, None)
        self.errors.pop(workspace_id, None)
        if source:
            self._run(source.disconnect())

    def disconnect(self, workspace_id):
        with self.lock:
            self._check(workspace_id)
            if workspace_id in self.recording:
                raise LiveConflict('Stop the acquisition before disconnecting.')
            self._disconnect(workspace_id)
            return self.status(workspace_id)

    def node_request(self, workspace_id, operation, node_id):
        with self.lock:
            self._check(workspace_id)
            if node_id is not None and (not isinstance(node_id, str) or not 0 < len(node_id) <= 1024):
                raise ValueError('Enter an OPC UA NodeId of up to 1024 characters.')
            if operation == 'read' and not node_id:
                raise ValueError('Select a node to read.')
            if workspace_id in self.recording:
                _, collector = self.recording[workspace_id]
                async def execute():
                    source = collector.source
                    if not source:
                        raise LiveConflict('The acquisition is reconnecting.')
                    return await (source.browse(node_id or 'i=85') if operation == 'browse' else source.read(node_id))
            else:
                source = self.preview.get(workspace_id)
                if not source:
                    raise LiveConflict('Connect to an OPC UA server first.')
                async def execute():
                    return await (source.browse(node_id or 'i=85') if operation == 'browse' else source.read(node_id))
            try:
                result = self._run(execute())
                self.errors.pop(workspace_id, None)
                return result
            except (ValueError, LiveConflict):
                raise
            except Exception as error:
                self.errors[workspace_id] = self._error('OPC UA ' + operation, error)
                raise LiveUnavailable(self.errors[workspace_id]) from None

    def _mappings(self, workspace_id, source, mappings):
        if not isinstance(mappings, list) or not 1 <= len(mappings) <= 64:
            raise ValueError('Select between 1 and 64 OPC UA variables.')
        linked = {m.get('signal_id') for m in mappings if isinstance(m, dict) and isinstance(m.get('signal_id'), str) and m['signal_id']}
        existing = {s['id'] for s in self.store.signals.catalog(workspace_id)} if linked else set()
        nodes, identities, result = set(), set(), []
        for mapping in mappings:
            if not isinstance(mapping, dict):
                raise ValueError('Each OPC UA mapping must be an object.')
            namespace = mapping.get('namespace_uri')
            if namespace is not None and (not isinstance(namespace, str) or len(namespace) > 1024):
                raise ValueError('Invalid OPC UA namespace URI.')
            node, namespace = source.mapping_identity(mapping.get('node_id'), namespace or None)
            identifier = node.partition(';')[2] if node.startswith('ns=') else node
            live_id = uuid5(NAMESPACE_URL, json_text(
                ['l5:opcua', workspace_id, source.config.endpoint, namespace, identifier])).hex
            chosen = mapping.get('signal_id') or live_id
            if not isinstance(chosen, str) or (chosen != live_id and chosen not in existing):
                raise ValueError('Select an L5 signal from the same workspace.')
            if node in nodes or chosen in identities:
                raise ValueError('Each OPC UA node and L5 signal may appear only once per session.')
            nodes.add(node)
            identities.add(chosen)
            result.append(dict(node_id=node, namespace_uri=namespace,
                signal_id=chosen, live_signal_id=live_id,
                display_name=self.store.name(mapping.get('display_name') or node),
                unit=self._text(mapping.get('unit'), 160), data_type=self._text(mapping.get('data_type'), 256)))
        return result

    @staticmethod
    def _text(value, limit):
        if value is None:
            return ''
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError(f'Mapping metadata must contain at most {limit} characters.')
        return value.strip()

    def start(self, workspace_id, body):
        from .live_opcua import LiveCollector

        with self.lock:
            self._check(workspace_id)
            if workspace_id in self.recording:
                raise LiveConflict('An acquisition is already recording in this workspace.')
            source = self.preview.get(workspace_id)
            if not source:
                raise LiveConflict('Connect to an OPC UA server first.')
            config = source.config
            mappings = self._mappings(workspace_id, source, body.get('mappings'))
            identity, stamp = uuid4().hex, utc()
            name = self.store.name(body.get('name') or 'OPC UA acquisition')
            with self.store.connect() as db:
                db.execute("INSERT INTO live_sessions VALUES (?, ?, ?, 'recording', ?, ?, ?, NULL)",
                           (identity, workspace_id, name, json_text(config.public()), json_text(mappings), stamp))
            collector = LiveCollector(config, mappings, lambda samples, events: self.append(identity, samples, events),
                                      source=source)
            self.preview.pop(workspace_id)
            try:
                self._run(collector.start())
            except Exception as error:
                self._run(source.disconnect())
                detail = self._error('Starting acquisition', error)
                self._finish(identity, 'failed', dict(kind='acquisition_failed', timestamp=utc(), detail=detail))
                raise LiveUnavailable(detail) from None
            self.recording[workspace_id] = identity, collector
            return self.session(workspace_id, identity)

    def stop(self, workspace_id, identity):
        with self.lock:
            self._check(workspace_id)
            session = self.session(workspace_id, identity)
            if session['state'] != 'recording':
                return session
            if self.recording.get(workspace_id, (None,))[0] != identity:
                raise LiveConflict('This acquisition is not owned by the current gateway.')
            self._stop(workspace_id, keep_source=True)
            return self.session(workspace_id, identity)

    def _stop(self, workspace_id, *, keep_source=False):
        identity, collector = self.recording[workspace_id]
        try:
            source = self._run(collector.stop(keep_source=keep_source))
        except Exception:
            raise LiveUnavailable('The acquisition could not flush all buffered data. Resolve the storage error and retry Stop.') from None
        try:
            self._finish(identity, 'completed')
        except Exception:
            if source:
                self._run(source.disconnect())
            raise LiveUnavailable('The acquisition data was flushed, but the session could not be finalized. Retry Stop.') from None
        self.recording.pop(workspace_id)
        if source:
            self.preview[workspace_id] = source

    def _finish(self, identity, state, event=None):
        with self.store.connect() as db:
            db.execute('UPDATE live_sessions SET state=?, stopped_at=? WHERE id=?', (state, utc(), identity))
            if event:
                self._event(db, identity, event)

    @contextmanager
    def workspace_removal(self, workspace_id):
        with self.lock:
            if workspace_id in self.recording:
                raise LiveConflict('Stop the acquisition before deleting the workspace.')
            self._disconnect(workspace_id)
            yield

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            errors = []
            for workspace_id, (identity, _) in list(self.recording.items()):
                try:
                    self._stop(workspace_id)
                except Exception as error:
                    errors.append(error)
                    try:
                        self._finish(identity, 'interrupted', dict(kind='storage_loss', timestamp=utc(),
                            detail='The shutdown could not flush all buffered observations. Loss count is unknown.'))
                    except Exception as storage_error:
                        errors.append(storage_error)
            for workspace_id in list(self.preview):
                try:
                    self._disconnect(workspace_id)
                except Exception as error:
                    errors.append(error)
            if self.loop:
                self.loop.call_soon_threadsafe(self.loop.stop)
                self.thread.join()
            if errors:
                raise LiveUnavailable('Live data shutdown did not finish cleanly. Check recorded session events.') from errors[0]

    @staticmethod
    def _session_row(row):
        return dict(row) | dict(config=json.loads(row['config']), mappings=json.loads(row['mappings']))

    def sessions(self, workspace_id):
        self.store.workspace(workspace_id)
        with self.store.connect() as db:
            return [self._session_row(row) for row in db.execute(
                'SELECT * FROM live_sessions WHERE workspace_id=? ORDER BY started_at DESC', (workspace_id,))]

    def session(self, workspace_id, identity):
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM live_sessions WHERE id=? AND workspace_id=?', (identity, workspace_id)).fetchone()
        if row is None:
            raise KeyError('Acquisition session not found.')
        return self._session_row(row)

    @staticmethod
    def _event(db, identity, event):
        stamp = utc(event['timestamp'])
        db.execute('INSERT INTO live_events(session_id,timestamp,event) VALUES (?,?,?)',
                   (identity, stamp, json_text(dict(event, timestamp=stamp))))

    def append(self, identity, samples, events):
        """Commit a batch and its diagnostics together; a failed batch is retryable."""
        with self.store.connect() as db:
            # Acquire the write lock before looking for previous observations.
            db.execute('BEGIN IMMEDIATE')
            latest = {}
            for observation in samples:
                signal, stamp = observation['signal_id'], utc(observation['timestamp'])
                if signal not in latest:
                    latest[signal] = db.execute('SELECT MAX(timestamp) FROM live_samples WHERE session_id=? AND signal_id=?',
                                                (identity, signal)).fetchone()[0]
                delayed = latest[signal] is not None and stamp < latest[signal]
                duplicate = latest[signal] is not None and stamp <= latest[signal] and db.execute(
                    'SELECT 1 FROM live_samples WHERE session_id=? AND signal_id=? AND timestamp=? LIMIT 1',
                    (identity, signal, stamp)).fetchone() is not None
                observation = dict(observation, timestamp=stamp, duplicate=duplicate, out_of_order=delayed)
                db.execute('INSERT INTO live_samples(session_id,timestamp,signal_id,observation) VALUES (?,?,?,?)',
                           (identity, stamp, signal, json_text(observation)))
                if duplicate or delayed:
                    for kind, active in (('duplicate_timestamp', duplicate), ('out_of_order', delayed)):
                        if active:
                            self._event(db, identity, dict(kind=kind, timestamp=observation['received_at'],
                                detail=f"{observation['node_id']} · {stamp}", signal_id=signal, count=1))
                latest[signal] = max(stamp, latest[signal] or stamp)
            for event in events:
                self._event(db, identity, event)

    @staticmethod
    def _page(db, table, payload, identity, start, end, limit, before, after):
        clause, args = ['session_id=?'], [identity]
        for value, condition in ((start, 'timestamp>=?'), (end, 'timestamp<=?'),
                                 (before, 'id<?'), (after, 'id>?')):
            if value is not None:
                clause.append(condition)
                args.append(value)
        order = 'id ASC' if after is not None else 'id DESC' if before is not None else 'timestamp DESC, id DESC'
        rows = db.execute(f"SELECT id,{payload} FROM {table} WHERE {' AND '.join(clause)} ORDER BY {order} LIMIT ?",
                          (*args, limit)).fetchall()
        if after is None:
            rows.reverse()
        return [dict(json.loads(row[payload]), id=row['id']) for row in rows]

    def samples(self, workspace_id, identity, *, start=None, end=None, limit=1000, before_id=None,
                after_id=None, before_event_id=None, after_event_id=None, include_latest=False):
        session = self.session(workspace_id, identity)
        start, end = interval(start, end)
        limit = int(limit)
        if not 1 <= limit <= 5000:
            raise ValueError('Sample page limit must be between 1 and 5000.')
        for before, after in ((before_id, after_id), (before_event_id, after_event_id)):
            if (before is not None and after is not None) or any(
                cursor is not None and not 0 <= cursor <= 2**63 - 1 for cursor in (before, after)
            ):
                raise ValueError('Choose one valid cursor per stream.')
        with self.store.connect() as db:
            db.execute('BEGIN')  # Each response observes one committed batch boundary.
            result = dict(samples=self._page(db, 'live_samples', 'observation', identity, start, end, limit, before_id, after_id),
                          events=self._page(db, 'live_events', 'event', identity, start, end, limit, before_event_id, after_event_id))
            if include_latest:
                bounds, args = '', []
                for value, condition in ((start, 'timestamp>=?'), (end, 'timestamp<=?')):
                    if value is not None:
                        bounds += f' AND {condition}'
                        args.append(value)
                result['latest'] = []
                for mapping in session['mappings']:
                    row = db.execute(f'''SELECT id,observation FROM live_samples WHERE session_id=? AND signal_id=?{bounds}
                                          ORDER BY timestamp DESC, id DESC LIMIT 1''',
                                     (identity, mapping['signal_id'], *args)).fetchone()
                    if row:
                        result['latest'].append(dict(json.loads(row['observation']), id=row['id']))
            return result

    def dataset(self, workspace_id, identity, body):
        session = self.session(workspace_id, identity)
        if session['state'] == 'recording':
            raise LiveConflict('Stop the acquisition before creating a dataset.')
        start, end = interval(body.get('start'), body.get('end'))
        name = self.store.name(body.get('name') or session['name'])
        return self._convert(session, name, start, end)

    def _convert(self, session, name, start, end):
        identity = session['id']
        clauses, args = ['session_id=?'], [identity]
        if start is not None:
            clauses.append('timestamp>=?')
            args.append(start)
        if end is not None:
            clauses.append('timestamp<=?')
            args.append(end)
        where = ' AND '.join(clauses)
        with self.store.connect() as db:
            rows = {}
            signals = set()
            mappings = {mapping['signal_id']: mapping for mapping in session['mappings']}
            # Bound materialization for normal in-process Dataset ingestion.
            max_rows = 2_000_000 // len(mappings)
            query = f'SELECT timestamp, signal_id, observation FROM live_samples WHERE {where} ORDER BY timestamp,id LIMIT 500001'
            for i, row in enumerate(db.execute(query, args)):
                if i >= 500_000 or (len(rows) >= max_rows and row['timestamp'] not in rows):
                    raise ValueError('This acquisition is too large for one Dataset. Select a shorter interval.')
                sample = json.loads(row['observation'])
                value = self._numeric(sample)
                rows.setdefault(row['timestamp'], {})[row['signal_id']] = value
            for values in rows.values():
                signals.update(signal for signal, value in values.items() if value is not None)
        if not signals:
            raise ValueError('The selected interval contains no good numerical OPC UA measurements.')
        chosen = [mapping for signal, mapping in mappings.items() if signal in signals]
        columns = [f"opc_{mapping['live_signal_id']}" for mapping in chosen]
        csv_data = StringIO()
        writer = csv.writer(csv_data, lineterminator='\n')
        writer.writerow(['timestamp', *columns])
        for stamp, values in rows.items():
            writer.writerow([stamp, *(values.get(mapping['signal_id']) for mapping in chosen)])
        raw = csv_data.getvalue()
        metadata, times, values = prepare_csv(raw, dict(timeKind='datetime', timeColumn='timestamp'))
        for column, mapping in zip(metadata['columns'], chosen, strict=True):
            column.update(displayName=mapping['display_name'], unit=mapping['unit'], device=session['config']['endpoint'],
                          logicalKey=mapping['signal_id'], tags=['opc-ua'], liveSignalId=mapping['live_signal_id'],
                          sourceSignalId=mapping['signal_id'], opcUaNodeId=mapping['node_id'])
        metadata['filename'] = f'opc-ua-{identity}.csv'
        metadata['acquisition'] = dict(sessionId=identity, endpoint=session['config']['endpoint'],
            start=start or next(iter(rows)), end=end or next(reversed(rows)), mappings=chosen,
            duplicatePolicy='last-arrival', alignment='exact-timestamp', qualityPolicy='good-numeric-only')
        return self.store.save_dataset(session['workspace_id'], name, metadata, times, values, raw)

    @staticmethod
    def _numeric(sample):
        value = sample['value']
        if sample['quality'] != 'good' or type(value) not in (float, int, bool):
            return None
        if type(value) is int and abs(value) > 2**53:
            return None  # Preserve large integers in raw evidence; avoid a lossy double.
        return float(value) if math.isfinite(value) else None
