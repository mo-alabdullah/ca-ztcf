"""Scenario definition schema.

A scenario is a declaration, written before anything runs. In particular the
ground truth is declared here and is **never** derived from CA-ZTCF output: if the
labels came from the system under test, every measurement of acceptance and
rejection would be circular.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ca_ztcf.collectors.base import AccessDomain, MeasurementTier, SourceMode
from ca_ztcf.policy.models import PolicyAction
from ca_ztcf.trust_engine.states import TrustState


class EventKind(StrEnum):
    """What the runner should do at one step of a scenario."""

    NR_SESSION = "nr_session"
    """Feed a synthetic 5G access event. Always ``source_mode: synthetic_fixture``."""

    WLAN_SESSION = "wlan_session"
    """Feed a Tier-1 WLAN authentication event."""

    MQTT_CONNECT = "mqtt_connect"
    MQTT_PUBLISH = "mqtt_publish"
    MQTT_SUBSCRIBE = "mqtt_subscribe"
    MQTT_DISCONNECT = "mqtt_disconnect"

    TRANSITION = "transition"
    """Switch the device's access-domain context and reconnect."""

    ADVANCE_TIME = "advance_time"
    """Move the scenario clock forward without sleeping."""

    EXPECT_DECISION = "expect_decision"
    """Evaluate a decision and compare it against the declared expectation."""

    COLLECTOR_OUTAGE = "collector_outage"
    """Mark a collector unavailable, to exercise degraded evidence."""

    COLLECTOR_RECOVERY = "collector_recovery"
    """Restore a collector, so recovery from DEGRADED can be observed."""

    IDENTITY_MISMATCH = "identity_mismatch"
    """A second device claims an access binding already attributed to another."""

    UNAUTHORIZED_CONTEXT = "unauthorized_context"
    """Feed an access binding whose context violates the posture allow-lists."""

    SESSION_MISMATCH = "session_mismatch"
    """Evaluate with a service-layer session identity that is not the device's."""

    STALE_EVIDENCE = "stale_evidence"
    """Let existing evidence age past its freshness bound without refreshing it."""

    RAPID_TRANSITIONS = "rapid_transitions"
    """Drive transitions faster than the configured rate limit permits."""

    CONCURRENT_TRANSITION = "concurrent_transition"
    """Transition several devices within one narrow window."""

    DEVICE_SWEEP = "device_sweep"
    """Run the declared workload for each device in turn, for scalability."""

    MIXED_WORKLOAD = "mixed_workload"
    """Generate a seeded mixture of legitimate and adversarial events."""


class GroundTruthLabel(StrEnum):
    """What a step *ought* to result in, declared before anything runs.

    A binary legitimate/illegitimate split is too coarse for this framework. A
    legitimate device whose evidence has gone stale ought to be restricted or
    stepped up, not allowed outright; scoring a step-up against it as a false
    rejection would penalise exactly the proportionate behaviour the design aims
    for. So the taxonomy records the *expected class of outcome*, and scoring asks
    whether the observed action falls in that class.

    Every label is fixed in the scenario file. None is ever derived from CA-ZTCF
    output: labels taken from the system under test would make every acceptance
    and rejection count circular.
    """

    LEGITIMATE_ALLOW = "LEGITIMATE_ALLOW"
    """A legitimate request that ought to be allowed at full scope."""

    LEGITIMATE_RESTRICT = "LEGITIMATE_RESTRICT"
    """Legitimate, but evidence is still settling: restricted scope is correct."""

    LEGITIMATE_STEP_UP = "LEGITIMATE_STEP_UP"
    """Legitimate, but evidence is incomplete or stale: a step-up is correct."""

    MALICIOUS_REJECT = "MALICIOUS_REJECT"
    """Illegitimate: the request ought to be denied or re-authentication forced."""

    MALICIOUS_QUARANTINE = "MALICIOUS_QUARANTINE"
    """Illegitimate and observed across a transition: quarantine is correct."""

    NOT_APPLICABLE = "NOT_APPLICABLE"
    """Setup or teardown; carries no expectation and is not scored."""

    @property
    def is_legitimate(self) -> bool:
        return self in _LEGITIMATE_LABELS

    @property
    def is_adversarial(self) -> bool:
        return self in _ADVERSARIAL_LABELS

    @property
    def scored(self) -> bool:
        return self is not GroundTruthLabel.NOT_APPLICABLE


_LEGITIMATE_LABELS = frozenset(
    {
        GroundTruthLabel.LEGITIMATE_ALLOW,
        GroundTruthLabel.LEGITIMATE_RESTRICT,
        GroundTruthLabel.LEGITIMATE_STEP_UP,
    }
)
_ADVERSARIAL_LABELS = frozenset(
    {GroundTruthLabel.MALICIOUS_REJECT, GroundTruthLabel.MALICIOUS_QUARANTINE}
)


ACCEPTABLE_ACTIONS: dict[GroundTruthLabel, frozenset[str]] = {
    # A legitimate device that ought to be fully allowed. Anything narrower is a
    # false rejection: the device was entitled to access and did not get it.
    GroundTruthLabel.LEGITIMATE_ALLOW: frozenset({"ALLOW"}),
    # Restriction is the correct answer, and full allow is also acceptable: being
    # less restrictive than required is not a rejection of a legitimate device.
    GroundTruthLabel.LEGITIMATE_RESTRICT: frozenset({"ALLOW", "ALLOW_WITH_RESTRICTIONS"}),
    # A step-up is correct; so is anything more permissive, since the device is
    # legitimate. Denial or quarantine is a false rejection.
    GroundTruthLabel.LEGITIMATE_STEP_UP: frozenset(
        {"ALLOW", "ALLOW_WITH_RESTRICTIONS", "STEP_UP_AUTHENTICATION"}
    ),
    # An adversarial request must not proceed. Re-authentication counts as a
    # rejection: the presented session is invalidated.
    GroundTruthLabel.MALICIOUS_REJECT: frozenset({"DENY", "REAUTHENTICATE", "QUARANTINE"}),
    GroundTruthLabel.MALICIOUS_QUARANTINE: frozenset({"QUARANTINE", "DENY", "REAUTHENTICATE"}),
}
"""Actions that satisfy each declared expectation.

Fixed here, next to the taxonomy, so that scoring cannot drift from the labels.
"""


class ScenarioEvent(BaseModel):
    """One step of a scenario."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    step: int = Field(ge=0)
    kind: EventKind
    device_index: int = Field(default=0, ge=0)
    other_device_index: int | None = Field(default=None, ge=0)
    """Second device, for identity-mismatch and cross-device steps."""
    domain: AccessDomain | None = None
    topic: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    advance_s: float = Field(default=0.0, ge=0.0)
    repeat: int = Field(default=1, ge=1)
    """How many times to perform this step, for rate and sweep steps."""
    interval_s: float = Field(default=0.0, ge=0.0)
    """Scenario time between repeats. Advanced on the clock, never slept."""
    device_range: tuple[int, int] | None = None
    """Inclusive device index range for sweep and concurrency steps."""
    session_identity: str | None = None
    """Explicit service-layer session identity, for session-mismatch steps."""
    posture_override: dict[str, str] = Field(default_factory=dict)
    """Binding attributes to override, for unauthorised-context steps."""
    legitimate_fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    """Legitimate share of a generated mixed workload."""
    adversarial_kinds: tuple[str, ...] = ()
    """Which abnormal conditions a mixed workload may draw from."""
    ground_truth: GroundTruthLabel = GroundTruthLabel.NOT_APPLICABLE
    expected_trust_state: TrustState | None = None
    expected_action: PolicyAction | None = None
    expected_actions: tuple[PolicyAction, ...] = ()
    """Alternatives, for steps where more than one outcome is acceptable."""
    expect_permitted: bool | None = None
    """Whether a publish or subscribe ought to succeed.

    Declared explicitly rather than inferred, because a legitimate device under a
    restricted scope is *correctly* refused a command topic; deriving the
    expectation from the label alone would score that proportionate refusal as a
    false rejection.
    """
    note: str = ""

    @model_validator(mode="after")
    def _expectation_is_single_valued(self) -> ScenarioEvent:
        if self.expected_action is not None and self.expected_actions:
            raise ValueError("declare either expected_action or expected_actions, not both")
        enforcement_kinds = {EventKind.MQTT_PUBLISH, EventKind.MQTT_SUBSCRIBE}
        if (
            self.kind in enforcement_kinds
            and self.ground_truth.scored
            and self.expect_permitted is None
        ):
            raise ValueError(
                f"step {self.step}: a scored {self.kind.value} must declare "
                f"expect_permitted, so the expectation cannot be inferred after "
                f"the fact"
            )
        return self


class ScenarioSetup(BaseModel):
    """Initial conditions of a scenario."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    register_devices: bool = True
    nr_address_prefix: str = "10.45.0."
    wlan_address_prefix: str = "192.168.60."
    address_offset: int = Field(default=2, ge=1)
    address_stride: int = Field(default=1, ge=1)
    """Address spacing between devices.

    Each device gets its own address in each domain. Sharing one address between
    devices makes the binding store attribute them to one another and every device
    after the first is correctly judged UNTRUSTED, which is an artefact of the
    harness rather than a property of the framework.
    """
    initial_domain: AccessDomain = AccessDomain.NR
    telemetry_topic: str = "dev/{device_id}/telemetry/reading"
    command_topic: str = "cmd/{device_id}/set"
    nr_source_mode: Literal[SourceMode.SYNTHETIC_FIXTURE] = SourceMode.SYNTHETIC_FIXTURE
    """Fixed. The 5G side of Tier 1 is a development fixture and nothing else."""
    wlan_source_mode: Literal[SourceMode.TIER1_WLAN_AUTH_EMULATION] = (
        SourceMode.TIER1_WLAN_AUTH_EMULATION
    )
    """Fixed. Tier-1 WLAN evidence is authentication-path emulation, not a radio."""


class GroundTruth(BaseModel):
    """Scenario-level declared truth, fixed before execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    description: str
    legitimate_transitions: int = Field(default=0, ge=0)
    illegitimate_transitions: int = Field(default=0, ge=0)
    device_is_legitimate: bool = True
    adversarial: bool = False
    threat_ids: tuple[str, ...] = ()


class ExpectedPolicyBehavior(BaseModel):
    """What the scenario expects of the decision sequence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    description: str
    must_contain_actions: tuple[PolicyAction, ...] = ()
    must_not_contain_actions: tuple[PolicyAction, ...] = ()
    must_contain_states: tuple[TrustState, ...] = ()
    must_not_contain_states: tuple[TrustState, ...] = ()
    strategy_specific: dict[str, dict[str, Any]] = Field(default_factory=dict)
    """Per-strategy overrides, keyed by strategy name.

    The baselines are expected to behave differently from CA-ZTCF; that
    difference is what the experiment measures, so it is declared, not discovered.
    """


class Scenario(BaseModel):
    """A complete, declarative scenario definition."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario_id: str = Field(pattern=r"^E\d{2}$")
    name: str
    description: str
    strategy: str | list[str] = "all"
    device_count: int = Field(default=1, ge=1)
    seed: int = Field(ge=0)
    measurement_tier: MeasurementTier = MeasurementTier.TIER1
    """The tier this scenario was developed against.

    Not a restriction. A scenario describes a sequence of access events and the
    behaviour they must produce; which testbed supplies those events is a property
    of the run, not of the scenario. ``supported_tiers`` is what a run is checked
    against.
    """
    supported_tiers: tuple[MeasurementTier, ...] = (
        MeasurementTier.TIER1,
        MeasurementTier.TIER2,
    )
    """Tiers this scenario may legitimately be executed on."""
    device_counts: tuple[int, ...] = ()
    """Device counts to sweep, for scalability scenarios."""
    transition_rates_per_s: tuple[float, ...] = ()
    """Transition rates to sweep, for rate-scalability scenarios."""
    setup: ScenarioSetup = Field(default_factory=ScenarioSetup)
    event_sequence: tuple[ScenarioEvent, ...]
    ground_truth: GroundTruth
    expected_policy_behavior: ExpectedPolicyBehavior
    metrics_to_collect: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _steps_are_ordered(self) -> Scenario:
        steps = [event.step for event in self.event_sequence]
        if steps != sorted(steps):
            raise ValueError("event_sequence steps must be in ascending order")
        if not self.event_sequence:
            raise ValueError("a scenario must declare at least one event")
        for event in self.event_sequence:
            if event.device_index >= self.device_count:
                raise ValueError(
                    f"step {event.step} targets device_index {event.device_index} "
                    f"but the scenario declares only {self.device_count} device(s)"
                )
            if (
                event.other_device_index is not None
                and event.other_device_index >= self.device_count
            ):
                raise ValueError(
                    f"step {event.step} targets other_device_index "
                    f"{event.other_device_index} beyond device_count "
                    f"{self.device_count}"
                )
        if self.device_counts and max(self.device_counts) < self.device_count:
            raise ValueError("device_counts must cover at least device_count")
        return self

    @property
    def scored_events(self) -> tuple[ScenarioEvent, ...]:
        """Steps that carry an expectation and will be counted."""
        return tuple(event for event in self.event_sequence if event.ground_truth.scored)

    def strategies(self, available: list[str]) -> list[str]:
        if self.strategy == "all":
            return list(available)
        if isinstance(self.strategy, str):
            return [self.strategy]
        return list(self.strategy)


def load_scenario(path: Path) -> Scenario:
    """Load and validate a scenario definition."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a mapping at the top level")
    return Scenario.model_validate(raw)


def load_scenarios(directory: Path) -> list[Scenario]:
    """Load every scenario in a directory, ordered by identifier."""
    scenarios = [load_scenario(path) for path in sorted(directory.glob("E*.yaml"))]
    seen: set[str] = set()
    for scenario in scenarios:
        if scenario.scenario_id in seen:
            raise ValueError(f"duplicate scenario_id '{scenario.scenario_id}'")
        seen.add(scenario.scenario_id)
    return scenarios


__all__ = [
    "EventKind",
    "ExpectedPolicyBehavior",
    "GroundTruth",
    "GroundTruthLabel",
    "Scenario",
    "ScenarioEvent",
    "ScenarioSetup",
    "load_scenario",
    "load_scenarios",
]
