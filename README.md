# CA-ZTCF — Coexistence-Aware Zero Trust Continuity Framework

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22544764.svg)](https://doi.org/10.5281/zenodo.22544764)

Research prototype of a **service-domain Zero Trust continuity function** that re-evaluates IoT device trust at
5G/WiFi access transitions, using only evidence each access domain can realistically expose — and without any
cross-domain identifier sharing.

Developed as the software artefact of a master's thesis in Computer Networks Engineering.

> **Scope of the evidence.** This release carries frozen experimental results from a **reproducible software-based
> 5G/WiFi coexistence testbed**: Open5GS with UERANSIM for real 5G NAS/NGAP/GTP-U, and `mac80211_hwsim` with hostapd
> and wpa_supplicant for a real IEEE 802.11 association and EAP-TLS exchange. **Both radios are simulated.** Nothing
> here supports a claim about RF propagation, physical radio handover, interference, signal strength, spectrum
> efficiency, channel quality or production mobile-network performance.

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

## Testbeds

**Tier 2 — the evaluation testbed.** A reproducible software-based 5G/WiFi coexistence environment in one VM. Each
access path lives in its own network namespace, so a device's traffic can only reach the enforcement point through
the access technology it is attributed to.

```
  ca-ztcf-ue namespace   --5G user plane (GTP-U)-->  10.99.0.1 : 1884
  ca-ztcf-sta namespace  --802.11 over hwsim----->   192.168.70.1 : 1884
                                                            |
                                              ca-ztcf-mqtt-pep --> mosquitto
                                                            |
                                                      ca-ztcf-core
```

Real 5G registration, PDU session and GTP-U through Open5GS 2.8.0 and UERANSIM v3.2.6. Real 802.11 association, RSN
four-way handshake and EAP-TLS through `mac80211_hwsim`, hostapd 2.10 and wpa_supplicant 2.10. **Simulated PHY in
both cases.** See [ADR-0009](docs/adr/ADR-0009-access-path-network-namespaces.md) and the
[Tier-2 guide](testbed/tier2/README.md).

**Tier 1 — the portable development testbed.** A synthetic 5G access-context fixture plus a real
`hostapd driver=wired` / `wpa_supplicant -Dwired` 802.1X/EAP-TLS exchange over a veth pair. **It is not 802.11 radio
access**, it carries `source_mode: tier1_wlan_auth_emulation`, and results from it are development validation only.
See [ADR-0007](docs/adr/ADR-0007-tier1-wlan-source-mode.md).

The MQTT enforcement point decides nothing itself: it calls the core for every decision and applies the answer, so
the application path cannot bypass the trust engine. It does not declare the access domain either — it sees a TCP
peer address, and the domain is derived from the access binding that matches it. Policy actions map onto MQTT 3.1.1
mechanisms only: CONNACK `0x05` for a refusal, SUBACK `0x80` for a refused subscription, silent drop with an audit
record for a refused publish.

## Experimental results

`results/final/` holds the frozen evidence. The protocol was
[committed before the first run](docs/experiments/final_experiment_protocol.md) and not edited afterwards; every
attempt appears in `results/final/run_ledger.csv`; and all processed data, tables, figures and statistics regenerate
from the raw output.

| | |
|---|---|
| Valid runs | 2160 (1620 primary, 540 sensitivity) |
| Scenarios | E01–E15 |
| Strategies | A independent, B300 static continuity, C CA-ZTCF; plus B30 and B1800 for sensitivity |
| Repetitions | 30, paired by seed across strategies |
| Device levels | 1, 5, 10, 25 **logical** devices |
| Transition rates | 1, 5, 10, 25 per second |

Start with [Table E](results/final/tables/table_e_security_outcomes.md) for the security outcomes,
[Table K](results/final/tables/table_k_statistics.md) for the tests and effect sizes,
[`findings.json`](results/final/processed/findings.json) for what the measurements support,
[`non_findings.md`](results/final/processed/non_findings.md) for what they did not, and
[`experimental_limitations.md`](results/final/processed/experimental_limitations.md) for the boundaries of all of it.

**E13 measures logical scalability.** The 25 devices have distinct service-domain identities, 5G addresses and
bindings, WLAN logical addresses and bindings, MQTT sessions and audit trails — but their WLAN addresses share one
802.11 association. It is not independent WiFi-radio association scalability, and nothing is extrapolated beyond 25.

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

`make smoke` drives the core flow — enrol, steady 5G session, 5G→WiFi transition, evidence settling, identity
mismatch, unregistered device. It is a functional check, not an experiment; see
[how-to-reproduce](docs/reproducibility/how-to-reproduce.md).

For the Tier-1 development runs:

```bash
make testbed-build && make testbed-up
make tier1-wlan
python scripts/mqtt_integration_flow.py
make experiments && make process && make verify
```

To reproduce the final campaign, see
[how to reproduce the final results](docs/reproducibility/final-results.md).

## Documentation

- Architecture: [system model](docs/architecture/system-model.md) · [components](docs/architecture/components.md) ·
  [evidence model](docs/architecture/evidence-model.md) · [trust states](docs/architecture/trust-states.md) ·
  [policy matrix](docs/architecture/policy-matrix.md)
- [Threat model](docs/threat-model/threat-model.md) · [scope and limits](docs/threat-model/scope-and-limits.md)
- Experiments: [**frozen final protocol**](docs/experiments/final_experiment_protocol.md) ·
  [amendments](docs/experiments/amendments/) · [matrix](docs/experiments/experiment-matrix.md) ·
  [metrics](docs/experiments/metrics.md) · [baselines](docs/experiments/baselines.md)
- Reproducibility: [environment](docs/reproducibility/environment.md) ·
  [determinism](docs/reproducibility/determinism.md) · [how to reproduce](docs/reproducibility/how-to-reproduce.md)
- Testbed: [MQTT enforcement](docs/architecture/mqtt-enforcement.md) ·
  [Tier-1 testbed](docs/reproducibility/tier1-testbed.md)
- Decisions: [ADR-0001](docs/adr/ADR-0001-criteria-based-contextual-trust.md) ·
  [ADR-0002](docs/adr/ADR-0002-no-cross-domain-identifier-sharing.md) ·
  [ADR-0003](docs/adr/ADR-0003-two-tier-testbed.md) ·
  [ADR-0004](docs/adr/ADR-0004-service-domain-device-identity.md) ·
  [ADR-0005](docs/adr/ADR-0005-unknown-device-deny.md) ·
  [ADR-0006](docs/adr/ADR-0006-synthetic-development-events-vs-live-testbed-evidence.md) ·
  [ADR-0007](docs/adr/ADR-0007-tier1-wlan-source-mode.md) ·
  [ADR-0008](docs/adr/ADR-0008-synthetic-fixture-vs-live-5g-schema.md) ·
  [ADR-0009](docs/adr/ADR-0009-access-path-network-namespaces.md)

## Status

`v1.0.2` — the thesis experimental release. The framework, both testbeds, the experiment infrastructure and the
frozen final results are complete.

The measurements were frozen at `v1.0.0`. `v1.0.1` corrected how three measurement gaps were *reported* — bytes were
never measured rather than zero, the trust-engine comparison exists for one strategy only, and the token-lifetime
analysis was untestable in seven of its nine scenarios — without changing any measurement. `v1.0.2` is an archival
metadata release carrying those same results unchanged; the raw-data archive is byte-identical across all three.

Two software defects were found by the project's own gates while the campaign was running, and both are recorded in
[`docs/experiments/amendments/`](docs/experiments/amendments/) rather than quietly patched: a resource record that
contradicted what it measured, and a trust engine that timed itself with the frozen scenario clock and therefore
reported exactly zero. In both cases the campaign was stopped, the defect fixed, a regression test added, the
affected runs invalidated and the matrix rerun. Neither touched a trust state, predicate, policy rule, evidence
model, ground-truth label, baseline algorithm or scenario.

## Archival and citation

`v1.0.2` is archived on Zenodo. It is the research artefact the thesis is written around.

| | |
|---|---|
| GitHub release | https://github.com/mo-alabdullah/ca-ztcf/releases/tag/v1.0.2 |
| Zenodo record | https://zenodo.org/records/22544765 |
| **Version DOI** | **[10.5281/zenodo.22544765](https://doi.org/10.5281/zenodo.22544765)** |
| Concept DOI | [10.5281/zenodo.22544764](https://doi.org/10.5281/zenodo.22544764) |

**Cite the version DOI**, `10.5281/zenodo.22544765`. It identifies the exact archived `v1.0.2`
release — one commit, one configuration hash, one set of frozen measurements — which is what makes a
result traceable to the code that produced it.

The concept DOI, `10.5281/zenodo.22544764`, identifies the CA-ZTCF software record across all
versions and always resolves to the most recent one. Use it for a project-level reference where
persistence across future versions matters more than identifying a specific one. The project badge
above uses the concept DOI for that reason.

Machine-readable metadata is in [`CITATION.cff`](CITATION.cff); ready-to-use IEEE, BibTeX and
methodology-paragraph forms are in [`docs/release/thesis-citation.md`](docs/release/thesis-citation.md).

The DOI fields were added after `v1.0.2` was tagged and archived, because a DOI cannot exist before
the release it identifies. The frozen commit `513fd96` does not contain them, and neither does the
Zenodo snapshot of it. That ordering is correct.

## Licence

Code: Apache-2.0. Documentation and results: CC BY 4.0. See [`LICENSE`](LICENSE).
