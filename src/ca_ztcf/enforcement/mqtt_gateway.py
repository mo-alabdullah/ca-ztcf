"""The CA-ZTCF MQTT Policy Enforcement Point.

An asyncio proxy that sits between an IoT device and Mosquitto:

    device  ->  CA-ZTCF MQTT PEP  ->  Mosquitto  ->  application topics

It is not a broker. It reads enough of each control packet to apply the active
decision, relays the rest verbatim, and consults the trust function whenever a
decision is absent or its lifetime has elapsed. Every enforcement outcome names
the decision that produced it, so enforcement is always traceable to a trust
evaluation.

Mapping from policy action to broker access, using only MQTT 3.1.1 semantics:

============================  ==================================================
ALLOW                         Full configured topic scope.
ALLOW_WITH_RESTRICTIONS       Restricted scope; publishes outside it are dropped,
                              subscriptions outside it are refused with SUBACK
                              0x80.
STEP_UP_AUTHENTICATION        Connection accepted, protected operations held. The
                              PEP publishes a challenge on ``ctl/<id>/challenge``
                              and admits the answer on ``ctl/<id>/response``.
REAUTHENTICATE                CONNECT refused with CONNACK 0x05; an established
                              session is closed. A new authentication is required.
QUARANTINE                    Only the quarantine namespace is reachable.
DENY                          CONNECT refused with CONNACK 0x05; protected
                              operations refused.
============================  ==================================================

MQTT 3.1.1 has no code for "policy denied", so every policy refusal uses CONNACK
``NOT_AUTHORIZED`` and, for a publish, a silent drop. A denied QoS 1 PUBLISH is
still acknowledged so the client does not retry indefinitely; the drop and its
reason are recorded in the audit log, which is where the explanation belongs.
This mirrors what a broker does on an ACL denial and is documented rather than
invented.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ca_ztcf.clock import Clock
from ca_ztcf.collectors.base import AccessDomain
from ca_ztcf.enforcement import mqtt_codec as codec
from ca_ztcf.enforcement.decision_client import DecisionClient, DecisionRequest
from ca_ztcf.enforcement.interface import topic_matches
from ca_ztcf.enforcement.mqtt_stream import CountingWriter, PacketReader
from ca_ztcf.errors import EnforcementError
from ca_ztcf.identity.models import ProofOfPossession
from ca_ztcf.policy.models import Decision, PolicyAction
from ca_ztcf.telemetry.logging import get_logger

logger = get_logger(__name__)

CHALLENGE_TOPIC = "ctl/{device_id}/challenge"
RESPONSE_TOPIC = "ctl/{device_id}/response"
DECISION_TOPIC = "ctl/{device_id}/decision"

HELD_ACTIONS = frozenset({PolicyAction.STEP_UP_AUTHENTICATION})
REFUSING_ACTIONS = frozenset({PolicyAction.DENY, PolicyAction.REAUTHENTICATE})


@dataclass
class SessionStats:
    """Per-connection counters, for the experiment metrics."""

    connection_id: str
    device_id: str = ""
    connected_at: datetime | None = None
    bytes_from_client: int = 0
    bytes_to_client: int = 0
    bytes_to_broker: int = 0
    bytes_from_broker: int = 0
    packets_from_client: int = 0
    packets_to_client: int = 0
    publishes_allowed: int = 0
    publishes_denied: int = 0
    subscriptions_allowed: int = 0
    subscriptions_denied: int = 0
    decisions_requested: int = 0
    step_up_challenges: int = 0
    step_up_successes: int = 0
    step_up_failures: int = 0
    connack_code: int | None = None
    decision_latency_ns: list[int] = field(default_factory=list)
    actions_seen: list[str] = field(default_factory=list)
    close_reason: str = ""

    def snapshot(self) -> dict[str, object]:
        return {
            "connection_id": self.connection_id,
            "device_id": self.device_id,
            "connected_at": self.connected_at.isoformat() if self.connected_at else None,
            "bytes_from_client": self.bytes_from_client,
            "bytes_to_client": self.bytes_to_client,
            "bytes_to_broker": self.bytes_to_broker,
            "bytes_from_broker": self.bytes_from_broker,
            "packets_from_client": self.packets_from_client,
            "packets_to_client": self.packets_to_client,
            "publishes_allowed": self.publishes_allowed,
            "publishes_denied": self.publishes_denied,
            "subscriptions_allowed": self.subscriptions_allowed,
            "subscriptions_denied": self.subscriptions_denied,
            "decisions_requested": self.decisions_requested,
            "step_up_challenges": self.step_up_challenges,
            "step_up_successes": self.step_up_successes,
            "step_up_failures": self.step_up_failures,
            "connack_code": self.connack_code,
            "decision_latency_ns": list(self.decision_latency_ns),
            "actions_seen": list(self.actions_seen),
            "close_reason": self.close_reason,
        }


@dataclass
class GatewayConfig:
    """Deployment parameters of the enforcement point."""

    listen_host: str = "0.0.0.0"  # noqa: S104 - container binds all interfaces by design
    listen_port: int = 1884
    broker_host: str = "127.0.0.1"
    broker_port: int = 1883
    default_domain: AccessDomain = AccessDomain.NR
    strategy: str | None = None
    connect_timeout_s: float = 10.0
    broker_connect_timeout_s: float = 10.0


def parse_proof(device_id: str, password: bytes | None) -> ProofOfPossession | None:
    """Read a proof-of-possession from the CONNECT password field.

    Wire format is ``<nonce>.<signature>``, both base64url. The MQTT password
    field is the natural carrier: it is per-connection, it is never logged, and it
    is never relayed upstream.
    """
    if not password:
        return None
    try:
        text = password.decode("ascii")
    except UnicodeDecodeError:
        return None
    nonce, separator, signature = text.partition(".")
    if not separator or not nonce or not signature:
        return None
    return ProofOfPossession(device_id=device_id, nonce=nonce, signature=signature)


def scope_permits(decision: Decision, topic: str) -> tuple[bool, str]:
    """Evaluate a topic against a decision's scope. Deny wins; default is deny."""
    for pattern in decision.scope.deny:
        if topic_matches(pattern, topic):
            return False, f"DENIED_BY_SCOPE:{decision.scope.name}:{pattern}"
    for pattern in decision.scope.allow:
        if topic_matches(pattern, topic):
            return True, f"ALLOWED_BY_SCOPE:{decision.scope.name}"
    return False, f"NOT_IN_SCOPE:{decision.scope.name}"


class MqttEnforcementGateway:
    """Serves the MQTT enforcement point."""

    def __init__(
        self,
        config: GatewayConfig,
        decisions: DecisionClient,
        clock: Clock,
        *,
        metrics: object | None = None,
        audit_sink: object | None = None,
    ) -> None:
        self._config = config
        self._decisions = decisions
        self._clock = clock
        self._metrics = metrics
        self._audit = audit_sink
        self._server: asyncio.AbstractServer | None = None
        self._sessions: dict[str, SessionStats] = {}
        self._completed: list[dict[str, object]] = []

    # -- lifecycle -------------------------------------------------------

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_client, self._config.listen_host, self._config.listen_port
        )
        logger.info(
            "mqtt enforcement point listening",
            extra={
                "listen": f"{self._config.listen_host}:{self._config.listen_port}",
                "broker": f"{self._config.broker_host}:{self._config.broker_port}",
            },
        )

    async def serve_forever(self) -> None:
        if self._server is None:
            await self.start()
        assert self._server is not None
        async with self._server:
            await self._server.serve_forever()

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            with contextlib.suppress(Exception):
                await self._server.wait_closed()
            self._server = None
        await self._decisions.close()

    @property
    def port(self) -> int:
        """The port actually bound, which differs from the configured one when 0."""
        sockets = getattr(self._server, "sockets", None) if self._server else None
        if not sockets:
            return self._config.listen_port
        return int(sockets[0].getsockname()[1])

    @property
    def completed_sessions(self) -> list[dict[str, object]]:
        return list(self._completed)

    def drain_sessions(self) -> list[dict[str, object]]:
        drained = self._completed
        self._completed = []
        return drained

    # -- connection handling ---------------------------------------------

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        connection_id = f"con-{uuid.uuid4().hex[:12]}"
        stats = SessionStats(connection_id=connection_id)
        client_reader = PacketReader(reader)
        client_writer = CountingWriter(writer)
        broker_writer: CountingWriter | None = None
        pump: asyncio.Task[None] | None = None

        try:
            first = await asyncio.wait_for(
                client_reader.read_packet(), timeout=self._config.connect_timeout_s
            )
            if first is None:
                stats.close_reason = "CLOSED_BEFORE_CONNECT"
                return
            if first.packet_type is not codec.PacketType.CONNECT:
                stats.close_reason = "FIRST_PACKET_NOT_CONNECT"
                await client_writer.write(
                    codec.build_connack(codec.ConnackReturnCode.NOT_AUTHORIZED)
                )
                return

            connect = codec.decode_connect(first)
            device_id = connect.username or connect.client_id
            stats.device_id = device_id
            stats.connected_at = self._clock.now()

            peer_address = client_writer.transport_peer or "0.0.0.0"  # noqa: S104
            proof = parse_proof(device_id, connect.password)

            decision = await self._decide(
                stats,
                device_id=device_id,
                peer_address=peer_address,
                session_identity=connect.client_id,
                proof=proof,
                resource=None,
            )

            if decision.action in REFUSING_ACTIONS:
                stats.connack_code = int(codec.ConnackReturnCode.NOT_AUTHORIZED)
                stats.close_reason = f"CONNECT_REFUSED:{decision.action.value}"
                await client_writer.write(
                    codec.build_connack(codec.ConnackReturnCode.NOT_AUTHORIZED)
                )
                return

            # Accepted: open the upstream connection and relay a CONNECT that
            # carries no credential material.
            try:
                broker_reader_raw, broker_writer_raw = await asyncio.wait_for(
                    asyncio.open_connection(self._config.broker_host, self._config.broker_port),
                    timeout=self._config.broker_connect_timeout_s,
                )
            except (TimeoutError, OSError) as exc:
                stats.connack_code = int(codec.ConnackReturnCode.SERVER_UNAVAILABLE)
                stats.close_reason = f"BROKER_UNREACHABLE:{exc}"
                await client_writer.write(
                    codec.build_connack(codec.ConnackReturnCode.SERVER_UNAVAILABLE)
                )
                return

            broker_reader = PacketReader(broker_reader_raw)
            broker_writer = CountingWriter(broker_writer_raw)

            upstream_connect = codec.build_connect(
                connect.client_id,
                username=device_id,
                password=None,
                keep_alive=connect.keep_alive,
                clean_session=connect.clean_session,
            )
            await broker_writer.write(upstream_connect)

            connack = await broker_reader.read_packet()
            if connack is None or connack.packet_type is not codec.PacketType.CONNACK:
                stats.close_reason = "BROKER_DID_NOT_ACK"
                await client_writer.write(
                    codec.build_connack(codec.ConnackReturnCode.SERVER_UNAVAILABLE)
                )
                return
            stats.connack_code = connack.payload[1] if len(connack.payload) > 1 else None
            await client_writer.write(connack.raw)

            self._sessions[connection_id] = stats
            pump = asyncio.create_task(
                self._pump_broker_to_client(broker_reader, client_writer, stats)
            )

            if decision.action in HELD_ACTIONS:
                await self._send_challenge(client_writer, stats, device_id)
            await self._announce_decision(client_writer, stats, decision, peer_address)

            await self._client_loop(
                client_reader, client_writer, broker_writer, stats, decision, peer_address
            )

        except asyncio.IncompleteReadError:
            stats.close_reason = stats.close_reason or "CLIENT_STREAM_TRUNCATED"
        except codec.MqttProtocolError as exc:
            stats.close_reason = f"PROTOCOL_ERROR:{exc}"
        except TimeoutError:
            stats.close_reason = "CONNECT_TIMEOUT"
        except (ConnectionError, OSError) as exc:
            stats.close_reason = f"TRANSPORT_ERROR:{exc}"
        except EnforcementError as exc:
            stats.close_reason = f"ENFORCEMENT_ERROR:{exc}"
            with contextlib.suppress(Exception):
                await client_writer.write(
                    codec.build_connack(codec.ConnackReturnCode.SERVER_UNAVAILABLE)
                )
        finally:
            if pump is not None:
                pump.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await pump
            stats.bytes_from_client = client_reader.bytes_read
            stats.packets_from_client = client_reader.packets_read
            stats.bytes_to_client = client_writer.bytes_written
            stats.packets_to_client = client_writer.packets_written
            if broker_writer is not None:
                stats.bytes_to_broker = broker_writer.bytes_written
                broker_writer.close()
                await broker_writer.wait_closed()
            client_writer.close()
            await client_writer.wait_closed()
            self._sessions.pop(connection_id, None)
            self._completed.append(stats.snapshot())

    # -- decision plumbing -----------------------------------------------

    async def _decide(
        self,
        stats: SessionStats,
        *,
        device_id: str,
        peer_address: str,
        session_identity: str | None,
        proof: ProofOfPossession | None,
        resource: str | None,
    ) -> Decision:
        started = time.perf_counter_ns()
        result = await self._decisions.decide(
            DecisionRequest(
                device_id=device_id,
                peer_address=peer_address,
                domain=self._config.default_domain,
                session_identity=session_identity,
                proof=proof,
                resource=resource,
                strategy=self._config.strategy,
            )
        )
        elapsed = time.perf_counter_ns() - started
        stats.decisions_requested += 1
        stats.decision_latency_ns.append(elapsed)
        stats.actions_seen.append(result.decision.action.value)
        return result.decision

    def _decision_expired(self, decision: Decision) -> bool:
        if decision.ttl_ms <= 0:
            return True
        return self._clock.now() > decision.created_at + timedelta(milliseconds=decision.ttl_ms)

    # -- relaying ---------------------------------------------------------

    async def _pump_broker_to_client(
        self, broker_reader: PacketReader, client_writer: CountingWriter, stats: SessionStats
    ) -> None:
        """Relay broker output to the client verbatim."""
        try:
            while True:
                packet = await broker_reader.read_packet()
                if packet is None:
                    return
                stats.bytes_from_broker = broker_reader.bytes_read
                await client_writer.write(packet.raw)
        except (asyncio.CancelledError, ConnectionError, OSError, codec.MqttProtocolError):
            return

    async def _client_loop(
        self,
        client_reader: PacketReader,
        client_writer: CountingWriter,
        broker_writer: CountingWriter,
        stats: SessionStats,
        decision: Decision,
        peer_address: str,
    ) -> None:
        device_id = stats.device_id
        response_topic = RESPONSE_TOPIC.format(device_id=device_id)

        while True:
            packet = await client_reader.read_packet()
            if packet is None:
                stats.close_reason = stats.close_reason or "CLIENT_CLOSED"
                return

            if packet.packet_type is codec.PacketType.DISCONNECT:
                stats.close_reason = "CLIENT_DISCONNECT"
                await broker_writer.write(packet.raw)
                return

            if packet.packet_type is codec.PacketType.PINGREQ:
                # Keep-alive is not a protected operation and is never held.
                await broker_writer.write(packet.raw)
                continue

            if packet.packet_type is codec.PacketType.PUBLISH:
                publish = codec.decode_publish(packet)

                if publish.topic == response_topic:
                    decision = await self._handle_step_up_response(
                        client_writer, stats, publish, peer_address, decision
                    )
                    if publish.qos == 1 and publish.packet_id is not None:
                        await client_writer.write(codec.build_puback(publish.packet_id))
                    if decision.action in REFUSING_ACTIONS:
                        stats.close_reason = f"SESSION_TERMINATED:{decision.action.value}"
                        return
                    continue

                decision = await self._refresh_if_needed(
                    stats, decision, device_id, peer_address, publish.topic
                )
                if decision.action in REFUSING_ACTIONS:
                    stats.close_reason = f"SESSION_TERMINATED:{decision.action.value}"
                    return

                permitted, reason = self._authorise(decision, publish.topic)
                if permitted:
                    stats.publishes_allowed += 1
                    await broker_writer.write(packet.raw)
                else:
                    stats.publishes_denied += 1
                    self._record_denial(stats, decision, "PUBLISH", publish.topic, reason)
                    # MQTT 3.1.1 has no negative acknowledgement for PUBLISH. The
                    # packet is dropped; a QoS 1 publish is still acknowledged so
                    # the client does not retry forever.
                    if publish.qos == 1 and publish.packet_id is not None:
                        await client_writer.write(codec.build_puback(publish.packet_id))
                continue

            if packet.packet_type is codec.PacketType.SUBSCRIBE:
                subscribe = codec.decode_subscribe(packet)
                decision = await self._refresh_if_needed(
                    stats, decision, device_id, peer_address, subscribe.subscriptions[0][0]
                )
                if decision.action in REFUSING_ACTIONS:
                    stats.close_reason = f"SESSION_TERMINATED:{decision.action.value}"
                    return

                granted: list[tuple[str, int]] = []
                codes: list[int] = []
                for topic_filter, requested_qos in subscribe.subscriptions:
                    permitted, reason = self._authorise(decision, topic_filter)
                    if permitted:
                        granted.append((topic_filter, requested_qos))
                        codes.append(requested_qos)
                        stats.subscriptions_allowed += 1
                    else:
                        codes.append(codec.SUBACK_FAILURE)
                        stats.subscriptions_denied += 1
                        self._record_denial(stats, decision, "SUBSCRIBE", topic_filter, reason)

                if granted:
                    # Forward only the permitted filters, so the broker never
                    # establishes a subscription policy has refused.
                    body = subscribe.packet_id.to_bytes(2, "big")
                    for topic_filter, requested_qos in granted:
                        body += codec.encode_string(topic_filter) + bytes([requested_qos])
                    await broker_writer.write(
                        codec.build_packet(codec.PacketType.SUBSCRIBE, 0x02, body)
                    )
                    if len(granted) != len(subscribe.subscriptions):
                        # A partial grant means the broker's SUBACK would not match
                        # the client's request, so the PEP answers instead.
                        await client_writer.write(codec.build_suback(subscribe.packet_id, codes))
                else:
                    await client_writer.write(codec.build_suback(subscribe.packet_id, codes))
                continue

            if packet.packet_type in {
                codec.PacketType.PUBACK,
                codec.PacketType.UNSUBSCRIBE,
                codec.PacketType.PUBREC,
                codec.PacketType.PUBREL,
                codec.PacketType.PUBCOMP,
            }:
                await broker_writer.write(packet.raw)
                continue

            stats.close_reason = f"UNSUPPORTED_PACKET:{packet.packet_type.name}"
            return

    async def _refresh_if_needed(
        self,
        stats: SessionStats,
        decision: Decision,
        device_id: str,
        peer_address: str,
        resource: str,
    ) -> Decision:
        """Re-consult the trust function when the decision's lifetime has elapsed."""
        if not self._decision_expired(decision):
            return decision
        return await self._decide(
            stats,
            device_id=device_id,
            peer_address=peer_address,
            session_identity=None,
            proof=None,
            resource=resource,
        )

    def _authorise(self, decision: Decision, topic: str) -> tuple[bool, str]:
        if decision.action in REFUSING_ACTIONS:
            return False, f"ACTION_{decision.action.value}"
        return scope_permits(decision, topic)

    # -- step-up ----------------------------------------------------------

    async def _send_challenge(
        self, client_writer: CountingWriter, stats: SessionStats, device_id: str
    ) -> None:
        try:
            nonce, expires_at = await self._decisions.issue_nonce(device_id)
        except EnforcementError:
            # An unregistered device cannot be challenged; it was already denied.
            return
        body = json.dumps(
            {"nonce": nonce, "expires_at": expires_at.isoformat(), "algorithm": "ed25519"}
        ).encode("utf-8")
        await client_writer.write(
            codec.build_publish(CHALLENGE_TOPIC.format(device_id=device_id), body)
        )
        stats.step_up_challenges += 1

    async def _announce_decision(
        self,
        client_writer: CountingWriter,
        stats: SessionStats,
        decision: Decision,
        peer_address: str | None = None,
    ) -> None:
        """Tell the device what was decided about it.

        ``observed_peer_address`` is the address this enforcement point actually
        saw on the socket. It is the address an access-domain collector must have
        a binding for, so surfacing it lets a device or an experiment runner see
        which address its evidence has to match instead of guessing. It is the
        device's own address; nothing about another party is disclosed.
        """
        body = json.dumps(
            {
                "decision_id": decision.decision_id,
                "action": decision.action.value,
                "trust_state": decision.trust_state.value,
                "scope": decision.scope.name,
                "ttl_ms": decision.ttl_ms,
                "reason_codes": list(decision.reason_codes),
                "observed_peer_address": peer_address,
            }
        ).encode("utf-8")
        await client_writer.write(
            codec.build_publish(DECISION_TOPIC.format(device_id=stats.device_id), body)
        )

    async def _handle_step_up_response(
        self,
        client_writer: CountingWriter,
        stats: SessionStats,
        publish: codec.PublishPacket,
        peer_address: str,
        decision: Decision,
    ) -> Decision:
        """Verify a step-up answer and re-evaluate. The response is never relayed."""
        try:
            body = json.loads(publish.payload.decode("utf-8"))
            proof = ProofOfPossession(
                device_id=stats.device_id,
                nonce=str(body["nonce"]),
                signature=str(body["signature"]),
            )
        except (ValueError, KeyError, UnicodeDecodeError):
            stats.step_up_failures += 1
            return decision

        refreshed = await self._decide(
            stats,
            device_id=stats.device_id,
            peer_address=peer_address,
            session_identity=None,
            proof=proof,
            resource=None,
        )
        if refreshed.action in HELD_ACTIONS or refreshed.action in REFUSING_ACTIONS:
            stats.step_up_failures += 1
        else:
            stats.step_up_successes += 1
        await self._announce_decision(client_writer, stats, refreshed, peer_address)
        return refreshed

    # -- audit ------------------------------------------------------------

    def _record_denial(
        self,
        stats: SessionStats,
        decision: Decision,
        operation: str,
        resource: str,
        reason: str,
    ) -> None:
        logger.info(
            "mqtt operation refused",
            extra={
                "connection_id": stats.connection_id,
                "device_id": stats.device_id,
                "operation": operation,
                "resource": resource,
                "reason": reason,
                "decision_id": decision.decision_id,
                "action": decision.action.value,
            },
        )
        writer = getattr(self._audit, "write", None)
        if callable(writer):
            writer(
                {
                    "record_type": "enforcement",
                    "enforcement_point": "mqtt",
                    "recorded_at": self._clock.now().isoformat(),
                    "connection_id": stats.connection_id,
                    "device_id": stats.device_id,
                    "operation": operation,
                    "resource": resource,
                    "permitted": False,
                    "reason": reason,
                    "decision_id": decision.decision_id,
                    "action": decision.action.value,
                    "trust_state": decision.trust_state.value,
                    "scope": decision.scope.name,
                    "config_hash": decision.config_hash,
                }
            )


__all__ = [
    "CHALLENGE_TOPIC",
    "DECISION_TOPIC",
    "RESPONSE_TOPIC",
    "GatewayConfig",
    "MqttEnforcementGateway",
    "SessionStats",
    "parse_proof",
    "scope_permits",
]
