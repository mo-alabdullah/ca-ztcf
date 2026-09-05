# Trust continuity states

Six states. They are **not** justified by a one-to-one mapping onto enforcement actions: `UNKNOWN` and `UNTRUSTED`
both deny, for different reasons and with different recovery paths, and an operator must be able to tell them apart.
States are justified on four axes instead, recorded in code in `ca_ztcf.trust_engine.states.STATE_DEFINITIONS`.

| State | Evidence semantics | Recovery path | Audit meaning | Policy consequence |
|---|---|---|---|---|
| `UNKNOWN` | No valid registry entry exists | Administrative enrolment, out of band | An unregistered device attempted access | DENY / `REGISTRATION_REQUIRED` |
| `STABLE` | All predicates hold; no recent transition | — | Steady legitimate operation | ALLOW |
| `TRANSITIONAL` | Valid device, recent domain change, evidence still settling | Transition window elapses with predicates holding | A legitimate access-domain change | ALLOW_WITH_RESTRICTIONS, or STEP_UP when REPEATED |
| `DEGRADED` | Evidence incomplete, stale or unavailable, without contradiction | Fresh evidence plus a successful step-up | Reduced assurance; the device may be legitimate | STEP_UP_AUTHENTICATION |
| `SUSPICIOUS` | Evidence contradictory or strongly abnormal | Full re-authentication plus a cooldown | Possible attack in progress | REAUTHENTICATE, or QUARANTINE across a transition |
| `UNTRUSTED` | Registered, but validation failed or the binding is claimed by another device | Administrative status change, then full re-authentication | Validation failure or a competing claim | DENY / `VALIDATION_FAILED` |

## Predicates

| Id | Name | Holds when |
|---|---|---|
| C1 | `IDENTITY_VALID` | The device is registered and administratively enabled |
| C2 | `POP_FRESH` | A verified proof-of-possession exists and is within its lifetime |
| C3 | `BINDING_PRESENT` | An access domain asserts a binding for the peer address |
| C4 | `BINDING_FRESH` | That binding was refreshed within the freshness bound |
| C5 | `BINDING_CONSISTENT` | That binding is not already attributed to a different device |
| C6 | `DOMAIN_STABLE` | No transition falls inside the stability window |
| C7 | `TRANSITION_RECENT` | A transition falls inside the transition window |
| C8 | `RATE_OK` | Transitions within the rate window are at or below the limit |
| C9 | `AUTHN_FAILURES_OK` | Authentication failures within the window are at or below the limit |
| C10 | `SESSION_CONSISTENT` | The service-layer session identity still matches the device |
| C11 | `DOMAIN_POSTURE_OK` | The access context satisfies the configured posture allow-lists |

Each predicate returns a result, a reason code and the evidence items it consulted — never a bare boolean.

## The ordered rule system

```
R0  C1 failed because the device is not registered       -> UNKNOWN
R1  not C1 (registered but disabled)  or  not C5         -> UNTRUSTED
R2  not C8 or not C9 or not C10 or (C3 and not C11)      -> SUSPICIOUS
R3  not C3 or not C4 or not C2                           -> DEGRADED
R4  C7                                                   -> TRANSITIONAL
R5  otherwise                                            -> STABLE
```

First match wins. The order is not arbitrary:

- **UNKNOWN precedes everything.** With no registry entry there is no identity against which any other evidence could
  be interpreted, and no public key against which a proof could be checked.
- **UNTRUSTED precedes SUSPICIOUS.** A revoked identity, or a binding claimed by another device, is a direct
  contradiction and outranks a rate anomaly.
- **SUSPICIOUS precedes DEGRADED.** Contradictory evidence must never be masked by evidence that also happens to be
  stale. Asserted by `test_contradiction_outranks_staleness`.
- **DEGRADED precedes TRANSITIONAL.** A device whose evidence is missing is not merely mid-transition, even when a
  transition is also under way. Asserted by `test_degradation_outranks_transition`.
- **The posture clause in R2 is guarded by C3**, so a device with no binding at all is DEGRADED (missing evidence)
  rather than SUSPICIOUS (a contradiction).

## Determinism

Given the same evidence record and the same configuration, the derived state, the firing rule and the reason codes are
always identical; only the generated evaluation identifier and the measured duration differ, and neither participates
in the derivation. Asserted by `test_repeated_evaluation_of_one_record_is_identical`.
