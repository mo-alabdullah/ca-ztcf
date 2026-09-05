"""Framing MQTT control packets off an asyncio stream."""

from __future__ import annotations

import asyncio
import contextlib

from ca_ztcf.enforcement.mqtt_codec import (
    MAX_REMAINING_LENGTH,
    MqttProtocolError,
    Packet,
    PacketType,
)


class PacketReader:
    """Reads whole MQTT control packets from a stream, counting bytes.

    The byte counter is what makes communication overhead measurable per
    connection without instrumenting the application.
    """

    def __init__(self, reader: asyncio.StreamReader) -> None:
        self._reader = reader
        self.bytes_read = 0
        self.packets_read = 0

    async def read_packet(self) -> Packet | None:
        """Read one packet, or ``None`` at end of stream."""
        first = await self._reader.read(1)
        if not first:
            return None
        raw = bytearray(first)

        multiplier = 1
        remaining = 0
        for _ in range(4):
            chunk = await self._reader.read(1)
            if not chunk:
                raise MqttProtocolError("stream ended inside the remaining length")
            raw += chunk
            byte = chunk[0]
            remaining += (byte & 0x7F) * multiplier
            if not byte & 0x80:
                break
            multiplier *= 128
        else:
            raise MqttProtocolError("malformed remaining length")

        if remaining > MAX_REMAINING_LENGTH:
            raise MqttProtocolError(f"remaining length too large: {remaining}")

        body = await self._reader.readexactly(remaining) if remaining else b""
        raw += body

        header = first[0]
        try:
            packet_type = PacketType(header >> 4)
        except ValueError as exc:
            raise MqttProtocolError(f"unknown packet type {header >> 4}") from exc

        self.bytes_read += len(raw)
        self.packets_read += 1
        return Packet(
            packet_type=packet_type,
            flags=header & 0x0F,
            payload=bytes(body),
            raw=bytes(raw),
        )


class CountingWriter:
    """Wraps a stream writer so that written bytes and packets are counted."""

    def __init__(self, writer: asyncio.StreamWriter) -> None:
        self._writer = writer
        self.bytes_written = 0
        self.packets_written = 0

    async def write(self, data: bytes) -> None:
        self._writer.write(data)
        self.bytes_written += len(data)
        self.packets_written += 1
        await self._writer.drain()

    def close(self) -> None:
        if not self._writer.is_closing():
            self._writer.close()

    async def wait_closed(self) -> None:
        # The peer may already be gone; closing is best effort.
        with contextlib.suppress(ConnectionError, OSError):
            await self._writer.wait_closed()

    @property
    def transport_peer(self) -> str | None:
        peer = self._writer.get_extra_info("peername")
        if isinstance(peer, tuple) and peer:
            return str(peer[0])
        return None


__all__ = ["CountingWriter", "PacketReader"]
