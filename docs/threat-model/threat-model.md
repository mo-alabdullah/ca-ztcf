# Threat model

## Scope

Authentication and trust continuity at the service domain, for an IoT device moving between 5G and WiFi access.

**In scope.** An adversary who: presents a device identity it does not own; replays previously valid evidence;
occupies a network address previously bound to another device; induces or forces access-domain transitions; connects
from an access context outside policy; or manipulates the service-layer session identity.

**Out of scope.** Radio-layer attacks (jamming, hidden-node exploitation, spectrum hijack); cryptanalysis; compromise
of the 5G core or of a network function; compromise of the WLAN authenticator; physical extraction of a device
private key. These are real and are documented in the coexistence literature, but they are not what this framework
addresses, and pretending otherwise would be dishonest.

**Adversary capability.** Can observe and inject at the service interface, and can influence which access domain a
device uses. Cannot forge an Ed25519 signature without the private key, and cannot break TLS.

**Environment.** An isolated laboratory. No public or third-party infrastructure is involved in any scenario.

## Threats and expected behaviour

| Id | Condition | Laboratory realisation | Predicate | Expected outcome |
|---|---|---|---|---|
| T1 | Valid normal transition | Domain change with all evidence fresh | C7 | TRANSITIONAL → ALLOW_WITH_RESTRICTIONS → STABLE |
| T2 | Stale or replayed evidence | Replay a binding and proof past their lifetimes | ¬C2 ∨ ¬C4 | DEGRADED → STEP_UP_AUTHENTICATION |
| T3 | Device identity mismatch | Device A's identity presented from an address bound to device B | ¬C5 | UNTRUSTED → DENY |
| T4 | Unauthorised device context | Association to an SSID, BSSID, AKM or gNB outside the allow-list | ¬C11 | SUSPICIOUS → REAUTHENTICATE or QUARANTINE |
| T5 | Unexpected access transition | Transition to a domain with no valid binding | ¬C3 | DEGRADED → STEP_UP_AUTHENTICATION |
| T6 | Excessive transition frequency | Scripted rapid alternation above the rate limit | ¬C8 | SUSPICIOUS → QUARANTINE |
| T7 | Session identity mismatch | Service-layer session identity changed mid-session | ¬C10 | SUSPICIOUS → REAUTHENTICATE |
| T8 | Context inconsistency | Two live bindings claiming one address in different domains | ¬C5 | UNTRUSTED → DENY |
| T9 | Evidence freshness violation | Collector heartbeat suppressed until the binding ages out | ¬C4 | DEGRADED → STEP_UP_AUTHENTICATION |
| T10 | Legitimate temporary degradation | Collector outage and recovery, device legitimate throughout | ¬C4, then all hold | DEGRADED → STEP_UP → STABLE, **no DENY** |

T10 is the control. A framework that denies everything is trivially "secure"; T10 is what makes that failure visible,
and it is the primary source of false-rejection measurements. Covered in this milestone by
`test_ca_ztcf_recovers_from_degraded_to_stable`.

## Explicit limits

1. **Device private key compromise defeats the scheme.** Proof-of-possession is the only thing binding an access
   session to a device identity (ADR-0004), so an adversary holding the key is indistinguishable from the device.
2. **No corroboration across domains.** By ADR-0002 the framework never compares access-domain identifiers, so it
   cannot use 5G-side identity evidence to corroborate a WLAN-side claim.
3. **Trust in the collectors.** An access-context collector is trusted to report its domain honestly. A compromised
   collector can fabricate bindings. Collector integrity is out of scope.
4. **No radio-layer visibility.** The framework reasons at the evidence level. Where a threat is radio-layer in
   origin, only its trust consequence is represented.
