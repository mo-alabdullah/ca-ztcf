"""Device Identity Registry.

Stores service-domain identities and their public keys. Private key material is
never accepted, stored, returned or logged.

The in-memory implementation is sufficient for the prototype and for the
experiment scale planned in the thesis; the optional JSON snapshot exists so that
a scenario can be seeded deterministically from a committed fixture.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ca_ztcf.clock import Clock
from ca_ztcf.errors import DeviceAlreadyRegisteredError, DeviceNotFoundError, RegistryError
from ca_ztcf.identity.models import DeviceIdentity, DeviceStatus
from ca_ztcf.identity.proof import fingerprint_public_key_pem


class DeviceIdentityRegistry:
    """In-memory registry of service-domain device identities."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._devices: dict[str, DeviceIdentity] = {}

    # -- queries ---------------------------------------------------------

    def get(self, device_id: str) -> DeviceIdentity | None:
        """Return the identity, or ``None`` when the device is not registered.

        A ``None`` result is what makes a device UNKNOWN, which is denied with
        reason ``REGISTRATION_REQUIRED`` rather than re-authenticated.
        """
        return self._devices.get(device_id)

    def require(self, device_id: str) -> DeviceIdentity:
        identity = self.get(device_id)
        if identity is None:
            raise DeviceNotFoundError(f"device '{device_id}' is not registered")
        return identity

    def exists(self, device_id: str) -> bool:
        return device_id in self._devices

    def list_devices(self) -> list[DeviceIdentity]:
        return [self._devices[key] for key in sorted(self._devices)]

    def __len__(self) -> int:
        return len(self._devices)

    # -- mutations -------------------------------------------------------

    def register(
        self,
        device_id: str,
        public_key_pem: str,
        *,
        labels: dict[str, str] | None = None,
        notes: str = "",
        status: DeviceStatus = DeviceStatus.ACTIVE,
    ) -> DeviceIdentity:
        """Enrol a device. Enrolment is an administrative act, outside the access path."""
        if device_id in self._devices:
            raise DeviceAlreadyRegisteredError(f"device '{device_id}' is already registered")
        try:
            fingerprint = fingerprint_public_key_pem(public_key_pem)
        except (ValueError, TypeError) as exc:
            raise RegistryError(
                f"public key for '{device_id}' is not a readable PEM: {exc}"
            ) from exc

        now = self._clock.now()
        identity = DeviceIdentity(
            device_id=device_id,
            public_key_pem=public_key_pem,
            public_key_fingerprint=fingerprint,
            status=status,
            created_at=now,
            updated_at=now,
            labels=dict(labels or {}),
            notes=notes,
        )
        self._devices[device_id] = identity
        return identity

    def set_status(self, device_id: str, status: DeviceStatus) -> DeviceIdentity:
        current = self.require(device_id)
        updated = current.model_copy(update={"status": status, "updated_at": self._clock.now()})
        self._devices[device_id] = updated
        return updated

    def remove(self, device_id: str) -> None:
        if self._devices.pop(device_id, None) is None:
            raise DeviceNotFoundError(f"device '{device_id}' is not registered")

    # -- deterministic seeding ------------------------------------------

    def snapshot(self) -> list[dict[str, object]]:
        """Serialise the registry. Contains public keys only."""
        return [identity.model_dump(mode="json") for identity in self.list_devices()]

    def load_snapshot(self, records: list[dict[str, object]]) -> int:
        """Load a registry snapshot, replacing current content. Returns the count loaded."""
        loaded: dict[str, DeviceIdentity] = {}
        for record in records:
            identity = DeviceIdentity.model_validate(record)
            loaded[identity.device_id] = identity
        self._devices = loaded
        return len(loaded)

    def load_snapshot_file(self, path: Path) -> int:
        if not path.is_file():
            raise RegistryError(f"registry snapshot not found: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise RegistryError(f"registry snapshot must be a JSON array: {path}")
        return self.load_snapshot(data)


def registry_status_reason(identity: DeviceIdentity | None) -> tuple[bool, str]:
    """Map a registry lookup to ``(identity_valid, reason_code)`` for predicate C1."""
    if identity is None:
        return False, "DEVICE_NOT_REGISTERED"
    if identity.status is DeviceStatus.REVOKED:
        return False, "DEVICE_REVOKED"
    if identity.status is DeviceStatus.SUSPENDED:
        return False, "DEVICE_SUSPENDED"
    return True, "IDENTITY_ACTIVE"


def registry_updated_at(identity: DeviceIdentity) -> datetime:
    return identity.updated_at
