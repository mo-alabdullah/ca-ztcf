"""Baseline B: simple static trust continuity.

After a first successful authentication the device receives a session token with a
fixed lifetime. While the token is valid it is honoured regardless of access
domain, transition, evidence freshness or binding conflict.

This baseline deliberately reintroduces the implicit trust that Zero Trust
rejects. It is expected to accept several of the adversarial scenarios; that
acceptance is the property being measured, and a scenario in which this baseline
does *not* fail is a scenario that needs correcting.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from ca_ztcf.collectors.transition import TransitionContext
from ca_ztcf.config import StrategyDefinition
from ca_ztcf.identity.registry import registry_status_reason
from ca_ztcf.strategies.interface import (
    AccessRequest,
    DecisionStrategy,
    StrategyDeps,
    StrategyOutcome,
)
from ca_ztcf.trust_engine.states import TrustState


@dataclass(frozen=True)
class SessionToken:
    """A bearer session token with a fixed lifetime."""

    device_id: str
    issued_at: datetime
    expires_at: datetime

    def is_valid(self, now: datetime) -> bool:
        return now <= self.expires_at


class StaticContinuityStrategy(DecisionStrategy):
    """Honours a previously issued session token until its lifetime expires."""

    kind = "static_continuity"

    def __init__(self, definition: StrategyDefinition, deps: StrategyDeps) -> None:
        super().__init__(definition, deps)
        self._tokens: dict[str, SessionToken] = {}

    @property
    def token_ttl_s(self) -> int:
        return int(self.definition.parameters.get("token_ttl_s", 300))

    def tokens_outstanding(self) -> int:
        return len(self._tokens)

    def clear_tokens(self) -> None:
        self._tokens.clear()

    def decide(self, request: AccessRequest) -> StrategyOutcome:
        deps = self.deps
        now = self.now(request)

        # Observed for parity with the other strategies; deliberately ignored when
        # deciding, which is exactly what makes this baseline "static".
        deps.transitions.observe(
            request.device_id, request.domain, peer_address=request.peer_address, at=now
        )

        token = self._tokens.get(request.device_id)
        if token is not None and token.is_valid(now):
            decision = deps.policy.direct(
                request.device_id,
                TrustState.STABLE,
                TransitionContext.NONE,
                strategy=self.name,
                reason_codes=("BASELINE_B_SESSION_TOKEN_VALID",),
            )
            return StrategyOutcome(
                decision=decision,
                notes={"baseline": "B", "token": "reused", "token_ttl_s": str(self.token_ttl_s)},
            )

        if token is not None:
            del self._tokens[request.device_id]

        identity = deps.registry.get(request.device_id)
        if identity is None:
            decision = deps.policy.direct(
                request.device_id,
                TrustState.UNKNOWN,
                TransitionContext.NONE,
                strategy=self.name,
                reason_codes=("DEVICE_NOT_REGISTERED",),
            )
            return StrategyOutcome(decision=decision, notes={"baseline": "B", "token": "none"})

        valid, reason = registry_status_reason(identity)
        if not valid:
            decision = deps.policy.direct(
                request.device_id,
                TrustState.UNTRUSTED,
                TransitionContext.NONE,
                strategy=self.name,
                reason_codes=(reason,),
            )
            return StrategyOutcome(decision=decision, notes={"baseline": "B", "token": "none"})

        pop = None
        if request.proof is not None:
            pop = deps.proof_verifier.verify(identity, request.proof)
            if not pop.valid:
                deps.counters.record_authn_failure(request.device_id, now)

        if pop is None or not pop.valid:
            decision = deps.policy.direct(
                request.device_id,
                TrustState.DEGRADED,
                TransitionContext.NONE,
                strategy=self.name,
                reason_codes=(pop.reason if pop is not None else "POP_NOT_PRESENTED",),
            )
            return StrategyOutcome(decision=decision, notes={"baseline": "B", "token": "none"})

        self._tokens[request.device_id] = SessionToken(
            device_id=request.device_id,
            issued_at=now,
            expires_at=now + timedelta(seconds=self.token_ttl_s),
        )
        decision = deps.policy.direct(
            request.device_id,
            TrustState.STABLE,
            TransitionContext.NONE,
            strategy=self.name,
            reason_codes=("BASELINE_B_SESSION_TOKEN_ISSUED",),
        )
        return StrategyOutcome(
            decision=decision,
            notes={"baseline": "B", "token": "issued", "token_ttl_s": str(self.token_ttl_s)},
        )


__all__ = ["SessionToken", "StaticContinuityStrategy"]
