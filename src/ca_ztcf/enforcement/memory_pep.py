"""In-memory Policy Enforcement Point.

Enforces decisions logically, without a network transport. It is the enforcement
point used by the unit and integration tests of this milestone and by the
development validation flow. The MQTT proxy enforcement point is Batch F.

Decision lifetime is honoured here: a decision whose TTL has elapsed is treated as
absent, so the enforcement point must re-consult the trust function. That is the
time-bounded dynamic policy behaviour the framework is designed around.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ca_ztcf.clock import Clock
from ca_ztcf.enforcement.interface import PolicyEnforcementPoint, topic_matches
from ca_ztcf.enforcement.models import EnforcementRequest, EnforcementResult, ResourceOperation
from ca_ztcf.policy.models import TERMINATING_ACTIONS, Decision, PolicyAction


class MemoryPEP(PolicyEnforcementPoint):
    """Holds one active decision per device and evaluates requests against it."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._decisions: dict[str, Decision] = {}
        # Last decision seen per device, retained after a terminating action so
        # that a subsequent request can be refused with the correct reason rather
        # than an indistinguishable "no active decision".
        self._last: dict[str, Decision] = {}

    # -- decision lifecycle ---------------------------------------------

    def apply(self, decision: Decision) -> None:
        if decision.action in TERMINATING_ACTIONS:
            # No session may continue past a denial or a re-authentication
            # requirement, so nothing is installed and any prior grant is dropped.
            self._decisions.pop(decision.device_id, None)
            self._last[decision.device_id] = decision
            return
        self._decisions[decision.device_id] = decision
        self._last[decision.device_id] = decision

    def active_decision(self, device_id: str) -> Decision | None:
        decision = self._decisions.get(device_id)
        if decision is None:
            return None
        if self._is_expired(decision):
            del self._decisions[device_id]
            return None
        return decision

    def revoke(self, device_id: str) -> None:
        self._decisions.pop(device_id, None)

    def reset(self) -> None:
        self._decisions.clear()
        self._last.clear()

    # -- enforcement -----------------------------------------------------

    def check(self, request: EnforcementRequest) -> EnforcementResult:
        now = self._clock.now()
        decision = self.active_decision(request.device_id)

        if decision is None:
            last = self._last.get(request.device_id)
            reason = "NO_ACTIVE_DECISION"
            action = None
            decision_id = None
            if last is not None:
                action = last.action
                decision_id = last.decision_id
                if last.action in TERMINATING_ACTIONS:
                    reason = f"ACTION_{last.action.value}"
                else:
                    reason = "DECISION_EXPIRED"
            return EnforcementResult(
                device_id=request.device_id,
                permitted=False,
                reason=reason,
                action=action,
                decision_id=decision_id,
                evaluated_at=now,
            )

        if decision.action is PolicyAction.ALLOW and request.operation is ResourceOperation.CONNECT:
            return self._permit(request, decision, "ALLOWED", now)

        if request.operation is ResourceOperation.CONNECT:
            # Connection is permitted for every non-terminating action; the scope
            # then constrains what the device may actually do.
            return self._permit(request, decision, f"CONNECT_UNDER_{decision.action.value}", now)

        scope = decision.scope
        for pattern in scope.deny:
            if topic_matches(pattern, request.resource):
                return EnforcementResult(
                    device_id=request.device_id,
                    permitted=False,
                    reason=f"DENIED_BY_SCOPE:{scope.name}:{pattern}",
                    action=decision.action,
                    decision_id=decision.decision_id,
                    evaluated_at=now,
                )
        for pattern in scope.allow:
            if topic_matches(pattern, request.resource):
                return self._permit(request, decision, f"ALLOWED_BY_SCOPE:{scope.name}", now)

        return EnforcementResult(
            device_id=request.device_id,
            permitted=False,
            reason=f"NOT_IN_SCOPE:{scope.name}",
            action=decision.action,
            decision_id=decision.decision_id,
            evaluated_at=now,
        )

    # -- internals -------------------------------------------------------

    def _permit(
        self,
        request: EnforcementRequest,
        decision: Decision,
        reason: str,
        now: datetime,
    ) -> EnforcementResult:
        return EnforcementResult(
            device_id=request.device_id,
            permitted=True,
            reason=reason,
            action=decision.action,
            decision_id=decision.decision_id,
            evaluated_at=now,
        )

    def _is_expired(self, decision: Decision) -> bool:
        if decision.ttl_ms <= 0:
            return True
        expiry = decision.created_at + timedelta(milliseconds=decision.ttl_ms)
        return self._clock.now() > expiry


__all__ = ["MemoryPEP"]
