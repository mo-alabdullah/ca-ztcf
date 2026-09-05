"""Models for the access-independent, service-domain device identity.

The CA-ZTCF ``device_id`` is a service-domain identifier bound to a device-held
key pair. It is deliberately **not** a MAC address, SUPI, PEI, IMEI or EAP
identity: those are access-domain identifiers and are treated as access evidence
only. See ``docs/adr/ADR-0004-service-domain-device-identity.md``.

The registry never stores private key material.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DeviceStatus(StrEnum):
    """Administrative status of a registered device.

    ``ACTIVE`` is the only status that satisfies predicate C1 (IDENTITY_VALID).
    ``SUSPENDED`` and ``REVOKED`` both yield UNTRUSTED, and differ only in whether
    an administrator is expected to restore the device.
    """

    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


PoPAlgorithm = Literal["ed25519"]
"""Signature algorithms accepted for proof-of-possession.

Ed25519 only, for the prototype: a single modern, misuse-resistant primitive from
the ``cryptography`` library, with no algorithm negotiation and therefore no
downgrade surface. No proprietary cryptography is used anywhere in this project.
"""


class DeviceIdentity(BaseModel):
    """A registered service-domain device identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    device_id: str = Field(min_length=1, max_length=128)
    public_key_pem: str = Field(description="PEM-encoded Ed25519 public key. Never a private key.")
    public_key_fingerprint: str = Field(
        min_length=16, description="SHA-256 hex digest of the DER SubjectPublicKeyInfo."
    )
    status: DeviceStatus = DeviceStatus.ACTIVE
    created_at: datetime
    updated_at: datetime
    labels: dict[str, str] = Field(
        default_factory=dict,
        description="Research metadata, for example scenario or device class. Never secrets.",
    )
    notes: str = ""

    @field_validator("device_id")
    @classmethod
    def _device_id_charset(cls, value: str) -> str:
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
        if not set(value) <= allowed:
            raise ValueError("device_id may contain only letters, digits, '-', '_' and '.'")
        return value

    @field_validator("public_key_pem")
    @classmethod
    def _reject_private_key(cls, value: str) -> str:
        if "PRIVATE KEY" in value.upper():
            raise ValueError("private key material must never be supplied to the registry")
        return value

    @property
    def is_enabled(self) -> bool:
        """Whether the administrative status permits the device to be trusted at all."""
        return self.status is DeviceStatus.ACTIVE


class ProofOfPossession(BaseModel):
    """A device's signature over a server-issued nonce."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    device_id: str
    nonce: str = Field(description="Base64url server-issued challenge, single use.")
    signature: str = Field(description="Base64url signature over the raw nonce bytes.")
    algorithm: PoPAlgorithm = "ed25519"


class PoPResult(BaseModel):
    """Outcome of verifying a proof-of-possession.

    ``valid`` is never inferred from the absence of an error: it is set only when
    a signature has actually been verified against a registered public key.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    device_id: str
    valid: bool
    reason: str
    verified_at: datetime | None = None
    algorithm: PoPAlgorithm | None = None
