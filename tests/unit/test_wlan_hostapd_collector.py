"""Tier-1 WLAN authentication-path collector."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ca_ztcf.collectors.base import SourceMode
from ca_ztcf.collectors.wlan import WlanEventType
from ca_ztcf.collectors.wlan_hostapd import (
    TIER1_SOURCE_MODE,
    HostapdEventSource,
    Tier1AuthEvent,
    parse_control_line,
    parse_event_record,
    to_wlan_access_event,
)
from ca_ztcf.errors import CollectorError

AT = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)


def _record(**overrides) -> dict[str, object]:
    base = {
        "event_type": "EAP_SUCCESS",
        "scenario": "valid",
        "outcome": "SUCCESS",
        "sta_mac": "02:00:00:00:00:11",
        "observed_at": "2026-06-01T12:00:00.000000Z",
        "source_mode": "tier1_wlan_auth_emulation",
        "eap_identity": "device@lab.invalid",
        "eap_method": "TLS",
    }
    base.update(overrides)
    return base


# --- provenance -------------------------------------------------------------


def test_tier1_source_mode_is_not_live_testbed() -> None:
    """The central safety property of this collector."""
    assert TIER1_SOURCE_MODE is SourceMode.TIER1_WLAN_AUTH_EMULATION
    assert TIER1_SOURCE_MODE is not SourceMode.LIVE_TESTBED
    assert TIER1_SOURCE_MODE.value == "tier1_wlan_auth_emulation"


def test_collector_refuses_an_event_claiming_live_testbed() -> None:
    """A Tier-1 collector must never accept a measurement claim."""
    with pytest.raises(CollectorError, match="live_testbed"):
        parse_event_record(_record(source_mode="live_testbed"))


def test_collector_refuses_synthetic_fixture_on_the_wlan_path() -> None:
    with pytest.raises(CollectorError):
        parse_event_record(_record(source_mode="synthetic_fixture"))


def test_every_produced_event_carries_the_tier1_mode() -> None:
    for event_type in ("EAP_SUCCESS", "EAP_FAILURE", "STA_AUTHENTICATED", "STA_DISCONNECTED"):
        event = parse_event_record(_record(event_type=event_type))
        mapped = to_wlan_access_event(event, peer_address="192.168.60.2")
        assert mapped is not None
        assert mapped.source_mode is SourceMode.TIER1_WLAN_AUTH_EMULATION


# --- parsing ----------------------------------------------------------------


def test_valid_authentication_maps_to_an_authenticated_station() -> None:
    mapped = to_wlan_access_event(parse_event_record(_record()), peer_address="192.168.60.2")
    assert mapped is not None
    assert mapped.event_type is WlanEventType.STA_AUTHENTICATED
    assert mapped.eap_success is True
    assert mapped.eap_identity == "device@lab.invalid"


def test_failed_authentication_is_evidence_not_a_dropped_event() -> None:
    """An EAP failure must reach the evidence model so C11 can fail."""
    mapped = to_wlan_access_event(
        parse_event_record(_record(event_type="EAP_FAILURE", outcome="FAILURE")),
        peer_address="192.168.60.2",
    )
    assert mapped is not None
    assert mapped.eap_success is False


def test_disconnect_maps_to_station_disconnected() -> None:
    mapped = to_wlan_access_event(
        parse_event_record(_record(event_type="STA_DISCONNECTED")),
        peer_address="192.168.60.2",
    )
    assert mapped is not None
    assert mapped.event_type is WlanEventType.STA_DISCONNECTED


def test_unknown_event_type_produces_nothing() -> None:
    assert (
        to_wlan_access_event(
            Tier1AuthEvent(
                event_type="SCENARIO_SKIPPED", outcome="SKIPPED", sta_mac="", observed_at=AT
            ),
            peer_address="192.168.60.2",
        )
        is None
    )


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("AP-STA-CONNECTED 02:00:00:00:00:11", "STA_AUTHENTICATED"),
        ("AP-STA-DISCONNECTED 02:00:00:00:00:11", "STA_DISCONNECTED"),
        ("CTRL-EVENT-EAP-SUCCESS EAP authentication completed", "EAP_SUCCESS"),
        ("CTRL-EVENT-EAP-FAILURE EAP authentication failed", "EAP_FAILURE"),
        ("STA 02:00:00:00:00:11 IEEE 802.1X: authenticated - EAP type: 13 (TLS)", "EAP_SUCCESS"),
    ],
)
def test_control_interface_lines(line: str, expected: str) -> None:
    event = parse_control_line(line, at=AT)
    assert event is not None
    assert event.event_type == expected


def test_irrelevant_control_lines_are_ignored() -> None:
    assert parse_control_line("wlan: interface state UNINITIALIZED->ENABLED", at=AT) is None


# --- event source -----------------------------------------------------------


def test_event_source_reports_unavailability_rather_than_raising(tmp_path: Path) -> None:
    """A collector outage is missing evidence, never an exception."""
    source = HostapdEventSource(tmp_path / "absent.jsonl")
    assert source.available() is False
    assert source.read_all() == []


def test_event_source_reads_and_tails(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(json.dumps(_record()) + "\n", encoding="utf-8")
    source = HostapdEventSource(path)

    assert source.available() is True
    assert len(source.read_new()) == 1
    assert source.read_new() == []

    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_record(event_type="STA_DISCONNECTED")) + "\n")
    fresh = source.read_new()
    assert len(fresh) == 1
    assert fresh[0].event_type == "STA_DISCONNECTED"


def test_event_source_falls_back_to_raw_control_lines(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text("AP-STA-CONNECTED 02:00:00:00:00:11\n", encoding="utf-8")
    events = HostapdEventSource(path).read_all()
    assert len(events) == 1
    assert events[0].event_type == "STA_AUTHENTICATED"


def test_raw_eap_secrets_never_appear_in_a_produced_event() -> None:
    """Only the outcome and the certificate identity are carried forward."""
    event = parse_event_record(_record())
    mapped = to_wlan_access_event(event, peer_address="192.168.60.2")
    assert mapped is not None
    serialised = mapped.model_dump_json()
    for forbidden in ("PRIVATE KEY", "pmk", "ptk", "msk", "psk"):
        assert forbidden.lower() not in serialised.lower()
