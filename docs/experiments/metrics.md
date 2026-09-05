# Metrics

## Exported today (Prometheus)

| Metric | Type | Labels |
|---|---|---|
| `ca_ztcf_decisions_total` | counter | strategy, trust_state, transition_context, action |
| `ca_ztcf_decision_duration_seconds` | histogram | strategy |
| `ca_ztcf_trust_state_total` | counter | trust_state, firing_rule |
| `ca_ztcf_policy_actions_total` | counter | action, rule_id |
| `ca_ztcf_transition_events_total` | counter | from_domain, to_domain |
| `ca_ztcf_auth_failures_total` | counter | reason |
| `ca_ztcf_engine_duration_seconds` | histogram | — |

`TrustEvaluation.engine_duration_ns` and `Decision.decision_duration_ns` are measured with the injected clock's
monotonic counter and recorded on every audit line.

## Planned for the experimental programme (Batch I)

Authentication latency; access transition latency; decision latency; end-to-end transition completion; full
re-authentication count; step-up count; trust-state transitions; messages and bytes exchanged; CPU and memory;
CA-ZTCF processing time; successful legitimate transitions; rejected illegitimate transitions; false rejection; false
acceptance; detection rate; policy-decision distribution; throughput; scalability.

## Reporting rules

Latency distributions are not assumed normal: report median, IQR, p95 and a bootstrap confidence interval, never a
bare mean.

**Every ratio is reported with its numerator and denominator.** No percentage appears anywhere without the raw counts
used to compute it, and false-rejection, false-acceptance and detection figures always appear alongside the full
confusion counts.

Time discipline: wall-clock UTC for evidence, expiry and audit records; the monotonic counter for durations only. A
monotonic reading is never written into an evidence record as a point in time.
