"""Proof-of-possession: nonce issuance and Ed25519 signature verification.

The device proves control of the private key matching its registered public key
by signing a single-use, time-limited nonce issued by the service domain. This is
the only mechanism by which an access binding is attributed to a device identity,
and it is what makes cross-domain identifier sharing unnecessary.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ca_ztcf.clock import Clock
from ca_ztcf.identity.models import DeviceIdentity, PoPResult, ProofOfPossession


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def fingerprint_public_key_pem(public_key_pem: str) -> str:
    """Return the SHA-256 hex digest of the DER SubjectPublicKeyInfo of a public key."""
    key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
    der = key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(der).hexdigest()


@dataclass(frozen=True)
class _IssuedNonce:
    device_id: str
    issued_at: datetime
    expires_at: datetime


class NonceIssuer:
    """Issues single-use, time-limited challenge nonces.

    A nonce is bound to one device and is consumed on first verification attempt,
    successful or not, so that a captured signature cannot be replayed.
    """

    def __init__(self, clock: Clock, ttl_s: int, *, nbytes: int = 32) -> None:
        self._clock = clock
        self._ttl = timedelta(seconds=ttl_s)
        self._nbytes = nbytes
        self._issued: dict[str, _IssuedNonce] = {}

    def issue(self, device_id: str) -> tuple[str, datetime]:
        """Issue a fresh nonce for ``device_id``; returns the nonce and its expiry."""
        now = self._clock.now()
        nonce = _b64url_encode(secrets.token_bytes(self._nbytes))
        expires_at = now + self._ttl
        self._issued[nonce] = _IssuedNonce(device_id, now, expires_at)
        self._purge(now)
        return nonce, expires_at

    def consume(self, nonce: str, device_id: str) -> tuple[bool, str]:
        """Consume a nonce. Returns ``(accepted, reason_code)``."""
        now = self._clock.now()
        record = self._issued.pop(nonce, None)
        if record is None:
            return False, "NONCE_UNKNOWN_OR_ALREADY_USED"
        if record.device_id != device_id:
            return False, "NONCE_DEVICE_MISMATCH"
        if now > record.expires_at:
            return False, "NONCE_EXPIRED"
        return True, "NONCE_OK"

    def _purge(self, now: datetime) -> None:
        expired = [n for n, rec in self._issued.items() if now > rec.expires_at]
        for nonce in expired:
            del self._issued[nonce]

    @property
    def outstanding(self) -> int:
        return len(self._issued)


class ProofVerifier:
    """Verifies a :class:`ProofOfPossession` against a registered identity."""

    def __init__(self, clock: Clock, nonce_issuer: NonceIssuer) -> None:
        self._clock = clock
        self._nonces = nonce_issuer

    def verify(self, identity: DeviceIdentity, proof: ProofOfPossession) -> PoPResult:
        now = self._clock.now()

        if proof.device_id != identity.device_id:
            return PoPResult(
                device_id=identity.device_id, valid=False, reason="POP_DEVICE_ID_MISMATCH"
            )

        accepted, nonce_reason = self._nonces.consume(proof.nonce, identity.device_id)
        if not accepted:
            return PoPResult(device_id=identity.device_id, valid=False, reason=nonce_reason)

        try:
            public_key = serialization.load_pem_public_key(identity.public_key_pem.encode("utf-8"))
        except (ValueError, TypeError):
            return PoPResult(
                device_id=identity.device_id, valid=False, reason="POP_PUBLIC_KEY_UNREADABLE"
            )

        if not isinstance(public_key, Ed25519PublicKey):
            return PoPResult(
                device_id=identity.device_id, valid=False, reason="POP_UNSUPPORTED_KEY_TYPE"
            )

        try:
            signature = _b64url_decode(proof.signature)
        except (ValueError, TypeError):
            return PoPResult(
                device_id=identity.device_id, valid=False, reason="POP_SIGNATURE_NOT_BASE64URL"
            )

        try:
            nonce_bytes = _b64url_decode(proof.nonce)
        except (ValueError, TypeError):
            return PoPResult(
                device_id=identity.device_id, valid=False, reason="POP_NONCE_NOT_BASE64URL"
            )

        try:
            public_key.verify(signature, nonce_bytes)
        except InvalidSignature:
            return PoPResult(
                device_id=identity.device_id, valid=False, reason="POP_SIGNATURE_INVALID"
            )

        return PoPResult(
            device_id=identity.device_id,
            valid=True,
            reason="POP_VERIFIED",
            verified_at=now,
            algorithm=proof.algorithm,
        )


class ProofStore:
    """Remembers the most recent successful proof-of-possession per device.

    Predicate C2 asks whether "a verified proof-of-possession exists and is within
    its lifetime". Without a store, a proof would have to accompany every single
    request, ``proof_of_possession_ttl_s`` would never be consulted, and a
    legitimate device would degrade the moment it stopped re-signing. The store is
    what gives that configured lifetime meaning.

    Only successful verifications are retained. A failure never displaces a valid
    proof, and an entry past its lifetime is discarded rather than returned, so a
    stale proof can never satisfy C2.
    """

    def __init__(self, clock: Clock, ttl_s: int) -> None:
        self._clock = clock
        self._ttl = timedelta(seconds=ttl_s)
        self._verified: dict[str, PoPResult] = {}

    def record(self, result: PoPResult) -> PoPResult:
        if result.valid and result.verified_at is not None:
            self._verified[result.device_id] = result
        return result

    def get(self, device_id: str, *, at: datetime | None = None) -> PoPResult | None:
        """Return the stored proof if it is still within its lifetime."""
        stored = self._verified.get(device_id)
        if stored is None or stored.verified_at is None:
            return None
        now = at if at is not None else self._clock.now()
        if now - stored.verified_at > self._ttl:
            del self._verified[device_id]
            return None
        return stored

    def invalidate(self, device_id: str) -> None:
        """Discard a device's proof, so the next decision requires a fresh one."""
        self._verified.pop(device_id, None)

    def reset(self) -> None:
        self._verified.clear()

    @property
    def outstanding(self) -> int:
        return len(self._verified)


def encode_nonce_bytes(nonce: str) -> bytes:
    """Return the raw bytes a device must sign for a given nonce string."""
    return _b64url_decode(nonce)


def encode_signature(raw_signature: bytes) -> str:
    """Encode a raw signature for transport."""
    return _b64url_encode(raw_signature)
