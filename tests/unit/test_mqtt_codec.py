"""MQTT 3.1.1 codec."""

from __future__ import annotations

import pytest

from ca_ztcf.enforcement import mqtt_codec as codec


@pytest.mark.parametrize(
    ("value", "encoded"),
    [
        (0, b"\x00"),
        (127, b"\x7f"),
        (128, b"\x80\x01"),
        (16383, b"\xff\x7f"),
        (16384, b"\x80\x80\x01"),
        (codec.MAX_REMAINING_LENGTH, b"\xff\xff\xff\x7f"),
    ],
)
def test_remaining_length_round_trip(value: int, encoded: bytes) -> None:
    assert codec.encode_remaining_length(value) == encoded
    assert codec.decode_remaining_length(encoded) == (value, len(encoded))


def test_remaining_length_rejects_out_of_range() -> None:
    with pytest.raises(codec.MqttProtocolError):
        codec.encode_remaining_length(codec.MAX_REMAINING_LENGTH + 1)
    with pytest.raises(codec.MqttProtocolError):
        codec.encode_remaining_length(-1)


def test_truncated_remaining_length_is_rejected() -> None:
    with pytest.raises(codec.MqttProtocolError):
        codec.decode_remaining_length(b"\x80")


def _packet(raw: bytes) -> codec.Packet:
    remaining, consumed = codec.decode_remaining_length(raw, 1)
    return codec.Packet(
        packet_type=codec.PacketType(raw[0] >> 4),
        flags=raw[0] & 0x0F,
        payload=raw[1 + consumed : 1 + consumed + remaining],
        raw=raw,
    )


def test_connect_round_trip_carries_credentials() -> None:
    raw = codec.build_connect("client-1", username="dev-1", password=b"nonce.sig")
    connect = codec.decode_connect(_packet(raw))
    assert connect.protocol_name == "MQTT"
    assert connect.protocol_level == 4
    assert connect.client_id == "client-1"
    assert connect.username == "dev-1"
    assert connect.password == b"nonce.sig"
    assert connect.clean_session is True


def test_connect_without_credentials() -> None:
    connect = codec.decode_connect(_packet(codec.build_connect("c")))
    assert connect.username is None
    assert connect.password is None
    assert connect.has_password is False


def test_publish_qos0_round_trip() -> None:
    publish = codec.decode_publish(_packet(codec.build_publish("dev/a/t", b"body")))
    assert publish.topic == "dev/a/t"
    assert publish.payload == b"body"
    assert publish.qos == 0
    assert publish.packet_id is None


def test_publish_qos1_carries_packet_id() -> None:
    raw = codec.build_publish("dev/a/t", b"x", qos=1, packet_id=77)
    publish = codec.decode_publish(_packet(raw))
    assert publish.qos == 1
    assert publish.packet_id == 77


def test_publish_qos1_requires_packet_id() -> None:
    with pytest.raises(codec.MqttProtocolError):
        codec.build_publish("t", b"x", qos=1)


def test_subscribe_round_trip() -> None:
    body = (12).to_bytes(2, "big")
    for topic, qos in [("dev/a/#", 0), ("cmd/a/x", 1)]:
        body += codec.encode_string(topic) + bytes([qos])
    subscribe = codec.decode_subscribe(
        _packet(codec.build_packet(codec.PacketType.SUBSCRIBE, 0x02, body))
    )
    assert subscribe.packet_id == 12
    assert subscribe.subscriptions == [("dev/a/#", 0), ("cmd/a/x", 1)]


def test_subscribe_without_topics_is_rejected() -> None:
    body = (1).to_bytes(2, "big")
    with pytest.raises(codec.MqttProtocolError):
        codec.decode_subscribe(_packet(codec.build_packet(codec.PacketType.SUBSCRIBE, 0x02, body)))


def test_connack_encodes_return_code() -> None:
    raw = codec.build_connack(codec.ConnackReturnCode.NOT_AUTHORIZED)
    assert raw[0] >> 4 == codec.PacketType.CONNACK
    assert raw[-1] == 5


def test_suback_failure_code_is_the_protocol_value() -> None:
    raw = codec.build_suback(5, [0, codec.SUBACK_FAILURE])
    assert codec.SUBACK_FAILURE == 0x80
    assert list(raw[-2:]) == [0, 0x80]


def test_puback_carries_packet_id() -> None:
    assert codec.decode_packet_id(_packet(codec.build_puback(4242))) == 4242


def test_oversized_string_is_rejected() -> None:
    with pytest.raises(codec.MqttProtocolError):
        codec.encode_string("x" * 70000)


def test_non_utf8_field_is_rejected() -> None:
    body = (2).to_bytes(2, "big") + b"\xff\xfe"
    with pytest.raises(codec.MqttProtocolError):
        codec.decode_publish(_packet(codec.build_packet(codec.PacketType.PUBLISH, 0, body)))
