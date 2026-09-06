"""Live WLAN access-context collector for the Tier-2 software-based testbed.

Consumes hostapd events produced over `mac80211_hwsim` virtual radios, where a
real IEEE 802.11 association and a real WPA2/WPA3-Enterprise EAP-TLS exchange take
place through the Linux `mac80211`/`cfg80211` stack.

**Provenance.** Events carry ``source_mode = live_testbed`` with
``access_implementation = mac80211_hwsim`` and ``testbed_type = software_based``.

The 802.11 state machine, the association and the EAP exchange are genuine. **The
PHY is simulated**: `mac80211_hwsim` provides virtual radios, not physical ones,
so there is no RF propagation, no interference and no channel measurement. Results
may be used as evidence about association and authentication behaviour, session
transitions, trust evaluation, policy enforcement and software latency. They may
**not** be used to claim RF performance, physical handover timing, interference or
spectrum coexistence.

The distinction from Tier 1 matters and is preserved: Tier 1 has no 802.11 at all,
only an 802.1X authentication path over veth.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ca_ztcf.collectors.base import AccessImplementation, InfrastructureKind, SourceMode
from ca_ztcf.collectors.wlan import WlanAccessEvent, WlanEventType
from ca_ztcf.errors import CollectorError

LIVE_SOURCE_MODE = SourceMode.LIVE_TESTBED
ACCESS_IMPLEMENTATION = AccessImplementation.MAC80211_HWSIM
TESTBED_TYPE = InfrastructureKind.SOFTWARE_BASED

_AP_STA_CONNECTED = re.compile(r"AP-STA-CONNECTED\s+(?P<mac>[0-9a-fA-F:]{17})")
_AP_STA_DISCONNECTED = re.compile(r"AP-STA-DISCONNECTED\s+(?P<mac>[0-9a-fA-F:]{17})")
_AUTHENTICATED = re.compile(
    r"STA (?P<mac>[0-9a-fA-F:]{17}) IEEE 802\.1X: authenticated - EAP type: \d+ "
    r"\((?P<method>\w+)\)"
)
_ASSOCIATED = re.compile(r"STA (?P<mac>[0-9a-fA-F:]{17}) IEEE 802\.11: associated")
_EAP_FAILURE = re.compile(r"CTRL-EVENT-EAP-FAILURE|EAP-Failure|authentication failed", re.I)


@dataclass(frozen=True)
class HwsimWlanEvent:
    """A normalised event observed from a live virtual-radio WLAN."""

    event_type: str
    outcome: str
    sta_mac: str
    observed_at: datetime
    eap_identity: str | None = None
    eap_method: str = "TLS"
    akm: str = "WPA2-EAP"
    ssid: str | None = None
    ap_bssid: str | None = None
    peer_address: str | None = None
    raw: str = ""

    @property
    def succeeded(self) -> bool:
        return self.outcome.upper() == "SUCCESS"


def _parse_timestamp(raw: str | None) -> datetime:
    if not raw:
        return datetime.now(UTC)
    text = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return datetime.now(UTC)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def parse_event_record(record: dict[str, object]) -> HwsimWlanEvent:
    """Parse a JSON event emitted by the Tier-2 WLAN capture script."""
    source_mode = str(record.get("source_mode", LIVE_SOURCE_MODE.value))
    if source_mode != LIVE_SOURCE_MODE.value:
        raise CollectorError(
            f"the live WLAN collector refuses an event claiming source_mode "
            f"'{source_mode}'; it only accepts '{LIVE_SOURCE_MODE.value}'"
        )
    implementation = str(record.get("access_implementation", ACCESS_IMPLEMENTATION.value))
    if implementation != ACCESS_IMPLEMENTATION.value:
        raise CollectorError(
            f"the live WLAN collector refuses access_implementation '{implementation}'; "
            f"it only observes mac80211_hwsim virtual radios"
        )
    testbed = str(record.get("testbed_type", TESTBED_TYPE.value))
    if testbed != TESTBED_TYPE.value:
        raise CollectorError(
            f"Tier-2 WLAN events must declare testbed_type '{TESTBED_TYPE.value}': "
            f"mac80211_hwsim has no physical radio, got '{testbed}'"
        )

    return HwsimWlanEvent(
        event_type=str(record.get("event_type", "UNKNOWN")),
        outcome=str(record.get("outcome", "UNKNOWN")),
        sta_mac=str(record.get("sta_mac", "")),
        observed_at=_parse_timestamp(record.get("observed_at")),  # type: ignore[arg-type]
        eap_identity=str(record["eap_identity"]) if record.get("eap_identity") else None,
        eap_method=str(record.get("eap_method", "TLS")),
        akm=str(record.get("akm", "WPA2-EAP")),
        ssid=str(record["ssid"]) if record.get("ssid") else None,
        ap_bssid=str(record["ap_bssid"]) if record.get("ap_bssid") else None,
        peer_address=str(record["peer_address"]) if record.get("peer_address") else None,
        raw=str(record.get("raw", "")),
    )


def parse_control_line(line: str, *, at: datetime | None = None) -> HwsimWlanEvent | None:
    """Parse one hostapd control-interface line from a virtual-radio WLAN."""
    observed_at = at or datetime.now(UTC)

    authenticated = _AUTHENTICATED.search(line)
    if authenticated:
        return HwsimWlanEvent(
            event_type="EAP_SUCCESS",
            outcome="SUCCESS",
            sta_mac=authenticated.group("mac"),
            observed_at=observed_at,
            eap_method=authenticated.group("method"),
            raw=line.strip(),
        )
    connected = _AP_STA_CONNECTED.search(line)
    if connected:
        return HwsimWlanEvent(
            event_type="STA_AUTHENTICATED",
            outcome="SUCCESS",
            sta_mac=connected.group("mac"),
            observed_at=observed_at,
            raw=line.strip(),
        )
    associated = _ASSOCIATED.search(line)
    if associated:
        return HwsimWlanEvent(
            event_type="STA_ASSOCIATED",
            outcome="SUCCESS",
            sta_mac=associated.group("mac"),
            observed_at=observed_at,
            raw=line.strip(),
        )
    disconnected = _AP_STA_DISCONNECTED.search(line)
    if disconnected:
        return HwsimWlanEvent(
            event_type="STA_DISCONNECTED",
            outcome="SUCCESS",
            sta_mac=disconnected.group("mac"),
            observed_at=observed_at,
            raw=line.strip(),
        )
    if _EAP_FAILURE.search(line):
        return HwsimWlanEvent(
            event_type="EAP_FAILURE",
            outcome="FAILURE",
            sta_mac="",
            observed_at=observed_at,
            raw=line.strip(),
        )
    return None


def to_wlan_access_event(
    event: HwsimWlanEvent,
    *,
    peer_address: str | None = None,
    ssid: str = "ca-ztcf-tier2",
    ap_bssid: str = "02:00:00:00:00:00",
    binding_lifetime_s: int | None = 120,
) -> WlanAccessEvent | None:
    """Map a live virtual-radio WLAN event onto the WLAN collector's schema."""
    address = peer_address or event.peer_address
    if address is None:
        return None

    if event.event_type in {"EAP_SUCCESS", "STA_AUTHENTICATED", "STA_ASSOCIATED"}:
        event_type = WlanEventType.STA_AUTHENTICATED
        eap_success = True
    elif event.event_type == "STA_DISCONNECTED":
        event_type = WlanEventType.STA_DISCONNECTED
        eap_success = False
    elif event.event_type == "EAP_FAILURE":
        # A failed authentication establishes no binding, but it is evidence and is
        # surfaced so predicate C11 can fail rather than the event being dropped.
        event_type = WlanEventType.STA_AUTHENTICATED
        eap_success = False
    else:
        return None

    return WlanAccessEvent(
        event_type=event_type,
        peer_address=address,
        observed_at=event.observed_at,
        source_mode=LIVE_SOURCE_MODE,
        sta_mac=event.sta_mac or None,
        eap_identity=event.eap_identity,
        eap_success=eap_success,
        akm=event.akm,
        ssid=event.ssid or ssid,
        ap_bssid=event.ap_bssid or ap_bssid,
        binding_lifetime_s=binding_lifetime_s,
    )


class HwsimEventSource:
    """Reads live WLAN events from the Tier-2 capture script's JSON Lines output."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._offset = 0

    @property
    def path(self) -> Path:
        return self._path

    def available(self) -> bool:
        return self._path.is_file()

    def read_all(self) -> list[HwsimWlanEvent]:
        if not self.available():
            return []
        events: list[HwsimWlanEvent] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                events.append(parse_event_record(json.loads(stripped)))
            except json.JSONDecodeError:
                parsed = parse_control_line(stripped)
                if parsed is not None:
                    events.append(parsed)
        return events

    def read_new(self) -> list[HwsimWlanEvent]:
        events = self.read_all()
        fresh = events[self._offset :]
        self._offset = len(events)
        return fresh

    def reset(self) -> None:
        self._offset = 0


def provenance() -> dict[str, str]:
    """Provenance stamped on every Tier-2 WLAN observation."""
    return {
        "source_mode": LIVE_SOURCE_MODE.value,
        "access_implementation": ACCESS_IMPLEMENTATION.value,
        "testbed_type": TESTBED_TYPE.value,
        "wifi_radio_mode": ACCESS_IMPLEMENTATION.value,
        "note": (
            "Real IEEE 802.11 association and EAP-TLS through the Linux "
            "mac80211/cfg80211 stack over virtual radios. Simulated PHY; no RF "
            "propagation, interference or channel measurement."
        ),
    }


__all__ = [
    "ACCESS_IMPLEMENTATION",
    "LIVE_SOURCE_MODE",
    "TESTBED_TYPE",
    "HwsimEventSource",
    "HwsimWlanEvent",
    "parse_control_line",
    "parse_event_record",
    "provenance",
    "to_wlan_access_event",
]
