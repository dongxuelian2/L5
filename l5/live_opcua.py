"""Read-only OPC UA transport and bounded, durable acquisition delivery."""
from __future__ import annotations

import asyncio
from base64 import b64encode
from collections import deque
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from ipaddress import ip_address
from itertools import islice
from math import isfinite
from urllib.parse import urlsplit
from uuid import UUID

from asyncua import Client, ua
from asyncua.common.utils import ServiceError
from asyncua.crypto import uacrypto
from asyncua.crypto.security_policies import SecurityPolicyBasic256Sha256
from asyncua.crypto.validator import CertificateValidator, CertificateValidatorOptions
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.serialization import Encoding


class OpcUaError(ValueError):
    """An error with text safe to expose to the local API and session history."""


def opcua_error(error):
    if isinstance(error, OpcUaError):
        return str(error)
    if isinstance(error, TimeoutError):
        return 'OPC UA request timed out.'
    if isinstance(error, (ua.UaStatusCodeError, ServiceError)):
        return ua.StatusCode(error.code).name
    if isinstance(error, InvalidSignature):
        return 'OPC UA server certificate or signature did not match the pinned certificate.'
    if isinstance(error, ConnectionError):
        return 'OPC UA connection interrupted or refused.'
    if isinstance(error, OSError):
        return 'OPC UA endpoint or certificate file is unavailable.'
    return f'OPC UA request failed ({type(error).__name__}).'


@dataclass(frozen=True)
class OpcUaConfig:
    endpoint: str
    security_mode: str = 'none'
    username: str = ''
    password: str = field(default='', repr=False)
    application_uri: str = ''
    client_certificate: str = ''
    client_private_key: str = ''
    private_key_password: str = field(default='', repr=False)
    server_certificate: str = ''
    sampling_interval_ms: float = 250
    publishing_interval_ms: float = 250
    timeout_seconds: float = 3
    buffer_capacity: int = 4096

    @classmethod
    def from_payload(cls, body):
        if not isinstance(body, dict):
            raise OpcUaError('OPC UA configuration must be an object.')
        options = {key: body[key] for key in cls.__dataclass_fields__ if key in body}
        options.setdefault('endpoint', '')
        return cls(**options)

    def __post_init__(self):
        fields = ('endpoint', 'security_mode', 'username', 'password', 'application_uri', 'client_certificate',
                  'client_private_key', 'private_key_password', 'server_certificate')
        for key in fields:
            value = getattr(self, key)
            if not isinstance(value, str) or len(value) > 4096 or '\0' in value:
                raise OpcUaError(f'Invalid OPC UA configuration field: {key}.')
        try:
            endpoint = urlsplit(self.endpoint)
            if (endpoint.scheme != 'opc.tcp' or not endpoint.hostname or not endpoint.port
                    or endpoint.username is not None or '?' in self.endpoint or '#' in self.endpoint
                    or any(ch.isspace() or ord(ch) < 32 for ch in self.endpoint)):
                raise ValueError
        except ValueError as error:
            raise OpcUaError('Enter an opc.tcp:// endpoint with a port and no embedded credentials, query, or fragment.') from error
        if self.security_mode not in ('none', 'sign', 'sign_and_encrypt'):
            raise OpcUaError('Select a supported OPC UA security mode.')
        if self.security_mode != 'none' and not all((self.client_certificate, self.client_private_key, self.server_certificate)):
            raise OpcUaError('Signed OPC UA connections require client certificate, private key and pinned server certificate files.')
        if (self.username or self.password) and (self.security_mode != 'sign_and_encrypt' or not self.username):
            raise OpcUaError('OPC UA username credentials require Sign & Encrypt mode and a username.')
        for key, lower, upper in (('sampling_interval_ms', 10, 60_000), ('publishing_interval_ms', 10, 60_000),
                                  ('timeout_seconds', 0.25, 30), ('buffer_capacity', 1, 50_000)):
            value = getattr(self, key)
            if (isinstance(value, bool) or not isinstance(value, (int, float)) or not lower <= value <= upper
                    or (key == 'buffer_capacity' and not isinstance(value, int))):
                raise OpcUaError(f'{key} must be between {lower} and {upper}.')

    def public(self):
        return {key: getattr(self, key) for key in self.__dataclass_fields__
                if key not in ('password', 'private_key_password')}


def _timestamp(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def _now():
    return _timestamp(datetime.now(timezone.utc))


def _value_json(value):
    """Normalize scalar values and cap the payload size of each queued observation."""
    if isinstance(value, int) and abs(value) >= 2**53:
        return str(value), 'integer'
    if value is None or isinstance(value, (bool, int)):
        return value, None
    if isinstance(value, float):
        return (value, None) if isfinite(value) else (str(value), 'nonfinite')
    if isinstance(value, str):
        return (value, None) if len(value) <= 4096 else (None, 'oversize')
    if isinstance(value, bytes):
        return (b64encode(value).decode('ascii'), 'base64') if len(value) <= 3072 else (None, 'oversize')
    if isinstance(value, datetime):
        return _timestamp(value), 'datetime'
    if isinstance(value, UUID):
        return str(value), 'guid'
    return None, 'unsupported'


def _observation(node_id, data_value, received_at, signal_id=None):
    source = _timestamp(data_value.SourceTimestamp)
    server = _timestamp(data_value.ServerTimestamp)
    # The UA binary DateTime zero value is the absent-time sentinel.
    if source == '1601-01-01T00:00:00.000000Z':
        source = None
    if server == '1601-01-01T00:00:00.000000Z':
        server = None
    variant = data_value.Value
    value, encoding = _value_json(variant.Value if variant is not None else None)
    status = data_value.StatusCode or ua.StatusCode()  # OPC UA omits Good status on the wire.
    quality = ('bad' if status.is_bad() else 'uncertain' if status.is_uncertain() else
               'invalid' if encoding in ('oversize', 'unsupported', 'nonfinite') else
               'missing' if value is None else 'good')
    return dict(node_id=node_id, signal_id=signal_id, value=value, value_encoding=encoding, quality=quality,
                variant_type=variant.VariantType.name if variant is not None else None,
                status_code=status.value, status_name=ua.StatusCode(status.value & 0xffff0000).name,
                source_timestamp=source, server_timestamp=server, received_at=received_at,
                source_picoseconds=data_value.SourcePicoseconds, server_picoseconds=data_value.ServerPicoseconds,
                timestamp=source or server or received_at,
                timestamp_origin='source' if source else 'server' if server else 'received')


def _node_id(value):
    if not isinstance(value, str) or not 0 < len(value) <= 1024:
        raise OpcUaError('Invalid OPC UA NodeId.')
    try:
        node_id = ua.NodeId.from_string(value)
    except (ValueError, TypeError, ua.UaError) as error:
        raise OpcUaError('Invalid OPC UA NodeId.') from error
    if isinstance(node_id, ua.ExpandedNodeId) and (node_id.ServerIndex or node_id.NamespaceUri):
        raise OpcUaError('Browse the connected OPC UA server for a local NodeId.')
    if not 0 <= node_id.NamespaceIndex <= 0xffff or (isinstance(node_id.Identifier, int) and not 0 <= node_id.Identifier <= 0xffffffff):
        raise OpcUaError('Invalid OPC UA NodeId.')
    return node_id


class OpcUaSource:
    def __init__(self, config: OpcUaConfig):
        self.config = config
        self._client = None
        self._namespaces = []

    async def connect(self):
        if self._client is not None:
            await self.check_health()
            return
        config = self.config
        client = Client(config.endpoint, timeout=config.timeout_seconds)
        client.name = 'L5 Live Data Gateway'
        client.max_messagesize = 4 * 1024 * 1024
        client.max_chunkcount = 64
        if config.security_mode != 'none':
            mode = ua.MessageSecurityMode.Sign if config.security_mode == 'sign' else ua.MessageSecurityMode.SignAndEncrypt
            try:
                certificate = await uacrypto.load_certificate(config.client_certificate)
                san = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            except (OSError, ValueError, TypeError, x509.ExtensionNotFound) as error:
                raise OpcUaError('Could not load an OPC UA client certificate with a subject alternative name.') from error
            uris = san.get_values_for_type(x509.UniformResourceIdentifier)
            if not uris or (config.application_uri and config.application_uri not in uris):
                raise OpcUaError('The OPC UA client application URI must match the client certificate.')
            client.application_uri = config.application_uri or uris[0]
            try:
                await client.set_security(SecurityPolicyBasic256Sha256, certificate.public_bytes(Encoding.DER), config.client_private_key,
                                          private_key_password=config.private_key_password or None,
                                          server_certificate=config.server_certificate, mode=mode)
            except (OSError, ValueError, TypeError) as error:
                raise OpcUaError('Could not load OPC UA certificate or private key. Check the files and key password.') from error
            client.certificate_validator = self._validate_server_certificate
        if config.username:
            client.set_user(config.username)
            client.set_password(config.password)
        try:
            await asyncio.wait_for(client.connect(), timeout=4 * config.timeout_seconds)
            self._namespaces = await client.get_namespace_array()
        except BaseException:
            await self._close(client)
            raise
        self._client = client

    async def _validate_server_certificate(self, certificate, application):
        # asyncua pins the peer certificate loaded above and verifies the server's signature.
        await CertificateValidator(CertificateValidatorOptions.EXT_VALIDATION | CertificateValidatorOptions.PEER_SERVER)(
            certificate, application)
        host = urlsplit(self.config.endpoint).hostname
        san = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        try:
            address = ip_address(host)
        except ValueError:
            matches = host.rstrip('.').casefold() in {name.rstrip('.').casefold() for name in san.get_values_for_type(x509.DNSName)}
        else:
            matches = address in san.get_values_for_type(x509.IPAddress)
        if not matches:
            raise ServiceError(ua.StatusCodes.BadCertificateHostNameInvalid)

    async def _close(self, client):
        with suppress(Exception):
            # asyncua closes the transport in disconnect's finally block, including on timeout.
            await asyncio.wait_for(client.disconnect(), timeout=self.config.timeout_seconds + 1)

    async def disconnect(self):
        client, self._client = self._client, None
        if client is not None:
            await self._close(client)

    def _connected_client(self):
        if self._client is None:
            raise OpcUaError('Connect to an OPC UA server first.')
        return self._client

    async def check_health(self):
        await self._connected_client().check_connection()

    def mapping_identity(self, node_id, namespace_uri=None):
        parsed = _node_id(node_id)
        if parsed.NamespaceIndex >= len(self._namespaces):
            raise OpcUaError('The selected OPC UA namespace is unavailable.')
        actual_uri = self._namespaces[parsed.NamespaceIndex]
        if namespace_uri and namespace_uri != actual_uri:
            raise OpcUaError('The selected OPC UA namespace does not match this server. Browse the node again.')
        return parsed.to_string(), actual_uri

    def resolve_node(self, node_id, namespace_uri=None):
        parsed = _node_id(node_id)
        if namespace_uri:
            try:
                index = self._namespaces.index(namespace_uri)
            except ValueError as error:
                raise OpcUaError('The selected OPC UA namespace is unavailable.') from error
            return ua.NodeId(parsed.Identifier, index, parsed.NodeIdType)
        return parsed

    async def browse(self, node_id='i=85'):
        return await asyncio.wait_for(self._browse(node_id), timeout=max(3, 3 * self.config.timeout_seconds))

    async def _browse(self, node_id):
        client = self._connected_client()
        request = ua.BrowseDescription()
        request.NodeId = _node_id(node_id)
        request.ReferenceTypeId = ua.NodeId(ua.ObjectIds.HierarchicalReferences)
        request.NodeClassMask = ua.NodeClass.Object | ua.NodeClass.Variable | ua.NodeClass.View
        request.ResultMask = ua.BrowseResultMask.All
        limit = 512
        page, = await client.uaclient.browse(ua.BrowseParameters(NodesToBrowse=[request], RequestedMaxReferencesPerNode=limit))
        children = []
        continuation = None
        try:
            while True:
                continuation = page.ContinuationPoint
                page.StatusCode.check()
                children.extend(page.References or [])
                if len(children) > limit or (continuation and len(children) == limit):
                    raise OpcUaError(f'This OPC UA folder contains more than {limit} children. Browse a smaller branch or enter its NodeId.')
                if not continuation:
                    break
                page, = await client.uaclient.browse_next(ua.BrowseNextParameters(False, [continuation]))
        finally:
            if continuation:
                with suppress(Exception):
                    await client.uaclient.browse_next(ua.BrowseNextParameters(True, [continuation]))
        children = [ref for ref in children if not getattr(ref.NodeId, 'ServerIndex', 0)
                    and not getattr(ref.NodeId, 'NamespaceUri', None)]
        if any(ref.NodeId.NamespaceIndex >= len(self._namespaces) for ref in children):
            self._namespaces = await client.get_namespace_array()
        result = []
        for offset in range(0, len(children), 16):
            result.extend(await asyncio.gather(*(self._describe(client, ref) for ref in children[offset:offset + 16])))
        return sorted(result, key=lambda row: (row['node_class'] == 'Variable', row['display_name'].casefold(), row['node_id']))

    async def _describe(self, client, ref):
        node = client.get_node(ref.NodeId)
        data_type = unit = None
        if ref.NodeClass == ua.NodeClass.Variable:
            with suppress(ua.UaStatusCodeError):
                type_id = await node.read_data_type()
                data_type = (ua.ObjectIdNames.get(type_id.Identifier) if type_id.NamespaceIndex == 0 else None) or type_id.to_string()
            with suppress(ua.UaStatusCodeError):
                unit_value = await (await node.get_child('0:EngineeringUnits')).read_value()
                if isinstance(unit_value, ua.EUInformation):
                    unit = unit_value.DisplayName.Text or unit_value.Description.Text
                elif isinstance(unit_value, str):
                    unit = unit_value
        index = ref.NodeId.NamespaceIndex
        return dict(node_id=ref.NodeId.to_string(), display_name=ref.DisplayName.Text or ref.BrowseName.Name or ref.NodeId.to_string(),
                    node_class=ref.NodeClass.name, data_type=data_type, unit=unit,
                    namespace_uri=self._namespaces[index] if index < len(self._namespaces) else None,
                    has_children=ref.NodeClass in (ua.NodeClass.Object, ua.NodeClass.View))

    async def read(self, node_id):
        node = self._connected_client().get_node(_node_id(node_id))
        params = ua.ReadParameters()
        params.TimestampsToReturn = ua.TimestampsToReturn.Both
        attribute = ua.ReadValueId()
        attribute.NodeId = node.nodeid
        attribute.AttributeId = ua.AttributeIds.Value
        params.NodesToRead = [attribute]
        value, = await node.session.read(params)
        return _observation(node.nodeid.to_string(), value, _now())


class _Subscription:
    """Handle complete UA PublishResults, including keepalives and absent Variants."""

    def __init__(self, source, collector):
        self.source = source
        self.collector = collector
        self.ua_client = source._connected_client().uaclient
        self.clock = asyncio.get_running_loop().time
        self.subscription_id = None
        self.last_publish = self.clock()
        self.last_sequence = None
        self.failure = None
        self.items = dict(enumerate(collector.mappings, 1))
        self.pending = self.items.copy()
        self.unavailable = {}
        self.last_value = {}
        self.silence_limit = {}
        self.silent = set()

    async def start(self):
        config = self.source.config
        params = ua.CreateSubscriptionParameters()
        params.RequestedPublishingInterval = config.publishing_interval_ms
        params.RequestedMaxKeepAliveCount = max(1, round(1000 / config.publishing_interval_ms))
        params.RequestedLifetimeCount = max(30, 3 * params.RequestedMaxKeepAliveCount)
        params.MaxNotificationsPerPublish = 256
        params.PublishingEnabled = True
        result = await self.ua_client.create_subscription(params, self._publish)
        self.subscription_id = result.SubscriptionId
        self.publishing_interval_ms = result.RevisedPublishingInterval
        self.publish_timeout = max(4.0, 3 * result.RevisedMaxKeepAliveCount * self.publishing_interval_ms / 1000
                                   + config.timeout_seconds)
        if self.publishing_interval_ms != config.publishing_interval_ms:
            self.collector._event('subscription_revised', f'Server revised the publishing interval to {self.publishing_interval_ms:g} ms.')
        await self.add_pending()

    async def add_pending(self):
        config = self.source.config
        requests = []
        handles = []
        for handle, mapping in self.pending.items():
            try:
                node = self.source.resolve_node(mapping['node_id'], mapping.get('namespace_uri'))
            except OpcUaError as error:
                self._mark_unavailable(handle, str(error))
                continue
            request = ua.MonitoredItemCreateRequest()
            request.ItemToMonitor.NodeId = node
            request.ItemToMonitor.AttributeId = ua.AttributeIds.Value
            request.MonitoringMode = ua.MonitoringMode.Reporting
            request.RequestedParameters.ClientHandle = handle
            request.RequestedParameters.SamplingInterval = config.sampling_interval_ms
            request.RequestedParameters.QueueSize = 64
            request.RequestedParameters.DiscardOldest = True
            requests.append(request)
            handles.append(handle)
        if not requests:
            return
        params = ua.CreateMonitoredItemsParameters()
        params.SubscriptionId = self.subscription_id
        params.TimestampsToReturn = ua.TimestampsToReturn.Both
        params.ItemsToCreate = requests
        results = await self.ua_client.create_monitored_items(params)
        for handle, result in zip(handles, results, strict=True):
            if not result.StatusCode.is_good():
                self._mark_unavailable(handle, result.StatusCode.name)
                continue
            if self.unavailable.pop(handle, None):
                self._item_event('subscription_available', handle, 'The server accepted this monitored item.')
            if result.RevisedSamplingInterval != config.sampling_interval_ms or result.RevisedQueueSize != 64:
                self._item_event('subscription_revised', handle, f'Server revised sampling to {result.RevisedSamplingInterval:g} ms '
                                 f'with a monitored item queue of {result.RevisedQueueSize}.')
            del self.pending[handle]
            self.last_value.setdefault(handle, self.clock())
            self.silence_limit[handle] = max(5.0, 5 * max(self.publishing_interval_ms, result.RevisedSamplingInterval) / 1000)

    def _mark_unavailable(self, handle, detail):
        if self.unavailable.get(handle) != detail:
            self.unavailable[handle] = detail
            self._item_event('subscription_unavailable', handle, detail)

    def _item_event(self, kind, handle, detail):
        mapping = self.items[handle]
        self.collector._event(kind, detail, node_id=mapping['node_id'], signal_id=mapping['signal_id'])

    async def check(self):
        if self.failure:
            raise OpcUaError(self.failure)
        await self.source.check_health()
        now = self.clock()
        if now - self.last_publish > self.publish_timeout:
            raise OpcUaError('OPC UA publish and keepalive messages stopped arriving.')
        for handle, threshold in self.silence_limit.items():
            if handle not in self.silent and now - self.last_value[handle] >= threshold:
                self.silent.add(handle)
                self._item_event('sampling_gap', handle, 'No recent data changes. A steady signal may also be quiet.')

    def _publish(self, result):
        self.last_publish = self.clock()
        message = result.NotificationMessage
        if not message.NotificationData:
            return
        if message.SequenceNumber:
            self._check_sequence(message.SequenceNumber)
        received_at = _now()
        for notification in message.NotificationData:
            if isinstance(notification, ua.StatusChangeNotification) and not notification.Status.is_good():
                self.failure = notification.Status.name
            elif isinstance(notification, ua.DataChangeNotification):
                for item in notification.MonitoredItems:
                    self._receive(item, received_at)

    def _check_sequence(self, sequence):
        # Notification sequence numbers roll over from UInt32 max to 1. Keepalives do not consume a number.
        expected = (self.last_sequence or 0) % 0xffffffff + 1
        missing = (sequence - expected) % 0xffffffff
        if 0 < missing < 0x80000000:
            self.collector._event('publish_gap', 'OPC UA publish sequence skipped notification messages.', count=missing)
        if missing < 0x80000000:
            self.last_sequence = sequence

    def _receive(self, item, received_at):
        handle = item.ClientHandle
        mapping = self.items.get(handle)
        if mapping is None:
            self.collector._event('notification_error', 'OPC UA sent an unknown monitored item handle.')
            return
        try:
            sample = _observation(mapping['node_id'], item.Value, received_at, mapping['signal_id'])
        except (ValueError, OverflowError, TypeError, AttributeError):
            self._item_event('notification_error', handle, 'OPC UA sent an unreadable data value.')
            return
        self.last_value[handle] = self.last_publish
        if handle in self.silent:
            self.silent.remove(handle)
            self._item_event('sampling_resumed', handle, 'Data changes resumed.')
        # DataValue info type (0x400) and Overflow (0x80) are carried in the same status word.
        if sample['status_code'] & 0xc80 == 0x480:
            self._item_event('server_overflow', handle, 'The OPC UA server reported a monitored item queue overflow; loss count unknown.')
        self.collector._receive(sample)

    async def close(self):
        if self.subscription_id is not None:
            result, = await self.ua_client.delete_subscriptions([self.subscription_id])
            result.check()


class LiveCollector:
    """Record on an asyncio loop and call the synchronous append sink on a worker thread.

    The sink must append both lists in one transaction, raising on failure. It may be
    called with no observations when there is an acquisition event to persist.
    """

    def __init__(self, config: OpcUaConfig, mappings, append, *, source=None):
        self.config = config
        self.mappings = [dict(mapping) for mapping in mappings]
        self.append = append
        self.source = source
        self._samples = deque()
        self._events = deque()
        self._loss = {}
        self._wake = asyncio.Event()
        self._stop = asyncio.Event()
        self._network_finished = False
        self._keep_source = False
        self._runner = self._writer = None
        self._dropped = 0
        self._last_notification = None
        self._state = 'connecting'
        self._error = None
        self._storage_error = None

    async def start(self):
        if self._runner is not None:
            raise OpcUaError('This acquisition has already been started.')
        if not self.mappings:
            raise OpcUaError('Select at least one OPC UA variable.')
        self._runner = asyncio.create_task(self._run())
        self._writer = asyncio.create_task(self._write())

    def status(self):
        return dict(connection_state=self._state, last_error=self._error, buffered=len(self._samples), dropped=self._dropped,
                    last_notification_at=self._last_notification)

    def _receive(self, sample):
        self._last_notification = sample['received_at']
        if len(self._samples) >= self.config.buffer_capacity:
            self._dropped += 1
            self._count_loss('buffer_overflow', 'Incoming observations dropped while the L5 buffer was full.')
        else:
            self._samples.append(sample)
            self._wake.set()

    def _event(self, kind, detail, **fields):
        if len(self._events) >= 256:
            self._count_loss('event_overflow', 'Additional acquisition events dropped while the event buffer was full.')
        else:
            self._events.append(dict(kind=kind, timestamp=_now(), detail=detail, **fields))
            self._wake.set()

    def _count_loss(self, kind, detail):
        stamp = _now()
        if kind not in self._loss:
            self._loss[kind] = dict(kind=kind, timestamp=stamp, detail=detail, count=0)
        self._loss[kind]['count'] += 1
        self._loss[kind]['last_timestamp'] = stamp
        self._wake.set()

    async def _flush(self):
        while self._samples or self._events or self._loss:
            samples = list(islice(self._samples, 512))
            events = list(self._events)
            loss, self._loss = self._loss, {}
            try:
                await asyncio.to_thread(self.append, samples, [*events, *loss.values()])
            except Exception:
                for kind, previous in loss.items():
                    if kind in self._loss:
                        previous['count'] += self._loss[kind]['count']
                        previous['last_timestamp'] = self._loss[kind]['last_timestamp']
                    self._loss[kind] = previous
                raise
            for _ in samples:
                self._samples.popleft()
            for _ in events:
                self._events.popleft()

    async def _write(self):
        while not self._network_finished or self._samples or self._events or self._loss:
            self._wake.clear()
            # Allow bursts to share one transaction. A stopped collector drains immediately.
            if not self._stop.is_set():
                await self._wait(0.05)
            try:
                await self._flush()
            except Exception as error:
                self._storage_error = error
                self._state = 'error'
                self._error = 'Could not persist OPC UA observations. Buffered data awaits a successful stop retry.'
                self._stop.set()
                return
            if not self._network_finished and not self._samples and not self._events and not self._loss:
                await self._wake.wait()

    async def _wait(self, seconds):
        with suppress(TimeoutError):
            await asyncio.wait_for(self._stop.wait(), seconds)

    async def _run(self):
        backoff = 0.5
        interrupted = False
        previously_connected = False
        try:
            while not self._stop.is_set():
                subscription = None
                healthy = False
                try:
                    if self.source is None:
                        self.source = OpcUaSource(self.config)
                    await self.source.connect()
                    subscription = _Subscription(self.source, self)
                    await subscription.start()
                    if not self._storage_error:
                        self._state, self._error = 'connected', None
                    healthy = previously_connected = True
                    backoff = 0.5
                    if interrupted:
                        self._event('connection_restored', 'OPC UA connection and subscription restored.')
                        interrupted = False
                    next_retry = subscription.clock() + 5
                    while not self._stop.is_set():
                        await subscription.check()
                        if subscription.pending and subscription.clock() >= next_retry:
                            await subscription.add_pending()
                            next_retry = subscription.clock() + 5
                        await self._wait(0.25)
                except Exception as error:
                    healthy = False
                    if not self._stop.is_set():
                        self._state, self._error = 'reconnecting', opcua_error(error)
                        if not interrupted:
                            kind = 'connection_interrupted' if previously_connected else 'connection_failed'
                            self._event(kind, self._error)
                            interrupted = True
                finally:
                    if subscription is not None and healthy:
                        try:
                            await subscription.close()
                        except Exception as error:
                            healthy = False
                            self._event('connection_interrupted', opcua_error(error))
                    if self.source is not None and not (healthy and self._keep_source and not self._storage_error):
                        await self.source.disconnect()
                        self.source = None
                if not self._stop.is_set():
                    await self._wait(backoff)
                    backoff = min(8.0, backoff * 2)
        finally:
            self._network_finished = True
            self._wake.set()

    async def stop(self, *, keep_source=False):
        self._keep_source = keep_source
        self._stop.set()
        if self._runner is not None:
            await self._runner
            await self._writer
        if self._storage_error:
            try:
                await self._flush()
            except Exception as error:
                raise OpcUaError(self._error) from error
            self._storage_error = None
        self._state = 'stopped'
        source, self.source = self.source, None
        if source is not None and not keep_source:
            await source.disconnect()
            return None
        return source
