# Baselines

Three approaches implement one interface (`ca_ztcf.strategies.interface.DecisionStrategy`) and share the same
collectors, evidence pipeline entry point, policy vocabulary, enforcement point, audit output and metrics. Only the
decision logic differs. That is what keeps the eventual comparison fair.

## Baseline A — independent authentication (`independent`)

Trust obtained in one access domain is never reused. Any detected transition requires a full re-authentication.
Outside a transition, access requires a valid registry entry and a fresh proof-of-possession. No trust state is
carried between requests, and no evidence record or trust evaluation is produced.

Bounds one end of the design space. Expected to be correct under the adversarial scenarios and to pay a
re-authentication cost at every transition — **both expectations are to be measured, not asserted.**

## Baseline B — static trust continuity (`static_continuity`)

After a first successful authentication the device receives a session token with a fixed lifetime. While the token is
valid it is honoured regardless of access domain, transition, evidence freshness or binding conflict.

This baseline deliberately reintroduces the implicit trust that Zero Trust rejects. It is expected to accept several
adversarial scenarios; that acceptance is the property being measured. **A scenario in which Baseline B does not fail
is a scenario that needs correcting, not a result.** Asserted today by
`test_baseline_b_reuses_its_token_across_a_transition`.

`token_ttl_s` will be swept over {30, 300, 1800} so the baseline is characterised across its trade-off rather than
evaluated at a single, easily strawmanned point.

## Proposed — CA-ZTCF (`ca_ztcf`)

The full pipeline: evidence → predicates → trust state → transition-aware policy → decision, with a complete trace.

## Fairness rules

Identical scenarios, seeds, workload, container images, hardware and repetition counts. Identical cryptographic
primitives and identical enforcement code path. Baseline A is given the same connection-reuse opportunities as the
others. No strategy receives information a real deployment could not obtain.
