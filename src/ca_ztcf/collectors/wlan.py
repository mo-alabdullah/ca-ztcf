"""WLAN access-context collector.

Consumes normalised WLAN authentication events and produces
:class:`AccessBinding` records.

In Tier 1 these events originate from a portable 802.1X/EAP-TLS
authentication-path emulation (``hostapd driver=wired`` authenticator with a
``wpa_supplicant -Dwired`` supplicant over a veth pair). That emulation exercises
real EAP authentication, real authenticator events and real identity binding, and
is sufficient to validate CA-ZTCF integration. It is **not** WiFi radio access:
it cannot be used to measure association latency, RF behaviour, 802.11 transition
latency or interference. Those require the Tier-2 testbed. The distinction is
carried in ``source_mode`` and must not be blurred in any result.

Station MAC and EAP identity are hashed with this collector's own salt on
ingestion and are never compared with any 5G identifier.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from ca_ztcf.collectors.base import AccessBinding, AccessDomain, BaseCollector, SourceMode
from ca_ztcf.errors import CollectorError


class WlanEventType(StrEnum):
    """WLAN authenticator events the collector understands."""

    STA_AUTHENTICATED = "STA_AUTHENTICATED"
    STA_REFRESHED = "STA_REFRESHED"
    STA_DISCONNECTED = "STA_DISCONNECTED"


class WlanAccessEvent(BaseModel):
    """A normalised WLAN authentication event.

    ``sta_mac`` and ``eap_identity`` are access-domain identifiers. They are
    hashed on ingestion; the raw values are neither stored nor logged, and neither
    may ever be used as the service-domain device identity.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: WlanEventType
    peer_address: str
    observed_at: datetime
    source_mode: SourceMode = SourceMode.SYNTHETIC_FIXTURE
    sta_mac: str | None = None
    eap_identity: str | None = None
    eap_success: bool = True
    akm: str = "WPA2-EAP"
    ssid: str | None = None
    ap_bssid: str | None = None
    binding_lifetime_s: int | None = 120


class WLANCollector(BaseCollector):
    """Normalises WLAN authentication events into access bindings."""

    domain = AccessDomain.WLAN
    source = "collector.wlan"

    def ingest(self, event: BaseModel) -> AccessBinding | None:
        if not isinstance(event, WlanAccessEvent):
            raise CollectorError(f"WLANCollector cannot ingest {type(event).__name__}")

        if event.event_type is WlanEventType.STA_DISCONNECTED:
            self._store.release(event.peer_address)
            return None

        attributes: dict[str, str] = {
            "akm": event.akm,
            "eap_success": "true" if event.eap_success else "false",
        }
        if event.sta_mac is not None:
            attributes["sta_mac_hash"] = self.hash_identifier(event.sta_mac)
        if event.eap_identity is not None:
            attributes["eap_identity_hash"] = self.hash_identifier(event.eap_identity)
        if event.ssid is not None:
            attributes["ssid"] = event.ssid
        if event.ap_bssid is not None:
            attributes["ap_bssid"] = event.ap_bssid

        binding = AccessBinding(
            binding_id=self._new_binding_id(),
            domain=self.domain,
            peer_address=event.peer_address,
            source=self.source,
            source_mode=event.source_mode,
            first_seen=event.observed_at,
            last_seen=event.observed_at,
            expires_at=self._expiry(event.observed_at, event.binding_lifetime_s),
            attributes=attributes,
        )
        return self._store.upsert(binding)

    def ingest_many(self, events: list[WlanAccessEvent]) -> list[AccessBinding]:
        produced: list[AccessBinding] = []
        for event in events:
            binding = self.ingest(event)
            if binding is not None:
                produced.append(binding)
        return produced


def sta_authenticated(
    peer_address: str,
    observed_at: datetime,
    *,
    sta_mac: str = "02:00:00:00:00:01",
    eap_identity: str = "fixture-device@lab.invalid",
    akm: str = "WPA2-EAP",
    ssid: str = "ca-ztcf-lab",
    ap_bssid: str = "02:00:00:00:0a:01",
    binding_lifetime_s: int | None = 120,
) -> WlanAccessEvent:
    """Convenience builder for a well-formed synthetic WLAN authentication event."""
    return WlanAccessEvent(
        event_type=WlanEventType.STA_AUTHENTICATED,
        peer_address=peer_address,
        observed_at=observed_at,
        source_mode=SourceMode.SYNTHETIC_FIXTURE,
        sta_mac=sta_mac,
        eap_identity=eap_identity,
        eap_success=True,
        akm=akm,
        ssid=ssid,
        ap_bssid=ap_bssid,
        binding_lifetime_s=binding_lifetime_s,
    )


WLAN_ATTRIBUTE_KEYS: tuple[str, ...] = (
    "akm",
    "eap_success",
    "sta_mac_hash",
    "eap_identity_hash",
    "ssid",
    "ap_bssid",
)
"""Attribute keys the WLAN collector may emit."""


__all__ = [
    "WLAN_ATTRIBUTE_KEYS",
    "WLANCollector",
    "WlanAccessEvent",
    "WlanEventType",
    "sta_authenticated",
]
