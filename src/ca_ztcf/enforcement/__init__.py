"""Policy enforcement: interface, models, in-memory PEP and the MQTT gateway."""

from __future__ import annotations

from ca_ztcf.enforcement.decision_client import (
    DecisionClient,
    DecisionRequest,
    DecisionResult,
    HttpDecisionClient,
    LocalDecisionClient,
)
from ca_ztcf.enforcement.interface import PolicyEnforcementPoint, topic_matches
from ca_ztcf.enforcement.memory_pep import MemoryPEP
from ca_ztcf.enforcement.models import EnforcementRequest, EnforcementResult, ResourceOperation
from ca_ztcf.enforcement.mqtt_gateway import (
    GatewayConfig,
    MqttEnforcementGateway,
    SessionStats,
    parse_proof,
    scope_permits,
)

__all__ = [
    "DecisionClient",
    "DecisionRequest",
    "DecisionResult",
    "EnforcementRequest",
    "EnforcementResult",
    "GatewayConfig",
    "HttpDecisionClient",
    "LocalDecisionClient",
    "MemoryPEP",
    "MqttEnforcementGateway",
    "PolicyEnforcementPoint",
    "ResourceOperation",
    "SessionStats",
    "parse_proof",
    "scope_permits",
    "topic_matches",
]
