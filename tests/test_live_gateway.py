"""Acceptance tests over real OPC UA and the normal L5 HTTP entry points."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from ipaddress import ip_address
import json
from pathlib import Path
from socket import gethostname
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import build_opener, ProxyHandler, Request

from asyncua import Server, ua
from asyncua.crypto.cert_gen import dump_private_key_as_pem, generate_private_key, generate_self_signed_app_certificate
from asyncua.server.user_managers import User, UserManager, UserRole
from cryptography import x509
from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, Encoding, PrivateFormat
from cryptography.x509.oid import ExtendedKeyUsageOID

from examples.opcua_tanks import simulation_rows, TankServer
from l5.live_opcua import OpcUaConfig, OpcUaSource
from l5.workspace import WorkspaceStore
from server import Handler


class QuietHandler(Handler):
    def log_message(self, *_args):
        pass


class LiveGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = self.enterContext(TemporaryDirectory())
        self.rows = simulation_rows(duration=16.4, fault_at=13.2)
        self.source = TankServer(port=0)
        await self.source.start(self.rows[0])
        self.addAsyncCleanup(self.source.stop)
        self.start_l5()
        self.addAsyncCleanup(self.stop_l5)
        workspace = await self.request('/workspaces', {'name': 'Live tank acceptance'})
        self.workspace = f'/workspaces/{workspace["id"]}'
        self.live = self.workspace + '/live'

    def start_l5(self):
        self.http = ThreadingHTTPServer(('127.0.0.1', 0), QuietHandler)
        self.http.workspace_store = WorkspaceStore(Path(self.folder))
        self.http_thread = threading.Thread(target=self.http.serve_forever, kwargs={'poll_interval': .05}, daemon=True)
        self.http_thread.start()

    async def stop_l5(self):
        if self.http is not None:
            await asyncio.to_thread(self.http.shutdown)
            await asyncio.to_thread(self.http.server_close)
            await asyncio.to_thread(self.http.workspace_store.close)
            self.http_thread.join()
            self.http = None

    async def request(self, path, body=None):
        request = Request(f'http://127.0.0.1:{self.http.server_port}/api{path}',
                          data=json.dumps(body).encode() if body is not None else None,
                          headers={'Content-Type': 'application/json'})

        def send():
            try:
                with build_opener(ProxyHandler({})).open(request, timeout=20) as response:
                    return json.load(response)
            except HTTPError as error:
                raise AssertionError(f'{request.get_method()} {path} returned {error.code}: {error.read().decode()}') from error

        return await asyncio.to_thread(send)

    async def wait_for(self, path, condition, timeout=12):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            payload = await self.request(path)
            if condition(payload):
                return payload
            if loop.time() >= deadline:
                self.fail(f'Timed out waiting for {path}: {str(payload)[-1200:]}')
            await asyncio.sleep(.05)

    async def connect_and_browse(self, **options):
        connected = await self.request(self.live + '/connect', dict(
            endpoint=self.source.endpoint, sampling_interval_ms=20, publishing_interval_ms=40,
            timeout_seconds=2, **options,
        ))
        self.assertEqual(connected['connection_state'], 'connected')
        objects = await self.request(self.live + '/browse')
        tanks = next(node for node in objects['nodes'] if node['display_name'] == 'Coupled Tanks')
        variables = await self.request(self.live + '/browse?' + urlencode({'node_id': tanks['node_id']}))
        nodes = {node['display_name']: node for node in variables['nodes']}
        self.assertIn('Inlet flow', nodes)
        self.assertIn('Pump command', nodes)
        level = nodes['Tank 2 measured level']
        self.assertEqual(level['node_class'], 'Variable')
        self.assertEqual(level['data_type'], 'Double')
        self.assertEqual(level['unit'], 'm')
        self.assertEqual(level['node_id'], self.source.nodes['level2'].nodeid.to_string())
        return nodes

    async def record(self, *nodes):
        fields = ('node_id', 'namespace_uri', 'display_name', 'unit', 'data_type', 'signal_id')
        mappings = [{key: node[key] for key in fields if key in node} for node in nodes]
        session = await self.request(self.live + '/sessions', dict(name='Tank recorder', mappings=mappings))
        self.assertEqual(session['state'], 'recording')
        return session, f'{self.live}/sessions/{session["id"]}'

    async def test_http_acquire_reopen_convert_and_detect(self):
        # Fixed source times make it possible to prove the recorded times are supplied by the OPC UA server.
        origin = datetime(2025, 1, 1, tzinfo=timezone.utc)

        def source_time(index):
            return origin + timedelta(seconds=index)

        def recorded_at(sample, index):
            return datetime.fromisoformat(sample['source_timestamp']) == source_time(index)

        await self.source.write('level2', self.rows[0]['level2'], source_time(-1))
        nodes = await self.connect_and_browse()
        level = nodes['Tank 2 measured level']
        current = await self.request(self.live + '/read?' + urlencode({'node_id': level['node_id']}))
        self.assertAlmostEqual(current['value'], self.rows[0]['level2'])
        self.assertEqual(current['quality'], 'good')
        self.assertIsNotNone(current['source_timestamp'])
        self.assertIsNotNone(current['server_timestamp'])
        existing = await self.request(self.workspace + '/datasets', {'csv': 't,tank2\n0,1\n1,1.02\n2,0.99\n3,1.01\n'})
        signal_id = existing['metadata']['columns'][0]['id']
        session, path = await self.record({**level, 'display_name': 'Vessel 2 level', 'signal_id': signal_id})
        self.assertEqual(session['mappings'][0]['signal_id'], signal_id)
        await self.wait_for(path + '/samples', lambda payload: len(payload['samples']) >= 1)

        status_by_index = {74: ua.StatusCodes.UncertainLastUsableValue, 76: ua.StatusCodes.BadNoCommunication}
        for index, row in enumerate(self.rows[:80]):
            value = row['level2'] + .00001 if index == 0 else row['level2']
            await self.source.write('level2', value, source_time(index), status=status_by_index.get(index, ua.StatusCodes.Good),
                                    server_time=source_time(index) + timedelta(milliseconds=5))
            await asyncio.sleep(.05)
        await self.wait_for(path + '/samples', lambda payload: any(recorded_at(s, 79) for s in payload['samples']))

        # Change the value at an old timestamp to test duplicates and then send a distinct, late timestamp.
        correction = self.rows[8]['level2'] + .00001
        await self.source.write('level2', correction, source_time(8))
        await asyncio.sleep(.08)
        await self.source.write('level2', self.rows[9]['level2'], source_time(8.5))
        final = await self.wait_for(path + '/samples', lambda payload: any(recorded_at(s, 8.5) for s in payload['samples']))
        samples = final['samples']
        on_time = next(s for s in samples if recorded_at(s, 79))
        self.assertAlmostEqual(on_time['value'], self.rows[79]['level2'])
        self.assertEqual(on_time['signal_id'], session['mappings'][0]['signal_id'])
        self.assertEqual(on_time['timestamp_origin'], 'source')
        self.assertEqual(datetime.fromisoformat(on_time['timestamp']), source_time(79))
        self.assertEqual(datetime.fromisoformat(on_time['server_timestamp']), source_time(79) + timedelta(milliseconds=5))
        self.assertEqual(on_time['status_code'], ua.StatusCodes.Good)
        duplicates = [s for s in samples if recorded_at(s, 8)]
        self.assertEqual(len(duplicates), 2)
        self.assertCountEqual([s['value'] for s in duplicates], [self.rows[8]['level2'], correction])
        self.assertEqual(sum(sample['duplicate'] for sample in duplicates), 1)
        self.assertTrue(next(s for s in samples if recorded_at(s, 8.5))['out_of_order'])
        self.assertTrue({'duplicate_timestamp', 'out_of_order'} <= {e['kind'] for e in final['events']})
        bad = next(s for s in samples if recorded_at(s, 76))
        self.assertEqual(bad['quality'], 'bad')
        self.assertEqual(bad['status_code'], ua.StatusCodes.BadNoCommunication)
        self.assertEqual(bad['status_name'], 'BadNoCommunication')
        uncertain = next(s for s in samples if recorded_at(s, 74))
        self.assertEqual(uncertain['quality'], 'uncertain')
        self.assertAlmostEqual(uncertain['value'], self.rows[74]['level2'])

        completed = await self.request(path + '/stop', {})
        self.assertEqual(completed['state'], 'completed')
        self.assertIsNotNone(completed['stopped_at'])
        persisted = await self.request(path + '/samples')
        arrival_order = sorted(persisted['samples'], key=lambda sample: sample['id'])
        cursor = arrival_order[-3]['id']
        tail = await self.request(path + '/samples?' + urlencode({'after_id': cursor, 'limit': 2}))
        self.assertEqual(tail['samples'], arrival_order[-2:])
        await self.stop_l5()
        self.start_l5()
        self.assertEqual(await self.request(path), completed)
        self.assertEqual(await self.request(path + '/samples'), persisted)
        self.assertIn(session['id'], [item['id'] for item in (await self.request(self.live + '/sessions'))['sessions']])

        dataset = await self.request(path + '/dataset', dict(name='Acquired Tank 2 level',
                                     start=source_time(0).isoformat(), end=source_time(79).isoformat()))
        self.assertEqual(dataset['metadata']['rowCount'], 81)
        self.assertEqual(dataset['metadata']['missingCount'], 2)
        column, = dataset['metadata']['columns']
        self.assertEqual(column['unit'], 'm')
        self.assertEqual(column['displayName'], 'Vessel 2 level')
        self.assertEqual(column['sourceSignalId'], signal_id)
        catalog = await self.request(self.workspace + '/signals')
        self.assertTrue(any(signal['datasetId'] == dataset['id'] and signal['id'] == column['id']
                            for signal in catalog['signals']))
        series = await self.request(f'/datasets/{dataset["id"]}/series')
        times = series['times']
        values = series['values'][column['name']]
        self.assertEqual(times, sorted(set(times)))
        self.assertAlmostEqual(values[8], correction)
        self.assertIsNone(values[75])
        self.assertIsNone(values[77])
        result = await self.request(self.workspace + '/analyses', dict(
            datasetId=dataset['id'], signals=[column['name']], algorithm='robust-maxz', fitFraction=.5,
            baselineRange=[times[0], times[66]], analysisRange=[times[67], times[-1]],
        ))
        self.assertGreater(result['summary']['flaggedSamples'], 0)

    async def test_subscription_recovers_from_source_restart(self):
        nodes = await self.connect_and_browse()
        _, path = await self.record(nodes['Tank 2 measured level'])
        await self.wait_for(path + '/samples', lambda payload: bool(payload['samples']))
        await self.source.stop()
        await self.wait_for(path + '/samples', lambda payload: any(e['kind'] == 'connection_interrupted'
                                                                    for e in payload['events']))
        await self.source.start(self.rows[0])
        await self.wait_for(path + '/samples', lambda payload: any(e['kind'] == 'connection_restored'
                                                                    for e in payload['events']))
        timestamp = datetime.now(timezone.utc)
        await self.source.write('level2', 1.75, timestamp)
        recovered = await self.wait_for(path + '/samples', lambda payload: any(s['value'] == 1.75
                                                                                for s in payload['samples']))
        sample = next(s for s in recovered['samples'] if s['value'] == 1.75)
        self.assertEqual(datetime.fromisoformat(sample['source_timestamp']), timestamp)
        await self.request(path + '/stop', {})

    async def test_initial_publish_overflow_is_durable(self):
        nodes = await self.connect_and_browse(buffer_capacity=1)
        variables = [node for node in nodes.values() if node['node_class'] == 'Variable']
        _, path = await self.record(*variables)
        await self.wait_for(path + '/samples', lambda payload: any(e['kind'] == 'buffer_overflow'
                                                                    for e in payload['events']))
        await self.request(path + '/stop', {})
        persisted = await self.request(path + '/samples')
        dropped = sum(e['count'] for e in persisted['events'] if e['kind'] == 'buffer_overflow')
        self.assertGreater(dropped, 0)
        self.assertEqual(len(persisted['samples']) + dropped, len(variables))

    async def test_storage_failure_retains_pending_observations_until_stop_retry(self):
        nodes = await self.connect_and_browse()
        attempts = []

        def disk_full(_session_id, samples, events):
            attempts.append((samples, events))
            raise OSError('disk full')

        gateway = self.http.workspace_store.live
        with patch.object(gateway, 'append', side_effect=disk_full):
            _, path = await self.record(nodes['Tank 2 measured level'])
            failed = await self.wait_for(self.live + '/status', lambda payload: payload['connection_state'] == 'error')
            self.assertEqual(failed['buffered'], 1)
            with self.assertRaisesRegex(AssertionError, 'could not flush all buffered data'):
                await self.request(path + '/stop', {})
            self.assertEqual((await self.request(path))['state'], 'recording')
            self.assertEqual((await self.request(path + '/samples'))['samples'], [])
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[0], attempts[1])
        self.assertEqual((await self.request(path + '/stop', {}))['state'], 'completed')
        persisted, = (await self.request(path + '/samples'))['samples']
        expected, = attempts[0][0]
        self.assertEqual(persisted['source_timestamp'], expected['source_timestamp'])
        self.assertEqual(persisted['value'], expected['value'])


class SecureSourceTests(unittest.IsolatedAsyncioTestCase):
    async def test_encrypted_channel_validates_pinned_certificate_and_endpoint_host(self):
        folder = Path(self.enterContext(TemporaryDirectory()))
        username, password, key_password = 'operator', 'opcua-test-password', 'opcua-test-key-password'
        credentials = (username, password)

        class TestUsers(UserManager):
            def get_user(self, _server, username=None, password=None, certificate=None):
                if (username, password) == credentials:
                    return User(role=UserRole.User)

        def certificate(name, purpose, address='127.0.0.1', key_passphrase=None):
            app_uri = f'urn:l5:test:{name}'
            key = generate_private_key()
            names = [x509.UniformResourceIdentifier(app_uri), x509.DNSName(gethostname()),
                     x509.IPAddress(ip_address(address))]
            cert = generate_self_signed_app_certificate(key, name, {}, names, extended=[purpose], days=1)
            cert_path, key_path = folder / f'{name}.der', folder / f'{name}.pem'
            cert_path.write_bytes(cert.public_bytes(Encoding.DER))
            key_path.write_bytes(dump_private_key_as_pem(key) if key_passphrase is None else key.private_bytes(
                Encoding.PEM, PrivateFormat.PKCS8, BestAvailableEncryption(key_passphrase.encode())))
            return app_uri, str(cert_path), str(key_path)

        async def start_secure(assets):
            server_uri, server_cert, server_key = assets
            server = Server(user_manager=TestUsers())
            await server.init()
            await server.set_application_uri(server_uri)
            server.set_endpoint('opc.tcp://127.0.0.1:0/l5/secure/')
            server.set_security_policy([ua.SecurityPolicyType.Basic256Sha256_SignAndEncrypt])
            server.set_identity_tokens([ua.UserNameIdentityToken])
            await server.load_certificate(server_cert)
            await server.load_private_key(server_key)
            namespace = await server.register_namespace('urn:l5:test:secure-signals')
            node = await server.nodes.objects.add_variable(ua.NodeId('value', namespace), 'Pressure', 42.5)
            await server.start()
            self.addAsyncCleanup(server.stop)
            return f'opc.tcp://127.0.0.1:{server.bserver.port}/l5/secure/', node.nodeid.to_string()

        server_assets = certificate('server', ExtendedKeyUsageOID.SERVER_AUTH)
        client_uri, client_cert, client_key = certificate('client', ExtendedKeyUsageOID.CLIENT_AUTH,
                                                         key_passphrase=key_password)
        wrong_host_assets = certificate('other-server', ExtendedKeyUsageOID.SERVER_AUTH, address='127.0.0.2')
        endpoint, node_id = await start_secure(server_assets)
        options = dict(endpoint=endpoint, security_mode='sign_and_encrypt', application_uri=client_uri,
                       client_certificate=client_cert, client_private_key=client_key, server_certificate=server_assets[1],
                       username=username, password=password, private_key_password=key_password, timeout_seconds=1.5)

        store = WorkspaceStore(folder / 'l5')
        self.addAsyncCleanup(asyncio.to_thread, store.close)
        workspace = store.create_workspace('Secure test')['id']
        status = await asyncio.to_thread(store.live.connect, workspace, options)
        self.assertEqual(status['connection_state'], 'connected')
        observation = await asyncio.to_thread(store.live.node_request, workspace, 'read', node_id)
        self.assertEqual(observation['value'], 42.5)
        session = await asyncio.to_thread(store.live.start, workspace, {'mappings': [{'node_id': node_id}]})
        completed = await asyncio.to_thread(store.live.stop, workspace, session['id'])
        for secret_key, secret in (('password', password), ('private_key_password', key_password)):
            self.assertNotIn(secret_key, status['config'])
            self.assertNotIn(secret_key, completed['config'])
            self.assertNotIn(secret.encode(), (store.root / 'workspace.sqlite3').read_bytes())

        wrong_pin = OpcUaSource(OpcUaConfig.from_payload({**options, 'server_certificate': wrong_host_assets[1]}))
        self.addAsyncCleanup(wrong_pin.disconnect)
        with self.assertRaises((ua.UaError, ConnectionError, TimeoutError)):
            await wrong_pin.connect()

        other_endpoint, _ = await start_secure(wrong_host_assets)
        wrong_host = OpcUaSource(OpcUaConfig.from_payload({**options, 'endpoint': other_endpoint,
                                                         'server_certificate': wrong_host_assets[1]}))
        self.addAsyncCleanup(wrong_host.disconnect)
        with self.assertRaises(ua.UaStatusCodeError) as invalid_hostname:
            await wrong_host.connect()
        self.assertEqual(invalid_hostname.exception.code, ua.StatusCodes.BadCertificateHostNameInvalid)


if __name__ == '__main__':
    unittest.main()
