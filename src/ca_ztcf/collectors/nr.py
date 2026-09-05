"""5G access-context collector.

Consumes normalised 5G core events and produces :class:`AccessBinding` records.

The collector is an *event consumer*. Placing the trust function as a consumer of
operator-exposed data, rather than inside a network function, is compatible with
the architectural freedom described in 3GPP TR 33.794, which locates the security
evaluation and monitoring function in the operator's domain, external to the 3GPP
network, and states that its application logic is outside 3GPP scope. No 3GPP
conformance or endorsement is claimed, and no 3GPP procedure is implemented here.

Until a Tier-2 Open5GS/UERANSIM capture exists, events come from a synthetic
fixture provider and carry ``source_mode = synthetic_fixture``. Such events are
development fixtures and are never reported as measured 5G results.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from ca_ztcf.collectors.base import AccessBinding, AccessDomain, BaseCollector, SourceMode
from ca_ztcf.errors import CollectorError


class NrEventType(StrEnum):
    """5G core events the collector understands."""

    SESSION_ESTABLISHED = "SESSION_ESTABLISHED"
    SESSION_REFRESHED = "SESSION_REFRESHED"
    SESSION_RELEASED = "SESSION_RELEASED"


class NrAccessEvent(BaseModel):
    """A normalised 5G core event.

    ``subscriber_ref`` is whatever intra-domain subscriber reference the operator
    exposes. It is hashed with the collector's own salt on ingestion and the raw
    value is neither stored nor logged. It is never compared with any WLAN
    identifier.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: NrEventType
    peer_address: str
    observed_at: datetime
    source_mode: SourceMode = SourceMode.SYNTHETIC_FIXTURE
    subscriber_ref: str | None = None
    pdu_session_id: str | None = None
    dnn: str | None = None
    gnb_id: str | None = None
    rat_type: str = "NR"
    registration_state: str = "REGISTERED"
    pdu_session_active: bool = True
    binding_lifetime_s: int | None = 120


class NRCollector(BaseCollector):
    """Normalises 5G core events into access bindings."""

    domain = AccessDomain.NR
    source = "collector.nr"

    def ingest(self, event: BaseModel) -> AccessBinding | None:
        if not isinstance(event, NrAccessEvent):
            raise CollectorError(f"NRCollector cannot ingest {type(event).__name__}")

        if event.event_type is NrEventType.SESSION_RELEASED:
            self._store.release(event.peer_address)
            return None

        attributes: dict[str, str] = {
            "rat_type": event.rat_type,
            "registration_state": event.registration_state,
            "pdu_session_active": "true" if event.pdu_session_active else "false",
        }
        if event.subscriber_ref is not None:
            # Salted, truncated, intra-domain only. Never comparable with a WLAN digest.
            attributes["subscriber_ref_hash"] = self.hash_identifier(event.subscriber_ref)
        if event.pdu_session_id is not None:
            attributes["pdu_session_id"] = event.pdu_session_id
        if event.dnn is not None:
            attributes["dnn"] = event.dnn
        if event.gnb_id is not None:
            attributes["gnb_id"] = event.gnb_id

        binding = AccessBinding(
            binding_id=self._new_binding_id(),
            domain=self.domain,
            peer_address=event.peer_address,
            source=self.source,
            source_mode=event.source_mode,
            first_seen=event.observed_at,
            last_seen=event.observed_at,
            expires_at=self._expiry(event.observed_at, event.binding_lifetime_s),
            attributes=attributes,
        )
        return self._store.upsert(binding)

    def ingest_many(self, events: list[NrAccessEvent]) -> list[AccessBinding]:
        produced: list[AccessBinding] = []
        for event in events:
            binding = self.ingest(event)
            if binding is not None:
                produced.append(binding)
        return produced


class SyntheticFixtureProvider:
    """Deterministic 5G event source for development and unit tests.

    Every event it produces is stamped ``source_mode = synthetic_fixture``. This
    provider exists so that batches A-E do not depend on a Tier-2 capture; it will
    be replaced or validated by ``source_mode = live_testbed`` events in the
    Tier-2 batch.
    """

    source_mode = SourceMode.SYNTHETIC_FIXTURE

    def __init__(self, events: list[NrAccessEvent] | None = None) -> None:
        self._events: list[NrAccessEvent] = list(events or [])
        self._cursor = 0

    def add(self, event: NrAccessEvent) -> None:
        if event.source_mode is not SourceMode.SYNTHETIC_FIXTURE:
            raise CollectorError("SyntheticFixtureProvider only accepts synthetic_fixture events")
        self._events.append(event)

    def extend(self, events: list[NrAccessEvent]) -> None:
        for event in events:
            self.add(event)

    def next_event(self) -> NrAccessEvent | None:
        if self._cursor >= len(self._events):
            return None
        event = self._events[self._cursor]
        self._cursor += 1
        return event

    def drain(self) -> list[NrAccessEvent]:
        remaining = self._events[self._cursor :]
        self._cursor = len(self._events)
        return remaining

    def reset(self) -> None:
        self._cursor = 0

    @property
    def pending(self) -> int:
        return max(0, len(self._events) - self._cursor)


def session_established(
    peer_address: str,
    observed_at: datetime,
    *,
    subscriber_ref: str = "fixture-subscriber-001",
    gnb_id: str = "gnb-001",
    dnn: str = "internet",
    pdu_session_id: str = "1",
    binding_lifetime_s: int | None = 120,
) -> NrAccessEvent:
    """Convenience builder for a well-formed synthetic 5G session-established event."""
    return NrAccessEvent(
        event_type=NrEventType.SESSION_ESTABLISHED,
        peer_address=peer_address,
        observed_at=observed_at,
        source_mode=SourceMode.SYNTHETIC_FIXTURE,
        subscriber_ref=subscriber_ref,
        pdu_session_id=pdu_session_id,
        dnn=dnn,
        gnb_id=gnb_id,
        binding_lifetime_s=binding_lifetime_s,
    )


NR_ATTRIBUTE_KEYS: tuple[str, ...] = (
    "rat_type",
    "registration_state",
    "pdu_session_active",
    "subscriber_ref_hash",
    "pdu_session_id",
    "dnn",
    "gnb_id",
)
"""Attribute keys the 5G collector may emit. Used by posture evaluation and docs."""


def parse_bool_attribute(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"true", "1", "yes"}


__all__ = [
    "NR_ATTRIBUTE_KEYS",
    "NRCollector",
    "NrAccessEvent",
    "NrEventType",
    "SyntheticFixtureProvider",
    "parse_bool_attribute",
    "session_established",
]
