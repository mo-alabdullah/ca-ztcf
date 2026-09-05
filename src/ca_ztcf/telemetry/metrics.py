"""Prometheus-compatible metrics.

A dedicated registry is used rather than the process-global default so that tests
can construct an isolated metrics object without duplicate-timeseries errors.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

_DURATION_BUCKETS = (
    0.0001,
    0.00025,
    0.0005,
    0.001,
    0.0025,
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
)


class Metrics:
    """The metric set exported by the CA-ZTCF service."""

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry if registry is not None else CollectorRegistry()

        self.decisions_total = Counter(
            "ca_ztcf_decisions_total",
            "Access decisions produced, by strategy, trust state, transition context and action.",
            ["strategy", "trust_state", "transition_context", "action"],
            registry=self.registry,
        )
        self.decision_duration_seconds = Histogram(
            "ca_ztcf_decision_duration_seconds",
            "Wall-clock duration of decision production, by strategy.",
            ["strategy"],
            buckets=_DURATION_BUCKETS,
            registry=self.registry,
        )
        self.trust_state_total = Counter(
            "ca_ztcf_trust_state_total",
            "Trust states derived, by state and by the rule that fired.",
            ["trust_state", "firing_rule"],
            registry=self.registry,
        )
        self.policy_actions_total = Counter(
            "ca_ztcf_policy_actions_total",
            "Enforcement actions selected, by action and policy rule.",
            ["action", "rule_id"],
            registry=self.registry,
        )
        self.transition_events_total = Counter(
            "ca_ztcf_transition_events_total",
            "Access-domain transitions detected, by source and target domain.",
            ["from_domain", "to_domain"],
            registry=self.registry,
        )
        self.auth_failures_total = Counter(
            "ca_ztcf_auth_failures_total",
            "Authentication failures observed, by reason code.",
            ["reason"],
            registry=self.registry,
        )
        self.engine_duration_seconds = Histogram(
            "ca_ztcf_engine_duration_seconds",
            "Duration of pure trust-engine predicate evaluation.",
            buckets=_DURATION_BUCKETS,
            registry=self.registry,
        )

    def render(self) -> bytes:
        return generate_latest(self.registry)


__all__ = ["CONTENT_TYPE", "Metrics"]
