"""Policy actions, access scopes and the decision record."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ca_ztcf.collectors.transition import TransitionContext
from ca_ztcf.trust_engine.states import TrustState


class PolicyAction(StrEnum):
    """The six enforcement actions.

    Each has a concrete behaviour at the Policy Enforcement Point, so each has a
    cost that can be measured. Note that several trust states may map to the same
    action; the reason codes distinguish them.
    """

    ALLOW = "ALLOW"
    """Full scope for the device's role."""

    ALLOW_WITH_RESTRICTIONS = "ALLOW_WITH_RESTRICTIONS"
    """Reduced scope while trust evidence settles; the session continues."""

    STEP_UP_AUTHENTICATION = "STEP_UP_AUTHENTICATION"
    """Additional evidence required; the session continues but is held."""

    REAUTHENTICATE = "REAUTHENTICATE"
    """The current session is invalidated; full authentication is required."""

    QUARANTINE = "QUARANTINE"
    """The device is isolated in a quarantine namespace for observation."""

    DENY = "DENY"
    """No access."""


TERMINATING_ACTIONS: frozenset[PolicyAction] = frozenset(
    {PolicyAction.REAUTHENTICATE, PolicyAction.DENY}
)
"""Actions after which no existing session may continue."""


class AccessScope(BaseModel):
    """A named allow/deny pattern set over resource identifiers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    description: str = ""
    allow: tuple[str, ...] = ()
    deny: tuple[str, ...] = ()

    def resolve(self, device_id: str) -> AccessScope:
        """Substitute ``{device_id}`` in every pattern."""
        return self.model_copy(
            update={
                "allow": tuple(p.replace("{device_id}", device_id) for p in self.allow),
                "deny": tuple(p.replace("{device_id}", device_id) for p in self.deny),
            }
        )


class Decision(BaseModel):
    """A complete, replayable access decision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: str = Field(default_factory=lambda: f"dec-{uuid.uuid4().hex[:16]}")
    device_id: str
    strategy: str
    trust_state: TrustState
    transition_context: TransitionContext
    action: PolicyAction
    scope: AccessScope
    ttl_ms: int
    reason_codes: tuple[str, ...]
    rule_id: str = ""
    predicate_trace_id: str | None = None
    evidence_record_id: str | None = None
    created_at: datetime
    config_hash: str
    decision_duration_ns: int = 0

    @property
    def permits_any_access(self) -> bool:
        return self.action in {
            PolicyAction.ALLOW,
            PolicyAction.ALLOW_WITH_RESTRICTIONS,
            PolicyAction.STEP_UP_AUTHENTICATION,
            PolicyAction.QUARANTINE,
        }

    def expires_at_ms(self) -> int:
        return int(self.created_at.timestamp() * 1000) + self.ttl_ms


__all__ = ["TERMINATING_ACTIONS", "AccessScope", "Decision", "PolicyAction"]
