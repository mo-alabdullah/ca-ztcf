"""A result must be labelled with the tier its evidence actually came from.

Two symmetrical mistakes are possible and both misrepresent the work: labelling a
Tier-2 run as a synthetic fixture understates it, and labelling a Tier-1 run as a
live testbed overstates it. The wording is therefore derived from the runs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from experiments.analysis.process import (
    MIXED_DISCLAIMER,
    TIER1_DISCLAIMER,
    TIER2_DISCLAIMER,
    RunRecord,
    disclaimer_for,
)
from experiments.runner.access_sources import FixtureAccessSource
from experiments.runner.controller import ScenarioRunner
from experiments.schemas.scenario import load_scenarios

from ca_ztcf.collectors.base import MeasurementTier

REPO = Path(__file__).resolve().parents[2]


def record(tier: str) -> RunRecord:
    return RunRecord(
        run_id=f"R-{tier}",
        scenario_id="E01",
        strategy="ca_ztcf",
        seed=1,
        measurement_tier=tier,
        metrics={},
        metadata={"measurement_tier": tier},
        decisions=[],
        events=[{"source_mode": "live_testbed" if tier == "tier2" else "synthetic_fixture"}],
    )


def test_tier1_runs_get_the_fixture_wording() -> None:
    text = disclaimer_for([record("tier1")])
    assert text == TIER1_DISCLAIMER
    assert "synthetic fixture" in text


def test_tier2_runs_get_the_live_software_testbed_wording() -> None:
    text = disclaimer_for([record("tier2")])
    assert text == TIER2_DISCLAIMER
    assert "Open5GS" in text and "mac80211_hwsim" in text
    assert "synthetic fixture" not in text


def test_every_disclaimer_denies_a_physical_radio_measurement() -> None:
    for text in (TIER1_DISCLAIMER, TIER2_DISCLAIMER, MIXED_DISCLAIMER):
        lowered = text.lower()
        assert "not final thesis result" in lowered
        assert "measurement" in lowered
        for claim in ("physical rf", "real rf", "commercial 5g"):
            assert claim not in lowered


def test_mixed_runs_are_not_labelled_as_either_tier_alone() -> None:
    text = disclaimer_for([record("tier1"), record("tier2")])
    assert text == MIXED_DISCLAIMER
    assert "Mixed" in text


def test_no_runs_falls_back_to_the_conservative_wording() -> None:
    assert disclaimer_for([]) == TIER1_DISCLAIMER


@pytest.fixture
def scenario():
    return load_scenarios(REPO / "experiments" / "scenarios")[0]


def test_runner_labels_a_run_by_its_access_source_not_the_scenario(scenario) -> None:
    """A scenario declares a tier; the evidence decides what the run really is."""
    runner = ScenarioRunner(
        scenario,
        "ca_ztcf",
        config_dir=REPO / "config",
        output_root=Path("/tmp/ca-ztcf-label-test"),
        start_time=datetime(2026, 6, 1, 9, 0, 0, tzinfo=UTC),
    )
    assert runner._tier() is MeasurementTier.TIER1

    # Only the source's name decides the label, so a stand-in with a Tier-2 name
    # is enough to show the runner follows the source and not the scenario file.
    runner.access_source = FixtureAccessSource(
        nr_address_prefix="10.45.10.",
        wlan_address_prefix="192.168.70.",
        address_offset=1,
        address_stride=1,
        name="tier2_live",
    )
    assert runner._tier() is MeasurementTier.TIER2
    assert "Open5GS" in runner._disclaimer()


def test_scenarios_may_run_on_either_tier(scenario) -> None:
    """A scenario describes access events and behaviour, not a testbed."""
    supported = {tier.value for tier in scenario.supported_tiers}
    assert supported == {"tier1", "tier2"}


def test_every_scenario_supports_the_live_tier() -> None:
    """The final campaign runs on Tier 2, so none may be tier-1-only by accident."""
    for candidate in load_scenarios(REPO / "experiments" / "scenarios"):
        assert MeasurementTier.TIER2 in candidate.supported_tiers, candidate.scenario_id
