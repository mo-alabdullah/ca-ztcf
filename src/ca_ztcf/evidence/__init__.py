"""The Dual-Context Evidence Model and the criteria predicates."""

from __future__ import annotations

from ca_ztcf.evidence.assembler import AssemblerInputs, EvidenceAssembler
from ca_ztcf.evidence.models import (
    EvidenceCategory,
    EvidenceItem,
    EvidenceRecord,
    ValidationStatus,
)
from ca_ztcf.evidence.predicates import (
    PredicateEvaluator,
    PredicateId,
    PredicateResult,
    PredicateVector,
)

__all__ = [
    "AssemblerInputs",
    "EvidenceAssembler",
    "EvidenceCategory",
    "EvidenceItem",
    "EvidenceRecord",
    "PredicateEvaluator",
    "PredicateId",
    "PredicateResult",
    "PredicateVector",
    "ValidationStatus",
]
