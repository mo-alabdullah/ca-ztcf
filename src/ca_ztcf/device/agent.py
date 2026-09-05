"""Research IoT device agent.

Connects to the service through the CA-ZTCF MQTT enforcement point, proves
possession of its service-domain key, publishes telemetry, subscribes to the
topics policy permits, answers step-up challenges, and switches its access-domain
context on request.

The agent binds its outgoing socket to a chosen local source address. Switching
that address is what makes an access-domain transition observable at the
enforcement point as a genuinely different peer address, rather than something
the device merely asserts.

Every application event is timestamped: UTC wall clock for the audit trail, and
``time.perf_counter_ns`` for durations.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ca_ztcf.collectors.base import AccessDomain
from ca_ztcf.device.keys import DeviceKeyPair
from ca_ztcf.enforcement import mqtt_codec as codec
from ca_ztcf.enforcement.mqtt_stream import CountingWriter, PacketReader
from ca_ztcf.errors import CaZtcfError
from ca_ztcf.telemetry.logging import get_logger

logger = get_logger(__name__)


class DeviceAgentError(CaZtcfError):
    """The agent could not complete an operation."""

    code = "DEVICE_AGENT_ERROR"


@dataclass
class AgentEvent:
    """One timestamped application event."""

    event_id: str
    device_id: str
    kind: str
    at: datetime
    monotonic_ns: int
    detail: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "device_id": self.device_id,
            "kind": self.kind,
            "at": self.at.isoformat(),
            "monotonic_ns": self.monotonic_ns,
            **self.detail,
        }


@dataclass
class AgentConfig:
    """Where the agent connects and how it identifies itself."""

    device_id: str
    gateway_host: str = "127.0.0.1"
    gateway_port: int = 1884
    client_id: str | None = None
    keep_alive: int = 60
    connect_timeout_s: float = 10.0
    source_address: str | None = None
    """Local address to bind the outgoing socket to; the access-domain context."""
    domain: AccessDomain = AccessDomain.NR


class DeviceAgent:
    """An MQTT client that speaks only what the experiments need."""

    def __init__(
        self,
        config: AgentConfig,
        keys: DeviceKeyPair,
        *,
        nonce_provider: object | None = None,
    ) -> None:
        self.config = config
        self.keys = keys
        self._nonce_provider = nonce_provider
        self._reader: PacketReader | None = None
        self._writer: CountingWriter | None = None
        self._packet_id = 0
        self.events: list[AgentEvent] = []
        self.connack_code: int | None = None
        self.last_decision: dict[str, object] | None = None
        self.challenges_answered = 0
        self.subscription_results: dict[str, int] = {}

    # -- event log --------------------------------------------------------

    def record(self, kind: str, **detail: object) -> AgentEvent:
        event = AgentEvent(
            event_id=f"evt-{uuid.uuid4().hex[:12]}",
            device_id=self.config.device_id,
            kind=kind,
            at=datetime.now(UTC),
            monotonic_ns=time.perf_counter_ns(),
            detail=detail,
        )
        self.events.append(event)
        return event

    def drain_events(self) -> list[dict[str, object]]:
        drained = [event.to_dict() for event in self.events]
        self.events = []
        return drained

    # -- connection -------------------------------------------------------

    @property
    def client_id(self) -> str:
        return self.config.client_id or self.config.device_id

    def _next_packet_id(self) -> int:
        self._packet_id = (self._packet_id % 65535) + 1
        return self._packet_id

    async def connect(self, nonce: str | None = None) -> int:
        """Connect through the enforcement point. Returns the CONNACK return code."""
        started = time.perf_counter_ns()

        local_addr = (self.config.source_address, 0) if self.config.source_address else None
        try:
            raw_reader, raw_writer = await asyncio.wait_for(
                asyncio.open_connection(
                    self.config.gateway_host, self.config.gateway_port, local_addr=local_addr
                ),
                timeout=self.config.connect_timeout_s,
            )
        except (TimeoutError, OSError) as exc:
            self.record("connect_failed", error=str(exc))
            raise DeviceAgentError(f"cannot reach the enforcement point: {exc}") from exc

        self._reader = PacketReader(raw_reader)
        self._writer = CountingWriter(raw_writer)

        credential = self.keys.credential(nonce) if nonce else None
        await self._writer.write(
            codec.build_connect(
                self.client_id,
                username=self.config.device_id,
                password=credential,
                keep_alive=self.config.keep_alive,
            )
        )

        packet = await asyncio.wait_for(
            self._reader.read_packet(), timeout=self.config.connect_timeout_s
        )
        if packet is None or packet.packet_type is not codec.PacketType.CONNACK:
            self.record("connack_missing")
            raise DeviceAgentError("no CONNACK received")

        self.connack_code = packet.payload[1] if len(packet.payload) > 1 else None
        self.record(
            "connected",
            connack_code=self.connack_code,
            duration_ns=time.perf_counter_ns() - started,
            source_address=self.config.source_address,
            domain=self.config.domain.value,
            proof_presented=credential is not None,
        )
        return int(self.connack_code or 0)

    async def disconnect(self) -> None:
        if self._writer is not None:
            with contextlib.suppress(Exception):
                await self._writer.write(codec.build_disconnect())
            self._writer.close()
            await self._writer.wait_closed()
        self._reader = None
        self._writer = None
        self.record("disconnected")

    @property
    def connected(self) -> bool:
        return self._writer is not None and self.connack_code == 0

    # -- operations -------------------------------------------------------

    async def publish(self, topic: str, payload: dict[str, object], *, qos: int = 0) -> int | None:
        """Publish telemetry. Returns the packet identifier for QoS 1."""
        if self._writer is None:
            raise DeviceAgentError("publish attempted while not connected")
        packet_id = self._next_packet_id() if qos > 0 else None
        started = time.perf_counter_ns()
        await self._writer.write(
            codec.build_publish(
                topic,
                json.dumps(payload, separators=(",", ":")).encode("utf-8"),
                qos=qos,
                packet_id=packet_id,
            )
        )
        self.record(
            "published",
            topic=topic,
            qos=qos,
            packet_id=packet_id,
            duration_ns=time.perf_counter_ns() - started,
        )
        return packet_id

    async def subscribe(
        self, topics: list[str], *, qos: int = 0, timeout_s: float = 5.0
    ) -> dict[str, int]:
        """Subscribe and return each filter's SUBACK return code.

        ``0x80`` means the enforcement point refused that filter, which is the
        protocol's own way of saying so.
        """
        if self._writer is None or self._reader is None:
            raise DeviceAgentError("subscribe attempted while not connected")
        packet_id = self._next_packet_id()
        body = packet_id.to_bytes(2, "big")
        for topic in topics:
            body += codec.encode_string(topic) + bytes([qos])
        await self._writer.write(codec.build_packet(codec.PacketType.SUBSCRIBE, 0x02, body))

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            packet = await asyncio.wait_for(self._reader.read_packet(), timeout=timeout_s)
            if packet is None:
                raise DeviceAgentError("stream closed while awaiting SUBACK")
            if packet.packet_type is codec.PacketType.SUBACK:
                codes = list(packet.payload[2:])
                results = dict(zip(topics, codes, strict=False))
                self.subscription_results.update(results)
                self.record("subscribed", topics=topics, return_codes=codes)
                return results
            await self._dispatch(packet)
        raise DeviceAgentError("timed out awaiting SUBACK")

    async def ping(self, *, timeout_s: float = 5.0) -> bool:
        if self._writer is None or self._reader is None:
            raise DeviceAgentError("ping attempted while not connected")
        await self._writer.write(codec.build_packet(codec.PacketType.PINGREQ, 0, b""))
        packet = await asyncio.wait_for(self._reader.read_packet(), timeout=timeout_s)
        if packet is None:
            return False
        if packet.packet_type is codec.PacketType.PINGRESP:
            self.record("ping_ok")
            return True
        await self._dispatch(packet)
        return False

    async def pump(self, *, duration_s: float = 0.5) -> None:
        """Process inbound packets for a while, answering any challenge that arrives."""
        if self._reader is None:
            return
        deadline = time.monotonic() + duration_s
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            try:
                packet = await asyncio.wait_for(self._reader.read_packet(), timeout=remaining)
            except (TimeoutError, asyncio.IncompleteReadError):
                return
            if packet is None:
                return
            await self._dispatch(packet)

    async def _dispatch(self, packet: codec.Packet) -> None:
        if packet.packet_type is not codec.PacketType.PUBLISH:
            return
        publish = codec.decode_publish(packet)
        if publish.qos == 1 and publish.packet_id is not None and self._writer is not None:
            await self._writer.write(codec.build_puback(publish.packet_id))

        if publish.topic.endswith("/challenge"):
            await self._answer_challenge(publish.payload)
        elif publish.topic.endswith("/decision"):
            with contextlib.suppress(ValueError, UnicodeDecodeError):
                self.last_decision = json.loads(publish.payload.decode("utf-8"))
                self.record("decision_received", **dict(self.last_decision or {}))
        else:
            self.record("message_received", topic=publish.topic, bytes=len(publish.payload))

    async def _answer_challenge(self, payload: bytes) -> None:
        """Sign the challenge nonce and publish the answer. The key never leaves."""
        try:
            body = json.loads(payload.decode("utf-8"))
            nonce = str(body["nonce"])
        except (ValueError, KeyError, UnicodeDecodeError):
            self.record("challenge_malformed")
            return
        if self._writer is None:
            return
        started = time.perf_counter_ns()
        answer = json.dumps(
            {"nonce": nonce, "signature": self.keys.sign_nonce(nonce), "algorithm": "ed25519"}
        ).encode("utf-8")
        await self._writer.write(
            codec.build_publish(f"ctl/{self.config.device_id}/response", answer)
        )
        self.challenges_answered += 1
        self.record("challenge_answered", duration_ns=time.perf_counter_ns() - started)

    # -- access-domain context -------------------------------------------

    def switch_access_context(self, domain: AccessDomain, source_address: str | None) -> AgentEvent:
        """Point the agent at a different access domain and source address.

        The caller reconnects afterwards; the new connection then presents a
        different peer address to the enforcement point.
        """
        previous_domain = self.config.domain
        previous_address = self.config.source_address
        self.config.domain = domain
        self.config.source_address = source_address
        return self.record(
            "access_context_switched",
            from_domain=previous_domain.value,
            to_domain=domain.value,
            from_address=previous_address,
            to_address=source_address,
        )

    @property
    def bytes_sent(self) -> int:
        return self._writer.bytes_written if self._writer else 0

    @property
    def bytes_received(self) -> int:
        return self._reader.bytes_read if self._reader else 0


__all__ = ["AgentConfig", "AgentEvent", "DeviceAgent", "DeviceAgentError"]
