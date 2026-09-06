"""The E06-E15 scenario declarations and multi-device isolation."""

from __future__ import annotations

from pathlib import Path

import pytest
from experiments.schemas.scenario import EventKind, GroundTruthLabel, load_scenario, load_scenarios

from ca_ztcf.collectors.base import MeasurementTier, SourceMode

SCENARIO_DIR = Path(__file__).resolve().parents[2] / "experiments" / "scenarios"
ALL_IDS = [f"E{index:02d}" for index in range(1, 16)]
NEW_IDS = [f"E{index:02d}" for index in range(6, 16)]


def test_all_fifteen_scenarios_exist_and_parse() -> None:
    assert [s.scenario_id for s in load_scenarios(SCENARIO_DIR)] == ALL_IDS


@pytest.mark.parametrize("scenario_id", NEW_IDS)
def test_new_scenario_is_complete(scenario_id: str) -> None:
    scenario = load_scenario(SCENARIO_DIR / f"{scenario_id}.yaml")
    assert scenario.name
    assert scenario.description
    assert scenario.seed > 0
    assert scenario.device_count >= 1
    assert scenario.event_sequence
    assert scenario.ground_truth.description
    assert scenario.expected_policy_behavior.description
    assert scenario.metrics_to_collect
    assert scenario.measurement_tier is MeasurementTier.TIER1


def test_every_scenario_has_a_unique_seed() -> None:
    seeds = [s.seed for s in load_scenarios(SCENARIO_DIR)]
    assert len(set(seeds)) == len(seeds)


def test_no_scenario_can_claim_a_live_measurement() -> None:
    for scenario in load_scenarios(SCENARIO_DIR):
        assert scenario.setup.nr_source_mode is SourceMode.SYNTHETIC_FIXTURE
        assert scenario.setup.wlan_source_mode is SourceMode.TIER1_WLAN_AUTH_EMULATION


def test_all_three_strategies_are_selected_by_every_scenario() -> None:
    available = ["ca_ztcf", "independent", "static_continuity"]
    for scenario in load_scenarios(SCENARIO_DIR):
        assert scenario.strategies(available) == available


# --- scenario-specific declarations -----------------------------------------


def test_e06_declares_stale_evidence_and_explicit_recovery() -> None:
    scenario = load_scenario(SCENARIO_DIR / "E06.yaml")
    kinds = [event.kind for event in scenario.event_sequence]
    assert EventKind.STALE_EVIDENCE in kinds
    assert scenario.ground_truth.adversarial is False
    # Recovery must be asserted, not assumed: the final scored step expects ALLOW.
    final = list(scenario.scored_events)[-1]
    assert final.ground_truth is GroundTruthLabel.LEGITIMATE_ALLOW


def test_e07_uses_two_separately_enrolled_identities() -> None:
    scenario = load_scenario(SCENARIO_DIR / "E07.yaml")
    assert scenario.device_count == 2
    mismatch = [e for e in scenario.event_sequence if e.kind is EventKind.IDENTITY_MISMATCH]
    assert len(mismatch) == 1
    assert mismatch[0].other_device_index is not None
    assert mismatch[0].ground_truth.is_adversarial


def test_e08_declares_a_posture_override_and_expects_no_normal_transition() -> None:
    scenario = load_scenario(SCENARIO_DIR / "E08.yaml")
    step = next(e for e in scenario.event_sequence if e.kind is EventKind.UNAUTHORIZED_CONTEXT)
    assert step.posture_override
    assert step.ground_truth.is_adversarial


def test_e09_drives_more_transitions_than_the_configured_limit(settings) -> None:
    scenario = load_scenario(SCENARIO_DIR / "E09.yaml")
    step = next(e for e in scenario.event_sequence if e.kind is EventKind.RAPID_TRANSITIONS)
    assert step.repeat > settings.transition.max_transitions_per_window, (
        "E09 must exceed the configured rate limit, which comes from config"
    )
    assert step.repeat * step.interval_s <= settings.transition.rate_window_s


def test_e10_declares_a_session_mismatch() -> None:
    scenario = load_scenario(SCENARIO_DIR / "E10.yaml")
    step = next(e for e in scenario.event_sequence if e.kind is EventKind.SESSION_MISMATCH)
    assert step.ground_truth.is_adversarial


def test_e11_is_the_false_rejection_control() -> None:
    """A framework that denied everything would look secure without this scenario."""
    scenario = load_scenario(SCENARIO_DIR / "E11.yaml")
    assert scenario.ground_truth.adversarial is False
    assert scenario.ground_truth.illegitimate_transitions == 0
    kinds = [e.kind for e in scenario.event_sequence]
    assert EventKind.COLLECTOR_OUTAGE in kinds
    assert EventKind.COLLECTOR_RECOVERY in kinds
    forbidden = set(scenario.expected_policy_behavior.must_not_contain_actions)
    assert {"DENY", "QUARANTINE"} <= {getattr(a, "value", a) for a in forbidden}
    for label in (e.ground_truth for e in scenario.scored_events):
        assert label.is_legitimate


def test_e12_gives_every_device_its_own_address() -> None:
    """Sharing an address makes devices claim one another's bindings."""
    scenario = load_scenario(SCENARIO_DIR / "E12.yaml")
    assert scenario.device_count >= 10
    assert scenario.setup.address_stride >= 1
    forbidden = {
        getattr(s, "value", s) for s in scenario.expected_policy_behavior.must_not_contain_states
    }
    assert "UNTRUSTED" in forbidden, (
        "UNTRUSTED in a concurrency scenario would indicate cross-device leakage"
    )


def test_e13_declares_a_device_count_sweep() -> None:
    scenario = load_scenario(SCENARIO_DIR / "E13.yaml")
    assert scenario.device_counts == (1, 5, 10, 25, 50, 100)
    assert max(scenario.device_counts) >= scenario.device_count


def test_e14_declares_a_transition_rate_sweep() -> None:
    scenario = load_scenario(SCENARIO_DIR / "E14.yaml")
    assert scenario.transition_rates_per_s
    assert list(scenario.transition_rates_per_s) == sorted(scenario.transition_rates_per_s)


def test_e15_declares_a_seeded_mixed_workload() -> None:
    scenario = load_scenario(SCENARIO_DIR / "E15.yaml")
    step = next(e for e in scenario.event_sequence if e.kind is EventKind.MIXED_WORKLOAD)
    assert step.legitimate_fraction == pytest.approx(0.8)
    assert len(step.adversarial_kinds) >= 5
    assert step.repeat >= 50
    assert scenario.ground_truth.adversarial is True


def test_e15_does_not_prejudge_which_strategy_wins() -> None:
    """Declaring an outcome here would prejudge the measurement."""
    scenario = load_scenario(SCENARIO_DIR / "E15.yaml")
    description = scenario.expected_policy_behavior.description.lower()
    assert any(
        phrase in description for phrase in ("measurement", "measured", "not assumed", "prejudge")
    )
    for override in scenario.expected_policy_behavior.strategy_specific.values():
        assert not override.get("must_contain_actions"), (
            "E15 must not declare which actions a strategy should produce"
        )


# --- schema guards ----------------------------------------------------------


def test_a_scored_enforcement_step_must_declare_its_expectation(tmp_path: Path) -> None:
    import yaml

    body = yaml.safe_load((SCENARIO_DIR / "E01.yaml").read_text(encoding="utf-8"))
    for event in body["event_sequence"]:
        if event["kind"] == "mqtt_publish":
            event.pop("expect_permitted", None)
    path = tmp_path / "E90.yaml"
    path.write_text(yaml.safe_dump(body), encoding="utf-8")
    with pytest.raises(ValueError, match="expect_permitted"):
        load_scenario(path)


def test_a_step_cannot_target_a_device_the_scenario_does_not_declare(tmp_path: Path) -> None:
    import yaml

    body = yaml.safe_load((SCENARIO_DIR / "E01.yaml").read_text(encoding="utf-8"))
    body["event_sequence"][1]["device_index"] = 7
    path = tmp_path / "E91.yaml"
    path.write_text(yaml.safe_dump(body), encoding="utf-8")
    with pytest.raises(ValueError, match="device_index"):
        load_scenario(path)
