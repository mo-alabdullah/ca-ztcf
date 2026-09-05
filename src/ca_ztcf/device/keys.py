"""Device key material handling.

Private keys live only on the device side and only under ``secrets/``, which is
git-ignored. Nothing in this module writes a private key anywhere else, and no
private key is ever sent to the service domain: the device proves possession by
signing, never by disclosing.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ca_ztcf.errors import CaZtcfError
from ca_ztcf.identity.models import ProofOfPossession


class DeviceKeyError(CaZtcfError):
    """Device key material is missing or unreadable."""

    code = "DEVICE_KEY_ERROR"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


@dataclass
class DeviceKeyPair:
    """A device's Ed25519 key pair."""

    device_id: str
    private_key: Ed25519PrivateKey

    @classmethod
    def generate(cls, device_id: str) -> DeviceKeyPair:
        return cls(device_id=device_id, private_key=Ed25519PrivateKey.generate())

    @classmethod
    def load(cls, device_id: str, private_key_path: Path) -> DeviceKeyPair:
        if not private_key_path.is_file():
            raise DeviceKeyError(f"private key not found: {private_key_path}")
        loaded = serialization.load_pem_private_key(private_key_path.read_bytes(), password=None)
        if not isinstance(loaded, Ed25519PrivateKey):
            raise DeviceKeyError(f"{private_key_path} is not an Ed25519 private key")
        return cls(device_id=device_id, private_key=loaded)

    @property
    def public_key_pem(self) -> str:
        return (
            self.private_key.public_key()
            .public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode("ascii")
        )

    def write_private_key(self, path: Path) -> Path:
        """Write the private key, owner-readable only, under a git-ignored path."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(
            self.private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        path.chmod(0o600)
        return path

    def write_public_key(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.public_key_pem, encoding="utf-8")
        path.chmod(0o644)
        return path

    def sign_nonce(self, nonce: str) -> str:
        return _b64url(self.private_key.sign(_b64url_decode(nonce)))

    def proof(self, nonce: str) -> ProofOfPossession:
        return ProofOfPossession(
            device_id=self.device_id, nonce=nonce, signature=self.sign_nonce(nonce)
        )

    def credential(self, nonce: str) -> bytes:
        """Encode a proof for the MQTT CONNECT password field as ``nonce.signature``."""
        return f"{nonce}.{self.sign_nonce(nonce)}".encode("ascii")


def research_device_id(index: int, prefix: str = "dev-res") -> str:
    """Deterministic research device identifier, for reproducible scenarios."""
    if index < 0:
        raise ValueError("device index must not be negative")
    return f"{prefix}-{index:04d}"


__all__ = ["DeviceKeyError", "DeviceKeyPair", "research_device_id"]
