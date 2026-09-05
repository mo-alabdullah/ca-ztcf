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


class GroundTruthLabel(StrEnum):
    """Whether a step is a legitimate access attempt or an illegitimate one.

    Declared before execution. Used to compute raw acceptance and rejection
    counts, never inferred afterwards.
    """

    LEGITIMATE = "legitimate"
    ILLEGITIMATE = "illegitimate"
    NOT_APPLICABLE = "not_applicable"


class ScenarioEvent(BaseModel):
    """One step of a scenario."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    step: int = Field(ge=0)
    kind: EventKind
    device_index: int = Field(default=0, ge=0)
    domain: AccessDomain | None = None
    topic: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    advance_s: float = Field(default=0.0, ge=0.0)
    ground_truth: GroundTruthLabel = GroundTruthLabel.NOT_APPLICABLE
    expected_trust_state: TrustState | None = None
    expected_action: PolicyAction | None = None
    expected_actions: tuple[PolicyAction, ...] = ()
    """Alternatives, for steps where more than one outcome is acceptable."""
    note: str = ""

    @model_validator(mode="after")
    def _expectation_is_single_valued(self) -> ScenarioEvent:
        if self.expected_action is not None and self.expected_actions:
            raise ValueError("declare either expected_action or expected_actions, not both")
        return self


class ScenarioSetup(BaseModel):
    """Initial conditions of a scenario."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    register_devices: bool = True
    nr_address_prefix: str = "10.45.0."
    wlan_address_prefix: str = "192.168.60."
    address_offset: int = Field(default=2, ge=1)
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
        return self

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
