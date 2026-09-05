# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
