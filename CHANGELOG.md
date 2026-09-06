# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.1] - 2026-09-06

Deterministic live access paths, and E01-E15 executed against Tier-2 evidence.

### Fixed
- **The live application paths did not cross the access networks they were
  attributed to.** The UE, the core, the access point and the station all shared
  the root network namespace and the services listened on `0.0.0.0`, so every
  service address was also a local address and the kernel delivered the traffic
  over loopback. The 5G path never entered GTP-U and the enforcement point
  observed the VM's own address instead of the UE tunnel address; the WLAN path
  had the same defect and it had been missed, since association and EAP-TLS were
  real but the application traffic never crossed the 802.11 link. Each access
  path now runs in its own network namespace with the service placed where only
  that path can reach it. `nr-binder` was not sufficient: `LD_PRELOAD` can bind a
  socket to the tunnel, but a locally-routed destination still short-circuits.
  See ADR-0009.
- **The enforcement point declared an access domain it could not know.** It sent
  a fixed default on every decision. With one live access path that default
  happened to be right; with two it mislabelled every connection arriving over
  the other access, so a device that had not moved was recorded as
  transitioning. The domain is now derived from the access binding matching the
  observed address, and each audit record carries `domain_source`.
- **Transitions were registered twice.** Every strategy calls
  `transitions.observe()` while deciding, so the harness announcing the
  transition as well inflated the rate window and made a first transition come
  back as a repeated one.
- Subscribers get static UE addresses; the dynamic pool issued a different
  address after every teardown, which made bindings unpredictable and runs
  impossible to repeat.
- A keepalive and an `ensure` repair path stop the UE dropping to RRC idle, from
  which it cannot resume while the gNB holds a stale UE context, leaving a tunnel
  interface that is up but carries nothing.

### Added
- A pluggable access-evidence source. `LiveTier2AccessSource` derives every event
  from what the access networks themselves logged and from the live interfaces
  that carry the traffic; it raises rather than substituting a fixture, because a
  run that quietly fell back would be reported as live evidence while not being
  live evidence.
- `run_matrix.py --access-source tier2 --repetitions N`, and repetition seeding
  so repetitions are independent samples that remain exactly reproducible.
- `network/verify_ue_path.py`, which proves the 5G source address independently
  of CA-ZTCF with a plain TCP server, a plain TCP client and captures on both
  ends of the tunnel.
- `network/ue_path.sh`, `network/sta_path.sh` and `network/capture_events.sh`, so
  a clean VM reproduces the arrangement without manual steps.
- A two-level reset: `soft` clears service state between repetitions, `full`
  returns to a freshly provisioned VM.
- ADR-0009 on the access-path namespaces.

### Changed
- A run is labelled with the tier its evidence actually came from, not the one
  its scenario declares. Scenarios declare `supported_tiers`; the processed
  tables and figure captions carry the disclaimer matching the evidence present.
- The source-mode gate is tier-aware in both directions: Tier 1 may never claim
  `live_testbed`, and Tier 2 may never claim `synthetic_fixture` or Tier-1 WLAN
  emulation.
- `make lint` and `make format` cover `experiments/`, which was outside the gate.

### Notes
- Tier-2 development validation only: E01-E15, three strategies, three
  repetitions, 135 of 135 runs. Descriptive statistics, no inferential test, no
  p-value, no finding. The final campaign has not been run and nothing is frozen.
- Still a software-based testbed. Real 5G NAS/NGAP/GTP-U and a real
  802.11/EAP-TLS stack over simulated radios: nothing here supports a claim about
  RF propagation, interference, channel quality or physical handover.

## [0.3.0] - 2026-09-06

Complete experiment model and the live software-based testbed (batches J and K).

### Added
- Ground-truth taxonomy of expected outcome classes (LEGITIMATE_ALLOW,
  LEGITIMATE_RESTRICT, LEGITIMATE_STEP_UP, MALICIOUS_REJECT,
  MALICIOUS_QUARANTINE), with scoring that asks whether the observed action fell
  in the declared class. Enforcement steps declare `expect_permitted` explicitly.
- Scenarios E06-E15, each run under all three strategies: stale evidence with
  explicit recovery, identity mismatch, unauthorised context, excessive
  transition rate, session mismatch, legitimate degradation and recovery,
  concurrent devices, and device-count and transition-rate scalability.
- Per-device address isolation, replacing the previous manual binding release.
- Live 5G collector for Open5GS/UERANSIM and live WLAN collector for
  mac80211_hwsim, both refusing events whose provenance they cannot produce.
- `InfrastructureKind` and `AccessImplementation`, so every Tier-2 observation
  states that it is software-based and names what produced it.
- Tier-2 provisioning tree: Lima VM definition, Open5GS and UERANSIM install,
  synthetic subscriber provisioning, 5G and WLAN bring-up, real transition
  orchestration with T0-T6 timestamps, service stack, validation flow and reset.
- ADR-0008 recording the synthetic-versus-real 5G schema comparison.

### Changed
- The 5G evidence schema follows the running core. `gnb_id` was an incorrect
  assumption: Open5GS logs no per-session gNB identifier, only the N2 peer
  address, so the collector reports `serving_node`. Posture policy therefore
  constrains a serving-node address, not a cell identity.
- The source-mode gate distinguishes tiers and rejects any physical-radio claim
  on software-testbed output.
- E15 draws legitimate and adversarial events from disjoint device cohorts, so
  every label is answerable.

### Notes
- **No experimental results.** Everything under `results/dev/` remains Tier-1
  development validation. Tier-2 is validated but the final campaign has not run.
- Tier 2 is a **software-based** testbed. Real 5G protocols and a real 802.11
  stack; no physical radio, so no RF, propagation, interference, channel-quality
  or physical-handover claim may be made from it.
- No inferential statistics are performed.

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
