"""Machine-supported findings, non-findings and the limitations record.

A finding here is a statement the measurements support, carrying the numbers, the
test, the corrected p-value, the effect size and the files it came from. Anything
that did not reach significance, or that the design cannot answer, goes in the
non-findings file instead.

Negative and inconclusive results stay visible. A campaign that reports only what
worked is not evidence, it is advocacy.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from experiments.analysis.final_report import (
    ADVERSARIAL_SCENARIOS,
    BANNER,
    E13_LEVELS,
    LABELS,
    PRIMARY,
    FinalRun,
)
from experiments.analysis.statistics import confusion_rates


def _direction(effect: dict[str, Any], first: str, second: str) -> str:
    value = effect.get("value")
    if value is None:
        return "no direction"
    if value > 0:
        return f"{LABELS.get(first, first)} higher than {LABELS.get(second, second)}"
    if value < 0:
        return f"{LABELS.get(second, second)} higher than {LABELS.get(first, first)}"
    return "no direction"


def build_findings(
    runs: list[FinalRun], statistics: dict[str, Any], root: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    non_findings: list[dict[str, Any]] = []

    # --- P1, security outcomes ------------------------------------------
    for entry in statistics["security"]:
        scenario = entry["scenario"]
        counts = {s: entry["per_strategy"][s]["aggregate"]["counts"] for s in PRIMARY}
        rates = {s: entry["per_strategy"][s]["aggregate"]["false_acceptance_rate"] for s in PRIMARY}
        test = entry["paired_binary_false_acceptance"]
        record = {
            "dimension": "P1",
            "metric": "false acceptance",
            "scenario": scenario,
            "comparison": "A vs B300 vs C",
            "measured": {
                LABELS[s]: {
                    "counts": counts[s],
                    "false_acceptance_rate": rates[s],
                    "denominator": entry["per_strategy"][s]["aggregate"][
                        "false_acceptance_denominator"
                    ],
                    "runs_with_any_false_acceptance": entry["per_strategy"][s][
                        "runs_with_any_false_acceptance"
                    ],
                }
                for s in PRIMARY
            },
            "experimental_unit": "run",
            "n_paired_runs": entry["n_paired_runs"],
            "supporting_table": "tables/table_e_security_outcomes.md",
            "supporting_statistics": "statistics/primary_security.json",
            "supporting_raw": "raw/ (per-run metrics.json confusion_raw)",
        }
        if test.get("applicable") and test.get("significant"):
            record.update(
                test="cochran_q with exact McNemar follow-up, Holm corrected",
                statistic=test["statistic"],
                p_value=test["p_value"],
                pairwise={
                    k: {
                        "p_value_holm": v.get("p_value_holm"),
                        "significant": v.get("significant_holm"),
                        "discordant": [v.get("discordant_b"), v.get("discordant_c")],
                    }
                    for k, v in test.get("pairwise", {}).items()
                },
            )
            findings.append(record)
        else:
            record.update(
                test="cochran_q",
                outcome="not significant" if test.get("applicable") else "not applicable",
                reason=test.get("reason", "omnibus not significant"),
            )
            non_findings.append(record)

    # --- P2-P5, continuous metrics --------------------------------------
    for comparison in statistics["continuous"]:
        omnibus = comparison["omnibus"]
        base = {
            "dimension": comparison["dimension"],
            "metric": comparison["metric"],
            "metric_label": comparison["metric_label"],
            "scenario": comparison["scenario"],
            "condition": comparison["condition"],
            "comparison": "A vs B300 vs C",
            "experimental_unit": "run",
            "n_paired_runs": comparison["n_paired_runs"],
            "measured": {LABELS[s]: comparison["descriptive"][s] for s in comparison["conditions"]},
            "supporting_statistics": "statistics/primary_continuous.json",
            "supporting_table": "tables/table_k_statistics.md",
        }
        if not omnibus.get("applicable"):
            non_findings.append(
                {
                    **base,
                    "test": "friedman",
                    "outcome": "not applicable",
                    "reason": omnibus.get("reason", ""),
                }
            )
            continue
        if not omnibus.get("significant"):
            non_findings.append(
                {
                    **base,
                    "test": "friedman",
                    "statistic": omnibus["statistic"],
                    "p_value": omnibus["p_value"],
                    "outcome": "not significant",
                    "reason": "omnibus p >= 0.05; no pairwise follow-up",
                }
            )
            continue
        for key, pair in comparison.get("pairwise", {}).items():
            first, second = key.split("_vs_")
            if not pair.get("applicable"):
                non_findings.append(
                    {
                        **base,
                        "pair": key,
                        "test": "wilcoxon_signed_rank",
                        "outcome": "not applicable",
                        "reason": pair.get("reason", ""),
                    }
                )
                continue
            record = {
                **base,
                "pair": key,
                "test": "friedman omnibus, then paired wilcoxon signed-rank, Holm corrected",
                "omnibus_p_value": omnibus["p_value"],
                "statistic": pair["statistic"],
                "p_value_raw": pair["p_value_raw"],
                "p_value_holm": pair.get("p_value_holm"),
                "effect_size": pair.get("effect_size"),
                "confidence_interval": pair.get("paired_bootstrap_ci"),
                "direction": _direction(pair.get("effect_size", {}), first, second),
            }
            if pair.get("significant_holm"):
                findings.append(record)
            else:
                non_findings.append({**record, "outcome": "not significant after Holm"})

    # --- P6, scalability: descriptive only ------------------------------
    scal = statistics["scalability"]
    findings.append(
        {
            "dimension": "P6",
            "metric": "decision latency versus logical device count",
            "scenario": "E13",
            "comparison": "descriptive across 1, 5, 10, 25 logical devices",
            "measured": {
                f"{level} devices": {
                    LABELS[s]: scal["levels"][str(level)][s]["decision_latency_ms_median"]
                    for s in PRIMARY
                }
                for level in E13_LEVELS
            },
            "test": "none; descriptive only",
            "experimental_unit": "run",
            "qualification": scal["qualification"],
            "supporting_table": "tables/table_j_logical_device_scalability.md",
            "supporting_statistics": "statistics/scalability.json",
        }
    )

    return findings, non_findings


LIMITATIONS = """# Experimental limitations

> **{banner}**

These are the boundaries of what the evidence in `results/final/` can support.
They are stated plainly because the value of the result depends on them being
understood, not on them being small.

## The testbed has no physical radio

Tier 2 is a **reproducible software-based 5G/WiFi coexistence testbed**. Every
protocol interaction is real; every radio is simulated.

- **UERANSIM is a software UE and gNB.** It speaks real 5G NAS, NGAP and GTP-U to
  Open5GS, and it synthesises the radio. It is not a commercial or physical 5G
  RAN, and no measurement from it describes one.
- **`mac80211_hwsim` is a simulated PHY.** The IEEE 802.11 association, the RSN
  four-way handshake and the EAP-TLS exchange are the real Linux implementations;
  the propagation is not real at all.

Nothing in these results supports a claim about RF propagation, physical radio
handover performance, interference, signal strength, spectrum efficiency,
channel-quality behaviour, or performance on a production mobile network.

## Scalability is logical, and bounded at 25

The maximum validated count is **25 logical devices**. Each has a distinct
service-domain identity, a distinct 5G address and access binding, a distinct WLAN
logical address and binding, a distinct MQTT session and a distinct audit trail.

**The 25 WLAN addresses share one IEEE 802.11 association.** E13 therefore
measures CA-ZTCF logical and service-domain scalability. It does **not** measure
independent WiFi-radio association scalability, and a run with 25 separate radio
associations would need 25 virtual radios and 25 supplicants, which was not
validated.

E13 declares 50 and 100 as possible future levels. They were **not run**. Nothing
here may be extrapolated to 50, 100 or 1000 devices.

## Transition rates are bounded by what was validated

E14 reports the four rates already validated: 1, 5, 10 and 25 transitions per
second. No higher rate was introduced to find a failure point, so no failure point
is claimed and no behaviour beyond 25 per second is described.

## Timing is single-host

Everything runs in one virtual machine on one host. Latency figures are influenced
by host scheduling, and they are software-testbed timings rather than the timings
of a distributed production deployment. The separate timing quantities — access
authentication, path switch, trust decision, application recovery and end-to-end
transition — are reported separately and must not be conflated. In the transition
records, `T4` to `T5` includes agent process start-up and is **not** a trust
decision time.

## Resource figures measure the experiment process

CPU and memory are sampled from the process that runs the trust function together
with the scenario driver. **They are not an IoT device measurement**: the device
agent is a separate process and, on Tier 2, lives in another network namespace. No
figure here describes what CA-ZTCF costs a constrained device.

## Two metrics were not measured

**Bytes exchanged (M9).** The metric counts bytes on the
device-to-enforcement-point socket. The experiment runner drives the framework in
process, so no such socket exists and the counter was never recorded in any of the
2160 runs. The byte-overhead half of P5 is unanswered by this campaign; message
counts were recorded and are reported.

**Trust engine evaluation time for the baselines (M12).** Neither baseline has a
trust engine, so the metric exists only for CA-ZTCF. It is reported descriptively
and no three-way comparison of it is possible.

## Token lifetime sensitivity is partly untested

Seven of the nine sensitivity scenarios span less scenario time than the shortest
token lifetime tested, so no token could expire in them and nothing was learned
about the lifetime there. The two that do outlast a 30-second token show no
difference at any lifetime — which is a result, but it rests on two scenarios
rather than nine.

## The 5G collector is version-specific

Access-context evidence is parsed from Open5GS 2.8.0's own log output. The parsing
follows what a running core actually emits, which is why `gnb_id` was corrected to
a serving-node address (ADR-0008). Another core, or another Open5GS release, needs
its own adapter, and posture policy constrains a serving-node address rather than
a cell identity.

## Adversarial conditions are injected by the harness

E06 to E10 and E15 apply their manipulations on top of real observations, and each
such event is marked. No access network can be asked to emit a genuinely malicious
event, so the adversary is modelled rather than observed. Ground truth is fixed by
the scenario before the run and is never derived from a CA-ZTCF decision.

## A laboratory is not a deployment

PLMN 999/70 is the 3GPP-reserved test network and the subscriber keys are
published Open5GS laboratory vectors. The workload is a controlled scenario set,
not production traffic. Nothing here establishes how the framework behaves under
an operator's real subscriber population, traffic mix or attack surface.
"""


def generate_all(runs: list[FinalRun], statistics: dict[str, Any], root: Path) -> list[Path]:
    processed = root / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    findings, non_findings = build_findings(runs, statistics, root)
    written: list[Path] = []

    path = processed / "findings.json"
    path.write_text(
        json.dumps(
            {
                "banner": BANNER,
                "note": (
                    "Machine-supported findings only. Each carries its measured "
                    "values, the test, the corrected p-value where one applies, the "
                    "effect size and the files it came from. No narrative claim "
                    "appears here."
                ),
                "experimental_unit": "run (scenario x strategy x seed)",
                "alpha": 0.05,
                "count": len(findings),
                "findings": findings,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    written.append(path)

    lines = [
        "# Non-findings and inconclusive results",
        "",
        f"> **{BANNER}**",
        "",
        "Hypotheses and comparisons the measurements did **not** support, or could "
        "not answer. They are listed because a campaign that reports only what "
        "worked is advocacy rather than evidence.",
        "",
        f"Total: **{len(non_findings)}**.",
        "",
    ]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in non_findings:
        grouped[entry.get("dimension", "?")].append(entry)
    titles = {
        "P1": "P1 — security decision outcome",
        "P2": "P2 — transition cost",
        "P3": "P3 — authentication cost",
        "P4": "P4 — trust engine cost",
        "P5": "P5 — resource cost",
        "P6": "P6 — scalability",
    }
    for dimension in sorted(grouped):
        lines.append(f"## {titles.get(dimension, dimension)}")
        lines.append("")
        for entry in grouped[dimension]:
            label = entry.get("metric_label", entry.get("metric", "?"))
            pair = f" [{entry['pair']}]" if entry.get("pair") else ""
            outcome = entry.get("outcome", "not significant")
            reason = entry.get("reason", "")
            p_holm = entry.get("p_value_holm")
            p_text = f", Holm p = {p_holm:.5f}" if isinstance(p_holm, float) else ""
            lines.append(
                f"- **{entry.get('scenario', '?')} — {label}**{pair}: {outcome}"
                f"{p_text}. {reason}".rstrip()
            )
        lines.append("")
    ttl_path = root / "statistics" / "ttl_sensitivity.json"
    if ttl_path.is_file():
        ttl = json.loads(ttl_path.read_text(encoding="utf-8"))["scenarios"]
        short = [e["scenario"] for e in ttl if not e["long_enough_to_expire_shortest_token"]]
        outlasting = [e["scenario"] for e in ttl if e["long_enough_to_expire_shortest_token"]]
        lines.extend(
            [
                "## Token lifetime sensitivity — no effect, for two different reasons",
                "",
                "Baseline B at 30, 300 and 1800 second token lifetimes produced "
                "**identical** confusion counts in all nine scenarios tested. Two "
                "distinct reasons sit behind that, and conflating them would overstate "
                "the result.",
                "",
                f"- **Untested, not unaffected.** {', '.join(short)} span less scenario "
                "time than the shortest lifetime, so no token could expire. Nothing was "
                "learned about the lifetime in these.",
                f"- **Genuinely unaffected.** {', '.join(outlasting)} do outlast a "
                "30-second token and still show no difference at any lifetime. In E15 "
                "the false acceptance rate is 1.0000 whether the token lives 30 seconds "
                "or 1800. Shortening it does not help, because the baseline "
                "re-authenticates on exactly the evidence it ignored before; its failure "
                "mode is not a lifetime that is too long.",
                "",
                "## Metrics that were not measured at all",
                "",
                "- **M9, bytes exchanged.** It counts bytes on the "
                "device-to-enforcement-point socket. The experiment runner drives the "
                "framework in process, so no such socket exists and the counter was "
                "never recorded in any of the 2160 runs. P5's byte-overhead dimension is "
                "therefore unanswered by this campaign. Message counts were recorded and "
                "are reported.",
                "- **M12, trust engine evaluation time, for the baselines.** Neither "
                "baseline has a trust engine, so the metric exists only for CA-ZTCF and "
                "no three-way comparison is possible. It is reported descriptively.",
                "",
            ]
        )
    lines.append("## What the design cannot answer at all")
    lines.append("")
    lines.extend(
        [
            "- Any question about physical radio behaviour. There is no physical radio.",
            "- Scalability beyond 25 logical devices, or any independent WiFi-radio "
            "association scalability.",
            "- Behaviour above 25 transitions per second.",
            "- What CA-ZTCF costs a constrained IoT device: the resource figures measure "
            "the experiment process, not the device agent.",
            "- Behaviour on a production network with real subscribers and real traffic.",
            "",
        ]
    )
    path = processed / "non_findings.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    written.append(path)

    path = processed / "experimental_limitations.md"
    path.write_text(LIMITATIONS.format(banner=BANNER), encoding="utf-8")
    written.append(path)

    # A compact per-scenario security summary, so the raw counts are one file away.
    summary: dict[str, Any] = {"banner": BANNER, "scenarios": {}}
    for scenario in ADVERSARIAL_SCENARIOS:
        per: dict[str, Any] = {}
        for strategy in PRIMARY:
            totals: Counter = Counter()
            for run in runs:
                if (run.campaign, run.scenario, run.strategy) == ("primary", scenario, strategy):
                    totals.update({k: v for k, v in run.confusion.items() if isinstance(v, int)})
            per[LABELS[strategy]] = confusion_rates(dict(totals))
        summary["scenarios"][scenario] = per
    path = processed / "security_summary.json"
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    written.append(path)

    return written
