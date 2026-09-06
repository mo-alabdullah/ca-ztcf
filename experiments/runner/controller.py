"""The experiment controller.

Executes a scenario against one decision strategy and writes machine-readable raw
output. Everything a result depends on is captured: the configuration hash, the
git commit, the environment, the seed, and the provenance of every access event.

Determinism. Scenario time advances explicitly through a ``FrozenClock``; the
runner never sleeps to make something happen. Randomness is seeded per run and
per device from the scenario's declared seed.

Provenance. Access evidence comes from a pluggable source. On Tier 1 the 5G
context is a synthetic development fixture and the WLAN side is
authentication-path emulation; on Tier 2 both are read from the live
software-based testbed's own logs and interfaces. The source is recorded on every
event and in the run metadata, and the live source never falls back to a fixture.

Nothing this runner produces on either tier is a measurement of real radio access.
"""

from __future__ import annotations

import json
import random
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ca_ztcf.api.state import AppState, build_app_state
from ca_ztcf.clock import FrozenClock
from ca_ztcf.collectors.base import AccessDomain, MeasurementTier
from ca_ztcf.device.keys import DeviceKeyPair, research_device_id
from ca_ztcf.policy.models import PolicyAction
from ca_ztcf.strategies.interface import AccessRequest
from experiments.runner.access_sources import AccessSource, build_access_source
from experiments.runner.metrics import MeasurementSubject, MetricsCollector, Timer
from experiments.runner.resources import ResourceSampler
from experiments.schemas.scenario import (
    ACCEPTABLE_ACTIONS,
    EventKind,
    Scenario,
)

PERMITTING_ACTIONS = frozenset({PolicyAction.ALLOW, PolicyAction.ALLOW_WITH_RESTRICTIONS})
"""Actions that let a device proceed with resource access.

STEP_UP_AUTHENTICATION is deliberately excluded: it holds protected operations,
so counting it as an acceptance would understate false rejection.
"""


def make_run_id(scenario_id: str, strategy: str, seed: int, at: datetime | None = None) -> str:
    """``<scenario>-<strategy>-<seed>-<UTC>``, as specified."""
    moment = at or datetime.now(UTC)
    return f"{scenario_id}-{strategy}-{seed}-{moment.strftime('%Y%m%dT%H%M%SZ')}"


def scrub(value: str | None) -> str | None:
    """Replace the user's home directory with "~".

    Run metadata is committed and later published. An absolute path carrying a
    username is not research-relevant, and it is exactly the kind of personal
    detail that should not travel with a result.
    """
    if value is None:
        return None
    home = str(Path.home())
    return value.replace(home, "~") if home and home != "/" else value


def _git(args: list[str], cwd: Path) -> str | None:
    """Read git metadata. The argument list is fixed by the caller, never user input."""
    git = shutil.which("git")
    if git is None:
        return None
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, resolved executable
            [git, *args], cwd=cwd, capture_output=True, text=True, timeout=10, check=False
        )
    except (subprocess.SubprocessError, OSError):
        return None
    return result.stdout.strip() or None if result.returncode == 0 else None


@dataclass
class RunResult:
    """Everything one scenario-strategy execution produced."""

    run_id: str
    scenario_id: str
    strategy: str
    seed: int
    measurement_tier: MeasurementTier
    started_at: datetime
    finished_at: datetime | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    resources: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


class ScenarioRunner:
    """Runs one scenario against one strategy, in process, deterministically."""

    def __init__(
        self,
        scenario: Scenario,
        strategy_name: str,
        *,
        config_dir: Path,
        output_root: Path,
        start_time: datetime | None = None,
        sample_resources: bool = False,
        resource_interval_s: float = 1.0,
        access_source: AccessSource | None = None,
        repetition: int = 0,
    ) -> None:
        self.scenario = scenario
        self.repetition = repetition
        self.strategy_name = strategy_name
        self.config_dir = config_dir
        self.output_root = output_root
        self.clock = FrozenClock(start=start_time or datetime(2026, 6, 1, 9, 0, 0, tzinfo=UTC))
        # Scenario randomness only. Never used for key material: device keys are
        # generated from the system CSPRNG so that a laboratory key is still a real
        # key. Determinism comes from the clock and the scenario, not from
        # predictable secrets.
        # Repetitions differ by seed so they are independent samples rather than
        # identical replays, and the offset is deterministic so a repetition can be
        # reproduced exactly.
        self.seed = scenario.seed + repetition
        self.rng = random.Random(self.seed)  # noqa: S311 - scenario sequencing only
        self.sample_resources = sample_resources
        self.resource_interval_s = resource_interval_s
        # Where access evidence comes from. Tier 1 by default; a Tier-2 run is
        # given a live source by the caller, and that source raises rather than
        # substituting a fixture when the testbed cannot supply a device's path.
        self.access_source: AccessSource = access_source or build_access_source(
            "tier1",
            nr_address_prefix=scenario.setup.nr_address_prefix,
            wlan_address_prefix=scenario.setup.wlan_address_prefix,
            address_offset=scenario.setup.address_offset,
            address_stride=scenario.setup.address_stride,
        )
        self.state: AppState | None = None
        self.keys: dict[str, DeviceKeyPair] = {}
        self.device_ids: list[str] = []
        self.addresses: dict[tuple[str, AccessDomain], str] = {}
        self.current_domain: dict[str, AccessDomain] = {}
        self.last_state: dict[str, str] = {}

    # -- setup ------------------------------------------------------------

    def _address(self, device_id: str, domain: AccessDomain, index: int) -> str:
        return self.access_source.address(index, domain)

    def prepare(self) -> None:
        self.state = build_app_state(
            config_dir=self.config_dir,
            clock=self.clock,
            audit_base_dir=self.output_root / "audit" / self.strategy_name,
        )
        for index in range(self.scenario.device_count):
            device_id = research_device_id(index, prefix=f"dev-{self.scenario.scenario_id.lower()}")
            self.device_ids.append(device_id)
            # Key generation is not seeded: Ed25519 key material must stay
            # unpredictable even in a laboratory. Determinism of the experiment
            # comes from the clock and the scenario, not from predictable keys.
            keypair = DeviceKeyPair.generate(device_id)
            self.keys[device_id] = keypair
            if self.scenario.setup.register_devices:
                self.state.registry.register(
                    device_id,
                    keypair.public_key_pem,
                    labels={"scenario": self.scenario.scenario_id, "index": str(index)},
                )
            for domain in (AccessDomain.NR, AccessDomain.WLAN):
                self.addresses[(device_id, domain)] = self._address(device_id, domain, index)
            self.current_domain[device_id] = self.scenario.setup.initial_domain

    # -- access-context events -------------------------------------------

    def _feed_nr(
        self,
        device_id: str,
        result: RunResult,
        metrics: MetricsCollector | None = None,
        overrides: dict[str, str] | None = None,
    ) -> None:
        """Feed a 5G access event from the configured access source."""
        assert self.state is not None
        index = self.device_ids.index(device_id)
        subject = self.access_source.subject(AccessDomain.NR)
        timer = Timer("nr_context", subject)
        extra = overrides or {}
        event = self.access_source.nr_event(device_id, index, self.clock.now(), extra)
        binding = self.state.nr_collector.ingest(event)
        if metrics is not None:
            metrics.observe("M1_NR", timer.stop() / 1_000_000, subject=subject)
        result.events.append(
            {
                "kind": "nr_session",
                "device_id": device_id,
                "at": self.clock.now().isoformat(),
                "peer_address": event.peer_address,
                "source_mode": event.source_mode.value,
                "access_source": self.access_source.name,
                **self.access_source.event_stamp(AccessDomain.NR),
                "measurement_subject": subject.value,
                "adversarial_override": sorted(extra) or None,
                "binding_id": binding.binding_id if binding else None,
            }
        )

    def _feed_wlan(
        self,
        device_id: str,
        result: RunResult,
        metrics: MetricsCollector | None = None,
        overrides: dict[str, str] | None = None,
    ) -> None:
        """Feed a WLAN access event from the configured access source."""
        assert self.state is not None
        index = self.device_ids.index(device_id)
        subject = self.access_source.subject(AccessDomain.WLAN)
        timer = Timer("wlan_context", subject)
        extra = overrides or {}
        event = self.access_source.wlan_event(device_id, index, self.clock.now(), extra)
        binding = self.state.wlan_collector.ingest(event)
        if metrics is not None:
            metrics.observe("M1_EAP", timer.stop() / 1_000_000, subject=subject)
        result.events.append(
            {
                "kind": "wlan_session",
                "device_id": device_id,
                "at": self.clock.now().isoformat(),
                "peer_address": event.peer_address,
                "source_mode": event.source_mode.value,
                "access_source": self.access_source.name,
                **self.access_source.event_stamp(AccessDomain.WLAN),
                "measurement_subject": subject.value,
                "adversarial_override": sorted(extra) or None,
                "binding_id": binding.binding_id if binding else None,
            }
        )

    # -- decisions --------------------------------------------------------

    def _decide(
        self,
        device_id: str,
        metrics: MetricsCollector,
        result: RunResult,
        *,
        with_proof: bool,
        session_identity: str | None = None,
        peer_address: str | None = None,
    ) -> Any:
        assert self.state is not None
        domain = self.current_domain[device_id]
        address = peer_address or self.addresses[(device_id, domain)]

        proof = None
        if with_proof:
            nonce, _ = self.state.nonces.issue(device_id)
            proof = self.keys[device_id].proof(nonce)

        timer = Timer("decision", MeasurementSubject.CA_ZTCF)
        outcome = self.state.strategy(self.strategy_name).decide(
            AccessRequest(
                device_id=device_id,
                peer_address=address,
                domain=domain,
                session_identity=session_identity if session_identity is not None else device_id,
                proof=proof,
                at=self.clock.now(),
            )
        )
        elapsed_ns = timer.stop()

        decision = outcome.decision
        self.state.pep.apply(decision)
        self.state.audit.write_decision(
            decision,
            evaluation=outcome.trust_evaluation,
            recorded_at=self.clock.now(),
            extra={"run_id": result.run_id, "scenario_id": self.scenario.scenario_id},
        )

        metrics.observe("M3", elapsed_ns / 1_000_000)
        if outcome.trust_evaluation is not None:
            metrics.observe("M12", outcome.trust_evaluation.engine_duration_ns / 1000)
        previous = self.last_state.get(device_id)
        metrics.record_decision(decision.action.value, decision.trust_state.value, previous)
        self.last_state[device_id] = decision.trust_state.value

        result.decisions.append(
            {
                "decision_id": decision.decision_id,
                "device_id": device_id,
                "at": self.clock.now().isoformat(),
                "strategy": decision.strategy,
                "trust_state": decision.trust_state.value,
                "previous_trust_state": previous,
                "transition_context": decision.transition_context.value,
                "action": decision.action.value,
                "scope": decision.scope.name,
                "ttl_ms": decision.ttl_ms,
                "reason_codes": list(decision.reason_codes),
                "policy_rule_id": decision.rule_id,
                "evidence_record_id": decision.evidence_record_id,
                "predicate_trace_id": decision.predicate_trace_id,
                "config_hash": decision.config_hash,
                "decision_latency_ms": elapsed_ns / 1_000_000,
                "engine_duration_ns": (
                    outcome.trust_evaluation.engine_duration_ns
                    if outcome.trust_evaluation
                    else None
                ),
                "domain": domain.value,
                "measurement_tier": self._effective_tier(),
                "declared_measurement_tier": self.scenario.measurement_tier.value,
            }
        )
        return decision

    # -- execution --------------------------------------------------------

    def run(self) -> RunResult:
        started = datetime.now(UTC)
        run_id = make_run_id(self.scenario.scenario_id, self.strategy_name, self.seed, started)
        result = RunResult(
            run_id=run_id,
            scenario_id=self.scenario.scenario_id,
            strategy=self.strategy_name,
            seed=self.seed,
            measurement_tier=self._tier(),
            started_at=started,
        )
        metrics = MetricsCollector(
            run_id=run_id,
            scenario_id=self.scenario.scenario_id,
            strategy=self.strategy_name,
            seed=self.seed,
            measurement_tier=self._tier(),
        )
        sampler = ResourceSampler(interval_s=self.resource_interval_s)
        if self.sample_resources:
            sampler.start()

        try:
            self.prepare()
            self._execute_events(result, metrics)
        except Exception as exc:
            result.errors.append(f"{type(exc).__name__}: {exc}")
        finally:
            if self.sample_resources:
                sampler.stop()
                result.resources = sampler.summary()
                for container, rows in result.resources.get("by_container", {}).items():
                    if container.endswith("core"):
                        cpu = rows["cpu_percent"].get("median")
                        mem = rows["memory_mib"].get("median")
                        if cpu is not None:
                            metrics.observe("M10", float(cpu))
                        if mem is not None:
                            metrics.observe("M11", float(mem))
            result.finished_at = datetime.now(UTC)
            result.metrics = metrics.summary()
            result.metadata = self._metadata(result)
        return result

    def _execute_events(self, result: RunResult, metrics: MetricsCollector) -> None:
        assert self.state is not None
        transition_timer: Timer | None = None

        for event in self.scenario.event_sequence:
            device_id = self.device_ids[min(event.device_index, len(self.device_ids) - 1)]

            if event.kind is EventKind.ADVANCE_TIME:
                self.clock.advance(seconds=event.advance_s)
                result.events.append(
                    {
                        "kind": "advance_time",
                        "at": self.clock.now().isoformat(),
                        "advance_s": event.advance_s,
                        "note": "scenario time advanced without sleeping",
                    }
                )
                continue

            if event.kind is EventKind.NR_SESSION:
                self._feed_nr(device_id, result, metrics)
                continue

            if event.kind is EventKind.WLAN_SESSION:
                self._feed_wlan(device_id, result, metrics)
                continue

            if event.kind is EventKind.STALE_EVIDENCE:
                # Existing evidence simply ages: nothing is refreshed and nothing
                # contradictory is introduced.
                self.clock.advance(seconds=event.advance_s)
                result.events.append(
                    {
                        "kind": "stale_evidence",
                        "device_id": device_id,
                        "at": self.clock.now().isoformat(),
                        "aged_by_s": event.advance_s,
                        "note": "no refresh; evidence ages past its freshness bound",
                    }
                )
                continue

            if event.kind is EventKind.IDENTITY_MISMATCH:
                other_index = event.other_device_index
                if other_index is None:
                    raise ValueError(
                        f"step {event.step}: identity_mismatch needs other_device_index"
                    )
                other_id = self.device_ids[other_index]
                # The other device presents itself from an address already
                # attributed to this one. No credential is forged: it is a
                # competing claim on an access binding.
                claimed = self.addresses[(device_id, self.current_domain[device_id])]
                decision = self._decide(
                    other_id, metrics, result, with_proof=True, peer_address=claimed
                )
                result.events.append(
                    {
                        "kind": "identity_mismatch",
                        "device_id": other_id,
                        "at": self.clock.now().isoformat(),
                        "claimed_address_of": device_id,
                        "peer_address": claimed,
                        "decision_id": decision.decision_id,
                    }
                )
                self._score(event, decision, metrics)
                continue

            if event.kind is EventKind.UNAUTHORIZED_CONTEXT:
                overrides = dict(event.posture_override) or {"akm": "OPEN"}
                target = event.domain or AccessDomain.WLAN
                if target is AccessDomain.WLAN:
                    self._feed_wlan(device_id, result, metrics, overrides)
                else:
                    self._feed_nr(device_id, result, metrics, overrides)
                self.current_domain[device_id] = target
                decision = self._decide(device_id, metrics, result, with_proof=True)
                result.events.append(
                    {
                        "kind": "unauthorized_context",
                        "device_id": device_id,
                        "at": self.clock.now().isoformat(),
                        "domain": target.value,
                        "overrides": overrides,
                        "decision_id": decision.decision_id,
                        "reason_codes": list(decision.reason_codes),
                    }
                )
                self._score(event, decision, metrics)
                continue

            if event.kind is EventKind.SESSION_MISMATCH:
                bogus = event.session_identity or f"not-{device_id}"
                decision = self._decide(
                    device_id, metrics, result, with_proof=True, session_identity=bogus
                )
                result.events.append(
                    {
                        "kind": "session_mismatch",
                        "device_id": device_id,
                        "at": self.clock.now().isoformat(),
                        "session_identity": bogus,
                        "decision_id": decision.decision_id,
                        "reason_codes": list(decision.reason_codes),
                    }
                )
                self._score(event, decision, metrics)
                continue

            if event.kind is EventKind.RAPID_TRANSITIONS:
                # The interval comes from the scenario, and the limit it breaches
                # comes from configuration; neither is hard-coded here.
                domains = [AccessDomain.NR, AccessDomain.WLAN]
                decision = None
                for index in range(event.repeat):
                    target = domains[index % 2]
                    if target is AccessDomain.NR:
                        self._feed_nr(device_id, result, metrics)
                    else:
                        self._feed_wlan(device_id, result, metrics)
                    self.current_domain[device_id] = target
                    decision = self._decide(device_id, metrics, result, with_proof=True)
                    result.events.append(
                        {
                            "kind": "rapid_transition",
                            "device_id": device_id,
                            "at": self.clock.now().isoformat(),
                            "iteration": index + 1,
                            "to_domain": target.value,
                            "transitions_in_window": self.state.transitions.transitions_in_window(
                                device_id, at=self.clock.now()
                            ),
                            "rate_limit": (
                                self.state.settings.transition.max_transitions_per_window
                            ),
                            "decision_id": decision.decision_id,
                        }
                    )
                    if event.interval_s:
                        self.clock.advance(seconds=event.interval_s)
                if decision is not None:
                    self._score(event, decision, metrics)
                continue

            if event.kind is EventKind.CONCURRENT_TRANSITION:
                start, end = event.device_range or (0, self.scenario.device_count - 1)
                target = event.domain or AccessDomain.WLAN
                for index in range(start, min(end, len(self.device_ids) - 1) + 1):
                    member = self.device_ids[index]
                    if target is AccessDomain.NR:
                        self._feed_nr(member, result, metrics)
                    else:
                        self._feed_wlan(member, result, metrics)
                    self.current_domain[member] = target
                    decision = self._decide(member, metrics, result, with_proof=True)
                    result.events.append(
                        {
                            "kind": "concurrent_transition",
                            "device_id": member,
                            "at": self.clock.now().isoformat(),
                            "to_domain": target.value,
                            "decision_id": decision.decision_id,
                        }
                    )
                    if event.ground_truth.scored:
                        self._score(event, decision, metrics)
                    if event.interval_s:
                        self.clock.advance(seconds=event.interval_s)
                continue

            if event.kind is EventKind.DEVICE_SWEEP:
                start, end = event.device_range or (0, self.scenario.device_count - 1)
                for index in range(start, min(end, len(self.device_ids) - 1) + 1):
                    member = self.device_ids[index]
                    self._feed_nr(member, result, metrics)
                    self.current_domain[member] = AccessDomain.NR
                    self._decide(member, metrics, result, with_proof=True)
                    self.clock.advance(seconds=event.interval_s or 1)
                    self._feed_wlan(member, result, metrics)
                    self.current_domain[member] = AccessDomain.WLAN
                    decision = self._decide(member, metrics, result, with_proof=True)
                    result.events.append(
                        {
                            "kind": "device_sweep",
                            "device_id": member,
                            "at": self.clock.now().isoformat(),
                            "decision_id": decision.decision_id,
                        }
                    )
                    if event.ground_truth.scored:
                        self._score(event, decision, metrics)
                metrics.observe("M20", float(end - start + 1))
                continue

            if event.kind is EventKind.MIXED_WORKLOAD:
                self._run_mixed_workload(event, result, metrics)
                continue

            if event.kind is EventKind.COLLECTOR_RECOVERY:
                domain = event.domain or AccessDomain.NR
                collector = (
                    self.state.nr_collector
                    if domain is AccessDomain.NR
                    else self.state.wlan_collector
                )
                collector.set_available(True)
                result.events.append(
                    {
                        "kind": "collector_recovery",
                        "at": self.clock.now().isoformat(),
                        "domain": domain.value,
                    }
                )
                continue

            if event.kind is EventKind.COLLECTOR_OUTAGE:
                domain = event.domain or AccessDomain.NR
                collector = (
                    self.state.nr_collector
                    if domain is AccessDomain.NR
                    else self.state.wlan_collector
                )
                collector.set_available(False)
                result.events.append(
                    {
                        "kind": "collector_outage",
                        "at": self.clock.now().isoformat(),
                        "domain": domain.value,
                    }
                )
                continue

            if event.kind is EventKind.TRANSITION:
                target = event.domain or AccessDomain.WLAN
                transition_timer = Timer("transition", MeasurementSubject.TRANSITION_ORCHESTRATION)
                previous = self.current_domain[device_id]
                self.current_domain[device_id] = target
                decision = self._decide(device_id, metrics, result, with_proof=True)
                metrics.observe("M2", transition_timer.stop() / 1_000_000)
                result.events.append(
                    {
                        "kind": "transition",
                        "device_id": device_id,
                        "at": self.clock.now().isoformat(),
                        "from_domain": previous.value,
                        "to_domain": target.value,
                        "measurement_subject": (MeasurementSubject.TRANSITION_ORCHESTRATION.value),
                        "note": ("access-context switch orchestration; not an 802.11 handover"),
                        "decision_id": decision.decision_id,
                    }
                )
                self._score(event, decision, metrics)
                if decision.action in PERMITTING_ACTIONS:
                    metrics.increment("M13")
                else:
                    metrics.increment("M14")
                continue

            if event.kind in {EventKind.MQTT_CONNECT, EventKind.EXPECT_DECISION}:
                decision = self._decide(
                    device_id,
                    metrics,
                    result,
                    with_proof=event.kind is EventKind.MQTT_CONNECT,
                )
                if event.kind is EventKind.MQTT_CONNECT:
                    metrics.observe(
                        "M1",
                        result.decisions[-1]["decision_latency_ms"],
                        subject=MeasurementSubject.APPLICATION,
                    )
                    metrics.increment("M8")
                self._score(event, decision, metrics)
                continue

            if event.kind in {EventKind.MQTT_PUBLISH, EventKind.MQTT_SUBSCRIBE}:
                topic = (event.topic or "dev/{device_id}/telemetry/reading").replace(
                    "{device_id}", device_id
                )
                from ca_ztcf.enforcement.models import EnforcementRequest, ResourceOperation

                operation = (
                    ResourceOperation.PUBLISH
                    if event.kind is EventKind.MQTT_PUBLISH
                    else ResourceOperation.SUBSCRIBE
                )
                enforcement = self.state.pep.check(
                    EnforcementRequest(device_id=device_id, operation=operation, resource=topic)
                )
                metrics.increment("M8")
                metrics.increment("M19")
                result.events.append(
                    {
                        "kind": event.kind.value,
                        "device_id": device_id,
                        "at": self.clock.now().isoformat(),
                        "topic": topic,
                        "permitted": enforcement.permitted,
                        "reason": enforcement.reason,
                        "decision_id": enforcement.decision_id,
                        "measurement_subject": MeasurementSubject.APPLICATION.value,
                    }
                )
                if event.ground_truth.scored:
                    # The expectation is whether the operation itself should have
                    # succeeded, declared in the scenario. A legitimate device
                    # under a restricted scope is correctly refused a command
                    # topic, and inferring the expectation would score that
                    # proportionate refusal as a false rejection.
                    expected = event.expect_permitted
                    metrics.record_ground_truth(
                        step=event.step,
                        label=event.ground_truth.value,
                        action=enforcement.action.value if enforcement.action else "NONE",
                        trust_state=self.last_state.get(device_id, "UNKNOWN"),
                        permitted=enforcement.permitted,
                        satisfied=(
                            enforcement.permitted == expected if expected is not None else None
                        ),
                    )
                continue

            if event.kind is EventKind.MQTT_DISCONNECT:
                self.state.pep.revoke(device_id)
                result.events.append(
                    {
                        "kind": "mqtt_disconnect",
                        "device_id": device_id,
                        "at": self.clock.now().isoformat(),
                    }
                )
                continue

    def _run_mixed_workload(self, event: Any, result: RunResult, metrics: MetricsCollector) -> None:
        """Generate a seeded mixture of legitimate and abnormal events.

        The plan is built in full, with its labels, **before any of it executes**.
        The labels therefore cannot depend on how CA-ZTCF responds, and the same
        seed reproduces the same workload for every strategy — which is what makes
        the three comparable at all.
        """
        assert self.state is not None
        from experiments.schemas.scenario import GroundTruthLabel

        legitimate_fraction = (
            event.legitimate_fraction if event.legitimate_fraction is not None else 0.8
        )
        kinds = event.adversarial_kinds or (
            "stale_evidence",
            "identity_mismatch",
            "unauthorized_context",
            "rapid_transition",
            "session_mismatch",
        )
        rng = random.Random(self.seed + event.step)  # noqa: S311 - workload only

        # Legitimate and adversarial events are drawn from DISJOINT device cohorts.
        #
        # Sharing devices makes labels ambiguous rather than making the workload
        # harder: a device correctly quarantined for a rapid-transition burst is
        # still in that state when its next event arrives, so labelling that event
        # "legitimate, expects restriction" asks for an outcome the scenario itself
        # made impossible. Separating the cohorts keeps every label answerable, and
        # it does so identically for all three strategies. Whether adversarial
        # history should contaminate a device's later legitimate traffic is a real
        # question, but it is a different one and belongs in its own scenario.
        device_count = len(self.device_ids)
        adversarial_cohort_size = max(1, round(device_count * (1.0 - legitimate_fraction)))
        adversarial_cohort = self.device_ids[device_count - adversarial_cohort_size :]
        legitimate_cohort = self.device_ids[: device_count - adversarial_cohort_size] or (
            self.device_ids
        )

        plan: list[dict[str, Any]] = []
        for index in range(event.repeat):
            if rng.random() < legitimate_fraction:
                plan.append(
                    {
                        "index": index,
                        "device_id": legitimate_cohort[index % len(legitimate_cohort)],
                        "class": "legitimate",
                        "cohort": "legitimate",
                        "kind": "transition",
                        "label": GroundTruthLabel.LEGITIMATE_RESTRICT.value,
                    }
                )
            else:
                plan.append(
                    {
                        "index": index,
                        "device_id": adversarial_cohort[index % len(adversarial_cohort)],
                        "class": "adversarial",
                        "cohort": "adversarial",
                        "kind": rng.choice(list(kinds)),
                        "label": GroundTruthLabel.MALICIOUS_REJECT.value,
                    }
                )

        result.events.append(
            {
                "kind": "mixed_workload_plan",
                "at": self.clock.now().isoformat(),
                "seed": self.seed + event.step,
                "legitimate_fraction": legitimate_fraction,
                "adversarial_kinds": list(kinds),
                "total": len(plan),
                "legitimate": sum(1 for p in plan if p["class"] == "legitimate"),
                "adversarial": sum(1 for p in plan if p["class"] == "adversarial"),
                "legitimate_cohort": list(legitimate_cohort),
                "adversarial_cohort": list(adversarial_cohort),
                "plan": plan,
                "note": "ground truth frozen before execution; never derived from output",
            }
        )

        domains = [AccessDomain.NR, AccessDomain.WLAN]
        for entry in plan:
            member = str(entry["device_id"])
            label = str(entry["label"])
            kind = str(entry["kind"])
            target = domains[int(entry["index"]) % 2]

            if entry["class"] == "legitimate":
                if target is AccessDomain.NR:
                    self._feed_nr(member, result, metrics)
                else:
                    self._feed_wlan(member, result, metrics)
                self.current_domain[member] = target
                decision = self._decide(member, metrics, result, with_proof=True)

            elif kind == "stale_evidence":
                self.clock.advance(seconds=self.state.settings.evidence.binding_freshness_max_s + 5)
                decision = self._decide(member, metrics, result, with_proof=False)

            elif kind == "identity_mismatch":
                # The victim is always a legitimate-cohort device, so the claim is
                # unambiguously a competing one.
                victim = legitimate_cohort[int(entry["index"]) % len(legitimate_cohort)]
                claimed = self.addresses[(victim, self.current_domain[victim])]
                decision = self._decide(
                    member, metrics, result, with_proof=True, peer_address=claimed
                )

            elif kind == "unauthorized_context":
                self._feed_wlan(member, result, metrics, {"akm": "OPEN"})
                self.current_domain[member] = AccessDomain.WLAN
                decision = self._decide(member, metrics, result, with_proof=True)

            elif kind == "rapid_transition":
                for step_index in range(
                    self.state.settings.transition.max_transitions_per_window + 2
                ):
                    inner = domains[step_index % 2]
                    if inner is AccessDomain.NR:
                        self._feed_nr(member, result, metrics)
                    else:
                        self._feed_wlan(member, result, metrics)
                    self.current_domain[member] = inner
                    self.clock.advance(seconds=1)
                decision = self._decide(member, metrics, result, with_proof=True)

            else:  # session_mismatch
                decision = self._decide(
                    member,
                    metrics,
                    result,
                    with_proof=True,
                    session_identity=f"not-{member}",
                )

            acceptable = ACCEPTABLE_ACTIONS.get(GroundTruthLabel(label), frozenset())
            metrics.record_ground_truth(
                step=event.step,
                label=label,
                action=decision.action.value,
                trust_state=decision.trust_state.value,
                permitted=decision.action in PERMITTING_ACTIONS,
                satisfied=decision.action.value in acceptable,
            )
            result.events.append(
                {
                    "kind": "mixed_workload_event",
                    "device_id": member,
                    "at": self.clock.now().isoformat(),
                    "class": entry["class"],
                    "generated_kind": kind,
                    "ground_truth": label,
                    "decision_id": decision.decision_id,
                    "action": decision.action.value,
                }
            )
            if event.interval_s:
                self.clock.advance(seconds=event.interval_s)

    def _score(self, event: Any, decision: Any, metrics: MetricsCollector) -> None:
        """Score a decision step against the class its label declared."""
        if not event.ground_truth.scored:
            return
        acceptable = ACCEPTABLE_ACTIONS.get(event.ground_truth, frozenset())
        metrics.record_ground_truth(
            step=event.step,
            label=event.ground_truth.value,
            action=decision.action.value,
            trust_state=decision.trust_state.value,
            permitted=decision.action in PERMITTING_ACTIONS,
            satisfied=decision.action.value in acceptable,
        )

    def _effective_tier(self) -> str:
        """The tier the evidence actually came from, not the one declared."""
        return self._tier().value

    def _tier(self) -> MeasurementTier:
        """The measurement tier of the access source that supplied the evidence.

        A scenario declares a tier, but the run's provenance is decided by where
        the evidence actually came from. Labelling a live Tier-2 run as Tier-1
        because the scenario file says so would misrepresent it in every derived
        table and figure.
        """
        return (
            MeasurementTier.TIER2
            if self.access_source.name.startswith("tier2")
            else MeasurementTier.TIER1
        )

    def _disclaimer(self) -> str:
        if self._effective_tier() == "tier2":
            return (
                "Tier-2 development validation on the live software-based testbed. "
                "Real 5G NAS/NGAP/GTP-U via Open5GS and UERANSIM, and a real IEEE "
                "802.11 association and EAP-TLS exchange via mac80211_hwsim, over "
                "simulated radios. Not an RF, propagation, interference, "
                "channel-quality, spectrum-coexistence or physical-handover "
                "measurement, and not final thesis experimental evidence."
            )
        return (
            "Tier-1 development validation. The 5G access context is a synthetic "
            "fixture and the WLAN side is 802.1X/EAP-TLS authentication-path "
            "emulation. Not a WiFi, RF, 802.11 or 5G measurement, and not final "
            "thesis experimental evidence."
        )

    def _metadata(self, result: RunResult) -> dict[str, Any]:
        import platform
        import sys

        repo = self.config_dir.parent
        assert self.state is not None
        return {
            "run_id": result.run_id,
            "scenario_id": self.scenario.scenario_id,
            "strategy": self.strategy_name,
            "seed": self.seed,
            "scenario_seed": self.scenario.seed,
            "device_count": self.scenario.device_count,
            "measurement_tier": self._effective_tier(),
            "declared_measurement_tier": self.scenario.measurement_tier.value,
            "result_class": "development_validation",
            "access_source": self.access_source.name,
            "access_source_provenance": self.access_source.provenance(),
            "repetition": self.repetition,
            "disclaimer": self._disclaimer(),
            "source_modes": sorted(
                {
                    str(event.get("source_mode"))
                    for event in result.events
                    if event.get("source_mode")
                }
            ),
            "config_hash": self.state.settings.config_hash,
            "config_dir": scrub(str(self.config_dir)),
            "git": {
                "commit_sha": _git(["rev-parse", "HEAD"], repo),
                "branch": _git(["rev-parse", "--abbrev-ref", "HEAD"], repo),
                "dirty": bool(_git(["status", "--porcelain"], repo)),
                "describe": _git(["describe", "--tags", "--always", "--dirty"], repo),
            },
            "environment": {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "machine": platform.machine(),
                "executable_basename": Path(sys.executable).name,
                "cwd": scrub(str(Path.cwd())),
            },
            "clock": {
                "type": "FrozenClock",
                "start": self.clock.now().isoformat(),
                "note": "scenario time advances explicitly; the runner never sleeps",
            },
            "timing": {
                "durations": "time.perf_counter_ns",
                "timestamps": "UTC wall clock",
            },
            "started_at": result.started_at.isoformat(),
            "finished_at": result.finished_at.isoformat() if result.finished_at else None,
        }


def write_run(result: RunResult, output_root: Path) -> dict[str, Path]:
    """Write a run's raw output. Append-only JSON Lines plus run metadata."""
    raw_dir = output_root / "raw" / result.run_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    meta_dir = output_root / "metadata"
    meta_dir.mkdir(parents=True, exist_ok=True)

    written: dict[str, Path] = {}

    def dump_lines(name: str, rows: list[dict[str, Any]]) -> None:
        path = raw_dir / name
        with path.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(
                    json.dumps(
                        {
                            "run_id": result.run_id,
                            "scenario_id": result.scenario_id,
                            "strategy": result.strategy,
                            "seed": result.seed,
                            **row,
                        },
                        default=str,
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                    + "\n"
                )
        written[name] = path

    dump_lines("events.jsonl", result.events)
    dump_lines("decisions.jsonl", result.decisions)

    metrics_path = raw_dir / "metrics.json"
    metrics_path.write_text(
        json.dumps(result.metrics, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    written["metrics.json"] = metrics_path

    if result.resources:
        resources_path = raw_dir / "resources.json"
        resources_path.write_text(
            json.dumps(result.resources, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        written["resources.json"] = resources_path

    meta_path = meta_dir / f"{result.run_id}.json"
    meta_path.write_text(
        json.dumps(
            {**result.metadata, "errors": result.errors, "ok": result.ok},
            indent=2,
            sort_keys=True,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    written["metadata"] = meta_path
    return written


def run_scenario(
    scenario: Scenario,
    strategy: str,
    *,
    config_dir: Path,
    output_root: Path,
    sample_resources: bool = False,
    access_source: AccessSource | None = None,
    repetition: int = 0,
) -> tuple[RunResult, dict[str, Path]]:
    runner = ScenarioRunner(
        scenario,
        strategy,
        config_dir=config_dir,
        output_root=output_root,
        sample_resources=sample_resources,
        access_source=access_source,
        repetition=repetition,
    )
    result = runner.run()
    written = write_run(result, output_root)
    return result, written


__all__ = [
    "PERMITTING_ACTIONS",
    "RunResult",
    "ScenarioRunner",
    "make_run_id",
    "run_scenario",
    "write_run",
]
