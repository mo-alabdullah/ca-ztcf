"""The record of one trust evaluation.

Everything needed to replay an evaluation is captured here: the evidence record
identifier, the full predicate vector, the rule that fired, the reason codes, the
configuration hash and the measured engine duration.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from ca_ztcf.evidence.predicates import PredicateResult
from ca_ztcf.trust_engine.states import TrustState


class TrustEvaluation(BaseModel):
    """Outcome of the trust engine for one device at one instant."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evaluation_id: str = Field(default_factory=lambda: f"trs-{uuid.uuid4().hex[:16]}")
    device_id: str
    previous_state: TrustState | None
    new_state: TrustState
    firing_rule: str
    reason_codes: tuple[str, ...]
    predicate_trace_id: str
    predicate_vector: tuple[PredicateResult, ...]
    evidence_record_id: str
    evaluated_at: datetime
    engine_duration_ns: int
    config_hash: str

    @property
    def state_changed(self) -> bool:
        return self.previous_state is not None and self.previous_state is not self.new_state

    def predicate_map(self) -> dict[str, bool]:
        return {item.predicate_id.value: item.result for item in self.predicate_vector}


__all__ = ["TrustEvaluation"]
