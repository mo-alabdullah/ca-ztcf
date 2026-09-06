# Scope and limits of this milestone (v1.0.0)

## What exists and is tested

The CA-ZTCF core: configuration with a stable hash; injectable clock; service-domain identity registry with Ed25519
proof-of-possession; 5G, WLAN and transition collectors; the versioned Dual-Context Evidence Model; eleven predicates;
the six-state trust engine; the transition-aware policy matrix; an in-memory policy enforcement point; three
interchangeable decision strategies; redacted append-only audit output; Prometheus metrics; an HTTP API; a container.

Added in v0.2.0: the MQTT enforcement point and Mosquitto integration; the research device agent; the Tier-1
portable 802.1X/EAP-TLS WLAN authentication-path emulation with a real hostapd authenticator; the hostapd event
collector; transition correlation with corroboration and stale/duplicate/out-of-order rejection; and the experiment
runner with scenarios E01-E05 under all three strategies.

Added in v0.3.0: scenarios E06-E15 with an outcome-class ground truth; per-device address isolation; the live
Open5GS/UERANSIM 5G collector and the live `mac80211_hwsim` WLAN collector; and the Tier-2 reproducible
software-based testbed with real 5G registration, PDU session and 802.11 association.

Added in v0.3.1: deterministic live access paths, each in its own network namespace, so a device's traffic can only
reach the enforcement point through the access technology it is attributed to; the access domain derived from the
access binding rather than declared by the enforcement point; and E01-E15 executed under all three strategies
against live Tier-2 evidence at a development repetition count.

Added in v1.0.0: the frozen final experiment protocol, the campaign driver and its run ledger, the statistical plan
as code, and the frozen final results with their manifests and checksums.

## What now exists

The final experimental evidence: 2160 valid runs under one commit and one
configuration hash, across fifteen scenarios, three decision strategies and thirty
paired repetitions, plus a token-lifetime sensitivity analysis. The protocol was
frozen before the first run, every attempt is recorded, and every derived artefact
regenerates from the raw output. See
`results/final/processed/findings.json` for what the measurements support and
`results/final/processed/non_findings.md` for what they did not.

## What still does not exist

The thesis chapters. This release is the artefact and the evidence they will be
written from.

Anything requiring a physical radio. Anything above 25 logical devices or 25
transitions per second. Any measurement of what CA-ZTCF costs a constrained IoT
device: the resource figures measure the experiment process, not the device agent.
Any evidence about behaviour on a production network with real subscribers and
real traffic.

E13's 25 devices share **one** IEEE 802.11 association, so its result is CA-ZTCF
logical and service-domain scalability, not independent WiFi-radio association
scalability.

## Tier 2 is software-based, not physical

Tier 2 is a **reproducible software-based 5G/WiFi coexistence testbed**. UERANSIM speaks real 5G NAS, NGAP and
GTP-U to Open5GS but synthesises the radio; `mac80211_hwsim` runs the real Linux 802.11 stack over a simulated PHY.

Tier-2 measurements may support statements about protocol and session transitions, authentication, trust
evaluation, policy enforcement, application continuity, software latency, and CPU, memory and message overhead.

They may **never** support statements about RF propagation performance, physical handover latency over real
radios, interference, channel quality, or spectrum coexistence performance. There is no physical radio anywhere in
this project.

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
