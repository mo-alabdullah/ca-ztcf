"""The Trust Continuity Engine.

An ordered rule system over the eleven predicates. The first rule whose condition
holds determines the state; the rule identifier and the reason codes are recorded,
so every decision can be explained and replayed.

Deterministic by construction: given the same evidence record and the same
configuration, the derived state, the firing rule and the reason codes are always
identical. Only the generated evaluation identifier and the measured duration
differ between runs, and neither participates in the derivation.

No weights, no scores, no probability, no machine learning.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ca_ztcf.clock import Clock
from ca_ztcf.config import Settings
from ca_ztcf.evidence.models import EvidenceRecord
from ca_ztcf.evidence.predicates import PredicateId as P
from ca_ztcf.evidence.predicates import PredicateVector
from ca_ztcf.trust_engine.decision_trace import TrustEvaluation
from ca_ztcf.trust_engine.states import TrustState


@dataclass(frozen=True)
class TrustRule:
    """One rule of the ordered derivation."""

    rule_id: str
    state: TrustState
    description: str
    condition: Callable[[PredicateVector], bool]
    reasons: Callable[[PredicateVector], tuple[str, ...]]


def _failed_reasons(vector: PredicateVector, ids: tuple[P, ...]) -> tuple[str, ...]:
    """Reason codes of the given predicates that did not hold, in declaration order."""
    return tuple(vector.get(pid).reason for pid in ids if not vector.ok(pid))


# ---------------------------------------------------------------------------
# The ordered rule system.
#
# R0  not C1 because the device is not registered   -> UNKNOWN
# R1  not C1 (registered but disabled) or not C5    -> UNTRUSTED
# R2  not C8 or not C9 or not C10 or (C3 and not C11) -> SUSPICIOUS
# R3  not C3 or not C4 or not C2                    -> DEGRADED
# R4  C7                                            -> TRANSITIONAL
# R5  otherwise                                     -> STABLE
#
# Ordering rationale:
#   * UNKNOWN precedes everything: with no registry entry there is no identity
#     against which any other evidence can be interpreted.
#   * UNTRUSTED precedes SUSPICIOUS: a revoked identity or a binding claimed by
#     another device is a direct contradiction and outranks a rate anomaly.
#   * SUSPICIOUS precedes DEGRADED: contradictory evidence must never be masked by
#     evidence that also happens to be stale.
#   * DEGRADED precedes TRANSITIONAL: a device whose evidence is missing or stale
#     is not merely mid-transition, even if a transition is also in progress.
#   * The posture clause is guarded by C3 so that a device with no binding at all
#     is DEGRADED (missing evidence) rather than SUSPICIOUS (contradiction).
# ---------------------------------------------------------------------------

RULES: tuple[TrustRule, ...] = (
    TrustRule(
        rule_id="R0",
        state=TrustState.UNKNOWN,
        description="No valid device registry entry exists.",
        condition=lambda v: v.get(P.C1).reason == "DEVICE_NOT_REGISTERED",
        reasons=lambda v: ("DEVICE_NOT_REGISTERED",),
    ),
    TrustRule(
        rule_id="R1",
        state=TrustState.UNTRUSTED,
        description="Identity validation failed, or the binding is claimed by another device.",
        condition=lambda v: not v.ok(P.C1) or not v.ok(P.C5),
        reasons=lambda v: _failed_reasons(v, (P.C1, P.C5)),
    ),
    TrustRule(
        rule_id="R2",
        state=TrustState.SUSPICIOUS,
        description="Contradictory or strongly abnormal evidence.",
        condition=lambda v: (
            not v.ok(P.C8) or not v.ok(P.C9) or not v.ok(P.C10) or (v.ok(P.C3) and not v.ok(P.C11))
        ),
        reasons=lambda v: (
            _failed_reasons(v, (P.C8, P.C9, P.C10))
            + ((v.get(P.C11).reason,) if v.ok(P.C3) and not v.ok(P.C11) else ())
        ),
    ),
    TrustRule(
        rule_id="R3",
        state=TrustState.DEGRADED,
        description="Evidence incomplete, stale or unavailable, without contradiction.",
        condition=lambda v: not v.ok(P.C3) or not v.ok(P.C4) or not v.ok(P.C2),
        reasons=lambda v: _failed_reasons(v, (P.C3, P.C4, P.C2)),
    ),
    TrustRule(
        rule_id="R4",
        state=TrustState.TRANSITIONAL,
        description="A legitimate access-domain transition is within the transition window.",
        condition=lambda v: v.ok(P.C7),
        reasons=lambda v: (v.get(P.C7).reason,),
    ),
    TrustRule(
        rule_id="R5",
        state=TrustState.STABLE,
        description="All predicates hold and no transition is within the stability window.",
        condition=lambda v: True,
        reasons=lambda v: ("EVIDENCE_CONSISTENT",),
    ),
)


class TrustEngine:
    """Derives a trust continuity state from a predicate vector."""

    def __init__(self, settings: Settings, clock: Clock) -> None:
        self._settings = settings
        self._clock = clock

    @property
    def rules(self) -> tuple[TrustRule, ...]:
        return RULES

    def evaluate(
        self,
        record: EvidenceRecord,
        vector: PredicateVector,
        *,
        previous_state: TrustState | None = None,
    ) -> TrustEvaluation:
        started_ns = self._clock.monotonic_ns()

        firing_rule = RULES[-1]
        reason_codes: tuple[str, ...] = ()
        for rule in RULES:
            if rule.condition(vector):
                firing_rule = rule
                reason_codes = rule.reasons(vector)
                break

        duration_ns = max(0, self._clock.monotonic_ns() - started_ns)

        return TrustEvaluation(
            device_id=record.device_id,
            previous_state=previous_state,
            new_state=firing_rule.state,
            firing_rule=firing_rule.rule_id,
            reason_codes=reason_codes or (firing_rule.rule_id,),
            predicate_trace_id=vector.trace_id,
            predicate_vector=vector.results,
            evidence_record_id=record.record_id,
            evaluated_at=record.assembled_at,
            engine_duration_ns=duration_ns,
            config_hash=self._settings.config_hash,
        )


class TrustStateManager:
    """Holds the current trust state per device, plus a bounded history."""

    def __init__(self, *, history_limit: int = 64) -> None:
        self._current: dict[str, TrustState] = {}
        self._entered_at: dict[str, str] = {}
        self._history: dict[str, list[tuple[str, TrustState]]] = {}
        self._history_limit = history_limit

    def current(self, device_id: str) -> TrustState | None:
        return self._current.get(device_id)

    def record(self, evaluation: TrustEvaluation) -> TrustState | None:
        """Store the outcome. Returns the state that was previously held."""
        previous = self._current.get(evaluation.device_id)
        self._current[evaluation.device_id] = evaluation.new_state
        if previous is not evaluation.new_state:
            self._entered_at[evaluation.device_id] = evaluation.evaluated_at.isoformat()
        entries = self._history.setdefault(evaluation.device_id, [])
        entries.append((evaluation.evaluated_at.isoformat(), evaluation.new_state))
        if len(entries) > self._history_limit:
            del entries[: len(entries) - self._history_limit]
        return previous

    def entered_at(self, device_id: str) -> str | None:
        return self._entered_at.get(device_id)

    def history(self, device_id: str) -> list[tuple[str, TrustState]]:
        return list(self._history.get(device_id, []))

    def reset(self, device_id: str | None = None) -> None:
        if device_id is None:
            self._current.clear()
            self._entered_at.clear()
            self._history.clear()
        else:
            self._current.pop(device_id, None)
            self._entered_at.pop(device_id, None)
            self._history.pop(device_id, None)

    def counts(self) -> dict[str, int]:
        tally: dict[str, int] = {}
        for state in self._current.values():
            tally[state.value] = tally.get(state.value, 0) + 1
        return tally


__all__ = ["RULES", "TrustEngine", "TrustRule", "TrustStateManager"]
