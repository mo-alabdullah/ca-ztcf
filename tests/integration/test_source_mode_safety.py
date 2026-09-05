"""The source-mode and results-path safety gates.

These are the checks that stop Tier-1 development output being mistaken for a
measurement of real radio infrastructure. A gate that cannot fail is worthless, so
the negative cases are tested as carefully as the positive ones.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ca_ztcf.collectors.base import (
    MEASUREMENT_SOURCE_MODES,
    TIER1_SOURCE_MODES,
    MeasurementTier,
    SourceMode,
)

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / "scripts" / "check_source_modes.py"


def run_gate(results: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GATE), "--results", str(results), "--repo", str(REPO)],
        capture_output=True,
        text=True,
        check=False,
    )


# --- the enum itself --------------------------------------------------------


def test_tier1_source_modes_exclude_live_testbed() -> None:
    assert SourceMode.LIVE_TESTBED not in TIER1_SOURCE_MODES
    assert SourceMode.TIER1_WLAN_AUTH_EMULATION in TIER1_SOURCE_MODES
    assert SourceMode.SYNTHETIC_FIXTURE in TIER1_SOURCE_MODES


def test_only_live_testbed_counts_as_a_measurement() -> None:
    assert frozenset({SourceMode.LIVE_TESTBED}) == MEASUREMENT_SOURCE_MODES
    assert SourceMode.TIER1_WLAN_AUTH_EMULATION not in MEASUREMENT_SOURCE_MODES
    assert SourceMode.SYNTHETIC_FIXTURE not in MEASUREMENT_SOURCE_MODES


def test_measurement_tiers_are_distinct() -> None:
    assert MeasurementTier.TIER1.value == "tier1"
    assert MeasurementTier.TIER2.value == "tier2"


# --- the gate ---------------------------------------------------------------


def _write(root: Path, events: list[dict[str, object]], metadata: dict[str, object]) -> None:
    raw = root / "raw" / "run-1"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
    )
    meta = root / "metadata"
    meta.mkdir(parents=True, exist_ok=True)
    (meta / "run-1.json").write_text(json.dumps(metadata), encoding="utf-8")


GOOD_METADATA: dict[str, object] = {
    "measurement_tier": "tier1",
    "result_class": "development_validation",
    "disclaimer": "Tier-1 development validation. Not a measurement.",
    "source_modes": ["synthetic_fixture", "tier1_wlan_auth_emulation"],
}


def test_gate_passes_on_correctly_labelled_output(tmp_path: Path) -> None:
    _write(
        tmp_path,
        [
            {"kind": "nr_session", "source_mode": "synthetic_fixture"},
            {"kind": "wlan_session", "source_mode": "tier1_wlan_auth_emulation"},
        ],
        GOOD_METADATA,
    )
    result = run_gate(tmp_path)
    assert result.returncode == 0, result.stdout
    assert "PASSED" in result.stdout


def test_gate_fails_when_a_wlan_event_claims_live_testbed(tmp_path: Path) -> None:
    _write(tmp_path, [{"kind": "wlan_session", "source_mode": "live_testbed"}], GOOD_METADATA)
    result = run_gate(tmp_path)
    assert result.returncode == 1
    assert "reserved for Tier-2" in result.stdout


def test_gate_fails_when_synthetic_nr_claims_live_testbed(tmp_path: Path) -> None:
    _write(tmp_path, [{"kind": "nr_session", "source_mode": "live_testbed"}], GOOD_METADATA)
    result = run_gate(tmp_path)
    assert result.returncode == 1
    assert "synthetic_fixture" in result.stdout


def test_gate_fails_when_a_wlan_event_claims_synthetic_fixture(tmp_path: Path) -> None:
    _write(tmp_path, [{"kind": "wlan_session", "source_mode": "synthetic_fixture"}], GOOD_METADATA)
    assert run_gate(tmp_path).returncode == 1


def test_gate_fails_on_an_unknown_source_mode(tmp_path: Path) -> None:
    _write(tmp_path, [{"kind": "nr_session", "source_mode": "made_up"}], GOOD_METADATA)
    result = run_gate(tmp_path)
    assert result.returncode == 1
    assert "unknown source_mode" in result.stdout


def test_gate_fails_when_a_tier1_run_omits_its_result_class(tmp_path: Path) -> None:
    metadata = dict(GOOD_METADATA)
    del metadata["result_class"]
    _write(tmp_path, [{"kind": "nr_session", "source_mode": "synthetic_fixture"}], metadata)
    result = run_gate(tmp_path)
    assert result.returncode == 1
    assert "development_validation" in result.stdout


def test_gate_fails_when_a_tier1_run_omits_its_disclaimer(tmp_path: Path) -> None:
    metadata = dict(GOOD_METADATA)
    del metadata["disclaimer"]
    _write(tmp_path, [{"kind": "nr_session", "source_mode": "synthetic_fixture"}], metadata)
    result = run_gate(tmp_path)
    assert result.returncode == 1
    assert "disclaimer" in result.stdout


def test_gate_fails_when_run_metadata_claims_live_testbed(tmp_path: Path) -> None:
    metadata = dict(GOOD_METADATA)
    metadata["source_modes"] = ["live_testbed"]
    _write(tmp_path, [{"kind": "nr_session", "source_mode": "synthetic_fixture"}], metadata)
    assert run_gate(tmp_path).returncode == 1


# --- the committed development tree ----------------------------------------


def test_committed_development_results_pass_the_gate() -> None:
    results = REPO / "results" / "dev"
    if not (results / "raw").is_dir():
        pytest.skip("no development results present")
    result = run_gate(results)
    assert result.returncode == 0, result.stdout
    assert "live_testbed present : no" in result.stdout


def test_no_development_run_is_written_to_a_final_results_path() -> None:
    for candidate in ("results/final", "results/thesis", "results/publication"):
        assert not (REPO / candidate).exists(), (
            f"{candidate} exists; Tier-1 development output must never live there"
        )
