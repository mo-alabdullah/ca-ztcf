# CA-ZTCF final experiment protocol

**Status: FROZEN.** Committed before the first final run.

Nothing in this document may be changed because of a result. If a correction
becomes unavoidable it goes in a separate, timestamped amendment that states what
changed and why, and the amendment is committed before the affected runs are
repeated. Amendments live in `docs/experiments/amendments/`.

---

## 1. Framework version

| | |
|---|---|
| Framework | CA-ZTCF (Coexistence-Aware Zero Trust Continuity Framework) |
| Version | 0.3.1 + the frozen-protocol commit |
| Architecture | **frozen**: trust states, predicate semantics, policy matrix, evidence model, ground-truth taxonomy, baseline algorithms, scenario meaning and enforcement semantics are closed to change for the duration of the campaign |

## 2. Commit and configuration

The campaign runs under **one** git SHA and **one** configuration hash. The
campaign driver checks both before the first run and after every run, and stops if
either changes. Results produced under two configurations must never share a
primary dataset.

| | |
|---|---|
| Baseline before the freeze | `c3463926420537f26e7ce2f7477a0bb1de533e1c` (tag `v0.3.1`) |
| Configuration hash | `a1d260b660c93e47a466deb9c00f26c880973356f7da4eda00cb8ec57cab044d` |

The configuration hash covers the two token-lifetime sensitivity variants of
baseline B, which are added **before** the campaign precisely so that the primary
and sensitivity campaigns share one hash.

## 3. Testbed architecture

Tier 2: **a reproducible software-based 5G/WiFi coexistence testbed.** One Lima
VM. Each access path lives in its own network namespace, so a device's traffic can
only reach the enforcement point through the access technology it is attributed
to (ADR-0009).

```
  root namespace                        ca-ztcf-ue namespace
  nr-gnb  RLS 10.200.0.1  <--veth-->    10.200.0.2 (uectl1)
          NGAP -> 127.0.0.5             uesimtunN  10.45.10.N/32
          GTP-U <-> 127.0.0.7           route 10.99.0.0/24 dev uesimtunN
  open5gs-upfd -> ogstun 10.45.0.1/16   (TCP rejected on the control veth)
  ztcfsvc0 (dummy) 10.99.0.1/32

  hostapd -> wlan0 192.168.70.1         ca-ztcf-sta namespace
       ^--- 802.11 over mac80211_hwsim -> wlan1 192.168.70.10 ..
                                          wpa_supplicant (EAP-TLS)
```

The 5G source address is proved deterministic independently of CA-ZTCF by
`testbed/tier2/network/verify_ue_path.py` before the campaign begins.

### What this testbed can and cannot support

**Supports:** authentication and session behaviour; access transitions; trust
continuity; policy enforcement; MQTT application continuity; software and testbed
latency; decision latency; message and byte overhead; CPU and memory overhead of
the measured process; controlled security scenarios; logical-device scalability.

**Does not support, and no claim may be made about:** physical RF propagation;
physical radio handover performance; interference; signal strength; spectrum
efficiency; channel-quality behaviour; production mobile-network performance.

## 4. Software versions

| Component | Version |
|---|---|
| Host | macOS 26.6.2 (25G83), Lima 2.2.0 |
| Guest | Ubuntu 24.04.4 LTS, kernel 6.8.0-138-generic, aarch64, 4 vCPU, 6 GiB |
| 5G core | Open5GS 2.8.0~noble5 |
| 5G RAN/UE | UERANSIM v3.2.6 (built with documented GCC 13 include flags) |
| WLAN | mac80211_hwsim; hostapd v2.10; wpa_supplicant v2.10 |
| Subscriber DB | MongoDB 8.0.29 |
| Broker | Mosquitto 2.0.18 |
| Runtime | Python 3.12.3 (guest), 3.12.13 (host analysis) |

## 5. Scenarios

The already validated definitions in `experiments/scenarios/` are used unchanged.

| Id | Subject |
|---|---|
| E01 | Steady 5G |
| E02 | Steady WiFi |
| E03 | 5G → WiFi transition |
| E04 | WiFi → 5G transition |
| E05 | Repeated alternating transitions |
| E06 | Stale evidence |
| E07 | Device identity mismatch |
| E08 | Unauthorised context |
| E09 | Rapid transition sequence |
| E10 | Session/service identity mismatch |
| E11 | Legitimate temporary degradation and recovery |
| E12 | Concurrent logical-device transition |
| E13 | Logical-device scalability |
| E14 | Transition-rate scalability |
| E15 | Mixed legitimate/adversarial workload |

### E13 device levels — frozen

**1, 5, 10, 25 logical devices.** E13 declares 50 and 100 as possible future
levels; they have **not** been validated and are **not** run. Nothing about them
is claimed.

E13 is executed once per level per strategy per seed. The level is a campaign
parameter recorded in run metadata; the scenario definition is unchanged.

### E14 transition rates — frozen

**1.0, 5.0, 10.0, 25.0 transitions per second**, exactly the rates already
validated and already present in `experiments/scenarios/E14.yaml`. All four are
swept within a single run, with a 90-second advance between levels so the rate
window clears and the levels stay independent. No higher rate is introduced.

### E15 mixed workload

The already validated deterministic generator is used. Legitimate and adversarial
events are drawn from **disjoint device cohorts**, so no device is both. Ground
truth is fixed by the scenario before the run. **Event labels are never derived
from CA-ZTCF decisions.**

## 6. Strategies

### Primary comparison

| Label | Strategy | Parameters |
|---|---|---|
| A | `independent` | Independent authentication in each access domain |
| B300 | `static_continuity` | `token_ttl_s = 300` |
| C | `ca_ztcf` | The framework |

### Sensitivity analysis — not part of the primary comparison

| Label | Strategy | Parameters |
|---|---|---|
| B30 | `static_continuity_ttl30` | `token_ttl_s = 30` |
| B1800 | `static_continuity_ttl1800` | `token_ttl_s = 1800` |

B30 and B1800 are the **same algorithm** at a different lifetime; a test asserts
this, so any difference is attributable to the lifetime alone. They are never
mixed into the three-way primary statistics.

**Sensitivity scenarios: E03, E04, E05, E06, E07, E08, E09, E10, E15.** Each
either crosses an access domain, presents evidence whose age matters, or mixes
legitimate and adversarial traffic — the three situations in which a token
lifetime can change the outcome. E01 and E02 are steady single-domain scenarios
that cannot distinguish lifetimes; E11–E14 measure cost at a fixed condition
rather than the trust decision a lifetime changes. B300 runs are taken from the
primary dataset rather than repeated, so no (scenario, strategy, seed) pair is
duplicated.

## 7. Repetitions and seeds

**R = 30** per primary scenario/strategy condition.

The 30 seeds are frozen in `experiments/final/seeds.yaml`, generated by the fixed
rule `20260906 + i` for `i` in 1..30, so the list is transparently not a selection
made after seeing results.

**The design is paired.** Repetition *i* uses the same seed across A, B300 and C,
and the sensitivity variants reuse the same seeds. A seed drives scenario
sequencing only; device keys come from the system CSPRNG.

A run that fails for an infrastructure reason is retried **with its own seed**. It
is never replaced by a different seed.

Primary matrix size: 14 scenarios × 3 strategies × 30 seeds, plus E13 at 4 levels
× 3 strategies × 30 seeds = **1620 conditions**. Sensitivity: 9 scenarios × 2
variants × 30 seeds = **540 conditions**.

## 8. Metrics

The already implemented metric set is used. No primary metric is added after
results are visible.

Decision and engine cost: decision latency (M3), pure trust-engine evaluation time
(M12). Authentication cost: full re-authentications (M5), step-ups (M6), trust
state changes (M7). Access cost: 5G context (M1_NR), WLAN authentication path
(M1_EAP), transition duration (M2). Application: messages (M8), bytes (M9),
success/failure (M19, M20). Resources: CPU (M10), memory (M11). Security: correct
and incorrect acceptance and rejection (M13–M17) and the raw confusion counts.

### Timing integrity — binding

These are separate quantities and must never be conflated in any table or figure:

- **access authentication latency** — authentication in the target access domain
- **path-switch latency** — the application path changing
- **trust decision latency** — the decision alone
- **application recovery latency** — the protected operation succeeding
- **end-to-end transition duration** — T0 to T6

**`T4 → T5` includes agent process start-up and MUST NOT be called pure CA-ZTCF
decision latency.** Pure decision latency is measured separately and reported
separately.

### Resource measurement — what is and is not measured

CPU and memory are sampled from the **experiment process**, which runs the trust
function together with the scenario driver. This is **not** an IoT device
measurement: the device agent is a separate process and, on Tier 2, lives in
another network namespace. No figure derived from it may be presented as a
device's resource consumption.

## 9. Primary outcomes

| | Dimension | Measured by |
|---|---|---|
| P1 | Security decision outcome | TP, TN, FP, FN; false acceptance; false rejection |
| P2 | Transition cost | end-to-end transition and application recovery time |
| P3 | Authentication cost | full re-authentication count; step-up count |
| P4 | Trust engine cost | pure decision and engine evaluation latency |
| P5 | Resource cost | CPU, memory, messages, bytes |
| P6 | Scalability | logical device count; validated transition rate |

All six are reported. Selecting only favourable dimensions afterwards is
forbidden.

## 10. Statistical plan

**Experimental unit: the run (a scenario × strategy × seed).** Thousands of events
inside one run are not independent repetitions and are never treated as such.

**Descriptive statistics are the default presentation**: n, median, IQR, p95, min,
max, plus paired bootstrap 95% confidence intervals. Latency and security
measurements are typically skewed; a sample of 30 is not a reason to assume
normality, and distributions are inspected rather than assumed.

**Primary three-strategy comparison of a continuous metric** (paired across A,
B300, C):

1. **Friedman test** as the omnibus test.
2. If the omnibus test is significant and a pairwise comparison is justified:
   **paired Wilcoxon signed-rank** tests.
3. **Holm correction** across the pairwise family.
4. Effect size: **matched-pairs rank-biserial correlation**, with the direction
   stated explicitly.

Mann-Whitney U is **not** used for paired primary comparisons.

**Binary and security outcomes**: raw confusion counts first, always. Run-level
paired rates are analysed paired. Where a formal categorical paired test is
warranted and its assumptions genuinely hold: **Cochran's Q** across the three
paired conditions, with **McNemar** for justified pairwise follow-up and Holm
correction. Otherwise raw counts, paired run-level rates and bootstrap intervals
are reported without a test.

**No percentage without its denominator.** Every rate table carries the raw counts
it was computed from.

Significance level α = 0.05 on Holm-adjusted p-values. Non-significant and
inconclusive outcomes are reported as such, in
`results/final/processed/non_findings.md`.

## 11. Run validity

A run is **VALID** only if all of the following hold:

- the expected testbed services were healthy before the run
- the git SHA matches the frozen SHA
- the configuration hash matches the frozen hash
- the scenario, strategy and seed are the intended ones
- no state survived from a previous run; reset succeeded
- the access path was established
- event generation completed
- metrics output completed
- audit output completed
- the provenance gate passed
- the privacy gate passed
- no unexpected harness exception occurred

### Infrastructure failure is not a security result

A VM crash, an Open5GS process crash unrelated to the scenario, host resource
exhaustion unrelated to the intended E14 load, a broken harness, a missing output
file, corrupted JSONL, a failed reset or loss of the controller are recorded
`INVALID_INFRASTRUCTURE_RUN`, **preserved**, excluded from primary statistics, and
retried with the same scenario, strategy and seed after the infrastructure is
restored.

### Software defect

If a failure is not clearly an infrastructure failure it is treated as a possible
software defect. The campaign **stops**. The failed raw runs are preserved, the
defect is fixed transparently, a regression test is added, the release candidate
is incremented, **every final run affected by the defect is invalidated**, and the
affected matrix is rerun consistently. Final data is never silently patched.

## 12. No silent exclusion

Every attempt appears in `results/final/run_ledger.csv` with `attempt_id`,
`run_id`, scenario, strategy, seed, condition, campaign, start, end, duration,
status, validity, reason, git SHA, config hash and result path. Statuses are
`VALID`, `INVALID_INFRASTRUCTURE_RUN`, `INVALID_SOFTWARE_DEFECT`, `ABORTED`.
Failed attempts are never deleted.

## 13. Process supervision

Every long-running command and background worker records its PID, start time and
log path, and has an explicit timeout, a success condition, a failure condition
and cleanup. Unbounded polling loops are forbidden. The campaign driver enforces a
per-run and a whole-campaign timeout and writes a session log. At the end of the
campaign, no experiment-related background process may remain unexpectedly active.

## 14. Result directory structure

```
results/final/
  raw/          one directory per run: events.jsonl, decisions.jsonl, metrics.json, resources.json
  processed/    derived tables, findings.json, non_findings.md, experimental_limitations.md
  metadata/     one file per run, plus the campaign index
  figures/
  tables/
  statistics/
  manifests/    SHA256SUMS, final_results_manifest.json
  logs/         campaign session logs
  run_ledger.csv
```

`results/dev/` is untouched. Development output and final output never mix.

## 15. Provenance requirements

Every final run must carry `source_mode: live_testbed`,
`testbed_type: software_based`, `access_implementation: ueransim` on 5G events and
`wifi_radio_mode: mac80211_hwsim` on WLAN events.

No final run may contain `synthetic_fixture`, `tier1_wlan_auth_emulation`,
`physical_rf` or `physical_5g_radio`. The source-mode gate enforces this
mechanically.

## 16. Privacy rules

Before release: secret scan, output privacy gate, source-mode gate, result-path
gate. Final material must contain no private key, subscriber authentication key,
cleartext SUPI or PEI, password, EAP secret, home-directory path or VM credential.
Synthetic research identifiers are permitted; PLMN 999/70 is the 3GPP-reserved
test network and the subscriber keys are published Open5GS laboratory vectors.

## 17. Reproducibility

All processed data, figures, tables and statistics are regenerated from
`results/final/raw/` by the committed pipeline. **No research value is typed by
hand.** After the campaign, the generated directories are moved aside and
regenerated, and the numerical content is compared. Where a rendering library
embeds non-deterministic metadata, figure binaries may differ; that is recorded
honestly rather than claimed as byte identity.

## 18. Known limitations

Carried into `results/final/processed/experimental_limitations.md` and not
minimised:

- Software-based testbed. **No physical RF anywhere.**
- UERANSIM is a software UE and gNB, not a commercial or physical 5G RAN.
- `mac80211_hwsim` is a simulated PHY, not RF propagation.
- Maximum **validated** logical-device count is **25**.
- **E13 does not represent 25 independent IEEE 802.11 radio associations.** The 25
  logical devices have distinct service-domain identities, distinct 5G addresses
  and bindings, distinct WLAN logical addresses and bindings, distinct MQTT
  sessions and distinct audit trails, but the WLAN addresses share **one** 802.11
  association. E13 therefore measures **CA-ZTCF logical/service-domain
  scalability**, not independent WiFi-radio association scalability.
- Single-host VM timing is influenced by host scheduling.
- The Open5GS log collector is specific to the deployed version; another core or
  another release needs its own adapter.
- A laboratory environment is not a production deployment.
