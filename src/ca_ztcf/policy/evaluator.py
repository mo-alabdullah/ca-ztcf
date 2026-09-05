"""Turns a trust evaluation into a complete, replayable decision."""

from __future__ import annotations

from ca_ztcf.clock import Clock
from ca_ztcf.collectors.transition import TransitionContext
from ca_ztcf.config import Settings
from ca_ztcf.policy.matrix import PolicyMatrix
from ca_ztcf.policy.models import Decision
from ca_ztcf.trust_engine.decision_trace import TrustEvaluation
from ca_ztcf.trust_engine.states import TrustState


class PolicyEvaluator:
    """Applies the Transition-Aware Policy Matrix."""

    def __init__(
        self, settings: Settings, clock: Clock, matrix: PolicyMatrix | None = None
    ) -> None:
        self._settings = settings
        self._clock = clock
        self._matrix = matrix if matrix is not None else PolicyMatrix(settings)

    @property
    def matrix(self) -> PolicyMatrix:
        return self._matrix

    def evaluate(
        self,
        evaluation: TrustEvaluation,
        context: TransitionContext,
        *,
        strategy: str,
        extra_reason_codes: tuple[str, ...] = (),
    ) -> Decision:
        started_ns = self._clock.monotonic_ns()
        outcome = self._matrix.lookup(evaluation.new_state, context)
        duration_ns = max(0, self._clock.monotonic_ns() - started_ns)

        reason_codes = tuple(
            dict.fromkeys(outcome.reason_codes + evaluation.reason_codes + extra_reason_codes)
        )

        return Decision(
            device_id=evaluation.device_id,
            strategy=strategy,
            trust_state=evaluation.new_state,
            transition_context=context,
            action=outcome.action,
            scope=outcome.scope.resolve(evaluation.device_id),
            ttl_ms=self._matrix.ttl_ms(outcome.action),
            reason_codes=reason_codes,
            rule_id=outcome.rule_id,
            predicate_trace_id=evaluation.predicate_trace_id,
            evidence_record_id=evaluation.evidence_record_id,
            created_at=evaluation.evaluated_at,
            config_hash=self._settings.config_hash,
            decision_duration_ns=duration_ns + evaluation.engine_duration_ns,
        )

    def direct(
        self,
        device_id: str,
        state: TrustState,
        context: TransitionContext,
        *,
        strategy: str,
        reason_codes: tuple[str, ...] = (),
    ) -> Decision:
        """Produce a decision without a trust evaluation.

        Used by the baseline strategies, which by definition do not run the
        CA-ZTCF evidence pipeline. They still emit the same ``Decision`` shape so
        that the enforcement point, audit output and metrics are identical across
        all three strategies and the comparison stays fair.
        """
        started_ns = self._clock.monotonic_ns()
        outcome = self._matrix.lookup(state, context)
        duration_ns = max(0, self._clock.monotonic_ns() - started_ns)
        return Decision(
            device_id=device_id,
            strategy=strategy,
            trust_state=state,
            transition_context=context,
            action=outcome.action,
            scope=outcome.scope.resolve(device_id),
            ttl_ms=self._matrix.ttl_ms(outcome.action),
            reason_codes=tuple(dict.fromkeys(outcome.reason_codes + reason_codes)),
            rule_id=outcome.rule_id,
            created_at=self._clock.now(),
            config_hash=self._settings.config_hash,
            decision_duration_ns=duration_ns,
        )


__all__ = ["PolicyEvaluator"]
