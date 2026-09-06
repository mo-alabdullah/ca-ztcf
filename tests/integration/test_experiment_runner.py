"""The experiment runner: execution, raw output, reproducibility and baselines."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from experiments.analysis import process, tables
from experiments.runner.controller import (
    PERMITTING_ACTIONS,
    ScenarioRunner,
    make_run_id,
    run_scenario,
    write_run,
)
from experiments.schemas.scenario import load_scenario, load_scenarios

from ca_ztcf.collectors.base import MeasurementTier, SourceMode

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]
SCENARIOS = REPO / "experiments" / "scenarios"
CONFIG = REPO / "config"
STRATEGIES = ["ca_ztcf", "independent", "static_continuity"]


def _run(scenario_id: str, strategy: str, out: Path):
    scenario = load_scenario(SCENARIOS / f"{scenario_id}.yaml")
    return run_scenario(scenario, strategy, config_dir=CONFIG, output_root=out)


# --- run identity and metadata ---------------------------------------------


def test_run_id_follows_the_declared_format() -> None:
    from datetime import UTC, datetime

    run_id = make_run_id("E01", "ca_ztcf", 1001, datetime(2026, 6, 1, 9, 0, 0, tzinfo=UTC))
    assert run_id == "E01-ca_ztcf-1001-20260601T090000Z"


def test_every_run_records_the_information_needed_to_reproduce_it(tmp_path: Path) -> None:
    result, written = _run("E01", "ca_ztcf", tmp_path)
    assert result.ok, result.errors

    metadata = json.loads(written["metadata"].read_text(encoding="utf-8"))
    for field in (
        "run_id",
        "scenario_id",
        "strategy",
        "seed",
        "device_count",
        "config_hash",
        "measurement_tier",
        "result_class",
        "disclaimer",
        "source_modes",
        "git",
        "environment",
        "clock",
        "timing",
        "started_at",
        "finished_at",
    ):
        assert field in metadata, f"metadata is missing {field}"
    assert metadata["config_hash"]
    assert metadata["timing"]["durations"] == "time.perf_counter_ns"
    assert metadata["timing"]["timestamps"] == "UTC wall clock"


def test_metadata_declares_tier1_and_its_disclaimer(tmp_path: Path) -> None:
    _, written = _run("E03", "ca_ztcf", tmp_path)
    metadata = json.loads(written["metadata"].read_text(encoding="utf-8"))
    assert metadata["measurement_tier"] == MeasurementTier.TIER1.value
    assert metadata["result_class"] == "development_validation"
    disclaimer = metadata["disclaimer"].lower()
    assert "synthetic" in disclaimer
    assert "not a wifi" in disclaimer
    assert "not final thesis" in disclaimer


def test_source_modes_are_only_the_permitted_tier1_values(tmp_path: Path) -> None:
    _, written = _run("E03", "ca_ztcf", tmp_path)
    metadata = json.loads(written["metadata"].read_text(encoding="utf-8"))
    assert SourceMode.LIVE_TESTBED.value not in metadata["source_modes"]
    assert set(metadata["source_modes"]) <= {
        SourceMode.SYNTHETIC_FIXTURE.value,
        SourceMode.TIER1_WLAN_AUTH_EMULATION.value,
    }


def test_nr_events_are_always_synthetic_and_wlan_always_tier1(tmp_path: Path) -> None:
    result, _ = _run("E03", "ca_ztcf", tmp_path)
    for event in result.events:
        if event.get("kind") == "nr_session":
            assert event["source_mode"] == SourceMode.SYNTHETIC_FIXTURE.value
        if event.get("kind") == "wlan_session":
            assert event["source_mode"] == SourceMode.TIER1_WLAN_AUTH_EMULATION.value


# --- raw output -------------------------------------------------------------


def test_raw_output_is_machine_readable_jsonl(tmp_path: Path) -> None:
    _result, written = _run("E03", "ca_ztcf", tmp_path)
    decisions_path = written["decisions.jsonl"]
    rows = [
        json.loads(line)
        for line in decisions_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert rows
    for row in rows:
        for field in (
            "run_id",
            "scenario_id",
            "strategy",
            "seed",
            "device_id",
            "decision_id",
            "at",
            "trust_state",
            "action",
            "reason_codes",
            "config_hash",
            "decision_latency_ms",
            "measurement_tier",
        ):
            assert field in row, f"decision row is missing {field}"


def test_raw_output_is_append_only(tmp_path: Path) -> None:
    scenario = load_scenario(SCENARIOS / "E01.yaml")
    runner = ScenarioRunner(scenario, "ca_ztcf", config_dir=CONFIG, output_root=tmp_path)
    result = runner.run()
    write_run(result, tmp_path)
    first = (tmp_path / "raw" / result.run_id / "events.jsonl").read_text(encoding="utf-8")
    write_run(result, tmp_path)
    second = (tmp_path / "raw" / result.run_id / "events.jsonl").read_text(encoding="utf-8")
    assert second.startswith(first)
    assert len(second) > len(first)


# --- determinism ------------------------------------------------------------


def test_repeated_runs_produce_the_same_decision_sequence(tmp_path: Path) -> None:
    """Same scenario, same seed, same configuration: same decisions."""
    sequences = []
    for index in range(3):
        result, _ = _run("E03", "ca_ztcf", tmp_path / f"run{index}")
        sequences.append(
            [(d["trust_state"], d["action"], tuple(d["reason_codes"])) for d in result.decisions]
        )
    assert sequences[0] == sequences[1] == sequences[2]


def test_all_scenarios_execute_under_all_strategies(tmp_path: Path) -> None:
    scenarios = load_scenarios(SCENARIOS)
    assert [s.scenario_id for s in scenarios] == [f"E{i:02d}" for i in range(1, 16)]
    for scenario in scenarios:
        for strategy in STRATEGIES:
            result, _ = run_scenario(scenario, strategy, config_dir=CONFIG, output_root=tmp_path)
            assert result.ok, f"{scenario.scenario_id}/{strategy}: {result.errors}"
            assert result.decisions, f"{scenario.scenario_id}/{strategy} produced no decisions"


# --- baselines --------------------------------------------------------------


def test_baselines_and_ca_ztcf_differ_on_a_transition(tmp_path: Path) -> None:
    """The comparison is only meaningful if the three actually diverge."""
    actions = {}
    for strategy in STRATEGIES:
        result, _written = _run("E03", strategy, tmp_path / strategy)
        actions[strategy] = set(result.metrics["policy_action_distribution"])

    assert "REAUTHENTICATE" in actions["independent"]
    assert "ALLOW_WITH_RESTRICTIONS" in actions["ca_ztcf"]
    assert actions["static_continuity"] == {"ALLOW"}
    assert actions["ca_ztcf"] != actions["independent"] != actions["static_continuity"]


def test_static_continuity_token_ttl_is_configurable(tmp_path: Path) -> None:
    scenario = load_scenario(SCENARIOS / "E03.yaml")
    runner = ScenarioRunner(scenario, "static_continuity", config_dir=CONFIG, output_root=tmp_path)
    runner.prepare()
    assert runner.state is not None
    strategy = runner.state.strategy("static_continuity")
    assert strategy.token_ttl_s > 0


@pytest.mark.parametrize("ttl", [30, 300, 1800])
def test_static_continuity_behaves_across_declared_token_lifetimes(
    tmp_path: Path, ttl: int
) -> None:
    """Baseline B is characterised across its trade-off, not at one point."""
    scenario = load_scenario(SCENARIOS / "E03.yaml")
    runner = ScenarioRunner(
        scenario, "static_continuity", config_dir=CONFIG, output_root=tmp_path / str(ttl)
    )
    runner.prepare()
    assert runner.state is not None
    strategy = runner.state.strategy("static_continuity")
    strategy.definition = strategy.definition.model_copy(
        update={"parameters": {"token_ttl_s": ttl}}
    )
    assert strategy.token_ttl_s == ttl
    result = runner.run()
    assert result.ok, result.errors


# --- ground truth -----------------------------------------------------------


def test_ground_truth_comes_from_the_scenario_not_the_output(tmp_path: Path) -> None:
    scenario = load_scenario(SCENARIOS / "E03.yaml")
    declared = {
        event.step: event.ground_truth.value
        for event in scenario.event_sequence
        if event.ground_truth.scored
    }
    result, _ = _run("E03", "ca_ztcf", tmp_path)
    for outcome in result.metrics["ground_truth_outcomes"]:
        assert outcome["ground_truth"] == declared[outcome["step"]]


def test_confusion_counts_carry_their_denominators(tmp_path: Path) -> None:
    result, _ = _run("E05", "ca_ztcf", tmp_path)
    confusion = result.metrics["confusion_raw"]
    assert confusion["labelled_total"] == (
        confusion["legitimate_total"] + confusion["illegitimate_total"]
    )
    assert confusion["labelled_total"] == (
        confusion["correct_acceptance"]
        + confusion["false_rejection"]
        + confusion["correct_rejection"]
        + confusion["false_acceptance"]
    )


def test_step_up_is_not_counted_as_an_acceptance() -> None:
    """Holding protected operations is not permitting access."""
    from ca_ztcf.policy.models import PolicyAction

    assert PolicyAction.STEP_UP_AUTHENTICATION not in PERMITTING_ACTIONS
    assert PolicyAction.ALLOW in PERMITTING_ACTIONS
    assert PolicyAction.ALLOW_WITH_RESTRICTIONS in PERMITTING_ACTIONS


# --- processing -------------------------------------------------------------


def test_processing_regenerates_identically_from_raw(tmp_path: Path) -> None:
    for strategy in STRATEGIES:
        _run("E01", strategy, tmp_path)

    first = process.process(tmp_path)
    summary_before = first["summary"].read_text(encoding="utf-8")
    process.process(tmp_path)
    assert first["summary"].read_text(encoding="utf-8") == summary_before


def test_generated_tables_carry_the_development_banner(tmp_path: Path) -> None:
    _run("E01", "ca_ztcf", tmp_path)
    process.process(tmp_path)
    for path in tables.generate_all(tmp_path):
        content = path.read_text(encoding="utf-8")
        assert "DEVELOPMENT VALIDATION" in content
        assert "NOT FINAL THESIS RESULT" in content


def test_processed_csv_reports_raw_counts_not_only_rates(tmp_path: Path) -> None:
    _run("E05", "ca_ztcf", tmp_path)
    outputs = process.process(tmp_path)
    header = outputs["confusion"].read_text(encoding="utf-8")
    for column in ("false_acceptance", "false_rejection", "legitimate_total", "illegitimate_total"):
        assert column in header
