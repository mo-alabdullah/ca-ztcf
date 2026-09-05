# The Transition-Aware Policy Matrix

Two axes: the trust continuity state, and the transition context. Making the transition an explicit axis is the point
of the framework, so it is a first-class input rather than an attribute buried in the evidence.

Loaded entirely from `config/policy/policy_matrix.yaml`. Rules are evaluated in declaration order; the first match
wins. The matrix is **total** — every (state, context) pair matches a declared rule and none falls through to the
default. Asserted by `test_matrix_is_total`.

## Transition contexts

`NONE`, `NR_TO_WLAN`, `WLAN_TO_NR`, `INTRA` (re-binding within one domain), `REPEATED` (transition count within the
rate window has reached `repeat_threshold`).

## Actions

| Action | Enforcement behaviour | TTL (research default) |
|---|---|---|
| `ALLOW` | Full scope | 60 000 ms |
| `ALLOW_WITH_RESTRICTIONS` | Reduced scope; session continues | 10 000 ms |
| `STEP_UP_AUTHENTICATION` | Resources held; control channel only | 10 000 ms |
| `REAUTHENTICATE` | Session invalidated; full authentication required | 0 ms |
| `QUARANTINE` | Isolated in a quarantine namespace | 30 000 ms |
| `DENY` | No access | 0 ms |

A decision's TTL bounds its lifetime: the enforcement point must re-consult CA-ZTCF when the TTL expires or when a
transition is observed, whichever comes first. Time-bounded decisions follow the dynamic-policy pattern described in
3GPP TR 33.794 clause 5.2.1; no conformance is claimed.

## The matrix

| Rule | State | Transition context | Action | Scope | Reason codes |
|---|---|---|---|---|---|
| P01 | UNKNOWN | any | DENY | none | `REGISTRATION_REQUIRED` |
| P02 | UNTRUSTED | any | DENY | none | `VALIDATION_FAILED` |
| P03 | SUSPICIOUS | NR_TO_WLAN, WLAN_TO_NR, REPEATED | QUARANTINE | quarantine | `CONTRADICTORY_EVIDENCE`, `DURING_ACCESS_TRANSITION` |
| P04 | SUSPICIOUS | NONE, INTRA | REAUTHENTICATE | none | `CONTRADICTORY_EVIDENCE` |
| P05 | DEGRADED | any | STEP_UP_AUTHENTICATION | step_up_pending | `INCOMPLETE_OR_STALE_EVIDENCE` |
| P06 | TRANSITIONAL | REPEATED | STEP_UP_AUTHENTICATION | step_up_pending | `REPEATED_TRANSITION` |
| P07 | TRANSITIONAL | NR_TO_WLAN, WLAN_TO_NR | ALLOW_WITH_RESTRICTIONS | restricted | `ACCESS_DOMAIN_TRANSITION` |
| P08 | TRANSITIONAL | INTRA | ALLOW_WITH_RESTRICTIONS | restricted | `INTRA_DOMAIN_REBINDING` |
| P09 | TRANSITIONAL | NONE | ALLOW_WITH_RESTRICTIONS | restricted | `TRANSITION_EVIDENCE_SETTLING` |
| P10 | STABLE | NONE, INTRA | ALLOW | full | `EVIDENCE_CONSISTENT` |
| P11 | STABLE | any | ALLOW_WITH_RESTRICTIONS | restricted | `UNEXPECTED_TRANSITION_CONTEXT_FOR_STABLE` |

P11 is defensive. STABLE requires C6, so a transition context other than NONE or INTRA should be unreachable; if it
occurs, the matrix restricts rather than allows and records the anomaly.

## Scopes

Defined in `config/policy/topic_scopes.yaml` over MQTT-style resource filters (`+` matches one level, `#` matches the
remainder). `deny` is checked first and wins; a resource matching neither list is refused.

Because enforcement is **default-deny**, `deny` is for *explicit* exclusions only. A catch-all `#` deny entry would be
evaluated first and would shadow that scope's own allow patterns — it is never correct. Asserted by
`test_enforcement_is_default_deny`.

| Scope | Allows | Denies |
|---|---|---|
| `full` | `dev/{id}/#`, `cmd/{id}/#`, `shared/telemetry/#` | — |
| `restricted` | `dev/{id}/telemetry/#`, `dev/{id}/status` | `cmd/#`, `shared/#` |
| `step_up_pending` | `ctl/{id}/challenge`, `ctl/{id}/response` | — |
| `quarantine` | `q/{id}/#` | — |
| `none` | — | — |
