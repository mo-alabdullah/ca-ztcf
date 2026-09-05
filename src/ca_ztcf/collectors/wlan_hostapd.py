"""Collector for the Tier-1 WLAN authentication path.

Consumes events emitted by a real ``hostapd`` acting as an IEEE 802.1X
authenticator, and normalises them into the existing ``WlanAccessEvent`` and
``AccessBinding`` schema so that everything downstream — evidence, predicates,
trust engine, policy — is unchanged.

Two forms are accepted:

* the JSON Lines the Tier-1 run script writes, which is the normal path;
* raw hostapd control-interface lines, so a live control socket can be attached
  later without changing the collector.

**Provenance.** Every event produced here carries
``source_mode = tier1_wlan_auth_emulation``. The EAP-TLS exchange behind it is
real, and so are the authenticator events, but there is no radio. This collector
never emits ``live_testbed``; that value is reserved for Tier 2, and the
source-mode safety gate fails the build if a Tier-1 WLAN event claims it.

**Secrets.** Raw EAP material never enters an event. The station identifier and
the EAP identity are hashed with the collector's own salt before they reach an
access binding, and are never compared with any 5G identifier.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ca_ztcf.collectors.base import SourceMode
from ca_ztcf.collectors.wlan import WlanAccessEvent, WlanEventType
from ca_ztcf.errors import CollectorError

TIER1_SOURCE_MODE = SourceMode.TIER1_WLAN_AUTH_EMULATION

# hostapd control-interface lines the collector understands.
_AP_STA_CONNECTED = re.compile(r"AP-STA-CONNECTED\s+([0-9a-fA-F:]{17})")
_AP_STA_DISCONNECTED = re.compile(r"AP-STA-DISCONNECTED\s+([0-9a-fA-F:]{17})")
_EAP_SUCCESS = re.compile(r"CTRL-EVENT-EAP-SUCCESS")
_EAP_FAILURE = re.compile(r"CTRL-EVENT-EAP-FAILURE|EAP-Failure")
_AUTHENTICATED = re.compile(
    r"STA ([0-9a-fA-F:]{17}) IEEE 802\.1X: authenticated - EAP type: \d+ \((\w+)\)"
)


@dataclass(frozen=True)
class Tier1AuthEvent:
    """A normalised Tier-1 authentication-path event."""

    event_type: str
    outcome: str
    sta_mac: str
    observed_at: datetime
    scenario: str = ""
    eap_identity: str | None = None
    eap_method: str = "TLS"
    authenticator: str = "hostapd-driver-wired"
    supplicant: str = "wpa_supplicant-Dwired"

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


def parse_event_record(record: dict[str, object]) -> Tier1AuthEvent:
    """Parse one JSON record written by the Tier-1 run script."""
    source_mode = str(record.get("source_mode", TIER1_SOURCE_MODE.value))
    if source_mode != TIER1_SOURCE_MODE.value:
        raise CollectorError(
            f"Tier-1 WLAN collector refuses an event claiming source_mode "
            f"'{source_mode}'; only '{TIER1_SOURCE_MODE.value}' is permitted here"
        )
    return Tier1AuthEvent(
        event_type=str(record.get("event_type", "UNKNOWN")),
        outcome=str(record.get("outcome", "UNKNOWN")),
        sta_mac=str(record.get("sta_mac", "")),
        observed_at=_parse_timestamp(record.get("observed_at")),  # type: ignore[arg-type]
        scenario=str(record.get("scenario", "")),
        eap_identity=(str(record["eap_identity"]) if record.get("eap_identity") else None),
        eap_method=str(record.get("eap_method", "TLS")),
    )


def parse_control_line(line: str, *, at: datetime | None = None) -> Tier1AuthEvent | None:
    """Parse a raw hostapd control-interface line, or return ``None`` if irrelevant."""
    observed_at = at or datetime.now(UTC)

    match = _AUTHENTICATED.search(line)
    if match:
        return Tier1AuthEvent(
            event_type="EAP_SUCCESS",
            outcome="SUCCESS",
            sta_mac=match.group(1),
            observed_at=observed_at,
            eap_method=match.group(2),
        )
    match = _AP_STA_CONNECTED.search(line)
    if match:
        return Tier1AuthEvent(
            event_type="STA_AUTHENTICATED",
            outcome="SUCCESS",
            sta_mac=match.group(1),
            observed_at=observed_at,
        )
    match = _AP_STA_DISCONNECTED.search(line)
    if match:
        return Tier1AuthEvent(
            event_type="STA_DISCONNECTED",
            outcome="SUCCESS",
            sta_mac=match.group(1),
            observed_at=observed_at,
        )
    if _EAP_SUCCESS.search(line):
        return Tier1AuthEvent(
            event_type="EAP_SUCCESS", outcome="SUCCESS", sta_mac="", observed_at=observed_at
        )
    if _EAP_FAILURE.search(line):
        return Tier1AuthEvent(
            event_type="EAP_FAILURE", outcome="FAILURE", sta_mac="", observed_at=observed_at
        )
    return None


def to_wlan_access_event(
    event: Tier1AuthEvent,
    *,
    peer_address: str,
    ssid: str = "ca-ztcf-tier1",
    ap_bssid: str = "02:00:00:00:0a:01",
    akm: str = "WPA2-EAP",
    binding_lifetime_s: int | None = 120,
) -> WlanAccessEvent | None:
    """Map a Tier-1 authentication event onto the WLAN collector's input schema.

    ``akm`` is a label describing the authentication and key-management suite this
    emulation stands in for. There is no 802.11 key management here; the value
    exists so that posture policy can be exercised, and it is meaningful only in
    combination with ``source_mode = tier1_wlan_auth_emulation``.
    """
    if event.event_type in {"EAP_SUCCESS", "STA_AUTHENTICATED"}:
        event_type = WlanEventType.STA_AUTHENTICATED
        eap_success = True
    elif event.event_type == "STA_DISCONNECTED":
        event_type = WlanEventType.STA_DISCONNECTED
        eap_success = False
    elif event.event_type == "EAP_FAILURE":
        # A failed authentication establishes no binding, but it is evidence: it
        # is surfaced as an authenticated-station event with eap_success false, so
        # predicate C11 fails rather than the event being silently dropped.
        event_type = WlanEventType.STA_AUTHENTICATED
        eap_success = False
    else:
        return None

    return WlanAccessEvent(
        event_type=event_type,
        peer_address=peer_address,
        observed_at=event.observed_at,
        source_mode=TIER1_SOURCE_MODE,
        sta_mac=event.sta_mac or None,
        eap_identity=event.eap_identity,
        eap_success=eap_success,
        akm=akm,
        ssid=ssid,
        ap_bssid=ap_bssid,
        binding_lifetime_s=binding_lifetime_s,
    )


class HostapdEventSource:
    """Reads Tier-1 authentication events from the run script's JSON Lines output."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._offset = 0

    @property
    def path(self) -> Path:
        return self._path

    def available(self) -> bool:
        """Whether the event source can currently be read.

        Unavailability is reported rather than raised, because a collector outage
        is missing evidence, not contradictory evidence.
        """
        return self._path.is_file()

    def read_all(self) -> list[Tier1AuthEvent]:
        if not self.available():
            return []
        events: list[Tier1AuthEvent] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                events.append(parse_event_record(json.loads(stripped)))
            except (json.JSONDecodeError, CollectorError):
                parsed = parse_control_line(stripped)
                if parsed is not None:
                    events.append(parsed)
        return events

    def read_new(self) -> list[Tier1AuthEvent]:
        """Read only events appended since the last call."""
        events = self.read_all()
        fresh = events[self._offset :]
        self._offset = len(events)
        return fresh

    def reset(self) -> None:
        self._offset = 0


__all__ = [
    "TIER1_SOURCE_MODE",
    "HostapdEventSource",
    "Tier1AuthEvent",
    "parse_control_line",
    "parse_event_record",
    "to_wlan_access_event",
]
