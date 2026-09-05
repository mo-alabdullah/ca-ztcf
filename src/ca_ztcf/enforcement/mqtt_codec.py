"""Minimal MQTT 3.1.1 codec.

Only the control packets the experiments need are implemented: CONNECT, CONNACK,
PUBLISH, PUBACK, SUBSCRIBE, SUBACK, UNSUBSCRIBE, UNSUBACK, PINGREQ, PINGRESP and
DISCONNECT. This is deliberately **not** a broker: Mosquitto is the broker. This
codec exists so that the Policy Enforcement Point can read enough of each packet
to make and apply an access decision, and relay the rest untouched.

Everything unrecognised is relayed verbatim rather than reinterpreted, so the
proxy cannot silently change application semantics.

Reference: MQTT Version 3.1.1, OASIS Standard, 29 October 2014.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

MAX_REMAINING_LENGTH = 268_435_455
"""Largest remaining length representable in four varint bytes (MQTT 3.1.1 2.2.3)."""


class PacketType(IntEnum):
    """MQTT control packet types (MQTT 3.1.1 table 2.1)."""

    CONNECT = 1
    CONNACK = 2
    PUBLISH = 3
    PUBACK = 4
    PUBREC = 5
    PUBREL = 6
    PUBCOMP = 7
    SUBSCRIBE = 8
    SUBACK = 9
    UNSUBSCRIBE = 10
    UNSUBACK = 11
    PINGREQ = 12
    PINGRESP = 13
    DISCONNECT = 14


class ConnackReturnCode(IntEnum):
    """CONNACK return codes (MQTT 3.1.1 table 3.1).

    The protocol offers no code for "policy denied", so ``NOT_AUTHORIZED`` is used
    for every policy refusal. The precise reason is recorded in the audit log,
    which is where an explanation belongs.
    """

    ACCEPTED = 0
    UNACCEPTABLE_PROTOCOL_VERSION = 1
    IDENTIFIER_REJECTED = 2
    SERVER_UNAVAILABLE = 3
    BAD_USERNAME_OR_PASSWORD = 4
    NOT_AUTHORIZED = 5


SUBACK_FAILURE = 0x80
"""SUBACK return code meaning the subscription was refused (MQTT 3.1.1 3.9.3)."""


class MqttProtocolError(ValueError):
    """A packet could not be decoded as MQTT 3.1.1."""


# ---------------------------------------------------------------------------
# Primitive encoding helpers
# ---------------------------------------------------------------------------


def encode_remaining_length(value: int) -> bytes:
    """Encode a remaining length as a variable byte integer."""
    if value < 0 or value > MAX_REMAINING_LENGTH:
        raise MqttProtocolError(f"remaining length out of range: {value}")
    out = bytearray()
    while True:
        byte = value % 128
        value //= 128
        if value > 0:
            byte |= 0x80
        out.append(byte)
        if value == 0:
            break
    return bytes(out)


def decode_remaining_length(data: bytes, offset: int = 0) -> tuple[int, int]:
    """Decode a variable byte integer; returns ``(value, bytes_consumed)``."""
    multiplier = 1
    value = 0
    consumed = 0
    while True:
        if offset + consumed >= len(data):
            raise MqttProtocolError("truncated remaining length")
        byte = data[offset + consumed]
        consumed += 1
        value += (byte & 0x7F) * multiplier
        if not byte & 0x80:
            return value, consumed
        multiplier *= 128
        if multiplier > 128**3:
            raise MqttProtocolError("malformed remaining length")


def encode_string(value: str) -> bytes:
    raw = value.encode("utf-8")
    if len(raw) > 0xFFFF:
        raise MqttProtocolError("UTF-8 string exceeds 65535 bytes")
    return len(raw).to_bytes(2, "big") + raw


def _read_bytes(payload: bytes, offset: int) -> tuple[bytes, int]:
    if offset + 2 > len(payload):
        raise MqttProtocolError("truncated length prefix")
    length = int.from_bytes(payload[offset : offset + 2], "big")
    start = offset + 2
    end = start + length
    if end > len(payload):
        raise MqttProtocolError("truncated length-prefixed field")
    return payload[start:end], end


def _read_string(payload: bytes, offset: int) -> tuple[str, int]:
    raw, next_offset = _read_bytes(payload, offset)
    try:
        return raw.decode("utf-8"), next_offset
    except UnicodeDecodeError as exc:
        raise MqttProtocolError("field is not valid UTF-8") from exc


# ---------------------------------------------------------------------------
# Packet model
# ---------------------------------------------------------------------------


@dataclass
class Packet:
    """A decoded control packet, retaining its exact wire bytes.

    ``raw`` is what gets relayed. Keeping it means the proxy forwards precisely
    what the client sent, byte for byte, unless it deliberately rewrites the
    packet.
    """

    packet_type: PacketType
    flags: int
    payload: bytes
    raw: bytes

    @property
    def qos(self) -> int:
        """PUBLISH QoS level, from the fixed header flags."""
        return (self.flags & 0x06) >> 1

    @property
    def dup(self) -> bool:
        return bool(self.flags & 0x08)

    @property
    def retain(self) -> bool:
        return bool(self.flags & 0x01)


@dataclass
class ConnectPacket:
    """The fields of a CONNECT the enforcement point needs.

    ``password`` carries the device's proof-of-possession. It is read once, used
    for verification, and never stored, logged or relayed upstream.
    """

    protocol_name: str
    protocol_level: int
    connect_flags: int
    keep_alive: int
    client_id: str
    will_topic: str | None = None
    will_payload: bytes | None = None
    username: str | None = None
    password: bytes | None = None

    @property
    def clean_session(self) -> bool:
        return bool(self.connect_flags & 0x02)

    @property
    def has_username(self) -> bool:
        return bool(self.connect_flags & 0x80)

    @property
    def has_password(self) -> bool:
        return bool(self.connect_flags & 0x40)


@dataclass
class PublishPacket:
    topic: str
    packet_id: int | None
    payload: bytes
    qos: int
    retain: bool = False
    dup: bool = False


@dataclass
class SubscribePacket:
    packet_id: int
    subscriptions: list[tuple[str, int]] = field(default_factory=list)


@dataclass
class UnsubscribePacket:
    packet_id: int
    topics: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------


def decode_connect(packet: Packet) -> ConnectPacket:
    payload = packet.payload
    protocol_name, offset = _read_string(payload, 0)
    if offset + 4 > len(payload):
        raise MqttProtocolError("truncated CONNECT variable header")
    protocol_level = payload[offset]
    connect_flags = payload[offset + 1]
    keep_alive = int.from_bytes(payload[offset + 2 : offset + 4], "big")
    offset += 4

    client_id, offset = _read_string(payload, offset)

    will_topic: str | None = None
    will_payload: bytes | None = None
    if connect_flags & 0x04:
        will_topic, offset = _read_string(payload, offset)
        will_payload, offset = _read_bytes(payload, offset)

    username: str | None = None
    if connect_flags & 0x80:
        username, offset = _read_string(payload, offset)

    password: bytes | None = None
    if connect_flags & 0x40:
        password, offset = _read_bytes(payload, offset)

    return ConnectPacket(
        protocol_name=protocol_name,
        protocol_level=protocol_level,
        connect_flags=connect_flags,
        keep_alive=keep_alive,
        client_id=client_id,
        will_topic=will_topic,
        will_payload=will_payload,
        username=username,
        password=password,
    )


def decode_publish(packet: Packet) -> PublishPacket:
    topic, offset = _read_string(packet.payload, 0)
    packet_id: int | None = None
    if packet.qos > 0:
        if offset + 2 > len(packet.payload):
            raise MqttProtocolError("truncated PUBLISH packet identifier")
        packet_id = int.from_bytes(packet.payload[offset : offset + 2], "big")
        offset += 2
    return PublishPacket(
        topic=topic,
        packet_id=packet_id,
        payload=packet.payload[offset:],
        qos=packet.qos,
        retain=packet.retain,
        dup=packet.dup,
    )


def decode_subscribe(packet: Packet) -> SubscribePacket:
    if len(packet.payload) < 2:
        raise MqttProtocolError("truncated SUBSCRIBE")
    packet_id = int.from_bytes(packet.payload[0:2], "big")
    offset = 2
    subscriptions: list[tuple[str, int]] = []
    while offset < len(packet.payload):
        topic, offset = _read_string(packet.payload, offset)
        if offset >= len(packet.payload):
            raise MqttProtocolError("SUBSCRIBE entry missing requested QoS")
        subscriptions.append((topic, packet.payload[offset] & 0x03))
        offset += 1
    if not subscriptions:
        raise MqttProtocolError("SUBSCRIBE must carry at least one topic filter")
    return SubscribePacket(packet_id=packet_id, subscriptions=subscriptions)


def decode_unsubscribe(packet: Packet) -> UnsubscribePacket:
    if len(packet.payload) < 2:
        raise MqttProtocolError("truncated UNSUBSCRIBE")
    packet_id = int.from_bytes(packet.payload[0:2], "big")
    offset = 2
    topics: list[str] = []
    while offset < len(packet.payload):
        topic, offset = _read_string(packet.payload, offset)
        topics.append(topic)
    return UnsubscribePacket(packet_id=packet_id, topics=topics)


def decode_packet_id(packet: Packet) -> int:
    """Read the packet identifier of an acknowledgement packet."""
    if len(packet.payload) < 2:
        raise MqttProtocolError(f"{packet.packet_type.name} is missing a packet identifier")
    return int.from_bytes(packet.payload[0:2], "big")


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------


def build_packet(packet_type: PacketType, flags: int, payload: bytes) -> bytes:
    header = bytes([(int(packet_type) << 4) | (flags & 0x0F)])
    return header + encode_remaining_length(len(payload)) + payload


def build_connack(return_code: ConnackReturnCode, *, session_present: bool = False) -> bytes:
    flags = 0x01 if session_present and return_code is ConnackReturnCode.ACCEPTED else 0x00
    return build_packet(PacketType.CONNACK, 0, bytes([flags, int(return_code)]))


def build_puback(packet_id: int) -> bytes:
    return build_packet(PacketType.PUBACK, 0, packet_id.to_bytes(2, "big"))


def build_suback(packet_id: int, return_codes: list[int]) -> bytes:
    return build_packet(PacketType.SUBACK, 0, packet_id.to_bytes(2, "big") + bytes(return_codes))


def build_unsuback(packet_id: int) -> bytes:
    return build_packet(PacketType.UNSUBACK, 0, packet_id.to_bytes(2, "big"))


def build_pingresp() -> bytes:
    return build_packet(PacketType.PINGRESP, 0, b"")


def build_disconnect() -> bytes:
    return build_packet(PacketType.DISCONNECT, 0, b"")


def build_publish(
    topic: str, payload: bytes, *, qos: int = 0, packet_id: int | None = None, retain: bool = False
) -> bytes:
    if qos > 0 and packet_id is None:
        raise MqttProtocolError("a PUBLISH with QoS > 0 requires a packet identifier")
    body = encode_string(topic)
    if qos > 0 and packet_id is not None:
        body += packet_id.to_bytes(2, "big")
    body += payload
    flags = ((qos & 0x03) << 1) | (0x01 if retain else 0x00)
    return build_packet(PacketType.PUBLISH, flags, body)


def build_connect(
    client_id: str,
    *,
    username: str | None = None,
    password: bytes | None = None,
    keep_alive: int = 60,
    clean_session: bool = True,
) -> bytes:
    """Build a CONNECT. Used by the device agent and to rewrite a proxied CONNECT."""
    flags = 0x02 if clean_session else 0x00
    if username is not None:
        flags |= 0x80
    if password is not None:
        flags |= 0x40

    body = encode_string("MQTT") + bytes([4, flags]) + keep_alive.to_bytes(2, "big")
    body += encode_string(client_id)
    if username is not None:
        body += encode_string(username)
    if password is not None:
        if len(password) > 0xFFFF:
            raise MqttProtocolError("password exceeds 65535 bytes")
        body += len(password).to_bytes(2, "big") + password
    return build_packet(PacketType.CONNECT, 0, body)


__all__ = [
    "MAX_REMAINING_LENGTH",
    "SUBACK_FAILURE",
    "ConnackReturnCode",
    "ConnectPacket",
    "MqttProtocolError",
    "Packet",
    "PacketType",
    "PublishPacket",
    "SubscribePacket",
    "UnsubscribePacket",
    "build_connack",
    "build_connect",
    "build_disconnect",
    "build_packet",
    "build_pingresp",
    "build_puback",
    "build_publish",
    "build_suback",
    "build_unsuback",
    "decode_connect",
    "decode_packet_id",
    "decode_publish",
    "decode_remaining_length",
    "decode_subscribe",
    "decode_unsubscribe",
    "encode_remaining_length",
    "encode_string",
]
