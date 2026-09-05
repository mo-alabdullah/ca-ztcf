# Tier-1 WLAN authentication path

## What this is, and what it is not

This directory sets up the **Tier-1 portable 802.1X/EAP-TLS WLAN
authentication-path emulation**:

- a real `hostapd` running with `driver=wired`, acting as an IEEE 802.1X
  authenticator with an integrated EAP server;
- a real `wpa_supplicant` running with `-Dwired`, acting as the supplicant;
- a real EAP-TLS exchange over a veth pair, using a research CA and real X.509
  certificates.

The EAP authentication is genuine. The authenticator events are genuine. The
identity binding is genuine. That is enough to validate the WLAN collector, the
evidence pipeline and CA-ZTCF integration end to end.

**It is not IEEE 802.11 radio access.** There is no radio, no association, no
4-way handshake over the air, no RF. Events from this environment carry
`source_mode: tier1_wlan_auth_emulation`, and results derived from them must
never be described as:

- real WiFi measurements
- RF measurements
- real 802.11 association or handover latency
- interference or contention behaviour
- final thesis experimental evidence

`source_mode: live_testbed` is reserved for Tier 2 — real Open5GS/UERANSIM and
real or `mac80211_hwsim` 802.11 radios. The source-mode safety gate
(`scripts/check_source_modes.py`) fails the build if a Tier-1 WLAN event ever
claims it.

## What runs where

| Component | Runs |
|---|---|
| `hostapd` (authenticator, integrated EAP server) | Linux container `tier1-wlan` |
| `wpa_supplicant` (supplicant) | same container, other end of the veth pair |
| veth pair `eapauth0` / `eapsta0` | inside the container's network namespace |
| WLAN collector | CA-ZTCF core, consuming the emitted event log |

Linux is required: `hostapd`'s wired driver and `wpa_supplicant`'s wired driver
both need real network interfaces and raw EAPOL frames. On macOS this runs inside
the container, which is a Linux environment. It is not forced into a container for
aesthetics — it needs `CAP_NET_ADMIN` and `CAP_NET_RAW`, and gets exactly those.

## Running it

```bash
docker compose -f deploy/compose/testbed.yml run --rm tier1-wlan
```

The run script generates the research CA and certificates if they are absent,
brings up the veth pair, starts hostapd, runs wpa_supplicant, and writes
normalised authentication events as JSON Lines to
`artifacts/tier1-wlan/events.jsonl`.

## Scenarios it produces

| Scenario | How | Expected event |
|---|---|---|
| Valid EAP-TLS authentication | correct client certificate | `EAP_SUCCESS`, `STA_AUTHENTICATED` |
| Invalid client certificate | certificate signed by an untrusted CA | `EAP_FAILURE` |
| Expired trust chain | certificate whose validity has passed | `EAP_FAILURE` |
| Authentication failure | no client certificate offered | `EAP_FAILURE` |
| Re-authentication | supplicant reconnects | second `EAP_SUCCESS` |
| Session removal | supplicant disconnects | `STA_DISCONNECTED` |

Collector unavailability and binding freshness expiry are driven by the
experiment runner rather than by hostapd, since they concern the collector and
the clock rather than the authentication exchange.

## Secrets

All key material is generated into `testbed/wlan/certs/`, which is git-ignored.
Nothing here is a production credential. Raw EAP material never leaves the
container: the collector records only whether authentication succeeded, the
certificate subject identity, and a salted digest of the station identifier.
