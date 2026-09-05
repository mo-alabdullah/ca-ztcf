# Scope and limits of this milestone (v0.2.0)

## What exists and is tested

The CA-ZTCF core: configuration with a stable hash; injectable clock; service-domain identity registry with Ed25519
proof-of-possession; 5G, WLAN and transition collectors; the versioned Dual-Context Evidence Model; eleven predicates;
the six-state trust engine; the transition-aware policy matrix; an in-memory policy enforcement point; three
interchangeable decision strategies; redacted append-only audit output; Prometheus metrics; an HTTP API; a container.

Added in v0.2.0: the MQTT enforcement point and Mosquitto integration; the research device agent; the Tier-1
portable 802.1X/EAP-TLS WLAN authentication-path emulation with a real hostapd authenticator; the hostapd event
collector; transition correlation with corroboration and stale/duplicate/out-of-order rejection; and the experiment
runner with scenarios E01-E05 under all three strategies.

## What does not exist yet

No Open5GS and no UERANSIM: the 5G access context is still a synthetic fixture. No `mac80211_hwsim` and no 802.11
radio of any kind. No scenarios E06-E15. No repetitions, no statistical analysis, and **no experimental results**,
therefore no findings.

## Claims that are NOT made

This milestone makes **no** performance or security claim. Specifically, nothing here asserts that CA-ZTCF reduces
latency, improves security, is lightweight, or scales better than either baseline. Those are hypotheses and design
objectives; they will be evaluated experimentally, and until then the correct phrasing is "designed to", "intended
to" and "will be evaluated for".

No conformance to any standard is claimed or tested. CA-ZTCF is placed as a service-domain security function, a
placement compatible with the architectural freedom described in 3GPP TR 33.794; that is a statement about placement,
not about conformance or endorsement.

## Data provenance in this milestone

Two provenance values appear, and neither is a measurement of real radio infrastructure:

- `synthetic_fixture` — every 5G-side access event. A development fixture, not a 5G measurement.
- `tier1_wlan_auth_emulation` — every WLAN-side event. Real EAP-TLS over a veth pair; **not** 802.11 radio access.

`live_testbed` is reserved for Tier 2 and appears nowhere. `scripts/check_source_modes.py` fails the build if a
Tier-1 event claims it, if a Tier-1 run omits its result class or disclaimer, or if development output is written to
a final-results path. The negative cases are tested. See ADR-0006 and ADR-0007.

Development output lives in `results/dev/` and `artifacts/dev-validation/`, deliberately separate from any
final-results tree, and every run and generated artefact carries a disclaimer.

## Statements that may NOT be made from Tier-1 data

Real WiFi measurements. RF measurements. Real 5G measurements. Real 5G/WiFi handover latency. 802.11 association
latency, interference or contention behaviour. Final thesis experimental evidence. Any statistical significance
claim: no inferential test has been run, by design.

## Tier boundaries

Tier 1 provides portable 802.1X/EAP-TLS authentication-path emulation for WLAN security-context generation. It
validates EAP authentication, authentication events, identity binding and CA-ZTCF integration. It **cannot** measure
WiFi association latency, RF behaviour, 802.11 radio transition latency or interference; those require Tier 2. Tier-1
and Tier-2 claims are never mixed. See ADR-0003.
