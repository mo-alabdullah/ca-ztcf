"""Typed exception hierarchy.

Every error carries a stable ``code`` so that failures are attributable in audit
output and in test assertions without matching on message text.
"""

from __future__ import annotations


class CaZtcfError(Exception):
    """Base class for every error raised by this package."""

    code: str = "CA_ZTCF_ERROR"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


class ConfigurationError(CaZtcfError):
    """Configuration is missing, malformed, or internally inconsistent."""

    code = "CONFIGURATION_ERROR"


class RegistryError(CaZtcfError):
    """Device registry operation failed."""

    code = "REGISTRY_ERROR"


class DeviceAlreadyRegisteredError(RegistryError):
    """A device with the requested identifier is already registered."""

    code = "DEVICE_ALREADY_REGISTERED"


class DeviceNotFoundError(RegistryError):
    """No registry entry exists for the requested device."""

    code = "DEVICE_NOT_FOUND"


class ProofOfPossessionError(CaZtcfError):
    """Proof-of-possession could not be verified."""

    code = "PROOF_OF_POSSESSION_ERROR"


class NonceError(ProofOfPossessionError):
    """A challenge nonce is unknown, expired, or already consumed."""

    code = "NONCE_ERROR"


class CollectorError(CaZtcfError):
    """An access-context collector could not produce normalised evidence."""

    code = "COLLECTOR_ERROR"


class EvidenceError(CaZtcfError):
    """The evidence record could not be assembled or is inconsistent."""

    code = "EVIDENCE_ERROR"


class PolicyError(CaZtcfError):
    """The policy matrix is malformed or produced no usable decision."""

    code = "POLICY_ERROR"


class StrategyError(CaZtcfError):
    """A decision strategy is unknown or could not produce a decision."""

    code = "STRATEGY_ERROR"


class EnforcementError(CaZtcfError):
    """The policy enforcement point could not apply or evaluate a decision."""

    code = "ENFORCEMENT_ERROR"
