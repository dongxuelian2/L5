"""Loopback OPC UA source driven by L5's coupled tank simulation."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import logging
import math

from asyncua import Server, ua

from l5.models.tanks import CoupledTankModel, FAULTS, SIGNALS


NAMESPACE_URI = 'urn:l5:demo:coupled-tanks'
MODEL_STEP = 0.2
UNIT_CODES = {'m': 'MTR', 'm³/s': 'MQS', '%': 'P1', 'fraction': 'C62'}


class TankServer:
    """Host sensor values from the model on a loopback-only, read-only server."""

    def __init__(self, port: int = 4840):
        self.port = port
        self.server = None
        self.nodes = {}

    @property
    def endpoint(self) -> str:
        return f'opc.tcp://127.0.0.1:{self.port}/l5/tanks/'

    async def start(self, row: dict) -> None:
        server = Server()
        server.set_endpoint(self.endpoint)
        server.set_server_name('L5 Coupled Tanks')
        server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
        server.set_identity_tokens([ua.AnonymousIdentityToken])
        await server.init()
        namespace = await server.register_namespace(NAMESPACE_URI)
        device = await server.nodes.objects.add_object(ua.NodeId('tanks', namespace), 'Coupled Tanks')
        for signal in SIGNALS:
            key = signal['key']
            unit = signal['unit']
            node = await device.add_variable(
                ua.NodeId(key, namespace), ua.QualifiedName(signal['label'], namespace),
                float(row[key]), ua.VariantType.Double,
            )
            eu = ua.EUInformation(
                NamespaceUri='http://www.opcfoundation.org/UA/units/un/cefact',
                UnitId=int.from_bytes(UNIT_CODES[unit].encode('ascii'), 'big'),
                DisplayName=ua.LocalizedText(unit), Description=ua.LocalizedText(unit),
            )
            await node.add_property(
                ua.NodeId(f'{key}.EngineeringUnits', namespace), ua.QualifiedName('EngineeringUnits', 0),
                ua.Variant(eu, ua.VariantType.ExtensionObject), datatype=ua.ObjectIds.EUInformation,
            )
            self.nodes[key] = node
        self.server = server
        await self.publish(row)
        try:
            await server.start()
        except Exception:
            self.server = None
            raise
        self.port = server.bserver.port  # port 0 lets tests request an available loopback port

    async def stop(self) -> None:
        if self.server is not None:
            await self.server.stop()
            self.server = None
            self.nodes.clear()

    async def write(self, key: str, value: float, source_time: datetime, *,
                    status: int = ua.StatusCodes.Good, server_time: datetime | None = None) -> None:
        sample = ua.DataValue(
            ua.Variant(float(value), ua.VariantType.Double),
            ua.StatusCode(status), SourceTimestamp=source_time,
            ServerTimestamp=server_time if server_time is not None else datetime.now(timezone.utc),
        )
        await self.server.write_attribute_value(self.nodes[key].nodeid, sample)

    async def publish(self, row: dict, *, level2_status: int = ua.StatusCodes.Good) -> None:
        timestamp = datetime.now(timezone.utc)
        for key in self.nodes:
            await self.write(key, row[key], timestamp,
                             status=level2_status if key == 'level2' else ua.StatusCodes.Good)


def simulation_rows(*, duration: float = 90.0, fault: str = 'sensor_bias', fault_at: float = 30.0,
                    seed: int = 1) -> list[dict]:
    model = CoupledTankModel()
    return model.simulate(model.validate(dict(duration=duration, step=MODEL_STEP, fault=fault,
                                              start=fault_at, seed=seed)))


async def run(args: argparse.Namespace) -> None:
    rows = simulation_rows(duration=args.cycle_length, fault=args.fault, fault_at=args.fault_at, seed=args.seed)
    server = TankServer(args.port)
    await server.start(rows[0])
    print(f'L5 coupled tanks available at {server.endpoint}', flush=True)
    interrupted = False
    try:
        while True:
            for row in rows:
                t = row['t']
                if not interrupted and args.interrupt_at is not None and t >= args.interrupt_at:
                    interrupted = True
                    print(f'Simulating a {args.interrupt_for:g} s connection interruption', flush=True)
                    await server.stop()
                    await asyncio.sleep(args.interrupt_for)
                    await server.start(row)
                    print(f'L5 coupled tanks available again at {server.endpoint}', flush=True)
                bad = args.bad_quality_at is not None and args.bad_quality_at <= t < args.bad_quality_at + args.bad_quality_for
                await server.publish(row, level2_status=ua.StatusCodes.BadNoCommunication if bad else ua.StatusCodes.Good)
                await asyncio.sleep(args.interval)
    finally:
        await server.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=4840)
    parser.add_argument('--interval', type=float, default=MODEL_STEP, help='Seconds between emitted frames')
    parser.add_argument('--cycle-length', type=float, default=90, help='Simulated seconds before restarting the trace')
    parser.add_argument('--fault', choices=sorted(FAULTS), default='sensor_bias')
    parser.add_argument('--fault-at', type=float, default=30, help='Fault onset in simulated seconds')
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--bad-quality-at', type=float, help='Tank 2 outage onset in simulated seconds')
    parser.add_argument('--bad-quality-for', type=float, default=3, help='Tank 2 outage in simulated seconds')
    parser.add_argument('--interrupt-at', type=float, help='One connection interruption in simulated seconds')
    parser.add_argument('--interrupt-for', type=float, default=5, help='Connection interruption in wall-clock seconds')
    args = parser.parse_args()
    if not 0 <= args.port <= 65535 or not 0.02 <= args.interval <= 10 or not 0.2 <= args.cycle_length <= 600:
        parser.error('Use port 0–65535, interval 0.02–10 s and cycle length 0.2–600 s.')
    for onset in (args.fault_at, args.bad_quality_at, args.interrupt_at):
        if onset is not None and not 0 <= onset <= args.cycle_length:
            parser.error('Each scenario onset must be inside the simulation cycle.')
    if any(not math.isfinite(seconds) or seconds <= 0 for seconds in (args.bad_quality_for, args.interrupt_for)):
        parser.error('Quality outage and interruption durations must be positive and finite.')
    if not 0 <= args.seed <= 2147483647:
        parser.error('Use a seed between 0 and 2147483647.')
    logging.basicConfig(level=logging.WARNING)
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
