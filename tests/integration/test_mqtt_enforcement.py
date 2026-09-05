"""End-to-end MQTT enforcement.

The device agent talks to the real enforcement gateway over a real socket, and the
gateway relays to a stub broker that speaks just enough MQTT to accept a session.
Mosquitto itself is exercised in the container flow; here the point is that
enforcement decisions actually reach the wire.
"""

from __future__ import annotations

import asyncio
import contextlib

import pytest

from ca_ztcf.collectors.base import AccessDomain
from ca_ztcf.collectors.fixtures import nr_event, wlan_event
from ca_ztcf.device.agent import AgentConfig, DeviceAgent
from ca_ztcf.device.keys import DeviceKeyPair
from ca_ztcf.enforcement import mqtt_codec as codec
from ca_ztcf.enforcement.decision_client import LocalDecisionClient
from ca_ztcf.enforcement.mqtt_gateway import GatewayConfig, MqttEnforcementGateway
from ca_ztcf.enforcement.mqtt_stream import PacketReader
from ca_ztcf.identity.models import DeviceStatus

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class StubBroker:
    """Accepts CONNECT, acknowledges, and records what the gateway forwarded."""

    def __init__(self) -> None:
        self.server: asyncio.AbstractServer | None = None
        self.received: list[codec.Packet] = []
        self.connects: list[codec.ConnectPacket] = []

    async def start(self) -> int:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        return int(self.server.sockets[0].getsockname()[1])

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        packets = PacketReader(reader)
        try:
            while True:
                packet = await packets.read_packet()
                if packet is None:
                    return
                self.received.append(packet)
                if packet.packet_type is codec.PacketType.CONNECT:
                    self.connects.append(codec.decode_connect(packet))
                    writer.write(codec.build_connack(codec.ConnackReturnCode.ACCEPTED))
                    await writer.drain()
                elif packet.packet_type is codec.PacketType.SUBSCRIBE:
                    subscribe = codec.decode_subscribe(packet)
                    writer.write(
                        codec.build_suback(
                            subscribe.packet_id, [q for _, q in subscribe.subscriptions]
                        )
                    )
                    await writer.drain()
                elif packet.packet_type is codec.PacketType.PINGREQ:
                    writer.write(codec.build_pingresp())
                    await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError, codec.MqttProtocolError):
            return
        finally:
            with contextlib.suppress(Exception):
                writer.close()

    async def stop(self) -> None:
        if self.server is not None:
            self.server.close()
            with contextlib.suppress(Exception):
                await self.server.wait_closed()

    def publishes(self) -> list[codec.PublishPacket]:
        return [
            codec.decode_publish(p)
            for p in self.received
            if p.packet_type is codec.PacketType.PUBLISH
        ]


@pytest.fixture
async def broker():
    stub = StubBroker()
    port = await stub.start()
    yield stub, port
    await stub.stop()


LOOPBACK = "127.0.0.1"
"""The address the gateway actually observes.

Access bindings must be registered for the peer address the enforcement point
sees on the socket, not for a notional one. That is the whole point of binding
evidence: the framework correlates the transport peer with an access domain's
assertion about that same address.
"""


@pytest.fixture
async def make_gateway(app_state, broker):
    """Build a gateway for a chosen access domain. Started gateways are cleaned up."""
    _, broker_port = broker
    started: list[MqttEnforcementGateway] = []

    async def _build(domain: AccessDomain = AccessDomain.NR) -> MqttEnforcementGateway:
        gw = MqttEnforcementGateway(
            GatewayConfig(
                listen_host=LOOPBACK,
                listen_port=0,
                broker_host=LOOPBACK,
                broker_port=broker_port,
                default_domain=domain,
            ),
            LocalDecisionClient(app_state),
            app_state.clock,
            audit_sink=app_state.audit,
        )
        await gw.start()
        started.append(gw)
        return gw

    yield _build
    for gw in started:
        await gw.stop()


@pytest.fixture
async def gateway(make_gateway):
    return await make_gateway(AccessDomain.NR)


def bind_nr(app_state, profile, address: str = LOOPBACK) -> None:
    """Register a synthetic 5G binding for the address the gateway will observe."""
    event = nr_event(profile, app_state.clock.now()).model_copy(update={"peer_address": address})
    app_state.nr_collector.ingest(event)


def bind_wlan(app_state, profile, address: str = LOOPBACK, **overrides) -> None:
    """Register a Tier-1 WLAN authentication binding for the observed address."""
    event = wlan_event(profile, app_state.clock.now(), **overrides).model_copy(
        update={"peer_address": address}
    )
    app_state.wlan_collector.ingest(event)


def observe_transition(app_state, profile, address: str = LOOPBACK) -> None:
    """Drive a real NR-to-WLAN transition for the observed address."""
    app_state.transitions.observe(
        profile.device_id, AccessDomain.NR, peer_address=address, at=app_state.clock.now()
    )
    app_state.clock.advance(seconds=2)
    app_state.transitions.observe(
        profile.device_id, AccessDomain.WLAN, peer_address=address, at=app_state.clock.now()
    )


def _agent(device_id: str, keys: DeviceKeyPair, port: int) -> DeviceAgent:
    return DeviceAgent(
        AgentConfig(device_id=device_id, gateway_host="127.0.0.1", gateway_port=port),
        keys,
    )


async def _connect(app_state, gateway, device_id, keys, *, with_proof=True):
    agent = _agent(device_id, keys, gateway.port)
    nonce = None
    if with_proof:
        nonce, _ = app_state.nonces.issue(device_id)
    code = await agent.connect(nonce)
    return agent, code


@pytest.fixture
def enrolled(app_state, profile):
    keys = DeviceKeyPair.generate(profile.device_id)
    app_state.registry.register(profile.device_id, keys.public_key_pem)
    bind_nr(app_state, profile)
    return keys


# --- STABLE -----------------------------------------------------------------


async def test_stable_device_connects_and_publishes(app_state, gateway, broker, profile, enrolled):
    stub, _ = broker
    agent, code = await _connect(app_state, gateway, profile.device_id, enrolled)
    assert code == 0

    await agent.publish(f"dev/{profile.device_id}/telemetry/reading", {"v": 1})
    await asyncio.sleep(0.05)
    await agent.disconnect()

    forwarded = [p.topic for p in stub.publishes()]
    assert f"dev/{profile.device_id}/telemetry/reading" in forwarded


async def test_credentials_are_never_relayed_to_the_broker(
    app_state, gateway, broker, profile, enrolled
):
    stub, _ = broker
    agent, code = await _connect(app_state, gateway, profile.device_id, enrolled)
    assert code == 0
    await agent.disconnect()

    assert stub.connects, "the gateway did not forward a CONNECT"
    upstream = stub.connects[-1]
    assert upstream.password is None, "proof-of-possession leaked to the broker"
    assert upstream.username == profile.device_id


async def test_restricted_topic_violation_is_not_forwarded(
    app_state, make_gateway, broker, profile, enrolled, settings
):
    """A device in TRANSITIONAL may publish telemetry but not reach command topics."""
    stub, _ = broker
    bind_wlan(app_state, profile)
    observe_transition(app_state, profile)
    gateway = await make_gateway(AccessDomain.WLAN)

    agent, code = await _connect(app_state, gateway, profile.device_id, enrolled)
    assert code == 0
    await agent.publish(f"cmd/{profile.device_id}/reboot", {"do": "it"})
    await agent.publish(f"dev/{profile.device_id}/telemetry/reading", {"v": 2})
    await asyncio.sleep(0.05)
    await agent.disconnect()

    forwarded = [p.topic for p in stub.publishes()]
    assert f"cmd/{profile.device_id}/reboot" not in forwarded
    assert f"dev/{profile.device_id}/telemetry/reading" in forwarded


async def test_denied_subscription_returns_suback_failure(
    app_state, make_gateway, profile, enrolled
):
    bind_wlan(app_state, profile)
    observe_transition(app_state, profile)
    gateway = await make_gateway(AccessDomain.WLAN)

    agent, code = await _connect(app_state, gateway, profile.device_id, enrolled)
    assert code == 0
    results = await agent.subscribe([f"cmd/{profile.device_id}/set"])
    await agent.disconnect()
    assert results[f"cmd/{profile.device_id}/set"] == codec.SUBACK_FAILURE


# --- refusals ---------------------------------------------------------------


async def test_unknown_device_connect_is_refused(app_state, gateway, profile):
    keys = DeviceKeyPair.generate("dev-not-enrolled")
    agent = _agent("dev-not-enrolled", keys, gateway.port)
    code = await agent.connect(None)
    assert code == int(codec.ConnackReturnCode.NOT_AUTHORIZED)
    await agent.disconnect()


async def test_untrusted_device_connect_is_refused(app_state, gateway, profile, enrolled):
    app_state.registry.set_status(profile.device_id, DeviceStatus.REVOKED)
    agent, code = await _connect(app_state, gateway, profile.device_id, enrolled)
    assert code == int(codec.ConnackReturnCode.NOT_AUTHORIZED)
    await agent.disconnect()


async def test_session_mismatch_terminates_the_session(app_state, gateway, profile, enrolled):
    """SUSPICIOUS outside a transition yields REAUTHENTICATE, which refuses CONNECT."""
    agent = DeviceAgent(
        AgentConfig(
            device_id=profile.device_id,
            gateway_host="127.0.0.1",
            gateway_port=gateway.port,
            client_id="somebody-elses-session",
        ),
        enrolled,
    )
    nonce, _ = app_state.nonces.issue(profile.device_id)
    code = await agent.connect(nonce)
    assert code == int(codec.ConnackReturnCode.NOT_AUTHORIZED)
    await agent.disconnect()


# --- step-up and quarantine -------------------------------------------------


async def test_step_up_challenge_is_issued_and_answered(app_state, gateway, profile, settings):
    """A DEGRADED device is challenged, answers, and regains access."""
    keys = DeviceKeyPair.generate(profile.device_id)
    app_state.registry.register(profile.device_id, keys.public_key_pem)
    # No access binding at all: evidence is missing, so the device is DEGRADED.
    agent = _agent(profile.device_id, keys, gateway.port)
    code = await agent.connect(None)
    assert code == 0

    await agent.pump(duration_s=0.4)
    assert agent.challenges_answered >= 1, "no step-up challenge reached the device"
    assert agent.last_decision is not None
    assert agent.last_decision["action"] == "STEP_UP_AUTHENTICATION"
    await agent.disconnect()


async def test_quarantine_confines_the_device_to_its_namespace(
    app_state, make_gateway, broker, profile, enrolled, settings
):
    """SUSPICIOUS across a transition quarantines: only q/<device_id>/# is reachable."""
    stub, _ = broker
    # A disallowed key-management suite makes the posture predicate fail, which is
    # contradictory evidence rather than missing evidence: SUSPICIOUS, and across a
    # transition that means QUARANTINE.
    bind_wlan(app_state, profile, akm="OPEN")
    observe_transition(app_state, profile)
    gateway = await make_gateway(AccessDomain.WLAN)

    agent, code = await _connect(app_state, gateway, profile.device_id, enrolled)
    assert code == 0

    await agent.publish(f"dev/{profile.device_id}/telemetry/reading", {"v": 3})
    await agent.publish(f"q/{profile.device_id}/observed", {"v": 4})
    await asyncio.sleep(0.05)
    await agent.disconnect()

    forwarded = [p.topic for p in stub.publishes()]
    assert f"dev/{profile.device_id}/telemetry/reading" not in forwarded
    assert f"q/{profile.device_id}/observed" in forwarded


# --- audit ------------------------------------------------------------------


async def test_audit_contains_the_decision_that_produced_enforcement(
    app_state, gateway, profile, enrolled
):
    agent, code = await _connect(app_state, gateway, profile.device_id, enrolled)
    assert code == 0
    await agent.publish(f"dev/{profile.device_id}/telemetry/reading", {"v": 1})
    await asyncio.sleep(0.05)
    await agent.disconnect()

    contents = app_state.audit.path.read_text(encoding="utf-8")
    assert '"enforcement_point":"mqtt"' in contents.replace(" ", "")
    assert app_state.audit.indexed_decisions >= 1


async def test_no_secret_material_reaches_logs_or_audit(
    app_state, gateway, profile, enrolled, caplog
):
    agent, code = await _connect(app_state, gateway, profile.device_id, enrolled)
    assert code == 0
    await agent.disconnect()

    contents = app_state.audit.path.read_text(encoding="utf-8")
    assert "PRIVATE KEY" not in contents.upper()
    assert enrolled.public_key_pem.strip() not in contents
    for record in caplog.records:
        assert "PRIVATE KEY" not in record.getMessage().upper()


async def test_gateway_records_session_statistics(app_state, gateway, profile, enrolled):
    agent, code = await _connect(app_state, gateway, profile.device_id, enrolled)
    assert code == 0
    await agent.publish(f"dev/{profile.device_id}/telemetry/reading", {"v": 1})
    await agent.publish(f"cmd/{profile.device_id}/x", {"v": 2})
    await asyncio.sleep(0.05)
    await agent.disconnect()
    await asyncio.sleep(0.05)

    sessions = gateway.completed_sessions
    assert sessions, "no session statistics were recorded"
    session = sessions[-1]
    assert session["device_id"] == profile.device_id
    assert session["bytes_from_client"] > 0
    assert session["decisions_requested"] >= 1
    assert session["decision_latency_ns"]
