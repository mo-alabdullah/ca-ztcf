"""Collector foundations: access domains, source modes, bindings and the base class.

A collector's contract is a *schema*, not a data source. The same
:class:`AccessBinding` shape is produced by a synthetic development fixture, by a
replayed capture, and by a live testbed; only ``source_mode`` distinguishes them.
That is what allows batches A-E to proceed before a Tier-2 capture exists.

Privacy rule enforced here: each collector hashes its own access-domain
identifiers with its own per-collector salt. Digests from different collectors are
therefore not comparable even in principle, and the framework never compares them.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ca_ztcf.clock import Clock


class AccessDomain(StrEnum):
    """The two independently secured access domains studied in this work."""

    NR = "NR"
    """5G access."""

    WLAN = "WLAN"
    """WiFi / wireless local-area access."""


class SourceMode(StrEnum):
    """Provenance of an observation. Recorded on every evidence item.

    ``SYNTHETIC_FIXTURE`` data is a development fixture and must never be
    presented as a measurement. ``LIVE_TESTBED`` data comes from a real Open5GS /
    UERANSIM or hostapd deployment. ``REPLAY_CAPTURE`` is a recorded live capture
    replayed deterministically.
    """

    SYNTHETIC_FIXTURE = "synthetic_fixture"
    REPLAY_CAPTURE = "replay_capture"
    LIVE_TESTBED = "live_testbed"
    SERVICE_DOMAIN = "service_domain"
    """Computed by CA-ZTCF itself rather than observed in an access domain."""


class AccessBinding(BaseModel):
    """An access domain's assertion about one network address.

    Semantics, deliberately narrow: *"at this time, address ``peer_address`` is
    bound to an authenticated session in my domain, with these properties."*
    The binding says nothing about which service-domain device is using it; that
    attribution is made only in the service domain, by proof-of-possession.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    binding_id: str
    domain: AccessDomain
    peer_address: str
    device_ref: str | None = Field(
        default=None,
        description=(
            "Service-domain device_id this binding has been attributed to, or None "
            "when unattributed. Set only by the service domain after successful "
            "proof-of-possession. Never supplied by an access domain."
        ),
    )
    source: str
    source_mode: SourceMode
    first_seen: datetime
    last_seen: datetime
    expires_at: datetime | None = None
    attributes: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Domain-specific properties, already scrubbed. Raw subscriber "
            "identifiers are hashed by the collector before they reach this field."
        ),
    )

    def age_seconds(self, now: datetime) -> float:
        return max(0.0, (now - self.last_seen).total_seconds())

    def is_expired(self, now: datetime) -> bool:
        return self.expires_at is not None and now > self.expires_at


class BindingStore:
    """Current access bindings, keyed by peer address.

    Also records attribution conflicts: when a second device claims an address
    already attributed to another, that is a direct contradiction of identity
    evidence (predicate C5) and is what drives threat T3 to UNTRUSTED.
    """

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._by_address: dict[str, AccessBinding] = {}

    def upsert(self, binding: AccessBinding) -> AccessBinding:
        """Insert or refresh a binding, preserving any existing attribution."""
        existing = self._by_address.get(binding.peer_address)
        if existing is not None and existing.domain == binding.domain:
            merged = binding.model_copy(
                update={
                    "binding_id": existing.binding_id,
                    "first_seen": existing.first_seen,
                    "device_ref": binding.device_ref or existing.device_ref,
                }
            )
        else:
            merged = binding
        self._by_address[merged.peer_address] = merged
        return merged

    def get(self, peer_address: str) -> AccessBinding | None:
        binding = self._by_address.get(peer_address)
        if binding is None:
            return None
        if binding.is_expired(self._clock.now()):
            return None
        return binding

    def claim(self, peer_address: str, device_id: str) -> tuple[AccessBinding | None, bool]:
        """Attribute an address to a device.

        Returns ``(binding, consistent)``. ``consistent`` is False when the address
        is already attributed to a different device; in that case the existing
        attribution is left untouched so the conflict remains observable.
        """
        binding = self.get(peer_address)
        if binding is None:
            return None, True
        if binding.device_ref is None:
            claimed = binding.model_copy(update={"device_ref": device_id})
            self._by_address[peer_address] = claimed
            return claimed, True
        if binding.device_ref == device_id:
            return binding, True
        return binding, False

    def release(self, peer_address: str) -> None:
        self._by_address.pop(peer_address, None)

    def all_bindings(self) -> list[AccessBinding]:
        return [self._by_address[key] for key in sorted(self._by_address)]

    def clear(self) -> None:
        self._by_address.clear()


class BaseCollector(ABC):
    """Common behaviour for access-context collectors."""

    domain: AccessDomain
    source: str

    def __init__(
        self,
        clock: Clock,
        store: BindingStore,
        *,
        hash_length: int = 16,
        salt: bytes | None = None,
    ) -> None:
        self._clock = clock
        self._store = store
        self._hash_length = hash_length
        # Per-collector salt. Never shared with another collector, which is what
        # makes cross-domain identifier comparison impossible by construction.
        self._salt = salt if salt is not None else secrets.token_bytes(32)
        self._available = True

    @property
    def available(self) -> bool:
        """Whether the collector is currently able to observe its domain.

        Unavailability contributes to DEGRADED, never to SUSPICIOUS: a collector
        outage is missing evidence, not contradictory evidence.
        """
        return self._available

    def set_available(self, available: bool) -> None:
        self._available = available

    def hash_identifier(self, raw: str) -> str:
        """Salted digest of an access-domain identifier, truncated for storage."""
        digest = hashlib.sha256(self._salt + raw.encode("utf-8")).hexdigest()
        return digest[: self._hash_length]

    def _new_binding_id(self) -> str:
        return f"bnd-{uuid.uuid4().hex[:16]}"

    def _expiry(self, observed_at: datetime, lifetime_s: int | None) -> datetime | None:
        if lifetime_s is None:
            return None
        return observed_at + timedelta(seconds=lifetime_s)

    @abstractmethod
    def ingest(self, event: BaseModel) -> AccessBinding | None:
        """Normalise one domain event into an access binding, or ``None`` on release."""
