# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.2] - 2026-09-06

**Archival metadata release.** Created after enabling the Zenodo-GitHub
integration, which only archives releases published after it is switched on, so a
new release was needed to trigger ingestion. It contains **the exact frozen
research results of v1.0.1**.

Nothing was rerun and nothing was recomputed. No framework change, no experiment
change, no result change, no statistical change, and no modification of the frozen
raw data. The only edits are the version string in `src/ca_ztcf/version.py`,
`pyproject.toml`, `CITATION.cff` and `.zenodo.json`, and this entry.

The three frozen hashes are unchanged, which is the check that the evidence is
untouched:

| Artefact | SHA-256 |
|---|---|
| Results manifest | `f5b4cd4884d62a2267c7520d00dad389e532b276d357b045bbc2983ad1d0ffbb` |
| SHA256SUMS | `fade4d7b70c1c20b3a6218de34fe12aab10d49ea9f3389fb868ffded7d5ae215` |
| Raw data archive | `b4e5ce650f29907b45bfd5c05c0a6ccc18ec247971f76aff267469fefa31f6b4` |

The raw-data archive keeps its `ca-ztcf-v1.0.1-final-results.tar.zst` name and the
results manifest keeps its recorded version of 1.0.1. Both describe the v1.0.1
campaign, and renaming them would imply a regeneration that did not happen.

The campaign itself remains attributable to commit
`a9ff4a5e1dc0fea65b63e2b366814c1860f04110` under configuration hash
`a1d260b660c93e47a466deb9c00f26c880973356f7da4eda00cb8ec57cab044d`.

## [1.0.1] - 2026-09-06

Reporting completeness. **No measurement changed.** The raw-data archive is
byte-identical to v1.0.0 — same SHA-256,
`b4e5ce650f29907b45bfd5c05c0a6ccc18ec247971f76aff267469fefa31f6b4` — which is the
check that the underlying evidence is untouched. This is the release to archive.

Three things the v1.0.0 reporting stated less than honestly, all found by reading
the generated output rather than by a reader afterwards:

### Fixed
- **Bytes exchanged were reported as zero; they were never measured.** Metric M9
  counts bytes on the device-to-enforcement-point socket, and the experiment runner
  drives the framework in process, so no such socket exists and the counter was
  never recorded in any of the 2160 runs. A zero says "no bytes were exchanged",
  which is a different and false claim. Table I now says **not measured**, and the
  byte half of P5 is listed as unanswered in the non-findings and the limitations.
- **The trust engine time comparison had silently vanished.** Only CA-ZTCF has a
  trust engine, so no paired three-way series exists, and the comparison simply did
  not appear — leaving a reader to wonder why. It is now recorded explicitly as
  descriptive-only, with the reason.
- **The token-lifetime result looked stronger than it is.** Baseline B produced
  identical outcomes at 30, 300 and 1800 seconds, but seven of the nine sensitivity
  scenarios span less scenario time than the shortest lifetime, so no token could
  expire in them and nothing was learned there. Scenario-clock spans are now
  recorded beside the result, and the two conclusions are separated: *untested* in
  seven scenarios, *genuinely unaffected* in the two that outlast a 30-second token.
  The substantive point is stated as well — the baseline's false acceptance rate in
  E15 is 1.0000 at every lifetime, because it re-authenticates on exactly the
  evidence it ignored before.

### Changed
- An unrecorded counter is `None` throughout the analysis rather than `0`.

## [1.0.0] - 2026-09-06

The thesis experimental release. The framework is frozen and the final evidence is
in `results/final/`.

### Added
- **The frozen final experiment protocol**, committed before the first run and not
  edited afterwards. It fixes the scenarios, strategies, seeds, metrics, the six
  primary outcome dimensions, the statistical plan, the run-validity and
  infrastructure-failure rules, the result layout and the known limitations.
  Corrections go in timestamped amendments, not into the protocol.
- **The final campaign**: 2160 valid runs under one commit and one configuration
  hash. 1620 primary (fifteen scenarios x three strategies x thirty paired seeds,
  with E13 at four logical-device levels) and 540 sensitivity (nine scenarios x two
  extra token lifetimes x the same seeds). Every attempt is in
  `results/final/run_ledger.csv`; nothing was excluded.
- A campaign driver that keeps that ledger, resumes from it, bounds every run, and
  stops on configuration drift or a failure it cannot attribute to infrastructure.
- The statistical plan as code: Friedman across the three paired strategies, paired
  Wilcoxon follow-up only where the omnibus test is significant, Holm correction,
  matched-pairs rank-biserial effect size, paired bootstrap confidence intervals,
  and Cochran's Q with exact McNemar for paired binary outcomes. The experimental
  unit is the run.
- Twelve generated tables, eight figures, `findings.json`, `non_findings.md` and
  `experimental_limitations.md` — all regenerated from raw output by
  `scripts/process_final_results.py` and checked by `scripts/verify_final_results.py`.
- `results/final/manifests/`: SHA-256 for every file, a manifest describing the
  campaign, and a deterministic archive of the raw runs and audit trail.
- ADR-0009 on the access-path network namespaces.

### Fixed
Two defects found by the project's own gates while the campaign was running. Both
stopped the campaign, both got a regression test, and both invalidated every
affected run rather than being patched into finished output. See
`docs/experiments/amendments/`.

- **AMEND-0001** — the resources record claimed the experiment runner was not
  measured while carrying that runner's own CPU and memory, and metric M10 was
  never observed because most runs finish inside one sampling interval. CPU is now
  reported as CPU seconds over wall time. Separately, every run written under
  `results/final/` declared `result_class: development_validation`; the result class
  is now a run parameter and the gate separates the two conditions it had merged.
- **AMEND-0002** — the trust engine and the policy evaluator timed themselves
  through the injected clock, which the experiment runner freezes. Metric M12, pure
  engine evaluation time, was structurally zero in 540 of 540 CA-ZTCF runs.
  Publishing that would have read as an immeasurably fast engine rather than a
  disconnected instrument. A frozen wall clock no longer freezes duration
  measurement.

### Changed
- The enforcement point no longer declares an access domain it cannot know; the
  domain is derived from the access binding matching the observed peer address, and
  each audit record carries `domain_source`.
- Metric definitions for CPU, memory and the two access-context latencies now
  describe what is measured on either tier, and say what is not measured.
- `make lint` and `make format` cover `experiments/`.

### Notes
- Both radios are simulated. Nothing in this release supports a claim about RF
  propagation, physical radio handover, interference, signal strength, spectrum
  efficiency, channel quality or production mobile-network performance.
- E13 measures **logical** scalability to 25 devices sharing one 802.11
  association. It is not independent WiFi-radio association scalability, and
  nothing is extrapolated beyond the validated levels.
- CITATION.cff still carries **no DOI**. One is added only once a release has
  actually been archived.

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
