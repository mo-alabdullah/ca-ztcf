# ADR-0001: A criteria-based, contextual trust algorithm — not a score

- Status: Accepted
- Date: 2026-09-06

## Context

The trust engine must turn evidence into a trust state. Two families are available.
NIST SP 800-207 clause 3.3.1 distinguishes them explicitly: a **criteria-based** algorithm requires a set of
qualified attributes to be satisfied, whereas a **score-based** algorithm computes a confidence level from
per-source values and configured weights and compares it with a threshold. The same clause distinguishes
**singular** algorithms, which judge each request in isolation, from **contextual** ones, which take the subject's
recent history into account, and states that a Zero Trust trust algorithm should ideally be contextual.

An earlier conceptual version of this framework left the choice open and gestured at "qualitative states".

## Decision

The trust engine is **criteria-based and contextual**:

- eleven named boolean predicates (C1–C11) over the evidence record;
- an ordered rule system, first match wins, producing one of six trust states;
- per-device history (transition counts, authentication-failure counts) supplies the contextual part;
- no weights, no scores, no probability, no machine learning.

## Consequences

**Positive.** Every decision is explainable: the firing rule, the reason codes and the full predicate vector are
recorded, so a decision can be replayed from its evidence. Given identical evidence and configuration, the outcome is
bit-identical, which is what makes exact-replay validation possible. Thresholds are declared in configuration with a
unit and a purpose rather than buried as weights whose provenance nobody can reconstruct.

**Negative.** Criteria-based logic is coarser than a score: it cannot express "slightly less trustworthy". Adding a
new consideration means adding a predicate and deciding where it sits in the rule order, which is more deliberate
than adjusting a weight. We accept this: for a master's research artefact, a defensible and reproducible decision
procedure is worth more than expressive granularity that nobody could justify numerically.

**Not decided here.** Whether this choice performs well is an open question. It is a design decision, not a result.
