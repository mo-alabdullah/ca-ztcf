"""The Policy Enforcement Point interface.

Keeping the decision (Policy Engine) separate from its enforcement follows the
PE/PA/PEP decomposition of NIST SP 800-207. The MQTT proxy enforcement point
arrives in Batch F; this milestone ships the in-memory implementation used by the
unit and integration tests.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ca_ztcf.enforcement.models import EnforcementRequest, EnforcementResult
from ca_ztcf.policy.models import Decision


class PolicyEnforcementPoint(ABC):
    """Applies decisions and evaluates resource requests against them."""

    @abstractmethod
    def apply(self, decision: Decision) -> None:
        """Install a decision as the active decision for its device."""

    @abstractmethod
    def check(self, request: EnforcementRequest) -> EnforcementResult:
        """Evaluate a request against the device's active decision."""

    @abstractmethod
    def active_decision(self, device_id: str) -> Decision | None:
        """Return the device's active, unexpired decision, if any."""

    @abstractmethod
    def revoke(self, device_id: str) -> None:
        """Discard any active decision for the device."""


def topic_matches(pattern: str, topic: str) -> bool:
    """MQTT-style topic filter matching.

    ``+`` matches exactly one level; ``#`` matches the remainder and must be the
    final level. Implemented here rather than pulled from a broker library so that
    the matching semantics used in decisions are explicit and testable.
    """
    if pattern == "#":
        return True
    pattern_levels = pattern.split("/")
    topic_levels = topic.split("/")

    for index, level in enumerate(pattern_levels):
        if level == "#":
            return index == len(pattern_levels) - 1
        if index >= len(topic_levels):
            return False
        if level == "+":
            continue
        if level != topic_levels[index]:
            return False
    return len(pattern_levels) == len(topic_levels)


__all__ = ["PolicyEnforcementPoint", "topic_matches"]
