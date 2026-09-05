"""The six trust continuity states, with their semantics stated explicitly.

States are **not** justified by a one-to-one mapping onto enforcement actions.
``UNKNOWN`` and ``UNTRUSTED`` both result in DENY, and that is correct: they carry
different evidence semantics, different recovery paths and different audit
meanings, and an operator must be able to tell them apart. Each state below
records those four axes so the justification lives with the code.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class TrustState(StrEnum):
    """Trust continuity state of a device at one instant."""

    UNKNOWN = "UNKNOWN"
    STABLE = "STABLE"
    TRANSITIONAL = "TRANSITIONAL"
    DEGRADED = "DEGRADED"
    SUSPICIOUS = "SUSPICIOUS"
    UNTRUSTED = "UNTRUSTED"


class StateDefinition(BaseModel):
    """The four axes on which a state is justified."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: TrustState
    evidence_semantics: str
    recovery_path: str
    audit_meaning: str
    policy_consequence: str


STATE_DEFINITIONS: dict[TrustState, StateDefinition] = {
    TrustState.UNKNOWN: StateDefinition(
        state=TrustState.UNKNOWN,
        evidence_semantics=(
            "No valid device registry entry exists. The device has not completed "
            "research enrolment, so there is no identity against which any other "
            "evidence could be interpreted."
        ),
        recovery_path=(
            "Administrative enrolment, out of band. A device must never bootstrap "
            "trust through the normal access-decision path."
        ),
        audit_meaning="An unregistered device attempted to access a resource.",
        policy_consequence="DENY with reason REGISTRATION_REQUIRED.",
    ),
    TrustState.STABLE: StateDefinition(
        state=TrustState.STABLE,
        evidence_semantics=(
            "Identity valid, access binding present, fresh and consistent, no "
            "recent access-domain transition, no contradictory evidence."
        ),
        recovery_path="Not applicable; this is the steady state.",
        audit_meaning="Steady legitimate operation within a single access domain.",
        policy_consequence="ALLOW at the device's full scope.",
    ),
    TrustState.TRANSITIONAL: StateDefinition(
        state=TrustState.TRANSITIONAL,
        evidence_semantics=(
            "A valid registered device has recently changed access domain. Enough "
            "evidence exists to continue with limited trust while the remaining "
            "evidence settles, but not enough to treat the device as stable."
        ),
        recovery_path=(
            "The configured transition window elapses with every predicate still "
            "holding, at which point the device returns to STABLE."
        ),
        audit_meaning="A legitimate access-domain change is in progress.",
        policy_consequence=(
            "ALLOW_WITH_RESTRICTIONS, or STEP_UP_AUTHENTICATION when the transition "
            "context is REPEATED."
        ),
    ),
    TrustState.DEGRADED: StateDefinition(
        state=TrustState.DEGRADED,
        evidence_semantics=(
            "Evidence is incomplete, stale or temporarily unavailable, and quality "
            "has fallen, but nothing contradicts the device's claim. Missing "
            "evidence is not contradictory evidence."
        ),
        recovery_path=(
            "Fresh evidence plus a successful step-up authentication restores the previous state."
        ),
        audit_meaning="Reduced assurance; the device may well be legitimate.",
        policy_consequence="STEP_UP_AUTHENTICATION with a restricted scope.",
    ),
    TrustState.SUSPICIOUS: StateDefinition(
        state=TrustState.SUSPICIOUS,
        evidence_semantics=(
            "Evidence is contradictory or strongly abnormal: the transition rate or "
            "authentication-failure count is over its limit, the service-layer "
            "session identity does not match, or the observed access context "
            "violates the configured posture."
        ),
        recovery_path=(
            "Full re-authentication, followed by a cooldown period during which the "
            "security counters must stay under their limits."
        ),
        audit_meaning="Possible attack in progress; the device is not merely degraded.",
        policy_consequence=(
            "REAUTHENTICATE outside a transition; QUARANTINE when observed across an "
            "access-domain change."
        ),
    ),
    TrustState.UNTRUSTED: StateDefinition(
        state=TrustState.UNTRUSTED,
        evidence_semantics=(
            "The device is registered, but identity validation failed (suspended or "
            "revoked) or the access binding is already attributed to a different "
            "device. This is a direct contradiction, not an absence."
        ),
        recovery_path=(
            "An administrative status change, then a full re-authentication. Unlike "
            "UNKNOWN, the identity exists and can be restored."
        ),
        audit_meaning="Validation failure or a competing claim on an access binding.",
        policy_consequence="DENY with reason VALIDATION_FAILED.",
    ),
}


TERMINAL_STATES: frozenset[TrustState] = frozenset({TrustState.UNKNOWN, TrustState.UNTRUSTED})
"""States from which no access is possible without action outside the access path."""


def describe(state: TrustState) -> StateDefinition:
    return STATE_DEFINITIONS[state]


__all__ = ["STATE_DEFINITIONS", "TERMINAL_STATES", "StateDefinition", "TrustState", "describe"]
