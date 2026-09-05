# Scope and limits of this milestone (v0.1.0)

## What exists and is tested

The CA-ZTCF core: configuration with a stable hash; injectable clock; service-domain identity registry with Ed25519
proof-of-possession; 5G, WLAN and transition collectors; the versioned Dual-Context Evidence Model; eleven predicates;
the six-state trust engine; the transition-aware policy matrix; an in-memory policy enforcement point; three
interchangeable decision strategies; redacted append-only audit output; Prometheus metrics; an HTTP API; a container.

## What does not exist yet

No MQTT enforcement point (Batch F). No real 802.1X/EAP integration (Batch G). No network-namespace transitions
(Batch H). No experiment controller, scenarios or metrics collection (Batch I). No Open5GS, UERANSIM, hostapd or
`mac80211_hwsim` (Batch K). No experimental results, and therefore no findings.

## Claims that are NOT made

This milestone makes **no** performance or security claim. Specifically, nothing here asserts that CA-ZTCF reduces
latency, improves security, is lightweight, or scales better than either baseline. Those are hypotheses and design
objectives; they will be evaluated experimentally, and until then the correct phrasing is "designed to", "intended
to" and "will be evaluated for".

No conformance to any standard is claimed or tested. CA-ZTCF is placed as a service-domain security function, a
placement compatible with the architectural freedom described in 3GPP TR 33.794; that is a statement about placement,
not about conformance or endorsement.

## Data provenance in this milestone

Every 5G-side access event is a development fixture carrying `source_mode: synthetic_fixture`. No measurement of any
kind has been taken. Development validation output lives in `artifacts/dev-validation/`, deliberately separate from
any future `results/` tree, and each report carries that disclaimer. See ADR-0006.

## Tier boundaries

Tier 1 provides portable 802.1X/EAP-TLS authentication-path emulation for WLAN security-context generation. It
validates EAP authentication, authentication events, identity binding and CA-ZTCF integration. It **cannot** measure
WiFi association latency, RF behaviour, 802.11 radio transition latency or interference; those require Tier 2. Tier-1
and Tier-2 claims are never mixed. See ADR-0003.
