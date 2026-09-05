# Experiment matrix (planned — not yet executed)

**Nothing in this file has been run.** The experiment controller is Batch I and the full suite is Batch L. This
document records the plan so that the implementation is built against it.

Fifteen scenarios, each run under all three strategies with fixed seeds and 30 repetitions. Baseline B is
additionally swept over three token lifetimes. Ground-truth labels (`legitimate` / `illegitimate`) are emitted by the
scenario generator **before** a run and are never derived from CA-ZTCF output.

| Id | Objective | Threat |
|---|---|---|
| E01 | Steady 5G session, no transition | — |
| E02 | Steady WLAN session, no transition | — |
| E03 | Normal 5G → WiFi transition | T1 |
| E04 | Normal WiFi → 5G transition | T1 |
| E05 | Repeated alternating transitions | T1 |
| E06 | Transition with stale evidence | T2, T9 |
| E07 | Transition with identity mismatch | T3, T8 |
| E08 | Unauthorised access context | T4 |
| E09 | Suspicious rapid transition sequence | T6 |
| E10 | Session identity mismatch | T7 |
| E11 | Temporary degradation then recovery | T10 |
| E12 | Concurrent multi-device transitions | — |
| E13 | Scalability by device count | — |
| E14 | Scalability by transition rate | — |
| E15 | Mixed realistic workload, 80 % benign / 20 % adversarial | T2–T9 |

Each scenario declares its expected outcome in its YAML; a verification script checks each run against that
declaration rather than against observed behaviour.

## Statistical intent (no statistics performed yet)

Scenarios and seeds are reused across strategies, so observations are paired and repeated. Planned analysis:
descriptive median, IQR and p95 with bootstrap confidence intervals; a three-strategy repeated comparison via the
**Friedman test** where its assumptions fit; pairwise follow-up via the **paired Wilcoxon signed-rank test**; **Holm**
correction for multiple comparisons; a paired effect size such as **rank-biserial correlation**.

The final test is selected after inspecting the real distributions. Mann–Whitney U is **not** fixed as the method.
