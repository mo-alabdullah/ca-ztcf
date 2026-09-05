# CA-ZTCF — Coexistence-Aware Zero Trust Continuity Framework

Research prototype of a **service-domain Zero Trust continuity function** that re-evaluates IoT device trust at
5G/WiFi access transitions, using only evidence each access domain can realistically expose — and without any
cross-domain identifier sharing.

Developed as the software artefact of a master's thesis in Computer Networks Engineering.

> **This software makes no performance or security claim.** Its properties are design objectives, to be evaluated
> experimentally in later releases. No experiment has been run; this release contains no results.

## The problem

An IoT device holds one identity but reaches its service through two independently secured access domains. The 5G
domain knows it by operator-held identifiers; the WLAN domain knows it by a station address and an EAP identity.
Neither can observe the other, and making them share subscriber information is both architecturally impractical and
blocked by privacy requirements (Ramezanpour et al., *Computer Networks* 221:109515, 2023, §3.2).

So at every transition the assurance obtained in the previous domain becomes unobservable at the service. That is
**trust discontinuity**. The two obvious responses are both unsatisfactory, and both are implemented here as
baselines: rebuild everything on every transition, or carry trust forward and reintroduce exactly the implicit trust
that Zero Trust rejects.

## The approach

Each access domain asserts only: *"at this time, address `a` is bound to an authenticated session in my domain, with
these properties and this freshness."* The binding of that assertion to a device identity happens solely in the
service domain, through the device's own Ed25519 proof-of-possession. No identifier crosses a domain boundary, and no
protocol changes in either domain.

Trust is then derived by a **criteria-based, contextual** algorithm in the sense of NIST SP 800-207 §3.3.1: eleven
named predicates over a versioned evidence record, an ordered rule system, six trust states, and a transition-aware
policy matrix. No weights, no scores, no machine learning — so every decision is explainable and exactly replayable.

CA-ZTCF is placed as an operator-domain / service-domain security function. That placement is compatible with the
architectural freedom described in 3GPP TR 33.794, which locates the security evaluation function in the operator's
domain, external to the 3GPP network, with its application logic outside 3GPP scope. **No 3GPP conformance or
endorsement is claimed or tested.**

## Trust states

| State | Meaning | Action |
|---|---|---|
| `UNKNOWN` | No registry entry; the device is not enrolled | DENY / `REGISTRATION_REQUIRED` |
| `STABLE` | All predicates hold; no recent transition | ALLOW |
| `TRANSITIONAL` | Valid device, recent domain change, evidence settling | ALLOW_WITH_RESTRICTIONS (STEP_UP when repeated) |
| `DEGRADED` | Evidence incomplete or stale, without contradiction | STEP_UP_AUTHENTICATION |
| `SUSPICIOUS` | Evidence contradictory or strongly abnormal | REAUTHENTICATE, or QUARANTINE across a transition |
| `UNTRUSTED` | Validation failed, or the binding is claimed by another device | DENY / `VALIDATION_FAILED` |

`UNKNOWN` and `UNTRUSTED` both deny, deliberately: different evidence semantics, different recovery paths, different
audit meanings. See [ADR-0005](docs/adr/ADR-0005-unknown-device-deny.md).

## Quick start

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
make check
```

```bash
make docker-build && make docker-up
curl -s localhost:8080/readyz
make smoke
```

`make smoke` drives the full flow — enrol, steady 5G session, 5G→WiFi transition, evidence settling, identity
mismatch, unregistered device. It is a functional check, not an experiment; see
[how-to-reproduce](docs/reproducibility/how-to-reproduce.md).

## Documentation

- Architecture: [system model](docs/architecture/system-model.md) · [components](docs/architecture/components.md) ·
  [evidence model](docs/architecture/evidence-model.md) · [trust states](docs/architecture/trust-states.md) ·
  [policy matrix](docs/architecture/policy-matrix.md)
- [Threat model](docs/threat-model/threat-model.md) · [scope and limits](docs/threat-model/scope-and-limits.md)
- Experiments (planned): [matrix](docs/experiments/experiment-matrix.md) ·
  [metrics](docs/experiments/metrics.md) · [baselines](docs/experiments/baselines.md)
- Reproducibility: [environment](docs/reproducibility/environment.md) ·
  [determinism](docs/reproducibility/determinism.md) · [how to reproduce](docs/reproducibility/how-to-reproduce.md)
- Decisions: [ADR-0001](docs/adr/ADR-0001-criteria-based-contextual-trust.md) ·
  [ADR-0002](docs/adr/ADR-0002-no-cross-domain-identifier-sharing.md) ·
  [ADR-0003](docs/adr/ADR-0003-two-tier-testbed.md) ·
  [ADR-0004](docs/adr/ADR-0004-service-domain-device-identity.md) ·
  [ADR-0005](docs/adr/ADR-0005-unknown-device-deny.md) ·
  [ADR-0006](docs/adr/ADR-0006-synthetic-development-events-vs-live-testbed-evidence.md)

## Status

`v0.1.0` — development prototype. The CA-ZTCF core is implemented and tested; the MQTT enforcement point, the real
5G and WiFi testbeds, the experiment controller and the experimental programme are later batches. All 5G-side events
in this release are development fixtures marked `source_mode: synthetic_fixture` and are **not** measurements.

## Citation

See [`CITATION.cff`](CITATION.cff). It carries **no DOI**: a DOI will be added only once a GitHub release has actually
been archived by Zenodo. No placeholder or fabricated DOI is committed at any point.

## Licence

Code: Apache-2.0. Documentation and results: CC BY 4.0. See [`LICENSE`](LICENSE).
