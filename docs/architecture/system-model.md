# System model

## The problem this addresses

An IoT device holds a long-lived cryptographic identity and consumes a service. During its lifetime it reaches that
service through two access domains secured independently of one another:

- **NR** — 5G access. The security context is anchored in operator credentials; the device is known to that domain by
  identifiers the operator does not disclose outside it.
- **WLAN** — WiFi access. The security context is anchored locally, through 802.1X/EAP or SAE; the device is known by
  a station address and an EAP identity the WLAN administrator does not disclose to the operator.

Neither domain observes the other's security context, and making them share subscriber information is both
architecturally impractical and blocked by privacy requirements (Ramezanpour et al., *Computer Networks* 221:109515,
2023, §3.2). So at every `NR → WLAN` or `WLAN → NR` transition, the assurance obtained in the previous domain becomes
unobservable at the service. That condition is **trust discontinuity**.

## Where CA-ZTCF sits

CA-ZTCF is a **service-domain security function**. It consumes access-context events that each domain can already
expose, and it decides access to a service-domain resource.

This placement is compatible with the architectural freedom described in 3GPP TR 33.794, which locates the security
evaluation and monitoring function in the operator's domain, external to the 3GPP network, and states that its
application logic is outside 3GPP scope. **No 3GPP conformance or endorsement is claimed, none is tested, and no 3GPP
procedure is implemented here.** TR 33.794 itself is scoped to the 5GC service-based architecture — trust between
network functions — not to device trust across heterogeneous access.

## Components

```
DEVICE                 ACCESS DOMAINS                    SERVICE DOMAIN (CA-ZTCF)
                     ┌ NR events ────► collectors.nr ──┐
device key pair      └ WLAN events ──► collectors.wlan ┤──► BindingStore
Ed25519, PoP                           collectors.transition ──► TransitionEvent
    │                                                  ▼
    │                        evidence.assembler ──► EvidenceRecord (schema_version "1")
    │                                                  ▼
    │                        evidence.predicates ──► C1..C11 PredicateVector
    │                                                  ▼
    │                        trust_engine.engine ──► TrustState (R0..R5) + TrustStateManager
    │                                                  ▼
    │                        policy.matrix ──► Decision {action, scope, ttl, reasons}
    ▼                                                  ▼
enforcement.memory_pep  ◄──────────────────────  telemetry.audit (append-only JSONL)
                                                       telemetry.metrics (Prometheus)
```

| Component | Module | Responsibility |
|---|---|---|
| Device identity registry | `identity/registry.py` | Service-domain identities and public keys. No private material. |
| Proof-of-possession | `identity/proof.py` | Single-use, time-limited nonces; Ed25519 verification. |
| 5G context collector | `collectors/nr.py` | Normalises 5G core events into access bindings. |
| WLAN context collector | `collectors/wlan.py` | Normalises WLAN authenticator events into access bindings. |
| Transition collector | `collectors/transition.py` | Diffs the per-device domain sequence; derives the transition context. |
| Binding store | `collectors/base.py` | Current bindings by peer address; detects competing attribution claims. |
| Evidence assembler | `evidence/assembler.py` | Builds the versioned Dual-Context Evidence Model. |
| Predicates | `evidence/predicates.py` | C1–C11, each returning a result, a reason and its evidence references. |
| Trust engine | `trust_engine/engine.py` | Ordered rules R0–R5 producing one of six trust states. |
| Trust state manager | `trust_engine/engine.py` | Current state and bounded history per device. |
| Policy matrix | `policy/matrix.py` | (trust state × transition context) → action, scope, TTL. |
| Policy enforcement point | `enforcement/memory_pep.py` | Applies decisions; honours their lifetime. |
| Telemetry and audit | `telemetry/` | Prometheus metrics; append-only redacted JSONL. |
| Strategies | `strategies/` | CA-ZTCF and the two baselines, behind one interface. |

## What CA-ZTCF never consumes

Cleartext subscriber identifiers outside their own domain; any 5G or WLAN key material; radio channel state or RF
fingerprints; any identifier shared between the operator and the WLAN. Anything that a real deployment could not
obtain does not belong in the evidence model.

## Realism boundary for this milestone

All 5G-side events are development fixtures carrying `source_mode: synthetic_fixture`. The WLAN side is exercised in
Tier 1 by a portable 802.1X/EAP-TLS authentication-path emulation, which is not WiFi radio access. See ADR-0003 and
ADR-0006.
