"""Enforcement request and result models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from ca_ztcf.policy.models import PolicyAction


class ResourceOperation(StrEnum):
    """Operations a Policy Enforcement Point mediates.

    Named after MQTT operations because the Batch F enforcement point is an MQTT
    proxy, but the interface itself is transport-neutral.
    """

    CONNECT = "CONNECT"
    PUBLISH = "PUBLISH"
    SUBSCRIBE = "SUBSCRIBE"


class EnforcementRequest(BaseModel):
    """A device's attempt to perform an operation on a resource."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    device_id: str
    operation: ResourceOperation
    resource: str = ""


class EnforcementResult(BaseModel):
    """The outcome of enforcing an active decision against a request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    device_id: str
    permitted: bool
    reason: str
    action: PolicyAction | None = None
    decision_id: str | None = None
    evaluated_at: datetime


__all__ = ["EnforcementRequest", "EnforcementResult", "ResourceOperation"]
