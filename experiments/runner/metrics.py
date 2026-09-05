"""Metric definitions and collection for the experiment runner.

Timing discipline, applied without exception:

* ``time.perf_counter_ns()`` for every duration. Wall-clock subtraction is never
  used for a latency, because it is not monotonic and its resolution is not
  guaranteed.
* UTC wall clock for every event and audit timestamp, so records can be
  correlated across processes.
* Sleeping is never a measurement mechanism. Scenario time advances explicitly.

Every metric records the tier that produced it and what was actually measured, so
a Tier-1 number can never later be mistaken for a radio measurement.
"""

from __future__ import annotations

import statistics
import time
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ca_ztcf.collectors.base import MeasurementTier


class MeasurementSubject(StrEnum):
    """What a measurement is actually of.

    Recorded on every metric. Without it, a decision latency and an EAP
    authentication duration would be indistinguishable once written to a file,
    and could be conflated later.
    """

    APPLICATION = "application"
    """MQTT client and broker path, measured at the device agent or the gateway."""

    CA_ZTCF = "ca_ztcf"
    """The trust function: evidence, predicates, engine, policy."""

    EAP_AUTH_PATH = "eap_authentication_path"
    """Tier-1 802.1X/EAP-TLS authentication path. NOT an 802.11 radio measurement."""

    SYNTHETIC_NR_CONTEXT = "synthetic_nr_context"
    """The synthetic 5G access context fixture. NOT a 5G measurement."""

    TRANSITION_ORCHESTRATION = "transition_orchestration"
    """The runner's own switching of access-domain context."""

    RESOURCE = "resource"
    """Container CPU and memory."""


@dataclass(frozen=True)
class MetricDefinition:
    """One metric, defined once so its meaning cannot drift."""

    metric_id: str
    name: str
    unit: str
    subject: MeasurementSubject
    definition: str


METRIC_DEFINITIONS: dict[str, MetricDefinition] = {
    d.metric_id: d
    for d in [
        MetricDefinition(
            "M1",
            "authentication_latency",
            "ms",
            MeasurementSubject.APPLICATION,
            "Authentication latency. At the application this is CONNECT to CONNACK; "
            "on the WLAN path it is the EAP-TLS exchange. The subject is recorded "
            "per sample so the two are never conflated.",
        ),
        MetricDefinition(
            "M2",
            "transition_duration",
            "ms",
            MeasurementSubject.TRANSITION_ORCHESTRATION,
            "Access-context switch initiated to the first decision under the new "
            "context. Orchestration time; NOT an 802.11 handover latency.",
        ),
        MetricDefinition(
            "M3",
            "decision_latency",
            "ms",
            MeasurementSubject.CA_ZTCF,
            "Decision request issued to decision returned, measured at the caller.",
        ),
        MetricDefinition(
            "M4",
            "application_transition_completion",
            "ms",
            MeasurementSubject.APPLICATION,
            "Transition initiated to the device regaining its full access scope.",
        ),
        MetricDefinition(
            "M5",
            "reauthentication_count",
            "count",
            MeasurementSubject.CA_ZTCF,
            "Number of REAUTHENTICATE actions issued.",
        ),
        MetricDefinition(
            "M6",
            "step_up_count",
            "count",
            MeasurementSubject.CA_ZTCF,
            "Number of STEP_UP_AUTHENTICATION actions issued.",
        ),
        MetricDefinition(
            "M7",
            "trust_state_transitions",
            "count",
            MeasurementSubject.CA_ZTCF,
            "Count of trust-state changes, by (from, to) pair.",
        ),
        MetricDefinition(
            "M8",
            "messages_exchanged",
            "count",
            MeasurementSubject.APPLICATION,
            "MQTT control packets exchanged between device and enforcement point.",
        ),
        MetricDefinition(
            "M9",
            "bytes_exchanged",
            "bytes",
            MeasurementSubject.APPLICATION,
            "Bytes on the device-to-enforcement-point socket, by direction.",
        ),
        MetricDefinition(
            "M10",
            "ca_ztcf_cpu",
            "percent",
            MeasurementSubject.RESOURCE,
            "Container CPU percentage, sampled at a fixed interval.",
        ),
        MetricDefinition(
            "M11",
            "ca_ztcf_memory",
            "MiB",
            MeasurementSubject.RESOURCE,
            "Container resident memory, sampled at a fixed interval.",
        ),
        MetricDefinition(
            "M12",
            "engine_evaluation_time",
            "us",
            MeasurementSubject.CA_ZTCF,
            "Pure predicate evaluation and state derivation, excluding transport.",
        ),
        MetricDefinition(
            "M13",
            "successful_legitimate_transitions",
            "count",
            MeasurementSubject.CA_ZTCF,
            "Transitions labelled legitimate that completed without denial or quarantine.",
        ),
        MetricDefinition(
            "M14",
            "denied_restricted_transitions",
            "count",
            MeasurementSubject.CA_ZTCF,
            "Transitions that received DENY, QUARANTINE or a blocking step-up.",
        ),
        MetricDefinition(
            "M15",
            "false_acceptance_raw",
            "count",
            MeasurementSubject.CA_ZTCF,
            "Steps labelled illegitimate that were allowed. Raw count, always "
            "reported with its denominator.",
        ),
        MetricDefinition(
            "M16",
            "false_rejection_raw",
            "count",
            MeasurementSubject.CA_ZTCF,
            "Steps labelled legitimate that were denied or quarantined. Raw count, "
            "always reported with its denominator.",
        ),
        MetricDefinition(
            "M17",
            "correct_decisions_raw",
            "count",
            MeasurementSubject.CA_ZTCF,
            "Correct acceptances and correct rejections, as raw counts.",
        ),
        MetricDefinition(
            "M18",
            "policy_action_distribution",
            "count",
            MeasurementSubject.CA_ZTCF,
            "Count of decisions per policy action.",
        ),
        MetricDefinition(
            "M19",
            "mqtt_operation_outcomes",
            "count",
            MeasurementSubject.APPLICATION,
            "MQTT publishes and subscriptions, split by permitted and refused.",
        ),
        MetricDefinition(
            "M20",
            "run_metadata",
            "n/a",
            MeasurementSubject.CA_ZTCF,
            "Device count, seed, durations and environment metadata for the run.",
        ),
        MetricDefinition(
            "M1_EAP",
            "eap_authentication_latency",
            "ms",
            MeasurementSubject.EAP_AUTH_PATH,
            "Tier-1 802.1X/EAP-TLS authentication-path exchange duration. NOT an "
            "802.11 association or radio measurement.",
        ),
        MetricDefinition(
            "M1_NR",
            "synthetic_nr_context_latency",
            "ms",
            MeasurementSubject.SYNTHETIC_NR_CONTEXT,
            "Time to establish the synthetic 5G access-context fixture. A fixture "
            "cost, NOT a 5G measurement.",
        ),
    ]
}


@dataclass
class Timer:
    """A monotonic duration measurement. Never uses wall-clock subtraction."""

    label: str
    subject: MeasurementSubject
    started_ns: int = field(default_factory=time.perf_counter_ns)
    ended_ns: int | None = None

    def stop(self) -> int:
        self.ended_ns = time.perf_counter_ns()
        return self.elapsed_ns

    @property
    def elapsed_ns(self) -> int:
        end = self.ended_ns if self.ended_ns is not None else time.perf_counter_ns()
        return max(0, end - self.started_ns)

    @property
    def elapsed_ms(self) -> float:
        return self.elapsed_ns / 1_000_000


def describe(values: list[float]) -> dict[str, Any]:
    """Descriptive statistics only.

    No inferential statistics are performed at this stage. Formal testing waits
    on the final experiment design once Tier 2 is operational, so nothing here
    produces a p-value or a significance claim.
    """
    if not values:
        return {"count": 0, "median": None, "iqr": None, "p95": None, "min": None, "max": None}
    ordered = sorted(values)
    count = len(ordered)

    def percentile(fraction: float) -> float:
        if count == 1:
            return ordered[0]
        position = fraction * (count - 1)
        lower = int(position)
        upper = min(lower + 1, count - 1)
        weight = position - lower
        return ordered[lower] * (1 - weight) + ordered[upper] * weight

    return {
        "count": count,
        "median": statistics.median(ordered),
        "q1": percentile(0.25),
        "q3": percentile(0.75),
        "iqr": percentile(0.75) - percentile(0.25),
        "p95": percentile(0.95),
        "min": ordered[0],
        "max": ordered[-1],
        "mean": statistics.fmean(ordered),
    }


@dataclass
class MetricsCollector:
    """Accumulates one run's measurements."""

    run_id: str
    scenario_id: str
    strategy: str
    seed: int
    measurement_tier: MeasurementTier = MeasurementTier.TIER1

    samples: dict[str, list[float]] = field(default_factory=dict)
    counters: Counter[str] = field(default_factory=Counter)
    action_counts: Counter[str] = field(default_factory=Counter)
    state_counts: Counter[str] = field(default_factory=Counter)
    state_transitions: Counter[str] = field(default_factory=Counter)
    ground_truth_outcomes: list[dict[str, Any]] = field(default_factory=list)
    subjects: dict[str, str] = field(default_factory=dict)
    sample_subjects: dict[str, list[str]] = field(default_factory=dict)

    def observe(
        self, metric_id: str, value: float, *, subject: MeasurementSubject | None = None
    ) -> None:
        """Record one sample.

        ``subject`` overrides the metric's default. The same metric identifier can
        legitimately be measured on different subjects in different scenarios: an
        authentication latency may be an MQTT exchange in one run and an EAP
        authentication-path exchange in another. Recording the subject per sample
        is what stops those two being conflated once they are in a file.
        """
        definition = METRIC_DEFINITIONS.get(metric_id)
        self.samples.setdefault(metric_id, []).append(value)
        resolved = subject or (definition.subject if definition is not None else None)
        if resolved is not None:
            self.subjects.setdefault(metric_id, resolved.value)
            self.sample_subjects.setdefault(metric_id, []).append(resolved.value)

    def increment(self, metric_id: str, amount: int = 1) -> None:
        self.counters[metric_id] += amount
        definition = METRIC_DEFINITIONS.get(metric_id)
        if definition is not None:
            self.subjects[metric_id] = definition.subject.value

    def record_decision(
        self, action: str, trust_state: str, previous_state: str | None = None
    ) -> None:
        self.action_counts[action] += 1
        self.state_counts[trust_state] += 1
        if previous_state is not None and previous_state != trust_state:
            self.state_transitions[f"{previous_state}->{trust_state}"] += 1
            self.increment("M7")
        if action == "REAUTHENTICATE":
            self.increment("M5")
        elif action == "STEP_UP_AUTHENTICATION":
            self.increment("M6")

    def record_ground_truth(
        self,
        *,
        step: int,
        label: str,
        action: str,
        trust_state: str,
        permitted: bool,
    ) -> None:
        """Score one labelled step against what actually happened.

        The label was declared in the scenario before execution. It is never
        derived from the decision, which is what keeps M15 and M16 meaningful.
        """
        outcome = "not_applicable"
        if label == "legitimate":
            outcome = "correct_acceptance" if permitted else "false_rejection"
        elif label == "illegitimate":
            outcome = "false_acceptance" if permitted else "correct_rejection"

        self.ground_truth_outcomes.append(
            {
                "step": step,
                "ground_truth": label,
                "action": action,
                "trust_state": trust_state,
                "permitted": permitted,
                "outcome": outcome,
            }
        )
        if outcome == "false_acceptance":
            self.increment("M15")
        elif outcome == "false_rejection":
            self.increment("M16")
        elif outcome in {"correct_acceptance", "correct_rejection"}:
            self.increment("M17")

    def confusion(self) -> dict[str, int]:
        """Raw confusion counts, with the denominators they came from."""
        tally = Counter(item["outcome"] for item in self.ground_truth_outcomes)
        legitimate = sum(
            1 for item in self.ground_truth_outcomes if item["ground_truth"] == "legitimate"
        )
        illegitimate = sum(
            1 for item in self.ground_truth_outcomes if item["ground_truth"] == "illegitimate"
        )
        return {
            "correct_acceptance": tally.get("correct_acceptance", 0),
            "false_rejection": tally.get("false_rejection", 0),
            "correct_rejection": tally.get("correct_rejection", 0),
            "false_acceptance": tally.get("false_acceptance", 0),
            "legitimate_total": legitimate,
            "illegitimate_total": illegitimate,
            "labelled_total": legitimate + illegitimate,
        }

    def summary(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "strategy": self.strategy,
            "seed": self.seed,
            "measurement_tier": self.measurement_tier.value,
            "metric_subjects": dict(self.subjects),
            "sample_subjects": {k: sorted(set(v)) for k, v in sorted(self.sample_subjects.items())},
            "distributions": {
                metric_id: {
                    **describe(values),
                    "unit": METRIC_DEFINITIONS[metric_id].unit
                    if metric_id in METRIC_DEFINITIONS
                    else "unknown",
                    "subject": self.subjects.get(metric_id, "unknown"),
                }
                for metric_id, values in sorted(self.samples.items())
            },
            "counters": dict(sorted(self.counters.items())),
            "policy_action_distribution": dict(sorted(self.action_counts.items())),
            "trust_state_distribution": dict(sorted(self.state_counts.items())),
            "trust_state_transitions": dict(sorted(self.state_transitions.items())),
            "confusion_raw": self.confusion(),
            "ground_truth_outcomes": self.ground_truth_outcomes,
        }


__all__ = [
    "METRIC_DEFINITIONS",
    "MeasurementSubject",
    "MetricDefinition",
    "MetricsCollector",
    "Timer",
    "describe",
]
