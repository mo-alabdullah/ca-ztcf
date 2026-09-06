"""Scenario parsing, ground truth, metrics and source-mode safety."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from experiments.runner.metrics import (
    METRIC_DEFINITIONS,
    MeasurementSubject,
    MetricsCollector,
    Timer,
    describe,
)
from experiments.schemas.scenario import (
    EventKind,
    GroundTruthLabel,
    load_scenario,
    load_scenarios,
)

from ca_ztcf.collectors.base import MeasurementTier, SourceMode

SCENARIO_DIR = Path(__file__).resolve().parents[2] / "experiments" / "scenarios"


# --- scenario parsing -------------------------------------------------------


def test_all_shipped_scenarios_parse() -> None:
    scenarios = load_scenarios(SCENARIO_DIR)
    assert [s.scenario_id for s in scenarios] == [f"E{i:02d}" for i in range(1, 16)]


def test_every_scenario_declares_the_required_fields() -> None:
    for scenario in load_scenarios(SCENARIO_DIR):
        assert scenario.scenario_id
        assert scenario.name
        assert scenario.description
        assert scenario.strategy
        assert scenario.device_count >= 1
        assert scenario.seed >= 0
        assert scenario.setup is not None
        assert scenario.event_sequence
        assert scenario.ground_truth.description
        assert scenario.expected_policy_behavior.description
        assert scenario.metrics_to_collect


def test_scenario_seeds_are_unique() -> None:
    seeds = [s.seed for s in load_scenarios(SCENARIO_DIR)]
    assert len(set(seeds)) == len(seeds)


def test_every_scenario_is_tier1_and_pins_its_source_modes() -> None:
    """Tier-1 scenarios cannot opt into claiming live measurements."""
    for scenario in load_scenarios(SCENARIO_DIR):
        assert scenario.measurement_tier is MeasurementTier.TIER1
        assert scenario.setup.nr_source_mode is SourceMode.SYNTHETIC_FIXTURE
        assert scenario.setup.wlan_source_mode is SourceMode.TIER1_WLAN_AUTH_EMULATION


def test_scenario_steps_must_be_ordered(tmp_path: Path) -> None:
    body = yaml.safe_load((SCENARIO_DIR / "E01.yaml").read_text(encoding="utf-8"))
    body["event_sequence"] = list(reversed(body["event_sequence"]))
    path = tmp_path / "E99.yaml"
    path.write_text(yaml.safe_dump(body), encoding="utf-8")
    with pytest.raises(ValueError, match="ascending"):
        load_scenario(path)


def test_scenario_rejects_conflicting_expectations(tmp_path: Path) -> None:
    body = yaml.safe_load((SCENARIO_DIR / "E01.yaml").read_text(encoding="utf-8"))
    body["event_sequence"][1]["expected_actions"] = ["ALLOW", "DENY"]
    path = tmp_path / "E98.yaml"
    path.write_text(yaml.safe_dump(body), encoding="utf-8")
    with pytest.raises(ValueError, match="not both"):
        load_scenario(path)


def test_unknown_field_is_rejected(tmp_path: Path) -> None:
    body = yaml.safe_load((SCENARIO_DIR / "E01.yaml").read_text(encoding="utf-8"))
    body["totally_unexpected"] = True
    path = tmp_path / "E97.yaml"
    path.write_text(yaml.safe_dump(body), encoding="utf-8")
    with pytest.raises(ValueError):
        load_scenario(path)


def test_ground_truth_is_declared_in_the_scenario_file() -> None:
    """Labels come from the declaration, never from observed output."""
    scenario = load_scenario(SCENARIO_DIR / "E03.yaml")
    labelled = [
        event
        for event in scenario.event_sequence
        if event.ground_truth is not GroundTruthLabel.NOT_APPLICABLE
    ]
    assert labelled, "E03 declares no labelled steps"
    assert scenario.ground_truth.legitimate_transitions == 1
    assert scenario.ground_truth.illegitimate_transitions == 0
    assert scenario.ground_truth.device_is_legitimate is True


def test_transition_scenarios_declare_a_transition_step() -> None:
    for scenario_id in ("E03", "E04", "E05"):
        scenario = load_scenario(SCENARIO_DIR / f"{scenario_id}.yaml")
        kinds = {event.kind for event in scenario.event_sequence}
        assert EventKind.TRANSITION in kinds


def test_strategies_resolves_all() -> None:
    scenario = load_scenario(SCENARIO_DIR / "E01.yaml")
    assert scenario.strategies(["a", "b"]) == ["a", "b"]


# --- metrics ----------------------------------------------------------------


def test_all_twenty_metrics_are_defined() -> None:
    for index in range(1, 21):
        assert f"M{index}" in METRIC_DEFINITIONS
    for definition in METRIC_DEFINITIONS.values():
        assert definition.unit
        assert definition.definition
        assert isinstance(definition.subject, MeasurementSubject)


def test_tier1_measurement_subjects_are_explicit() -> None:
    """Nothing may be recorded as an unqualified WiFi or 5G measurement."""
    subjects = {d.subject for d in METRIC_DEFINITIONS.values()}
    assert MeasurementSubject.EAP_AUTH_PATH in subjects
    assert MeasurementSubject.SYNTHETIC_NR_CONTEXT in subjects
    # The transition metric must say in its own definition that it is not a
    # handover latency, so the caveat travels with the number.
    assert "handover" in METRIC_DEFINITIONS["M2"].definition.lower()
    # Both access-context metrics must disclaim being a radio measurement in their
    # own definition, so the caveat travels with the number onto any tier.
    for metric in ("M1_EAP", "M1_NR"):
        definition = METRIC_DEFINITIONS[metric].definition.lower()
        assert "not a radio measurement" in definition, metric
        assert "each run records which" in definition, metric
    # The resource metrics must say what they measure and what they do not.
    for metric in ("M10", "M11"):
        definition = METRIC_DEFINITIONS[metric].definition.lower()
        assert "never an iot device" in definition, metric


def test_sample_subject_can_be_overridden_per_observation() -> None:
    """One metric id, two subjects, never conflated."""
    collector = MetricsCollector(run_id="r", scenario_id="E01", strategy="ca_ztcf", seed=1)
    collector.observe("M1", 1.0, subject=MeasurementSubject.APPLICATION)
    collector.observe("M1", 2.0, subject=MeasurementSubject.EAP_AUTH_PATH)
    summary = collector.summary()
    assert set(summary["sample_subjects"]["M1"]) == {"application", "eap_authentication_path"}


def test_describe_reports_only_descriptive_statistics() -> None:
    result = describe([1.0, 2.0, 3.0, 4.0, 100.0])
    assert set(result) == {"count", "median", "q1", "q3", "iqr", "p95", "min", "max", "mean"}
    assert "p_value" not in result
    assert result["count"] == 5
    assert result["median"] == 3.0


def test_describe_handles_empty_input() -> None:
    assert describe([])["count"] == 0


def test_timer_uses_a_monotonic_source() -> None:
    timer = Timer("t", MeasurementSubject.CA_ZTCF)
    elapsed = timer.stop()
    assert elapsed >= 0
    assert timer.elapsed_ms == pytest.approx(elapsed / 1_000_000)


def _collector() -> MetricsCollector:
    return MetricsCollector(run_id="r", scenario_id="E01", strategy="ca_ztcf", seed=1)


def test_ground_truth_scoring_is_symmetric() -> None:
    """One of each confusion cell, scored from the declared expectation class."""
    collector = _collector()
    collector.record_ground_truth(
        step=0, label="LEGITIMATE_ALLOW", action="ALLOW", trust_state="STABLE", permitted=True
    )
    collector.record_ground_truth(
        step=1,
        label="LEGITIMATE_ALLOW",
        action="DENY",
        trust_state="UNTRUSTED",
        permitted=False,
    )
    collector.record_ground_truth(
        step=2, label="MALICIOUS_REJECT", action="ALLOW", trust_state="STABLE", permitted=True
    )
    collector.record_ground_truth(
        step=3,
        label="MALICIOUS_REJECT",
        action="DENY",
        trust_state="UNTRUSTED",
        permitted=False,
    )

    confusion = collector.confusion()
    assert confusion["correct_acceptance"] == 1
    assert confusion["false_rejection"] == 1
    assert confusion["false_acceptance"] == 1
    assert confusion["correct_rejection"] == 1
    assert confusion["legitimate_total"] == 2
    assert confusion["adversarial_total"] == 2
    assert confusion["labelled_total"] == 4
    # Security convention: the adversarial step is the positive class.
    assert confusion["true_positive"] == confusion["correct_rejection"]
    assert confusion["false_negative"] == confusion["false_acceptance"]
    assert confusion["true_negative"] == confusion["correct_acceptance"]
    assert confusion["false_positive"] == confusion["false_rejection"]


def test_proportionate_outcomes_are_not_false_rejections() -> None:
    """A step-up for a device declared LEGITIMATE_STEP_UP is correct, not a rejection.

    Scoring any non-ALLOW as a rejection would penalise exactly the proportionate
    behaviour the framework is designed to produce.
    """
    collector = _collector()
    collector.record_ground_truth(
        step=0,
        label="LEGITIMATE_STEP_UP",
        action="STEP_UP_AUTHENTICATION",
        trust_state="DEGRADED",
        permitted=False,
    )
    collector.record_ground_truth(
        step=1,
        label="LEGITIMATE_RESTRICT",
        action="ALLOW_WITH_RESTRICTIONS",
        trust_state="TRANSITIONAL",
        permitted=True,
    )
    confusion = collector.confusion()
    assert confusion["false_rejection"] == 0
    assert confusion["correct_acceptance"] == 2


def test_denying_a_legitimate_device_is_a_false_rejection() -> None:
    collector = _collector()
    collector.record_ground_truth(
        step=0,
        label="LEGITIMATE_STEP_UP",
        action="DENY",
        trust_state="UNTRUSTED",
        permitted=False,
    )
    assert collector.confusion()["false_rejection"] == 1


def test_allowing_an_adversarial_step_is_a_false_acceptance() -> None:
    collector = _collector()
    collector.record_ground_truth(
        step=0,
        label="MALICIOUS_QUARANTINE",
        action="ALLOW_WITH_RESTRICTIONS",
        trust_state="TRANSITIONAL",
        permitted=True,
    )
    assert collector.confusion()["false_acceptance"] == 1


def test_confusion_always_reports_its_denominators() -> None:
    """A rate without its denominator is not reportable."""
    collector = _collector()
    collector.record_ground_truth(
        step=0, label="LEGITIMATE_ALLOW", action="ALLOW", trust_state="STABLE", permitted=True
    )
    confusion = collector.confusion()
    for field in ("legitimate_total", "adversarial_total", "labelled_total"):
        assert field in confusion


def test_decision_recording_counts_state_transitions() -> None:
    collector = _collector()
    collector.record_decision("ALLOW", "STABLE", None)
    collector.record_decision("ALLOW_WITH_RESTRICTIONS", "TRANSITIONAL", "STABLE")
    collector.record_decision("STEP_UP_AUTHENTICATION", "DEGRADED", "TRANSITIONAL")
    collector.record_decision("REAUTHENTICATE", "SUSPICIOUS", "DEGRADED")

    assert collector.counters["M7"] == 3
    assert collector.counters["M5"] == 1
    assert collector.counters["M6"] == 1
    assert collector.state_transitions["STABLE->TRANSITIONAL"] == 1


def test_summary_records_the_measurement_tier() -> None:
    summary = _collector().summary()
    assert summary["measurement_tier"] == MeasurementTier.TIER1.value
    assert "confusion_raw" in summary
    assert "distributions" in summary


# --- resource sampling ------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected_mib"),
    [
        ("44.23MiB / 8.788GiB", 44.23),
        ("1.5GiB / 8GiB", 1536.0),
        ("512KiB / 8GiB", 0.5),
        ("1048576B / 8GiB", 1.0),
        ("not-a-value", 0.0),
    ],
)
def test_memory_parsing_prefers_the_longest_unit(raw: str, expected_mib: float) -> None:
    """ "B" is a suffix of "MiB"; matching it first would scale by a million."""
    from experiments.runner.resources import _parse_memory

    assert _parse_memory(raw) == pytest.approx(expected_mib, rel=1e-3)


@pytest.mark.parametrize(("raw", "expected"), [("16.20%", 16.20), ("0.05%", 0.05), ("bad", 0.0)])
def test_cpu_percent_parsing(raw: str, expected: float) -> None:
    from experiments.runner.resources import _parse_percent

    assert _parse_percent(raw) == pytest.approx(expected)


def test_resource_summary_declares_its_sampling_mechanism() -> None:
    from experiments.runner.resources import ResourceSampler

    summary = ResourceSampler(interval_s=1.0).summary()
    assert summary["sample_interval_s"] == 1.0
    assert "docker stats" in summary["sampling_mechanism"]
    assert "device agent" in summary["excluded"]


def test_run_ids_do_not_collide_within_one_second() -> None:
    """A campaign repeats a condition inside the same second.

    E13 runs one condition at four device levels and an infrastructure retry
    repeats a condition outright. Two runs sharing an identifier would share a raw
    directory and append into each other's JSON Lines.
    """
    from experiments.runner.controller import make_run_id

    ids = {make_run_id("E13", "ca_ztcf", 20260907) for _ in range(200)}
    assert len(ids) == 200


def test_resource_record_does_not_contradict_what_it_measured() -> None:
    """The exclusion note must not deny measuring what the process block measures.

    An earlier version said the experiment runner was not measured while carrying
    that runner's own CPU and memory beside it. A reader trusting the note would
    have misread every resource figure in the final results.
    """
    from experiments.runner.resources import ProcessResourceSampler, ResourceSampler

    summary = ResourceSampler(interval_s=0.1).summary()
    summary["process"] = ProcessResourceSampler(interval_s=0.1).summary()
    excluded = summary["excluded"].lower()
    assert "device agent" in excluded
    assert "experiment runner are not measured" not in excluded
    assert summary["process"]["subject"] == "experiment_process"
    assert "not an iot device measurement" in summary["process"]["note"].lower()


def test_cpu_utilisation_is_defined_for_a_run_shorter_than_one_sample() -> None:
    """Most runs finish inside one sampling interval.

    Interval sampling then yields nothing, and shortening the interval would
    perturb the latency being measured. CPU seconds over wall time is exact and
    always defined, so that is what must be reported.
    """
    import time

    from experiments.runner.resources import ProcessResourceSampler

    sampler = ProcessResourceSampler(interval_s=5.0)
    sampler.start()
    sum(range(200_000))
    time.sleep(0.05)
    sampler.stop()
    summary = sampler.summary()
    assert summary["sample_count"] == 0
    assert summary["cpu_seconds_total"] is not None
    assert summary["cpu_percent_mean_over_run"] is not None
    assert summary["wall_seconds"] > 0
