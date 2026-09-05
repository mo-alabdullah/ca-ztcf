# ADR-0005: An unknown device is denied, not re-authenticated

- Status: Accepted
- Date: 2026-09-06
- Supersedes: an earlier draft in which UNKNOWN mapped to REAUTHENTICATE.

## Context

`UNKNOWN` means there is no valid device registry entry: the device has not completed research enrolment. An earlier
design mapped it to REAUTHENTICATE, on the reasoning that a device should be given the chance to authenticate.

That reasoning is wrong. Re-authentication on the normal access path would let an unregistered device bootstrap
trust through the very path that is supposed to be gated by enrolment. There is also nothing to authenticate
*against*: with no registry entry there is no public key, so no proof-of-possession can be verified.

That earlier design also justified the state set by a one-state-to-one-action bijection, which forced each state to
own a distinct action. That constraint is artificial.

## Decision

`UNKNOWN` maps to **DENY** with reason `REGISTRATION_REQUIRED`. Enrolment is a separate administrative procedure,
outside the access-decision path.

The bijection argument is withdrawn. `UNKNOWN` and `UNTRUSTED` both deny, and that is correct. States are justified
instead on four axes, recorded in code in `ca_ztcf.trust_engine.states.STATE_DEFINITIONS` and asserted by
`tests/unit/test_trust_engine.py::test_unknown_and_untrusted_share_an_action_but_differ_elsewhere`:

| | UNKNOWN | UNTRUSTED |
|---|---|---|
| Evidence semantics | no registry record exists | registered, but validation failed or the binding is claimed by another device |
| Recovery path | administrative enrolment, out of band | administrative status change, then full re-authentication |
| Audit meaning | an unregistered device attempted access | validation failure or a competing claim |
| Policy consequence | DENY / `REGISTRATION_REQUIRED` | DENY / `VALIDATION_FAILED` |

## Consequences

**Positive.** Enrolment stays a genuine gate. An operator reading the audit log can immediately distinguish "someone
plugged in an unknown device" from "a known device failed validation" — different incidents with different responses.

**Negative.** A device whose registry entry is lost is locked out until an administrator restores it. That is the
intended behaviour, not a defect.
