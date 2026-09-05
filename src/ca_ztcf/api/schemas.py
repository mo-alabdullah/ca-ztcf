"""Request and response schemas for the HTTP API.

The API never accepts or returns private key material. ``DeviceResponse`` carries
the public key and its fingerprint only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ca_ztcf.collectors.base import AccessDomain, SourceMode
from ca_ztcf.collectors.transition import TransitionContext
from ca_ztcf.identity.models import DeviceStatus, PoPAlgorithm
from ca_ztcf.policy.models import PolicyAction
from ca_ztcf.trust_engine.states import TrustState


class HealthResponse(BaseModel):
    status: str
    service: str


class ReadyResponse(BaseModel):
    status: str
    checks: dict[str, str]


class VersionResponse(BaseModel):
    service: str
    version: str
    schema_version: str
    environment: str


class ConfigHashResponse(BaseModel):
    config_hash: str
    short_config_hash: str
    config_dir: str


# --- devices ---------------------------------------------------------------


class RegisterDeviceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str = Field(min_length=1, max_length=128)
    public_key_pem: str = Field(description="PEM-encoded Ed25519 public key.")
    labels: dict[str, str] = Field(default_factory=dict)
    notes: str = ""


class DeviceStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: DeviceStatus


class DeviceResponse(BaseModel):
    device_id: str
    public_key_fingerprint: str
    public_key_pem: str
    status: DeviceStatus
    created_at: datetime
    updated_at: datetime
    labels: dict[str, str]
    notes: str


class NonceResponse(BaseModel):
    device_id: str
    nonce: str
    expires_at: datetime
    algorithm: PoPAlgorithm = "ed25519"


# --- collectors ------------------------------------------------------------


class CollectorEventRequest(BaseModel):
    """A normalised access-domain event.

    ``source_mode`` must be stated. Development fixtures use
    ``synthetic_fixture``; only a real testbed may use ``live_testbed``.
    """

    model_config = ConfigDict(extra="forbid")

    domain: AccessDomain
    peer_address: str
    observed_at: datetime | None = None
    source_mode: SourceMode = SourceMode.SYNTHETIC_FIXTURE
    event_type: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    binding_lifetime_s: int | None = 120


class BindingResponse(BaseModel):
    binding_id: str
    domain: AccessDomain
    peer_address: str
    device_ref: str | None
    source: str
    source_mode: SourceMode
    first_seen: datetime
    last_seen: datetime
    expires_at: datetime | None
    attributes: dict[str, str]


# --- transitions -----------------------------------------------------------


class TransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str
    domain: AccessDomain
    peer_address: str | None = None
    at: datetime | None = None


class TransitionResponse(BaseModel):
    device_id: str
    transition_detected: bool
    transition_context: TransitionContext
    from_domain: AccessDomain | None = None
    to_domain: AccessDomain | None = None
    detected_at: datetime | None = None
    gap_ms: int | None = None
    transitions_in_window: int = 0
    repeated: bool = False


# --- evaluation ------------------------------------------------------------


class ProofPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nonce: str
    signature: str
    algorithm: PoPAlgorithm = "ed25519"


class EvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str
    peer_address: str
    domain: AccessDomain
    session_identity: str | None = None
    proof: ProofPayload | None = None
    resource: str | None = None
    at: datetime | None = Field(
        default=None,
        description=(
            "Research affordance: evaluate as at this instant instead of now, so a "
            "scenario can express elapsed time without sleeping."
        ),
    )


class PredicateResponse(BaseModel):
    predicate_id: str
    name: str
    result: bool
    reason: str
    evidence_refs: list[str]


class EvidenceItemResponse(BaseModel):
    name: str
    category: str
    value: bool | int | float | str | None
    source: str
    source_mode: SourceMode
    observed_at: datetime
    expires_at: datetime | None
    validation: str
    detail: str


class EvidenceEvaluateResponse(BaseModel):
    device_id: str
    schema_version: str
    evidence_record_id: str
    assembled_at: datetime
    config_hash: str
    contains_synthetic_evidence: bool
    items: list[EvidenceItemResponse]
    predicates: list[PredicateResponse]
    trust_state: TrustState
    previous_state: TrustState | None
    firing_rule: str
    reason_codes: list[str]
    engine_duration_ns: int
    transition_context: TransitionContext


class ScopeResponse(BaseModel):
    name: str
    allow: list[str]
    deny: list[str]


class DecisionResponse(BaseModel):
    decision_id: str
    device_id: str
    strategy: str
    trust_state: TrustState
    transition_context: TransitionContext
    action: PolicyAction
    scope: ScopeResponse
    ttl_ms: int
    reason_codes: list[str]
    policy_rule_id: str
    predicate_trace_id: str | None
    evidence_record_id: str | None
    created_at: datetime
    config_hash: str
    decision_duration_ns: int


class DecisionEvaluateRequest(EvaluateRequest):
    strategy: str | None = Field(
        default=None, description="Configured strategy name; defaults to ca_ztcf."
    )


class ErrorResponse(BaseModel):
    code: str
    message: str


__all__ = [
    "BindingResponse",
    "CollectorEventRequest",
    "ConfigHashResponse",
    "DecisionEvaluateRequest",
    "DecisionResponse",
    "DeviceResponse",
    "DeviceStatusRequest",
    "ErrorResponse",
    "EvaluateRequest",
    "EvidenceEvaluateResponse",
    "EvidenceItemResponse",
    "HealthResponse",
    "NonceResponse",
    "PredicateResponse",
    "ProofPayload",
    "ReadyResponse",
    "RegisterDeviceRequest",
    "ScopeResponse",
    "TransitionRequest",
    "TransitionResponse",
    "VersionResponse",
]
