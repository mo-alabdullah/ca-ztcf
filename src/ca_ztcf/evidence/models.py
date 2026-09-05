"""The Dual-Context Evidence Model.

One versioned record per evaluation. The model deliberately keeps 5G-side and
WLAN-side observations distinct and adds transition evidence explicitly, so that
assurance obtained in one domain is never silently reused in the other.

Every item carries its source, source mode, observation time, optional expiry and
a validation status. An item that cannot be produced or emulated reproducibly does
not belong in this model.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ca_ztcf.collectors.base import SourceMode
from ca_ztcf.version import SCHEMA_VERSION

EvidenceValue = bool | int | float | str | None


class EvidenceCategory(StrEnum):
    """The six categories of the Dual-Context Evidence Model."""

    DEVICE_IDENTITY = "DEVICE_IDENTITY"
    ACCESS_BINDING = "ACCESS_BINDING"
    ACCESS_CONTEXT = "ACCESS_CONTEXT"
    SECURITY_EVENTS = "SECURITY_EVENTS"
    DOMAIN_POSTURE = "DOMAIN_POSTURE"
    EVIDENCE_METADATA = "EVIDENCE_METADATA"


class ValidationStatus(StrEnum):
    """Whether an item was actually validated, and if not, why not.

    ``MISSING`` and ``STALE`` describe absent or aged evidence and contribute to
    DEGRADED. ``INVALID`` describes evidence that failed validation and may
    contribute to UNTRUSTED or SUSPICIOUS. ``UNVERIFIED`` means the item was
    recorded but no validation applies to it.
    """

    VALID = "VALID"
    INVALID = "INVALID"
    STALE = "STALE"
    MISSING = "MISSING"
    UNVERIFIED = "UNVERIFIED"


class EvidenceItem(BaseModel):
    """A single, individually attributable piece of evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    category: EvidenceCategory
    value: EvidenceValue
    source: str
    source_mode: SourceMode
    observed_at: datetime
    expires_at: datetime | None = None
    validation: ValidationStatus = ValidationStatus.UNVERIFIED
    detail: str = ""

    def age_seconds(self, now: datetime) -> float:
        return max(0.0, (now - self.observed_at).total_seconds())

    def is_expired(self, now: datetime) -> bool:
        return self.expires_at is not None and now > self.expires_at

    @property
    def as_bool(self) -> bool:
        """Interpret the value as a boolean; non-boolean values are False."""
        return self.value is True

    @property
    def as_int(self) -> int:
        if isinstance(self.value, bool):
            return int(self.value)
        if isinstance(self.value, int):
            return self.value
        if isinstance(self.value, float):
            return int(self.value)
        return 0


# ---------------------------------------------------------------------------
# Canonical item names. Referenced by predicates, documentation and tests so that
# a rename cannot silently break the traceability from a decision to its evidence.
# ---------------------------------------------------------------------------

# 1. Device identity
IDENTITY_REGISTERED = "identity_registered"
IDENTITY_ENABLED = "identity_enabled"
PROOF_OF_POSSESSION_VALID = "proof_of_possession_valid"
PUBLIC_KEY_FINGERPRINT = "public_key_fingerprint"

# 2. Access binding
BINDING_PRESENT = "binding_present"
BINDING_DOMAIN = "binding_domain"
BINDING_FRESH = "binding_fresh"
BINDING_CONSISTENT = "binding_consistent"

# 3. Access context
CURRENT_DOMAIN = "current_domain"
PREVIOUS_DOMAIN = "previous_domain"
TRANSITION_DETECTED = "transition_detected"
TRANSITION_AGE = "transition_age"
TRANSITION_COUNT_WINDOW = "transition_count_window"

# 4. Security events
AUTHENTICATION_FAILURE_COUNT = "authentication_failure_count"
IDENTITY_MISMATCH = "identity_mismatch"
SESSION_MISMATCH = "session_mismatch"
UNAUTHORIZED_CONTEXT = "unauthorized_context"

# 5. Domain posture
DOMAIN_POSTURE_OK = "domain_posture_ok"
COLLECTOR_AVAILABLE = "collector_available"
EVIDENCE_COMPLETE = "evidence_complete"

# 6. Evidence metadata
ASSEMBLED_AT = "assembled_at"
EVIDENCE_AGE = "evidence_age"
SCHEMA_VERSION_ITEM = "schema_version"
CONFIG_HASH_ITEM = "config_hash"


ITEM_CATEGORIES: dict[str, EvidenceCategory] = {
    IDENTITY_REGISTERED: EvidenceCategory.DEVICE_IDENTITY,
    IDENTITY_ENABLED: EvidenceCategory.DEVICE_IDENTITY,
    PROOF_OF_POSSESSION_VALID: EvidenceCategory.DEVICE_IDENTITY,
    PUBLIC_KEY_FINGERPRINT: EvidenceCategory.DEVICE_IDENTITY,
    BINDING_PRESENT: EvidenceCategory.ACCESS_BINDING,
    BINDING_DOMAIN: EvidenceCategory.ACCESS_BINDING,
    BINDING_FRESH: EvidenceCategory.ACCESS_BINDING,
    BINDING_CONSISTENT: EvidenceCategory.ACCESS_BINDING,
    CURRENT_DOMAIN: EvidenceCategory.ACCESS_CONTEXT,
    PREVIOUS_DOMAIN: EvidenceCategory.ACCESS_CONTEXT,
    TRANSITION_DETECTED: EvidenceCategory.ACCESS_CONTEXT,
    TRANSITION_AGE: EvidenceCategory.ACCESS_CONTEXT,
    TRANSITION_COUNT_WINDOW: EvidenceCategory.ACCESS_CONTEXT,
    AUTHENTICATION_FAILURE_COUNT: EvidenceCategory.SECURITY_EVENTS,
    IDENTITY_MISMATCH: EvidenceCategory.SECURITY_EVENTS,
    SESSION_MISMATCH: EvidenceCategory.SECURITY_EVENTS,
    UNAUTHORIZED_CONTEXT: EvidenceCategory.SECURITY_EVENTS,
    DOMAIN_POSTURE_OK: EvidenceCategory.DOMAIN_POSTURE,
    COLLECTOR_AVAILABLE: EvidenceCategory.DOMAIN_POSTURE,
    EVIDENCE_COMPLETE: EvidenceCategory.DOMAIN_POSTURE,
    ASSEMBLED_AT: EvidenceCategory.EVIDENCE_METADATA,
    EVIDENCE_AGE: EvidenceCategory.EVIDENCE_METADATA,
    SCHEMA_VERSION_ITEM: EvidenceCategory.EVIDENCE_METADATA,
    CONFIG_HASH_ITEM: EvidenceCategory.EVIDENCE_METADATA,
}


class EvidenceRecord(BaseModel):
    """A complete, versioned evidence record for one device at one instant."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = SCHEMA_VERSION
    record_id: str = Field(default_factory=lambda: f"evr-{uuid.uuid4().hex[:16]}")
    device_id: str
    assembled_at: datetime
    config_hash: str
    items: dict[str, EvidenceItem]

    def item(self, name: str) -> EvidenceItem | None:
        return self.items.get(name)

    def value(self, name: str) -> EvidenceValue:
        found = self.items.get(name)
        return found.value if found is not None else None

    def flag(self, name: str) -> bool:
        """Boolean accessor; a missing item is False, never an exception."""
        found = self.items.get(name)
        return found.as_bool if found is not None else False

    def number(self, name: str) -> int:
        found = self.items.get(name)
        return found.as_int if found is not None else 0

    def text(self, name: str) -> str | None:
        found = self.items.get(name)
        if found is None or found.value is None:
            return None
        return str(found.value)

    def by_category(self, category: EvidenceCategory) -> dict[str, EvidenceItem]:
        return {
            name: item for name, item in sorted(self.items.items()) if item.category is category
        }

    def source_modes(self) -> set[SourceMode]:
        """All provenance modes present, so a record's tier is always attributable."""
        return {item.source_mode for item in self.items.values()}

    def contains_synthetic(self) -> bool:
        return SourceMode.SYNTHETIC_FIXTURE in self.source_modes()


__all__ = [
    "ASSEMBLED_AT",
    "AUTHENTICATION_FAILURE_COUNT",
    "BINDING_CONSISTENT",
    "BINDING_DOMAIN",
    "BINDING_FRESH",
    "BINDING_PRESENT",
    "COLLECTOR_AVAILABLE",
    "CONFIG_HASH_ITEM",
    "CURRENT_DOMAIN",
    "DOMAIN_POSTURE_OK",
    "EVIDENCE_AGE",
    "EVIDENCE_COMPLETE",
    "IDENTITY_ENABLED",
    "IDENTITY_MISMATCH",
    "IDENTITY_REGISTERED",
    "ITEM_CATEGORIES",
    "PREVIOUS_DOMAIN",
    "PROOF_OF_POSSESSION_VALID",
    "PUBLIC_KEY_FINGERPRINT",
    "SCHEMA_VERSION_ITEM",
    "SESSION_MISMATCH",
    "TRANSITION_AGE",
    "TRANSITION_COUNT_WINDOW",
    "TRANSITION_DETECTED",
    "UNAUTHORIZED_CONTEXT",
    "EvidenceCategory",
    "EvidenceItem",
    "EvidenceRecord",
    "EvidenceValue",
    "ValidationStatus",
]
