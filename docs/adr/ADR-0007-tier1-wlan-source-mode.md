# ADR-0007: A distinct source mode for the Tier-1 WLAN authentication path

- Status: Accepted
- Date: 2026-09-06
- Refines: ADR-0003 (two-tier testbed), ADR-0006 (synthetic versus live evidence)

## Context

Tier 1 generates WLAN security context with a real `hostapd driver=wired`
authenticator and a real `wpa_supplicant -Dwired` supplicant exchanging genuine
EAP-TLS over a veth pair. The EAP exchange is real, the authenticator events are
real, and the certificate identity binding is real.

None of that makes it 802.11. There is no radio, no association, no over-the-air
handshake, no contention and no RF. An earlier draft of `SourceMode` had only
`synthetic_fixture` and `live_testbed`, which left this evidence with no honest
label: calling it synthetic understates it, and calling it `live_testbed` would
be a false claim that a WiFi measurement had been taken.

The risk is concrete. A latency measured across this path could be reported as a
"WiFi handover latency" months later by someone reading a CSV, and nothing in the
data would contradict them.

## Decision

A third value, `tier1_wlan_auth_emulation`, names exactly what this is: the
**Tier-1 portable 802.1X/EAP-TLS WLAN authentication-path emulation**.

- `live_testbed` is reserved for Tier 2: a real Open5GS core with UERANSIM, or
  hostapd driving real or `mac80211_hwsim` 802.11 radios.
- The Tier-1 WLAN collector refuses to parse an event claiming `live_testbed`,
  and refuses `synthetic_fixture` on the WLAN path.
- `MeasurementTier` and `MeasurementSubject` are recorded on every run and every
  metric sample, so a number always carries what it is a measurement *of*.
- `scripts/check_source_modes.py` fails the build if a Tier-1 WLAN event claims
  `live_testbed`, if synthetic 5G evidence claims it, if a Tier-1 run omits its
  result class or disclaimer, or if development output appears under a
  final-results path.

## Consequences

**Positive.** The distinction is enforced by code and by a gate with tested
negative cases, not by remembering to be careful. Provenance travels with the
data into every CSV, figure and table.

**Negative.** A third value makes the enum less tidy, and every new evidence
source must now decide which mode it is. That cost is worth paying: the failure
it prevents is a false claim in a thesis.

**What may never be claimed from Tier-1 WLAN data.** Association latency, RF
behaviour, 802.11 transition latency, interference or contention behaviour, or
any statement of the form "measured over WiFi".
