"""Shared test fixtures.

Every test uses a FrozenClock. No test sleeps: elapsed time is expressed by
advancing the clock, which is what keeps the suite fast and deterministic.
"""

from __future__ import annotations

import base64
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ca_ztcf.api.app import create_app
from ca_ztcf.api.state import AppState, build_app_state
from ca_ztcf.clock import FrozenClock
from ca_ztcf.collectors.base import AccessDomain
from ca_ztcf.collectors.fixtures import FixtureProfile
from ca_ztcf.config import Settings, load_settings
from ca_ztcf.identity.models import ProofOfPossession
from ca_ztcf.identity.proof import encode_nonce_bytes, encode_signature

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = REPO_ROOT / "config"
T0 = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)

# PEM-shaped text assembled at runtime, so the pattern never appears whole in the
# source. These are NOT keys: they are fixtures asserting that such input is
# rejected or redacted. Assembling them keeps the secret scanner meaningful
# instead of accumulating suppressions.
_PEM_BEGIN = "-----BEGIN " + "PRIVATE KEY-----"
_PEM_END = "-----END " + "PRIVATE KEY-----"


def fake_pem(body: str = "not-a-real-key") -> str:
    """Return PEM-shaped text that is deliberately not a key."""
    return f"{_PEM_BEGIN}\n{body}\n{_PEM_END}\n"


class DeviceKey:
    """A test device key pair. The private key never leaves the test process."""

    def __init__(self) -> None:
        self._private = Ed25519PrivateKey.generate()

    @property
    def public_pem(self) -> str:
        return (
            self._private.public_key()
            .public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode("ascii")
        )

    def sign_nonce(self, nonce: str) -> str:
        return encode_signature(self._private.sign(encode_nonce_bytes(nonce)))

    def proof(self, device_id: str, nonce: str) -> ProofOfPossession:
        return ProofOfPossession(device_id=device_id, nonce=nonce, signature=self.sign_nonce(nonce))

    def bad_proof(self, device_id: str, nonce: str) -> ProofOfPossession:
        """A syntactically valid but cryptographically wrong signature."""
        wrong = Ed25519PrivateKey.generate()
        signature = (
            base64.urlsafe_b64encode(wrong.sign(encode_nonce_bytes(nonce)))
            .rstrip(b"=")
            .decode("ascii")
        )
        return ProofOfPossession(device_id=device_id, nonce=nonce, signature=signature)


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(start=T0)


@pytest.fixture(scope="session")
def settings() -> Settings:
    return load_settings(CONFIG_DIR)


@pytest.fixture
def app_state(clock: FrozenClock, tmp_path: Path, settings: Settings) -> AppState:
    return build_app_state(settings=settings, clock=clock, audit_base_dir=tmp_path)


@pytest.fixture
def device_key() -> DeviceKey:
    return DeviceKey()


@pytest.fixture
def profile() -> FixtureProfile:
    return FixtureProfile()


@pytest.fixture
def registered(app_state: AppState, device_key: DeviceKey, profile: FixtureProfile) -> str:
    app_state.registry.register(profile.device_id, device_key.public_pem)
    return profile.device_id


@pytest.fixture
def fresh_proof(app_state: AppState, device_key: DeviceKey):
    def _make(device_id: str) -> ProofOfPossession:
        nonce, _ = app_state.nonces.issue(device_id)
        return device_key.proof(device_id, nonce)

    return _make


@pytest.fixture
def client(app_state: AppState) -> Iterator[object]:
    from fastapi.testclient import TestClient

    app = create_app(state=app_state)
    with TestClient(app) as test_client:
        yield test_client


NR = AccessDomain.NR
WLAN = AccessDomain.WLAN
