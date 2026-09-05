"""Baseline A: independent authentication.

Trust obtained in one access domain is never reused. Any detected access-domain
transition requires a full re-authentication. Outside a transition, access
requires a valid registry entry and a fresh proof-of-possession. No trust state is
carried between requests.

This baseline exists to bound one end of the design space. It is expected to be
correct under the adversarial scenarios and to pay a re-authentication cost at
every transition; both expectations are to be measured, not asserted.
"""

from __future__ import annotations

from ca_ztcf.collectors.transition import TransitionContext
from ca_ztcf.evidence.freshness import is_fresh
from ca_ztcf.identity.registry import registry_status_reason
from ca_ztcf.strategies.interface import AccessRequest, DecisionStrategy, StrategyOutcome
from ca_ztcf.trust_engine.states import TrustState


class IndependentAuthenticationStrategy(DecisionStrategy):
    """Full authentication on every transition; no continuity of any kind."""

    kind = "independent"

    def decide(self, request: AccessRequest) -> StrategyOutcome:
        deps = self.deps
        now = self.now(request)
        pop_ttl = int(
            self.definition.parameters.get(
                "proof_of_possession_ttl_s", deps.settings.evidence.proof_of_possession_ttl_s
            )
        )

        identity = deps.registry.get(request.device_id)

        # The transition is still observed, because a transition is a fact about
        # the world rather than a feature of a strategy. What differs is that this
        # baseline reacts to it by discarding everything.
        deps.transitions.observe(
            request.device_id, request.domain, peer_address=request.peer_address, at=now
        )
        transition_recent = deps.transitions.is_transition_recent(request.device_id, at=now)
        context = deps.transitions.context_for(request.device_id, at=now)

        if identity is None:
            return self._outcome(request, TrustState.UNKNOWN, context, ("DEVICE_NOT_REGISTERED",))

        valid, reason = registry_status_reason(identity)
        if not valid:
            return self._outcome(request, TrustState.UNTRUSTED, context, (reason,))

        if transition_recent:
            # The defining behaviour of this baseline: prior trust is not reused.
            return self._outcome(
                request,
                TrustState.SUSPICIOUS
                if context is TransitionContext.REPEATED
                else TrustState.UNKNOWN,
                TransitionContext.NONE,
                ("BASELINE_A_TRANSITION_REQUIRES_FULL_REAUTHENTICATION",),
                force_reauthenticate=True,
            )

        pop = None
        if request.proof is not None:
            pop = deps.proofs.record(deps.proof_verifier.verify(identity, request.proof))
            if not pop.valid:
                deps.counters.record_authn_failure(request.device_id, now)
        else:
            # The same proof lifetime the other approaches get, so the comparison
            # measures the decision logic rather than an artificial handicap.
            pop = deps.proofs.get(request.device_id, at=now)

        if pop is None or not pop.valid or pop.verified_at is None:
            return self._outcome(
                request,
                TrustState.DEGRADED,
                context,
                (pop.reason if pop is not None else "POP_NOT_PRESENTED",),
            )

        if not is_fresh(pop.verified_at, now, pop_ttl):
            return self._outcome(request, TrustState.DEGRADED, context, ("POP_STALE",))

        return self._outcome(
            request, TrustState.STABLE, TransitionContext.NONE, ("BASELINE_A_FULLY_AUTHENTICATED",)
        )

    def _outcome(
        self,
        request: AccessRequest,
        state: TrustState,
        context: TransitionContext,
        reasons: tuple[str, ...],
        *,
        force_reauthenticate: bool = False,
    ) -> StrategyOutcome:
        deps = self.deps
        if force_reauthenticate:
            # Map to the policy matrix entry that yields REAUTHENTICATE while
            # keeping the Decision shape identical across strategies.
            decision = deps.policy.direct(
                request.device_id,
                TrustState.SUSPICIOUS,
                TransitionContext.NONE,
                strategy=self.name,
                reason_codes=reasons,
            )
        else:
            decision = deps.policy.direct(
                request.device_id, state, context, strategy=self.name, reason_codes=reasons
            )
        return StrategyOutcome(decision=decision, notes={"baseline": "A"})


__all__ = ["IndependentAuthenticationStrategy"]
