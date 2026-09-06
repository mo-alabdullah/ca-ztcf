"""Where access evidence comes from, and what it is allowed to claim.

The mistake these tests exist to prevent is a Tier-2 run that quietly used a
fixture and was reported as live evidence. The live source must fail loudly rather
than substitute anything, and the two sources must never be confusable in the
output they stamp.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from experiments.runner.access_sources import (
    AccessSourceError,
    FixtureAccessSource,
    LiveTier2AccessSource,
    build_access_source,
)
from experiments.runner.metrics import MeasurementSubject

from ca_ztcf.collectors.base import AccessDomain, SourceMode

AT = datetime(2026, 6, 1, 9, 0, 0, tzinfo=UTC)


def fixture_source() -> FixtureAccessSource:
    return FixtureAccessSource(
        nr_address_prefix="10.45.0.",
        wlan_address_prefix="192.168.60.",
        address_offset=2,
        address_stride=1,
    )


def live_source() -> LiveTier2AccessSource:
    """A live source with its snapshot supplied, so the test needs no testbed."""
    source = LiveTier2AccessSource()
    source.nr_addresses = ["10.45.10.1", "10.45.10.2"]
    source.wlan_addresses = ["192.168.70.10", "192.168.70.11"]
    source._sta_mac = "02:00:00:00:01:00"
    from ca_ztcf.collectors.nr_open5gs import parse_log_line
    from ca_ztcf.collectors.wlan_hwsim import parse_control_line

    for address in source.nr_addresses:
        event = parse_log_line(
            f"[smf] INFO: UE SUPI[imsi-999700000000001] DNN[internet] IPv4[{address}] IPv6[]"
        )
        assert event is not None
        source._nr_by_address[address] = event
    associated = parse_control_line("wlan0: AP-STA-CONNECTED 02:00:00:00:01:00")
    assert associated is not None
    source._wlan_events = [associated]
    return source


# -- Tier 1 ----------------------------------------------------------------


def test_fixture_source_declares_tier1_modes() -> None:
    source = fixture_source()
    nr = source.nr_event("dev-0", 0, AT, {})
    wlan = source.wlan_event("dev-0", 0, AT, {})
    assert nr.source_mode is SourceMode.SYNTHETIC_FIXTURE
    assert wlan.source_mode is SourceMode.TIER1_WLAN_AUTH_EMULATION


def test_fixture_source_names_no_access_implementation() -> None:
    """There is no access network in Tier 1 to name, so nothing may be claimed."""
    source = fixture_source()
    assert source.event_stamp(AccessDomain.NR) == {}
    assert source.event_stamp(AccessDomain.WLAN) == {}


def test_fixture_addresses_respect_stride() -> None:
    source = FixtureAccessSource(
        nr_address_prefix="10.45.0.",
        wlan_address_prefix="192.168.60.",
        address_offset=2,
        address_stride=4,
    )
    assert source.address(0, AccessDomain.NR) == "10.45.0.2"
    assert source.address(2, AccessDomain.NR) == "10.45.0.10"


# -- Tier 2 ----------------------------------------------------------------


def test_live_source_declares_live_testbed_on_both_domains() -> None:
    source = live_source()
    nr = source.nr_event("dev-0", 0, AT, {})
    wlan = source.wlan_event("dev-0", 0, AT, {})
    assert nr.source_mode is SourceMode.LIVE_TESTBED
    assert wlan.source_mode is SourceMode.LIVE_TESTBED


def test_live_source_stamps_the_software_implementation() -> None:
    source = live_source()
    nr_stamp = source.event_stamp(AccessDomain.NR)
    wlan_stamp = source.event_stamp(AccessDomain.WLAN)
    assert nr_stamp["access_implementation"] == "ueransim"
    assert wlan_stamp["access_implementation"] == "mac80211_hwsim"
    assert nr_stamp["testbed_type"] == "software_based"
    assert wlan_stamp["testbed_type"] == "software_based"


def test_live_source_never_claims_a_physical_radio() -> None:
    provenance = live_source().provenance()
    serialised = " ".join(provenance.values()).lower()
    for claim in ("physical rf", "physical 5g radio", "physical wifi", "real rf"):
        assert claim not in serialised
    assert "not an rf" in serialised


def test_live_source_uses_the_real_observed_subscriber_and_address() -> None:
    source = live_source()
    event = source.nr_event("dev-0", 0, AT, {})
    assert event.peer_address == "10.45.10.1"
    assert event.subscriber_ref == "imsi-999700000000001"


def test_live_source_gives_each_device_its_own_address() -> None:
    """Two devices must never collapse onto one observed source identity."""
    source = live_source()
    first = source.nr_event("dev-0", 0, AT, {})
    second = source.nr_event("dev-1", 1, AT, {})
    assert first.peer_address != second.peer_address
    wlan_first = source.wlan_event("dev-0", 0, AT, {})
    wlan_second = source.wlan_event("dev-1", 1, AT, {})
    assert wlan_first.peer_address != wlan_second.peer_address


def test_live_source_refuses_a_device_it_has_no_path_for() -> None:
    """The failure that matters: no fixture fallback, ever."""
    source = live_source()
    with pytest.raises(AccessSourceError) as excinfo:
        source.nr_event("dev-9", 9, AT, {})
    assert "will not substitute a fixture" in str(excinfo.value)


def test_live_source_refuses_an_address_with_no_live_session() -> None:
    source = live_source()
    source.nr_addresses.append("10.45.10.99")
    with pytest.raises(AccessSourceError) as excinfo:
        source.nr_event("dev-2", 2, AT, {})
    assert "refusing to substitute a synthetic fixture" in str(excinfo.value)


def test_live_source_reports_its_capacity() -> None:
    source = live_source()
    assert source.capacity(AccessDomain.NR) == 2
    assert source.capacity(AccessDomain.WLAN) == 2


def test_adversarial_overrides_apply_on_top_of_a_live_observation() -> None:
    """E06-E10 manipulate real evidence; the manipulation is the experiment's."""
    source = live_source()
    event = source.nr_event("dev-0", 0, AT, {"registration_state": "DEREGISTERED"})
    assert event.registration_state == "DEREGISTERED"
    # Everything not overridden still comes from the live observation.
    assert event.subscriber_ref == "imsi-999700000000001"
    assert event.source_mode is SourceMode.LIVE_TESTBED

    wlan = source.wlan_event("dev-0", 0, AT, {"eap_success": "false"})
    assert wlan.eap_success is False


def test_measurement_subjects_distinguish_the_two_tiers() -> None:
    assert fixture_source().subject(AccessDomain.NR) is (MeasurementSubject.SYNTHETIC_NR_CONTEXT)
    assert live_source().subject(AccessDomain.NR) is MeasurementSubject.LIVE_NR_CONTEXT
    assert live_source().subject(AccessDomain.WLAN) is (MeasurementSubject.LIVE_WLAN_CONTEXT)


def test_live_load_fails_when_the_testbed_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing testbed is missing evidence, not something to work around."""
    monkeypatch.setattr(
        "experiments.runner.access_sources.netns_interface_addresses",
        lambda namespace, prefix: {},
    )
    with pytest.raises(AccessSourceError) as excinfo:
        LiveTier2AccessSource().load()
    assert "not live" in str(excinfo.value)


def test_build_access_source_rejects_an_unknown_kind() -> None:
    with pytest.raises(AccessSourceError):
        build_access_source(
            "tier3",
            nr_address_prefix="10.45.0.",
            wlan_address_prefix="192.168.60.",
            address_offset=2,
            address_stride=1,
        )
