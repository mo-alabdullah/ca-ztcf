# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-09-06

Tier-1 testbed and experiment infrastructure (batches F-I).

### Added
- **MQTT enforcement point** (`ca_ztcf.enforcement.mqtt_gateway`): an asyncio proxy between the
  device and Mosquitto that consults the trust function for every decision and applies the answer
  using only MQTT 3.1.1 mechanisms. Credentials travel in the CONNECT password field and are
  stripped before the CONNECT is relayed, so the broker never sees them.
- Minimal MQTT 3.1.1 codec covering CONNECT, CONNACK, PUBLISH, PUBACK, SUBSCRIBE, SUBACK,
  UNSUBSCRIBE, UNSUBACK, PINGREQ, PINGRESP and DISCONNECT. Unrecognised packets are relayed
  verbatim rather than reinterpreted.
- Research IoT device agent with deterministic identities, proof-of-possession over MQTT,
  step-up challenge handling and access-context switching.
- Mosquitto in Compose as the protected resource, with no host port.
- **Tier-1 portable 802.1X/EAP-TLS WLAN authentication-path emulation**: real
  `hostapd driver=wired` and real `wpa_supplicant -Dwired` over a veth pair, with a research CA
  and six verified scenarios (valid, re-authentication, untrusted CA, expired chain, no
  certificate, disconnect).
- WLAN collector for hostapd events, normalising them into the existing binding schema.
- Transition collector extended with transition identifiers, start and completion times, reasons,
  sequence numbers, source-event references, corroboration against the binding store, and
  rejection of stale, duplicate and out-of-order observations.
- Experiment infrastructure: declarative YAML scenarios with ground truth fixed before execution,
  a deterministic runner, twenty-two metric definitions, container resource sampling, raw JSONL
  output, and an analysis pipeline generating tables and figures from raw data only.
- Scenarios E01-E05, each executed under all three strategies.
- Research endpoints for device state, active decision, step-up, transition detail and audit
  lookup by decision identifier.

### Changed
- `SourceMode` gained `tier1_wlan_auth_emulation`, and `live_testbed` is now reserved for Tier 2.
  Added `MeasurementTier` and `MeasurementSubject` so every metric records what it measures.
- Proof-of-possession is now remembered for its configured lifetime. Previously a proof had to
  accompany every request, which made `proof_of_possession_ttl_s` unreachable and degraded a
  legitimate device immediately.

### Fixed
- Mosquitto could not start under `cap_drop: ALL`; it now runs as its own unprivileged user and
  needs no privilege drop.
- Both container healthchecks probed `/dev/tcp`, which neither image's shell supports.

### Notes
- **No experimental results.** Everything under `results/dev/` is Tier-1 development validation.
  The 5G context is a synthetic fixture and the WLAN side is authentication-path emulation;
  neither is a measurement of real radio infrastructure, and no conclusion is drawn from either.
- No inferential statistics are performed. Descriptive summaries only.

## [0.1.0] - 2026-09-06

First development prototype: the CA-ZTCF core (batches A-E).

### Added
- Project scaffolding: packaging, linting, type checking, test harness, Makefile, Docker image.
- Configuration subsystem with a stable configuration hash; every research threshold is declared
  in `config/` with a name, unit, purpose and an explicit statement that it is an experimental
  value rather than a validated universal one.
- Injectable `Clock` abstraction (`SystemClock`, `FrozenClock`) so that freshness, staleness and
  transition-window logic can be tested without sleeping.
- Service-domain `DeviceIdentityRegistry` with Ed25519 proof-of-possession verification and
  single-use, time-limited nonces. Private key material is never stored or logged.
- Access-context collectors (`NRCollector` with a synthetic fixture provider, `WLANCollector`,
  `TransitionCollector`) producing normalised, typed `AccessBinding` and `TransitionEvent` records.
- Versioned Dual-Context Evidence Model (`schema_version: "1"`) in which every item carries its
  source, source mode, observation time, expiry and validation status.
- Eleven named, explainable predicates (C1-C11) returning reasons and evidence references.
- Trust engine implementing six trust states through an ordered, deterministic rule system.
- Transition-aware policy matrix (configuration-driven) with six enforcement actions, and an
  in-memory Policy Enforcement Point.
- Three interchangeable decision strategies: independent authentication, static continuity, CA-ZTCF.
- Append-only JSONL research audit output with secret redaction, and Prometheus metrics.
- HTTP API: health, readiness, version, configuration hash, metrics, and research endpoints for
  device registration, collector event ingestion, evidence evaluation, transitions and decisions.
- Architecture, threat-model, experiment and reproducibility documentation, plus six ADRs.

### Notes
- No experimental results are produced by this release. All 5G-side events are
  `source_mode: synthetic_fixture` development fixtures and are not measurements.
