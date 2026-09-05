"""Deterministic development fixtures.

Everything produced here is a development fixture, stamped
``source_mode = synthetic_fixture``. Fixtures exist so that batches A-E can be
built and tested before a Tier-2 Open5GS/UERANSIM or hostapd capture exists. They
are never a measurement and must never be reported as one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from ca_ztcf.collectors.base import AccessDomain, SourceMode
from ca_ztcf.collectors.nr import NrAccessEvent, NrEventType
from ca_ztcf.collectors.wlan import WlanAccessEvent, WlanEventType

FIXTURE_NR_ADDRESS = "10.45.0.2"
FIXTURE_WLAN_ADDRESS = "192.168.60.2"


@dataclass(frozen=True)
class FixtureProfile:
    """Parameters of a synthetic device used in development and unit tests."""

    device_id: str = "dev-fixture-001"
    subscriber_ref: str = "fixture-subscriber-001"
    sta_mac: str = "02:00:00:00:00:01"
    eap_identity: str = "fixture-device@lab.invalid"
    nr_address: str = FIXTURE_NR_ADDRESS
    wlan_address: str = FIXTURE_WLAN_ADDRESS
    gnb_id: str = "gnb-001"
    ssid: str = "ca-ztcf-lab"
    ap_bssid: str = "02:00:00:00:0a:01"
    akm: str = "WPA2-EAP"
    binding_lifetime_s: int = 120


def nr_event(
    profile: FixtureProfile,
    observed_at: datetime,
    *,
    event_type: NrEventType = NrEventType.SESSION_ESTABLISHED,
    registration_state: str = "REGISTERED",
    pdu_session_active: bool = True,
    gnb_id: str | None = None,
) -> NrAccessEvent:
    return NrAccessEvent(
        event_type=event_type,
        peer_address=profile.nr_address,
        observed_at=observed_at,
        source_mode=SourceMode.SYNTHETIC_FIXTURE,
        subscriber_ref=profile.subscriber_ref,
        pdu_session_id="1",
        dnn="internet",
        gnb_id=gnb_id if gnb_id is not None else profile.gnb_id,
        rat_type="NR",
        registration_state=registration_state,
        pdu_session_active=pdu_session_active,
        binding_lifetime_s=profile.binding_lifetime_s,
    )


def wlan_event(
    profile: FixtureProfile,
    observed_at: datetime,
    *,
    event_type: WlanEventType = WlanEventType.STA_AUTHENTICATED,
    eap_success: bool = True,
    akm: str | None = None,
    ssid: str | None = None,
) -> WlanAccessEvent:
    return WlanAccessEvent(
        event_type=event_type,
        peer_address=profile.wlan_address,
        observed_at=observed_at,
        source_mode=SourceMode.SYNTHETIC_FIXTURE,
        sta_mac=profile.sta_mac,
        eap_identity=profile.eap_identity,
        eap_success=eap_success,
        akm=akm if akm is not None else profile.akm,
        ssid=ssid if ssid is not None else profile.ssid,
        ap_bssid=profile.ap_bssid,
        binding_lifetime_s=profile.binding_lifetime_s,
    )


def steady_nr_sequence(
    profile: FixtureProfile,
    start: datetime,
    *,
    count: int = 3,
    interval_s: int = 10,
) -> list[NrAccessEvent]:
    """A device remaining in the 5G domain, refreshing its binding periodically."""
    events = [nr_event(profile, start)]
    for index in range(1, count):
        events.append(
            nr_event(
                profile,
                start + timedelta(seconds=interval_s * index),
                event_type=NrEventType.SESSION_REFRESHED,
            )
        )
    return events


def nr_to_wlan_sequence(
    profile: FixtureProfile,
    start: datetime,
    *,
    gap_s: int = 5,
) -> tuple[list[NrAccessEvent], list[WlanAccessEvent]]:
    """A legitimate 5G to WLAN transition: 5G session released, WLAN authenticated."""
    nr_events = [
        nr_event(profile, start),
        nr_event(
            profile,
            start + timedelta(seconds=gap_s),
            event_type=NrEventType.SESSION_RELEASED,
        ),
    ]
    wlan_events = [wlan_event(profile, start + timedelta(seconds=gap_s))]
    return nr_events, wlan_events


DOMAIN_ADDRESSES: dict[AccessDomain, str] = {
    AccessDomain.NR: FIXTURE_NR_ADDRESS,
    AccessDomain.WLAN: FIXTURE_WLAN_ADDRESS,
}


__all__ = [
    "DOMAIN_ADDRESSES",
    "FIXTURE_NR_ADDRESS",
    "FIXTURE_WLAN_ADDRESS",
    "FixtureProfile",
    "nr_event",
    "nr_to_wlan_sequence",
    "steady_nr_sequence",
    "wlan_event",
]
