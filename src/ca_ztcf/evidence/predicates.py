"""The eleven named predicates C1-C11.

Design decision: the trust algorithm is **criteria-based and contextual** in the
sense of NIST SP 800-207 clause 3.3.1, which distinguishes criteria-based from
score-based algorithms and singular from contextual ones. No weights, no scores,
no probability, no machine learning. Every predicate returns a reason code and the
evidence items it consulted, so that a decision can always be explained and
replayed from its recorded evidence.

See ``docs/adr/ADR-0001-criteria-based-contextual-trust.md``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ca_ztcf.config import Settings
from ca_ztcf.evidence import models as m
from ca_ztcf.evidence.models import EvidenceRecord


class PredicateId(StrEnum):
    """Stable identifiers. Never renumber: audit records refer to these."""

    C1 = "C1"
    C2 = "C2"
    C3 = "C3"
    C4 = "C4"
    C5 = "C5"
    C6 = "C6"
    C7 = "C7"
    C8 = "C8"
    C9 = "C9"
    C10 = "C10"
    C11 = "C11"


PREDICATE_NAMES: dict[PredicateId, str] = {
    PredicateId.C1: "IDENTITY_VALID",
    PredicateId.C2: "POP_FRESH",
    PredicateId.C3: "BINDING_PRESENT",
    PredicateId.C4: "BINDING_FRESH",
    PredicateId.C5: "BINDING_CONSISTENT",
    PredicateId.C6: "DOMAIN_STABLE",
    PredicateId.C7: "TRANSITION_RECENT",
    PredicateId.C8: "RATE_OK",
    PredicateId.C9: "AUTHN_FAILURES_OK",
    PredicateId.C10: "SESSION_CONSISTENT",
    PredicateId.C11: "DOMAIN_POSTURE_OK",
}

PREDICATE_PURPOSE: dict[PredicateId, str] = {
    PredicateId.C1: "The device is registered and administratively enabled.",
    PredicateId.C2: "A verified proof-of-possession exists and is within its lifetime.",
    PredicateId.C3: "An access domain currently asserts a binding for the peer address.",
    PredicateId.C4: "That binding has been refreshed within the configured freshness bound.",
    PredicateId.C5: "That binding is not already attributed to a different device.",
    PredicateId.C6: "No access-domain transition falls inside the stability window.",
    PredicateId.C7: "An access-domain transition falls inside the transition window.",
    PredicateId.C8: "Transitions within the rate window are at or below the configured limit.",
    PredicateId.C9: "Authentication failures within the window are at or below the limit.",
    PredicateId.C10: "The service-layer session identity still matches the device identity.",
    PredicateId.C11: "The observed access context satisfies the configured posture allow-lists.",
}


class PredicateResult(BaseModel):
    """The outcome of one predicate, with its justification."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    predicate_id: PredicateId
    name: str
    result: bool
    reason: str
    evidence_refs: tuple[str, ...] = ()
    evaluated_at: datetime

    def __bool__(self) -> bool:
        return self.result


class PredicateVector(BaseModel):
    """All eleven predicate results for one evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trace_id: str = Field(default_factory=lambda: f"prd-{uuid.uuid4().hex[:16]}")
    device_id: str
    evidence_record_id: str
    evaluated_at: datetime
    results: tuple[PredicateResult, ...]

    def get(self, predicate_id: PredicateId) -> PredicateResult:
        for item in self.results:
            if item.predicate_id is predicate_id:
                return item
        raise KeyError(f"predicate {predicate_id} was not evaluated")

    def ok(self, predicate_id: PredicateId) -> bool:
        return self.get(predicate_id).result

    def failed(self) -> tuple[PredicateResult, ...]:
        return tuple(item for item in self.results if not item.result)

    def reasons_for_failures(self) -> tuple[str, ...]:
        return tuple(item.reason for item in self.failed())

    def as_map(self) -> dict[str, bool]:
        return {item.predicate_id.value: item.result for item in self.results}


class PredicateEvaluator:
    """Evaluates C1-C11 against an evidence record and the configured thresholds."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def evaluate(self, record: EvidenceRecord) -> PredicateVector:
        now = record.assembled_at
        cfg = self._settings
        results: list[PredicateResult] = []

        def emit(
            predicate_id: PredicateId,
            result: bool,
            reason: str,
            refs: tuple[str, ...],
        ) -> None:
            results.append(
                PredicateResult(
                    predicate_id=predicate_id,
                    name=PREDICATE_NAMES[predicate_id],
                    result=result,
                    reason=reason,
                    evidence_refs=refs,
                    evaluated_at=now,
                )
            )

        # C1 IDENTITY_VALID
        registered = record.flag(m.IDENTITY_REGISTERED)
        enabled = record.flag(m.IDENTITY_ENABLED)
        if not registered:
            emit(PredicateId.C1, False, "DEVICE_NOT_REGISTERED", (m.IDENTITY_REGISTERED,))
        elif not enabled:
            status_item = record.item(m.IDENTITY_ENABLED)
            detail = status_item.detail if status_item is not None else "DISABLED"
            emit(
                PredicateId.C1,
                False,
                f"DEVICE_NOT_ENABLED:{detail}",
                (m.IDENTITY_REGISTERED, m.IDENTITY_ENABLED),
            )
        else:
            emit(
                PredicateId.C1, True, "IDENTITY_VALID", (m.IDENTITY_REGISTERED, m.IDENTITY_ENABLED)
            )

        # C2 POP_FRESH
        pop_item = record.item(m.PROOF_OF_POSSESSION_VALID)
        pop_ok = record.flag(m.PROOF_OF_POSSESSION_VALID)
        pop_reason = (
            "POP_FRESH"
            if pop_ok
            else (pop_item.detail if pop_item is not None and pop_item.detail else "POP_NOT_FRESH")
        )
        emit(PredicateId.C2, pop_ok, pop_reason, (m.PROOF_OF_POSSESSION_VALID,))

        # C3 BINDING_PRESENT
        binding_present = record.flag(m.BINDING_PRESENT)
        emit(
            PredicateId.C3,
            binding_present,
            "BINDING_PRESENT" if binding_present else "NO_ACCESS_BINDING_FOR_PEER_ADDRESS",
            (m.BINDING_PRESENT, m.BINDING_DOMAIN),
        )

        # C4 BINDING_FRESH
        binding_fresh = record.flag(m.BINDING_FRESH)
        fresh_item = record.item(m.BINDING_FRESH)
        if binding_fresh:
            fresh_reason = "BINDING_FRESH"
        elif not binding_present:
            fresh_reason = "NO_ACCESS_BINDING_FOR_PEER_ADDRESS"
        else:
            detail = fresh_item.detail if fresh_item is not None else ""
            fresh_reason = (
                f"BINDING_STALE:max_s={cfg.evidence.binding_freshness_max_s}"
                f"{':' + detail if detail else ''}"
            )
        emit(PredicateId.C4, binding_fresh, fresh_reason, (m.BINDING_FRESH,))

        # C5 BINDING_CONSISTENT
        consistent = record.flag(m.BINDING_CONSISTENT)
        emit(
            PredicateId.C5,
            consistent,
            "BINDING_CONSISTENT" if consistent else "BINDING_CLAIMED_BY_ANOTHER_DEVICE",
            (m.BINDING_CONSISTENT, m.IDENTITY_MISMATCH),
        )

        # C6 DOMAIN_STABLE / C7 TRANSITION_RECENT
        transition_recent = record.flag(m.TRANSITION_DETECTED)
        age_value = record.value(m.TRANSITION_AGE)
        age_text = f"age_s={age_value}" if age_value is not None else "no_transition_on_record"
        emit(
            PredicateId.C6,
            not transition_recent,
            "DOMAIN_STABLE"
            if not transition_recent
            else f"TRANSITION_WITHIN_STABILITY_WINDOW:{age_text}",
            (m.TRANSITION_DETECTED, m.TRANSITION_AGE),
        )
        emit(
            PredicateId.C7,
            transition_recent,
            f"TRANSITION_RECENT:{age_text}" if transition_recent else "NO_RECENT_TRANSITION",
            (m.TRANSITION_DETECTED, m.TRANSITION_AGE),
        )

        # C8 RATE_OK
        count = record.number(m.TRANSITION_COUNT_WINDOW)
        limit = cfg.transition.max_transitions_per_window
        rate_ok = count <= limit
        emit(
            PredicateId.C8,
            rate_ok,
            f"RATE_OK:{count}<={limit}" if rate_ok else f"TRANSITION_RATE_EXCEEDED:{count}>{limit}",
            (m.TRANSITION_COUNT_WINDOW,),
        )

        # C9 AUTHN_FAILURES_OK
        failures = record.number(m.AUTHENTICATION_FAILURE_COUNT)
        max_failures = cfg.security.max_authn_failures
        failures_ok = failures <= max_failures
        emit(
            PredicateId.C9,
            failures_ok,
            f"AUTHN_FAILURES_OK:{failures}<={max_failures}"
            if failures_ok
            else f"AUTHN_FAILURES_EXCEEDED:{failures}>{max_failures}",
            (m.AUTHENTICATION_FAILURE_COUNT,),
        )

        # C10 SESSION_CONSISTENT
        session_mismatch = record.flag(m.SESSION_MISMATCH)
        emit(
            PredicateId.C10,
            not session_mismatch,
            "SESSION_CONSISTENT" if not session_mismatch else "SESSION_IDENTITY_MISMATCH",
            (m.SESSION_MISMATCH,),
        )

        # C11 DOMAIN_POSTURE_OK
        posture_ok = record.flag(m.DOMAIN_POSTURE_OK)
        posture_item = record.item(m.DOMAIN_POSTURE_OK)
        posture_reason = posture_item.detail if posture_item is not None else "POSTURE_UNKNOWN"
        emit(
            PredicateId.C11,
            posture_ok,
            posture_reason,
            (m.DOMAIN_POSTURE_OK, m.UNAUTHORIZED_CONTEXT),
        )

        return PredicateVector(
            device_id=record.device_id,
            evidence_record_id=record.record_id,
            evaluated_at=now,
            results=tuple(results),
        )


__all__ = [
    "PREDICATE_NAMES",
    "PREDICATE_PURPOSE",
    "PredicateEvaluator",
    "PredicateId",
    "PredicateResult",
    "PredicateVector",
]
