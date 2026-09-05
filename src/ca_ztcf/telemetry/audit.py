"""Append-only JSONL research audit output.

One record per decision, carrying everything needed to replay it: configuration
hash, evidence record identifier, full predicate trace, trust state, transition
context, action, reason codes, timestamps and durations.

Redaction is applied unconditionally and recursively. Keys matching the configured
denylist are replaced with a marker, and any string that looks like PEM key
material is replaced regardless of its key. Redaction is a property of the writer,
not of its callers, so no caller can bypass it.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from ca_ztcf.config import AuditSettings
from ca_ztcf.policy.models import Decision
from ca_ztcf.trust_engine.decision_trace import TrustEvaluation

REDACTED = "[REDACTED]"

_PEM_MARKERS = ("-----BEGIN", "PRIVATE KEY", "BEGIN OPENSSH")


def _looks_like_key_material(value: str) -> bool:
    upper = value.upper()
    return any(marker in upper for marker in _PEM_MARKERS)


def redact_mapping(value: dict[str, Any], denylist: frozenset[str]) -> dict[str, Any]:
    """Redact a mapping, preserving its type for callers that need a dictionary."""
    return {
        key: (REDACTED if key.lower() in denylist else redact(item, denylist))
        for key, item in value.items()
    }


def redact(value: Any, denylist: frozenset[str]) -> Any:
    """Recursively redact sensitive keys and anything resembling key material."""
    if isinstance(value, dict):
        return redact_mapping(value, denylist)
    if isinstance(value, (list, tuple)):
        return [redact(item, denylist) for item in value]
    if isinstance(value, str) and _looks_like_key_material(value):
        return REDACTED
    return value


class AuditWriter:
    """Thread-safe, append-only JSONL writer."""

    def __init__(self, settings: AuditSettings, *, base_dir: Path | None = None) -> None:
        self._enabled = settings.enabled
        self._denylist = frozenset(key.lower() for key in settings.redact_keys)
        base = base_dir if base_dir is not None else Path.cwd()
        self._path = (base / settings.path).resolve()
        self._lock = threading.Lock()
        self._written = 0
        # Decision records indexed by identifier, so enforcement can be traced back
        # to the evaluation that produced it without re-reading the whole log.
        self._by_decision: dict[str, dict[str, Any]] = {}
        if self._enabled:
            self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    @property
    def written(self) -> int:
        return self._written

    @property
    def enabled(self) -> bool:
        return self._enabled

    def write(self, record: dict[str, Any]) -> dict[str, Any]:
        """Redact and append one record. Returns the redacted record."""
        cleaned = redact_mapping(record, self._denylist)
        if not self._enabled:
            return cleaned
        line = json.dumps(cleaned, default=str, separators=(",", ":"), sort_keys=True)
        with self._lock:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            self._written += 1
        return cleaned

    def write_decision(
        self,
        decision: Decision,
        *,
        evaluation: TrustEvaluation | None = None,
        recorded_at: datetime | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Write a complete, replayable decision record."""
        record: dict[str, Any] = {
            "record_type": "decision",
            "recorded_at": (recorded_at or decision.created_at).isoformat(),
            "decision_id": decision.decision_id,
            "device_id": decision.device_id,
            "strategy": decision.strategy,
            "trust_state": decision.trust_state.value,
            "transition_context": decision.transition_context.value,
            "action": decision.action.value,
            "scope": {
                "name": decision.scope.name,
                "allow": list(decision.scope.allow),
                "deny": list(decision.scope.deny),
            },
            "ttl_ms": decision.ttl_ms,
            "reason_codes": list(decision.reason_codes),
            "policy_rule_id": decision.rule_id,
            "predicate_trace_id": decision.predicate_trace_id,
            "evidence_record_id": decision.evidence_record_id,
            "created_at": decision.created_at.isoformat(),
            "config_hash": decision.config_hash,
            "decision_duration_ns": decision.decision_duration_ns,
        }
        if evaluation is not None:
            record["trust_evaluation"] = {
                "evaluation_id": evaluation.evaluation_id,
                "previous_state": (
                    evaluation.previous_state.value if evaluation.previous_state else None
                ),
                "new_state": evaluation.new_state.value,
                "firing_rule": evaluation.firing_rule,
                "reason_codes": list(evaluation.reason_codes),
                "engine_duration_ns": evaluation.engine_duration_ns,
                "predicates": [
                    {
                        "predicate_id": item.predicate_id.value,
                        "name": item.name,
                        "result": item.result,
                        "reason": item.reason,
                        "evidence_refs": list(item.evidence_refs),
                    }
                    for item in evaluation.predicate_vector
                ],
            }
        if extra:
            record["extra"] = extra
        written = self.write(record)
        with self._lock:
            self._by_decision[decision.decision_id] = written
        return written

    def find_decision(self, decision_id: str) -> dict[str, Any] | None:
        """Return the redacted record a decision produced, if it is still indexed."""
        with self._lock:
            return self._by_decision.get(decision_id)

    @property
    def indexed_decisions(self) -> int:
        with self._lock:
            return len(self._by_decision)


__all__ = ["REDACTED", "AuditWriter", "redact", "redact_mapping"]
