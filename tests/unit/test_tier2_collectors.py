"""Tier-2 live collectors and their provenance discipline.

The central property under test: Tier 2 is a **software-based** testbed. UERANSIM
speaks real 5G protocols to Open5GS but has no radio; mac80211_hwsim runs the real
Linux 802.11 stack over a simulated PHY. Neither may ever be labelled as physical
RF, and both must say what produced them.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ca_ztcf.collectors.base import (
    CLAIMS_FORBIDDEN_FOR_SOFTWARE_TESTBED,
    AccessImplementation,
    InfrastructureKind,
    SourceMode,
)
from ca_ztcf.collectors.nr_open5gs import (
    Open5gsEventSource,
    parse_log_line,
    to_nr_access_event,
)
from ca_ztcf.collectors.nr_open5gs import (
    parse_event_record as parse_nr_record,
)
from ca_ztcf.collectors.nr_open5gs import (
    provenance as nr_provenance,
)
from ca_ztcf.collectors.wlan import WlanEventType
from ca_ztcf.collectors.wlan_hwsim import (
    HwsimEventSource,
    parse_control_line,
)
from ca_ztcf.collectors.wlan_hwsim import (
    parse_event_record as parse_wlan_record,
)
from ca_ztcf.collectors.wlan_hwsim import (
    provenance as wlan_provenance,
)
from ca_ztcf.collectors.wlan_hwsim import (
    to_wlan_access_event as to_hwsim_event,
)
from ca_ztcf.errors import CollectorError

AT = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)


def _nr_record(**overrides) -> dict[str, object]:
    base = {
        "event_type": "SESSION_ESTABLISHED",
        "supi": "imsi-999700000000001",
        "peer_address": "10.45.0.2",
        "observed_at": "2026-06-01T12:00:00.000000Z",
        "source_mode": "live_testbed",
        "access_implementation": "ueransim",
        "testbed_type": "software_based",
        "dnn": "internet",
        "gnb_id": "ueransim-gnb",
    }
    base.update(overrides)
    return base


def _wlan_record(**overrides) -> dict[str, object]:
    base = {
        "event_type": "EAP_SUCCESS",
        "outcome": "SUCCESS",
        "sta_mac": "02:00:00:00:01:00",
        "peer_address": "192.168.70.10",
        "observed_at": "2026-06-01T12:00:00.000000Z",
        "source_mode": "live_testbed",
        "access_implementation": "mac80211_hwsim",
        "testbed_type": "software_based",
        "akm": "WPA2-EAP",
        "eap_identity": "device@lab.invalid",
    }
    base.update(overrides)
    return base


# --- provenance vocabulary --------------------------------------------------


def test_tier2_is_declared_software_based_not_physical() -> None:
    assert InfrastructureKind.SOFTWARE_BASED.value == "software_based"
    assert nr_provenance()["testbed_type"] == InfrastructureKind.SOFTWARE_BASED.value
    assert wlan_provenance()["testbed_type"] == InfrastructureKind.SOFTWARE_BASED.value


def test_provenance_names_the_implementation_that_produced_it() -> None:
    assert nr_provenance()["5g_access_mode"] == AccessImplementation.UERANSIM.value
    assert wlan_provenance()["wifi_radio_mode"] == AccessImplementation.MAC80211_HWSIM.value


def test_provenance_notes_state_there_is_no_physical_radio() -> None:
    """The caveat must travel with the data, not live only in documentation."""
    assert "no physical radio" in nr_provenance()["note"].lower()
    note = wlan_provenance()["note"].lower()
    assert "simulated phy" in note
    assert "no rf propagation" in note


def test_forbidden_claims_cover_the_physical_radio_vocabulary() -> None:
    for claim in ("physical_rf", "rf_propagation", "commercial_5g_network"):
        assert claim in CLAIMS_FORBIDDEN_FOR_SOFTWARE_TESTBED


# --- the live 5G collector --------------------------------------------------


def test_live_5g_event_parses_and_keeps_its_provenance() -> None:
    event = parse_nr_record(_nr_record())
    mapped = to_nr_access_event(event)
    assert mapped is not None
    assert mapped.source_mode is SourceMode.LIVE_TESTBED
    assert mapped.subscriber_ref == "imsi-999700000000001"


def test_live_5g_collector_refuses_a_synthetic_fixture() -> None:
    with pytest.raises(CollectorError, match="live_testbed"):
        parse_nr_record(_nr_record(source_mode="synthetic_fixture"))


def test_live_5g_collector_refuses_a_foreign_implementation() -> None:
    with pytest.raises(CollectorError, match="UERANSIM"):
        parse_nr_record(_nr_record(access_implementation="mac80211_hwsim"))


def test_live_5g_collector_refuses_a_physical_radio_claim() -> None:
    """The check that stops a software testbed being reported as a real network."""
    with pytest.raises(CollectorError, match="no physical radio"):
        parse_nr_record(_nr_record(testbed_type="physical_rf"))


def test_registration_without_an_address_binds_nothing() -> None:
    """A registration alone does not say which address to trust."""
    event = parse_nr_record(_nr_record(event_type="REGISTERED", peer_address=None))
    assert to_nr_access_event(event) is None


def test_session_release_is_mapped_as_a_release() -> None:
    from ca_ztcf.collectors.nr import NrEventType

    event = parse_nr_record(_nr_record(event_type="SESSION_RELEASED", pdu_session_active=False))
    mapped = to_nr_access_event(event)
    assert mapped is not None
    assert mapped.event_type is NrEventType.SESSION_RELEASED


# Verbatim lines from a RUNNING Open5GS 2.8.0 core with UERANSIM attached. Using
# invented formats here would test the parser against our own assumptions, which
# is precisely the mistake ADR-0008 records.
REAL_SMF_SESSION = (
    "09/06 10:44:22.975: [smf] INFO: UE SUPI[imsi-999700000000001] DNN[internet] "
    "IPv4[10.45.0.2] IPv6[] (../src/smf/npcf-handler.c:647)"
)
REAL_UPF_SESSION = (
    "09/06 10:44:22.975: [upf] INFO: UE F-SEID[UP:0x7b7 CP:0x31] APN[internet] "
    "PDN-Type[1] IPv4[10.45.0.2] IPv6[] (../src/upf/context.c:498)"
)
REAL_AMF_CONTEXT = (
    "09/06 10:44:22.983: [amf] INFO: [imsi-999700000000001:1:11][0:0:NULL] "
    "/nsmf-pdusession/v1/sm-contexts/{smContextRef}/modify"
)
REAL_AMF_SLICE = (
    "09/06 10:44:22.960: [gmm] INFO: UE SUPI[imsi-999700000000001] DNN[internet] "
    "LBO[0] S_NSSAI[SST:1 SD:0xffffff] smContextRef[NULL]"
)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (REAL_SMF_SESSION, "SESSION_ESTABLISHED"),
        (REAL_UPF_SESSION, "SESSION_ESTABLISHED"),
        ("[imsi-999700000000001] Registration complete", "REGISTERED"),
        (REAL_AMF_CONTEXT + " UE SM Context Release", "SESSION_RELEASED"),
    ],
)
def test_open5gs_log_lines(line: str, expected: str) -> None:
    event = parse_log_line(line, at=AT)
    assert event is not None
    assert event.event_type == expected


def test_smf_line_is_the_authoritative_supi_to_address_binding() -> None:
    event = parse_log_line(REAL_SMF_SESSION, at=AT)
    assert event is not None
    assert event.supi == "imsi-999700000000001"
    assert event.peer_address == "10.45.0.2"
    assert event.dnn == "internet"


def test_upf_line_supplies_an_address_without_a_supi() -> None:
    event = parse_log_line(REAL_UPF_SESSION, at=AT)
    assert event is not None
    assert event.peer_address == "10.45.0.2"
    assert event.supi is None


def test_pdu_session_id_is_derived_from_the_amf_context_tag() -> None:
    """Open5GS does not log it as a field; ADR-0008 records it as derivable."""
    event = parse_log_line(REAL_AMF_CONTEXT + " UE SM Context Release", at=AT)
    assert event is not None
    assert event.pdu_session_id == "1"


def test_slice_identity_is_captured_even_though_unused() -> None:
    event = parse_log_line(REAL_AMF_SLICE + " Registration complete", at=AT)
    assert event is not None
    assert event.snssai == "SST:1 SD:0xffffff"


def test_release_is_matched_before_establishment() -> None:
    """A release line also names the SUPI; misreading it would resurrect a session."""
    line = REAL_SMF_SESSION + " UE SM Context Release"
    event = parse_log_line(line, at=AT)
    assert event is not None
    assert event.event_type == "SESSION_RELEASED"
    assert event.pdu_session_active is False


def test_serving_node_is_the_n2_address_not_an_invented_cell_id() -> None:
    """ADR-0008: Open5GS logs no per-session gNB identifier."""
    event = parse_log_line("[imsi-999700000000001] Registration complete gNB-N2[127.0.0.1]", at=AT)
    assert event is not None
    assert event.serving_node == "127.0.0.1"


def test_irrelevant_open5gs_lines_are_ignored() -> None:
    assert parse_log_line("[app] Open5GS daemon v2.8.0", at=AT) is None


def test_5g_event_source_reports_unavailability(tmp_path: Path) -> None:
    source = Open5gsEventSource(tmp_path / "absent.jsonl")
    assert source.available() is False
    assert source.read_all() == []


def test_5g_event_source_tails(tmp_path: Path) -> None:
    path = tmp_path / "nr-events.jsonl"
    path.write_text(json.dumps(_nr_record()) + "\n", encoding="utf-8")
    source = Open5gsEventSource(path)
    assert len(source.read_new()) == 1
    assert source.read_new() == []


# --- the live WLAN collector ------------------------------------------------


def test_live_wlan_event_parses_and_keeps_its_provenance() -> None:
    mapped = to_hwsim_event(parse_wlan_record(_wlan_record()))
    assert mapped is not None
    assert mapped.source_mode is SourceMode.LIVE_TESTBED
    assert mapped.event_type is WlanEventType.STA_AUTHENTICATED
    assert mapped.eap_success is True


def test_live_wlan_collector_refuses_tier1_emulation_events() -> None:
    """Tier-1 authentication-path emulation is not 802.11 and must not pose as it."""
    with pytest.raises(CollectorError, match="live_testbed"):
        parse_wlan_record(_wlan_record(source_mode="tier1_wlan_auth_emulation"))


def test_live_wlan_collector_refuses_a_physical_radio_claim() -> None:
    with pytest.raises(CollectorError, match="no physical radio"):
        parse_wlan_record(_wlan_record(testbed_type="physical_rf"))


def test_live_wlan_collector_refuses_a_foreign_implementation() -> None:
    with pytest.raises(CollectorError, match="mac80211_hwsim"):
        parse_wlan_record(_wlan_record(access_implementation="ueransim"))


def test_failed_association_is_evidence_not_a_dropped_event() -> None:
    mapped = to_hwsim_event(
        parse_wlan_record(_wlan_record(event_type="EAP_FAILURE", outcome="FAILURE"))
    )
    assert mapped is not None
    assert mapped.eap_success is False


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("STA 02:00:00:00:01:00 IEEE 802.11: associated", "STA_ASSOCIATED"),
        ("STA 02:00:00:00:01:00 IEEE 802.1X: authenticated - EAP type: 13 (TLS)", "EAP_SUCCESS"),
        ("AP-STA-CONNECTED 02:00:00:00:01:00", "STA_AUTHENTICATED"),
        ("AP-STA-DISCONNECTED 02:00:00:00:01:00", "STA_DISCONNECTED"),
        ("CTRL-EVENT-EAP-FAILURE authentication failed", "EAP_FAILURE"),
    ],
)
def test_hostapd_control_lines_over_virtual_radios(line: str, expected: str) -> None:
    event = parse_control_line(line, at=AT)
    assert event is not None
    assert event.event_type == expected


def test_wlan_event_source_tails(tmp_path: Path) -> None:
    path = tmp_path / "wlan-events.jsonl"
    path.write_text(json.dumps(_wlan_record()) + "\n", encoding="utf-8")
    source = HwsimEventSource(path)
    assert len(source.read_new()) == 1
    assert source.read_new() == []


# --- identity discipline ----------------------------------------------------


def test_subscriber_identifier_is_hashed_before_it_reaches_a_binding(clock) -> None:
    """SUPI is access evidence, never the service-domain identity."""
    from ca_ztcf.collectors.base import BindingStore
    from ca_ztcf.collectors.nr import NRCollector

    store = BindingStore(clock)
    collector = NRCollector(clock, store)
    event = to_nr_access_event(parse_nr_record(_nr_record()))
    assert event is not None
    binding = collector.ingest(event)
    assert binding is not None
    assert "imsi-999700000000001" not in str(binding.attributes)
    assert "subscriber_ref_hash" in binding.attributes


def test_5g_and_wlan_identifiers_are_never_comparable(clock) -> None:
    from ca_ztcf.collectors.base import BindingStore
    from ca_ztcf.collectors.nr import NRCollector
    from ca_ztcf.collectors.wlan import WLANCollector

    store = BindingStore(clock)
    nr = NRCollector(clock, store)
    wlan = WLANCollector(clock, store)
    shared = "identical-raw-identifier"
    assert nr.hash_identifier(shared) != wlan.hash_identifier(shared)
