"""Where a scenario's access-domain evidence comes from.

Two sources, one interface. The controller asks for an access event and does not
care which testbed produced it; what it must never do is silently substitute one
for the other, so every event carries the provenance of the source that made it.

``FixtureAccessSource``
    Tier 1. The 5G context is a synthetic development fixture and the WLAN context
    is 802.1X/EAP-TLS authentication-path emulation over a wired driver. Neither
    is a radio measurement, and the 5G side is not a measurement of anything.

``LiveTier2AccessSource``
    Tier 2. Every event is derived from what the access networks themselves
    logged: Open5GS's own registration and PDU-session lines, and hostapd's own
    association, RSN-handshake and EAP-TLS lines. Addresses are read from the live
    interfaces that actually carry the traffic. If a device has no live
    observation, the source raises rather than inventing one — there is no fixture
    fallback, because a Tier-2 run that quietly fell back would be reported as
    live evidence while not being live evidence.

    SOFTWARE-BASED TESTBED. Real 5G NAS/NGAP/GTP-U and a real 802.11/EAP-TLS
    stack over simulated radios. Nothing from it may be used to claim RF
    propagation, interference, channel quality or physical handover behaviour.

Adversarial scenarios (E06-E10) apply overrides — stale evidence, a mismatched
identity, an unauthorised context. On the live source those overrides are applied
on top of a real observation and are marked ``adversarial_override`` on the event
record, because the manipulation is the experiment's, not the network's. No access
network can be asked to emit a genuinely malicious event.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol

from ca_ztcf.collectors.base import AccessDomain, SourceMode
from ca_ztcf.collectors.nr import NrAccessEvent, NrEventType
from ca_ztcf.collectors.nr_open5gs import Open5gsEvent, Open5gsEventSource, to_nr_access_event
from ca_ztcf.collectors.wlan import WlanAccessEvent, WlanEventType
from ca_ztcf.collectors.wlan_hwsim import HwsimEventSource, HwsimWlanEvent, to_wlan_access_event
from ca_ztcf.errors import CaZtcfError
from experiments.runner.metrics import MeasurementSubject


class AccessSourceError(CaZtcfError):
    """The access source cannot produce the evidence a scenario asked for."""

    code = "ACCESS_SOURCE_ERROR"


class AccessSource(Protocol):
    """Supplies access-domain evidence for one scenario run."""

    name: str

    def provenance(self) -> dict[str, str]: ...

    def address(self, index: int, domain: AccessDomain) -> str: ...

    def subject(self, domain: AccessDomain) -> MeasurementSubject: ...

    def event_stamp(self, domain: AccessDomain) -> dict[str, str]:
        """Provenance stamped on every event record this source produces."""
        ...

    def nr_event(
        self, device_id: str, index: int, at: datetime, overrides: dict[str, str]
    ) -> NrAccessEvent: ...

    def wlan_event(
        self, device_id: str, index: int, at: datetime, overrides: dict[str, str]
    ) -> WlanAccessEvent: ...


# ---------------------------------------------------------------------------
# Tier 1
# ---------------------------------------------------------------------------


@dataclass
class FixtureAccessSource:
    """Tier-1 evidence: a synthetic 5G fixture and WLAN authentication emulation."""

    nr_address_prefix: str
    wlan_address_prefix: str
    address_offset: int
    address_stride: int
    name: str = "tier1_fixture"

    def provenance(self) -> dict[str, str]:
        return {
            "nr_source_mode": SourceMode.SYNTHETIC_FIXTURE.value,
            "wlan_source_mode": SourceMode.TIER1_WLAN_AUTH_EMULATION.value,
            "measurement_tier": "tier1",
            "note": (
                "synthetic 5G development fixture and 802.1X/EAP-TLS "
                "authentication-path emulation; neither is a radio measurement"
            ),
        }

    def address(self, index: int, domain: AccessDomain) -> str:
        prefix = self.nr_address_prefix if domain is AccessDomain.NR else self.wlan_address_prefix
        return f"{prefix}{self.address_offset + index * self.address_stride}"

    def subject(self, domain: AccessDomain) -> MeasurementSubject:
        return (
            MeasurementSubject.SYNTHETIC_NR_CONTEXT
            if domain is AccessDomain.NR
            else MeasurementSubject.EAP_AUTH_PATH
        )

    def event_stamp(self, domain: AccessDomain) -> dict[str, str]:
        # Tier-1 output names no access implementation because there is no access
        # network here to name: the 5G side is a fixture and the WLAN side is an
        # authentication path over a wired driver.
        return {}

    def nr_event(
        self, device_id: str, index: int, at: datetime, overrides: dict[str, str]
    ) -> NrAccessEvent:
        return NrAccessEvent(
            event_type=NrEventType.SESSION_ESTABLISHED,
            peer_address=self.address(index, AccessDomain.NR),
            observed_at=at,
            source_mode=SourceMode.SYNTHETIC_FIXTURE,
            subscriber_ref=f"fixture-sub-{device_id}",
            pdu_session_id="1",
            dnn="internet",
            gnb_id=overrides.get("gnb_id", "gnb-001"),
            rat_type=overrides.get("rat_type", "NR"),
            registration_state=overrides.get("registration_state", "REGISTERED"),
            pdu_session_active=overrides.get("pdu_session_active", "true") == "true",
        )

    def wlan_event(
        self, device_id: str, index: int, at: datetime, overrides: dict[str, str]
    ) -> WlanAccessEvent:
        return WlanAccessEvent(
            event_type=WlanEventType.STA_AUTHENTICATED,
            peer_address=self.address(index, AccessDomain.WLAN),
            observed_at=at,
            source_mode=SourceMode.TIER1_WLAN_AUTH_EMULATION,
            sta_mac=f"02:00:00:00:{index:02x}:11",
            eap_identity=f"{device_id}@lab.invalid",
            eap_success=overrides.get("eap_success", "true") == "true",
            akm=overrides.get("akm", "WPA2-EAP"),
            ssid=overrides.get("ssid", "ca-ztcf-tier1"),
            ap_bssid=overrides.get("ap_bssid", "02:00:00:00:0a:01"),
        )


# ---------------------------------------------------------------------------
# Tier 2
# ---------------------------------------------------------------------------


def _run(argv: list[str]) -> str:
    result = subprocess.run(  # noqa: S603 - fixed argv
        argv, capture_output=True, text=True, check=False, timeout=30
    )
    return result.stdout.strip()


def netns_interface_addresses(namespace: str, prefix: str) -> dict[str, str]:
    """Live IPv4 addresses in a namespace, keyed by interface name.

    Read from the interfaces that actually carry the traffic, so an address used
    in an experiment is one a packet can really be sourced from.
    """
    out = _run(["sudo", "ip", "netns", "exec", namespace, "ip", "-4", "-o", "addr", "show"])
    found: dict[str, str] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 4 or parts[2] != "inet":
            continue
        name, address = parts[1], parts[3].split("/")[0]
        if name.startswith(prefix):
            found.setdefault(name, address)
    return found


def netns_address_list(namespace: str, interface: str) -> list[str]:
    """Every IPv4 address on one interface in a namespace, in kernel order."""
    out = _run(
        ["sudo", "ip", "netns", "exec", namespace, "ip", "-4", "-o", "addr", "show", interface]
    )
    return [p.split()[3].split("/")[0] for p in out.splitlines() if " inet " in p]


@dataclass
class LiveTier2AccessSource:
    """Tier-2 evidence read from the live software-based testbed."""

    ue_namespace: str = "ca-ztcf-ue"
    sta_namespace: str = "ca-ztcf-sta"
    sta_interface: str = "wlan1"
    nr_stream: Path = Path("/var/lib/ca-ztcf/tier2/open5gs-events.log")
    wlan_stream: Path = Path("/var/lib/ca-ztcf/tier2/hostapd.log")
    ssid: str = "ca-ztcf-tier2"
    name: str = "tier2_live"

    nr_addresses: list[str] = field(default_factory=list)
    wlan_addresses: list[str] = field(default_factory=list)
    _nr_by_address: dict[str, Open5gsEvent] = field(default_factory=dict)
    _wlan_events: list[HwsimWlanEvent] = field(default_factory=list)
    _sta_mac: str = ""

    def load(self) -> LiveTier2AccessSource:
        """Snapshot the live testbed. Raises if it is not actually live."""
        tunnels = netns_interface_addresses(self.ue_namespace, "uesimtun")
        self.nr_addresses = [
            tunnels[name] for name in sorted(tunnels, key=lambda n: int(n[len("uesimtun") :]))
        ]
        self.wlan_addresses = netns_address_list(self.sta_namespace, self.sta_interface)
        self._sta_mac = _run(
            [
                "sudo",
                "ip",
                "netns",
                "exec",
                self.sta_namespace,
                "cat",
                f"/sys/class/net/{self.sta_interface}/address",
            ]
        )

        if not self.nr_addresses:
            raise AccessSourceError(
                f"no UE tunnels in namespace {self.ue_namespace}: the 5G path is not live"
            )
        if not self.wlan_addresses:
            raise AccessSourceError(
                f"no station addresses in namespace {self.sta_namespace}: the WLAN path is not live"
            )

        nr_source = Open5gsEventSource(self.nr_stream)
        if not nr_source.available():
            raise AccessSourceError(f"5G event stream not present: {self.nr_stream}")
        # The last observation for an address wins: a later release or
        # re-establishment is the current truth about that session.
        for event in nr_source.read_all():
            if event.peer_address:
                self._nr_by_address[event.peer_address] = event

        wlan_source = HwsimEventSource(self.wlan_stream)
        if not wlan_source.available():
            raise AccessSourceError(f"WLAN event stream not present: {self.wlan_stream}")
        self._wlan_events = [e for e in wlan_source.read_all() if e.succeeded]
        if not self._wlan_events:
            raise AccessSourceError(
                f"no successful WLAN association in {self.wlan_stream}: "
                "the station has not authenticated"
            )
        return self

    # -- interface --------------------------------------------------------

    def provenance(self) -> dict[str, str]:
        return {
            "nr_source_mode": SourceMode.LIVE_TESTBED.value,
            "wlan_source_mode": SourceMode.LIVE_TESTBED.value,
            "measurement_tier": "tier2",
            "testbed_type": "software_based",
            "access_implementation_5g": "ueransim",
            "wifi_radio_mode": "mac80211_hwsim",
            "nr_stream": str(self.nr_stream),
            "wlan_stream": str(self.wlan_stream),
            "ue_namespace": self.ue_namespace,
            "sta_namespace": self.sta_namespace,
            "live_ue_sessions": str(len(self.nr_addresses)),
            "live_station_addresses": str(len(self.wlan_addresses)),
            "note": (
                "live software-based testbed: real 5G NAS/NGAP/GTP-U and a real "
                "802.11/EAP-TLS stack over simulated radios; not an RF, "
                "propagation, interference, channel-quality or physical-handover "
                "measurement"
            ),
        }

    def capacity(self, domain: AccessDomain) -> int:
        return len(self.nr_addresses if domain is AccessDomain.NR else self.wlan_addresses)

    def address(self, index: int, domain: AccessDomain) -> str:
        pool = self.nr_addresses if domain is AccessDomain.NR else self.wlan_addresses
        if index >= len(pool):
            raise AccessSourceError(
                f"device index {index} has no live {domain.value} access path: "
                f"the testbed provides {len(pool)}. Start more UEs or station "
                "addresses; the source will not substitute a fixture."
            )
        return pool[index]

    def subject(self, domain: AccessDomain) -> MeasurementSubject:
        return (
            MeasurementSubject.LIVE_NR_CONTEXT
            if domain is AccessDomain.NR
            else MeasurementSubject.LIVE_WLAN_CONTEXT
        )

    def event_stamp(self, domain: AccessDomain) -> dict[str, str]:
        if domain is AccessDomain.NR:
            return {
                "testbed_type": "software_based",
                "access_implementation": "ueransim",
                "5g_access_mode": "ueransim",
            }
        return {
            "testbed_type": "software_based",
            "access_implementation": "mac80211_hwsim",
            "wifi_radio_mode": "mac80211_hwsim",
        }

    def nr_event(
        self, device_id: str, index: int, at: datetime, overrides: dict[str, str]
    ) -> NrAccessEvent:
        address = self.address(index, AccessDomain.NR)
        observed = self._nr_by_address.get(address)
        if observed is None:
            raise AccessSourceError(
                f"no live Open5GS session observed for {address}; refusing to "
                "substitute a synthetic fixture"
            )
        event = to_nr_access_event(observed, peer_address=address)
        if event is None:
            raise AccessSourceError(f"live 5G observation for {address} carries no binding")
        # The scenario's timeline governs when evidence is presented; the content
        # is the live observation. Adversarial overrides are applied on top.
        return NrAccessEvent(
            event_type=event.event_type,
            peer_address=event.peer_address,
            observed_at=at,
            source_mode=SourceMode.LIVE_TESTBED,
            subscriber_ref=event.subscriber_ref,
            pdu_session_id=event.pdu_session_id,
            dnn=event.dnn,
            gnb_id=overrides.get("gnb_id", event.gnb_id),
            rat_type=overrides.get("rat_type", event.rat_type),
            registration_state=overrides.get("registration_state", event.registration_state),
            pdu_session_active=(
                overrides["pdu_session_active"] == "true"
                if "pdu_session_active" in overrides
                else event.pdu_session_active
            ),
        )

    def wlan_event(
        self, device_id: str, index: int, at: datetime, overrides: dict[str, str]
    ) -> WlanAccessEvent:
        address = self.address(index, AccessDomain.WLAN)
        observed = self._wlan_events[-1]
        event = to_wlan_access_event(observed, peer_address=address, ssid=self.ssid)
        if event is None:
            raise AccessSourceError("live WLAN observation carries no binding")
        return WlanAccessEvent(
            event_type=event.event_type,
            peer_address=address,
            observed_at=at,
            source_mode=SourceMode.LIVE_TESTBED,
            # One real station carries every device's address, so the MAC is the
            # station's. Devices stay distinct by address and by service-domain
            # identity; the MAC is hashed by the collector and never compared with
            # any 5G identifier.
            sta_mac=self._sta_mac or event.sta_mac,
            eap_identity=f"{device_id}@lab.invalid",
            eap_success=(
                overrides["eap_success"] == "true"
                if "eap_success" in overrides
                else event.eap_success
            ),
            akm=overrides.get("akm", event.akm),
            ssid=overrides.get("ssid", event.ssid or self.ssid),
            ap_bssid=overrides.get("ap_bssid", event.ap_bssid),
        )


def build_access_source(
    kind: str,
    *,
    nr_address_prefix: str,
    wlan_address_prefix: str,
    address_offset: int,
    address_stride: int,
) -> AccessSource:
    """``tier1`` for the fixture source, ``tier2`` for the live testbed."""
    if kind == "tier1":
        return FixtureAccessSource(
            nr_address_prefix=nr_address_prefix,
            wlan_address_prefix=wlan_address_prefix,
            address_offset=address_offset,
            address_stride=address_stride,
        )
    if kind == "tier2":
        return LiveTier2AccessSource().load()
    raise AccessSourceError(f"unknown access source: {kind}")


__all__ = [
    "AccessSource",
    "AccessSourceError",
    "FixtureAccessSource",
    "LiveTier2AccessSource",
    "build_access_source",
    "netns_address_list",
    "netns_interface_addresses",
]
