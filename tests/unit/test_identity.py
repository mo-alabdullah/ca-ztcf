"""Device identity registry and proof-of-possession."""

from __future__ import annotations

import pytest
from tests.conftest import DeviceKey, fake_pem

from ca_ztcf.clock import FrozenClock
from ca_ztcf.errors import DeviceAlreadyRegisteredError, DeviceNotFoundError, RegistryError
from ca_ztcf.identity.models import DeviceStatus
from ca_ztcf.identity.proof import NonceIssuer, ProofVerifier, fingerprint_public_key_pem
from ca_ztcf.identity.registry import DeviceIdentityRegistry, registry_status_reason


@pytest.fixture
def registry(clock: FrozenClock) -> DeviceIdentityRegistry:
    return DeviceIdentityRegistry(clock)


def test_register_and_fetch(registry: DeviceIdentityRegistry, device_key: DeviceKey) -> None:
    identity = registry.register("dev-001", device_key.public_pem, labels={"class": "sensor"})
    assert identity.device_id == "dev-001"
    assert identity.status is DeviceStatus.ACTIVE
    assert identity.public_key_fingerprint == fingerprint_public_key_pem(device_key.public_pem)
    assert registry.get("dev-001") == identity
    assert len(registry) == 1


def test_unregistered_device_returns_none(registry: DeviceIdentityRegistry) -> None:
    assert registry.get("dev-absent") is None
    with pytest.raises(DeviceNotFoundError):
        registry.require("dev-absent")


def test_duplicate_registration_is_rejected(
    registry: DeviceIdentityRegistry, device_key: DeviceKey
) -> None:
    registry.register("dev-001", device_key.public_pem)
    with pytest.raises(DeviceAlreadyRegisteredError):
        registry.register("dev-001", device_key.public_pem)


def test_private_key_is_never_accepted(registry: DeviceIdentityRegistry) -> None:
    fake_private = fake_pem("not-a-real-key")
    with pytest.raises((RegistryError, ValueError)):
        registry.register("dev-001", fake_private)


def test_registry_snapshot_contains_no_private_material(
    registry: DeviceIdentityRegistry, device_key: DeviceKey
) -> None:
    registry.register("dev-001", device_key.public_pem)
    snapshot = registry.snapshot()
    assert "PRIVATE KEY" not in str(snapshot).upper()


def test_status_transitions_and_reasons(
    registry: DeviceIdentityRegistry, device_key: DeviceKey, clock: FrozenClock
) -> None:
    identity = registry.register("dev-001", device_key.public_pem)
    assert registry_status_reason(identity) == (True, "IDENTITY_ACTIVE")
    assert registry_status_reason(None) == (False, "DEVICE_NOT_REGISTERED")

    clock.advance(seconds=1)
    suspended = registry.set_status("dev-001", DeviceStatus.SUSPENDED)
    assert registry_status_reason(suspended) == (False, "DEVICE_SUSPENDED")
    assert suspended.updated_at > identity.updated_at

    revoked = registry.set_status("dev-001", DeviceStatus.REVOKED)
    assert registry_status_reason(revoked) == (False, "DEVICE_REVOKED")


def test_proof_of_possession_valid_case(
    registry: DeviceIdentityRegistry, device_key: DeviceKey, clock: FrozenClock
) -> None:
    identity = registry.register("dev-001", device_key.public_pem)
    issuer = NonceIssuer(clock, ttl_s=60)
    verifier = ProofVerifier(clock, issuer)

    nonce, expires_at = issuer.issue("dev-001")
    assert expires_at > clock.now()

    result = verifier.verify(identity, device_key.proof("dev-001", nonce))
    assert result.valid is True
    assert result.reason == "POP_VERIFIED"
    assert result.verified_at == clock.now()


def test_proof_of_possession_invalid_signature(
    registry: DeviceIdentityRegistry, device_key: DeviceKey, clock: FrozenClock
) -> None:
    identity = registry.register("dev-001", device_key.public_pem)
    issuer = NonceIssuer(clock, ttl_s=60)
    verifier = ProofVerifier(clock, issuer)
    nonce, _ = issuer.issue("dev-001")

    result = verifier.verify(identity, device_key.bad_proof("dev-001", nonce))
    assert result.valid is False
    assert result.reason == "POP_SIGNATURE_INVALID"
    assert result.verified_at is None


def test_nonce_is_single_use(
    registry: DeviceIdentityRegistry, device_key: DeviceKey, clock: FrozenClock
) -> None:
    identity = registry.register("dev-001", device_key.public_pem)
    issuer = NonceIssuer(clock, ttl_s=60)
    verifier = ProofVerifier(clock, issuer)
    nonce, _ = issuer.issue("dev-001")

    assert verifier.verify(identity, device_key.proof("dev-001", nonce)).valid is True
    replay = verifier.verify(identity, device_key.proof("dev-001", nonce))
    assert replay.valid is False
    assert replay.reason == "NONCE_UNKNOWN_OR_ALREADY_USED"


def test_nonce_expires(
    registry: DeviceIdentityRegistry, device_key: DeviceKey, clock: FrozenClock
) -> None:
    identity = registry.register("dev-001", device_key.public_pem)
    issuer = NonceIssuer(clock, ttl_s=60)
    verifier = ProofVerifier(clock, issuer)
    nonce, _ = issuer.issue("dev-001")

    clock.advance(seconds=61)
    result = verifier.verify(identity, device_key.proof("dev-001", nonce))
    assert result.valid is False
    assert result.reason == "NONCE_EXPIRED"


def test_nonce_is_bound_to_one_device(
    registry: DeviceIdentityRegistry, device_key: DeviceKey, clock: FrozenClock
) -> None:
    registry.register("dev-001", device_key.public_pem)
    other = registry.register("dev-002", DeviceKey().public_pem)
    issuer = NonceIssuer(clock, ttl_s=60)
    verifier = ProofVerifier(clock, issuer)
    nonce, _ = issuer.issue("dev-001")

    result = verifier.verify(other, device_key.proof("dev-002", nonce))
    assert result.valid is False
    assert result.reason == "NONCE_DEVICE_MISMATCH"
