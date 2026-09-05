# ADR-0002: No cross-domain identifier sharing

- Status: Accepted
- Date: 2026-09-06

## Context

The framework must relate a device's 5G access session to its WLAN access session in order to reason about a
transition. The obvious approach is to correlate access-domain identifiers, or to introduce a trusted third party
that issues tokens both networks accept.

Ramezanpour, Jagannath and Jagannath (*Computer Networks* 221:109515, 2023, §3.2) assess exactly that approach for
5G/WiFi coexistence and reject it on two grounds: it "requires substantial changes in the security architecture of
networks which seems impractical", and privacy requirements protecting identifiers and traffic "prevent sharing
information of users between networks".

## Decision

CA-ZTCF never compares an identifier from one access domain with an identifier from another.

- Each access domain asserts only: *"at this time, address `a` is bound to an authenticated session in my domain,
  with these properties and this freshness."*
- Domain identifiers (subscriber reference, EAP identity, station MAC) are hashed **inside their own collector**,
  using a salt generated independently per collector, and are used only for intra-domain continuity.
- The binding between an access session and a device identity is established solely in the service domain, by the
  device's own cryptographic proof-of-possession combined with the currently observed binding for its peer address.

The independence of the salts is enforced in code and asserted by
`tests/unit/test_collectors.py::test_collector_salts_are_independent_so_digests_never_collide`: the same raw string
hashes differently in each collector, so cross-domain comparison is impossible rather than merely forbidden.

## Consequences

**Positive.** No protocol change is required in either access domain, no operator↔WLAN agreement is needed, and no
subscriber information crosses a domain boundary. This is a direct engineering answer to the objection above.

**Negative.** The framework cannot detect an adversary who controls a device's private key, because the private key
is the only thing tying the two domains together. It also cannot use domain-specific identity evidence to
corroborate a claim across domains. Both limits are stated in the threat model rather than worked around.
