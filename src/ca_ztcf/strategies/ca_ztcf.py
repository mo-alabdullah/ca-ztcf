"""The proposed approach: the full CA-ZTCF pipeline.

evidence -> predicates -> trust state -> transition-aware policy -> decision.

This strategy is designed to re-evaluate trust at access-domain transitions using
only evidence that each domain can realistically expose. Whether that design
objective is met, and at what cost, is to be evaluated experimentally.
"""

from __future__ import annotations

from ca_ztcf.evidence.assembler import AssemblerInputs
from ca_ztcf.identity.models import PoPResult
from ca_ztcf.strategies.interface import AccessRequest, DecisionStrategy, StrategyOutcome


class CAZTCFStrategy(DecisionStrategy):
    """Full evidence-driven, transition-aware trust re-evaluation."""

    kind = "ca_ztcf"

    def decide(self, request: AccessRequest) -> StrategyOutcome:
        deps = self.deps
        now = self.now(request)

        identity = deps.registry.get(request.device_id)

        # Proof-of-possession is the only mechanism that attributes an access
        # binding to a service-domain identity. No access-domain identifier is
        # ever used for this, and no identifier is compared across domains.
        pop_result: PoPResult | None = None
        if request.proof is not None and identity is not None:
            pop_result = deps.proofs.record(deps.proof_verifier.verify(identity, request.proof))
            if not pop_result.valid:
                deps.counters.record_authn_failure(request.device_id, now)
        elif identity is not None:
            # No fresh proof presented: fall back to the last verified one, which
            # C2 accepts only while it is within its configured lifetime.
            pop_result = deps.proofs.get(request.device_id, at=now)

        transition = deps.transitions.observe(
            request.device_id, request.domain, peer_address=request.peer_address, at=now
        )
        context = deps.transitions.context_for(request.device_id, at=now)

        binding, consistent = deps.binding_store.claim(request.peer_address, request.device_id)
        if not consistent:
            deps.counters.record_identity_conflict(request.device_id)

        session_consistent = (
            request.session_identity is None
            or request.session_identity == request.device_id
            or request.session_identity.startswith(f"{request.device_id}:")
        )

        record = deps.assembler.assemble(
            AssemblerInputs(
                device_id=request.device_id,
                identity=identity,
                pop_result=pop_result,
                binding=binding,
                binding_consistent=consistent,
                current_domain=deps.transitions.current_domain(request.device_id),
                previous_domain=deps.transitions.previous_domain(request.device_id),
                transition=deps.transitions.last_transition(request.device_id),
                transition_recent=deps.transitions.is_transition_recent(request.device_id, at=now),
                transitions_in_window=deps.transitions.transitions_in_window(
                    request.device_id, at=now
                ),
                authentication_failure_count=deps.counters.authn_failures(request.device_id, now),
                session_consistent=session_consistent,
                collector_available=True,
                evaluated_at=now,
            )
        )

        vector = deps.predicates.evaluate(record)
        previous_state = deps.state_manager.current(request.device_id)
        evaluation = deps.trust_engine.evaluate(record, vector, previous_state=previous_state)
        deps.state_manager.record(evaluation)

        decision = deps.policy.evaluate(evaluation, context, strategy=self.name)

        notes = {"transition_detected": "true" if transition is not None else "false"}
        return StrategyOutcome(
            decision=decision,
            evidence=record,
            predicates=vector,
            trust_evaluation=evaluation,
            notes=notes,
        )


__all__ = ["CAZTCFStrategy"]
