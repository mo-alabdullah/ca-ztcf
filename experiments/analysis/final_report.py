"""Derive every final artefact from the frozen raw output.

Nothing here is typed by hand and nothing is chosen after seeing a result: the
comparisons, the tests and the six outcome dimensions were fixed in
``docs/experiments/final_experiment_protocol.md`` before the campaign ran.

The unit of analysis is the **run** — one (scenario, strategy, seed, condition).
A run contributes one value per metric. The thousands of decisions inside a run
are not independent repetitions and are never treated as such.
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from experiments.analysis.statistics import (
    PairedComparison,
    cochran_q,
    compare_three_paired,
    confusion_rates,
    describe,
)

PRIMARY = ["independent", "static_continuity", "ca_ztcf"]
"""A, B300, C. Declaration order only; it carries no ranking."""

LABELS = {
    "independent": "A independent",
    "static_continuity": "B300 static continuity",
    "ca_ztcf": "C CA-ZTCF",
    "static_continuity_ttl30": "B30 static continuity",
    "static_continuity_ttl1800": "B1800 static continuity",
}

SENSITIVITY = ["static_continuity_ttl30", "static_continuity", "static_continuity_ttl1800"]

TRANSITION_SCENARIOS = ["E03", "E04", "E05", "E09", "E12"]
"""Scenarios where a transition actually occurs, so a transition cost exists."""

ADVERSARIAL_SCENARIOS = ["E06", "E07", "E08", "E09", "E10", "E15"]
"""Scenarios carrying adversarial ground truth, so a confusion matrix is meaningful."""

E13_LEVELS = [1, 5, 10, 25]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


@dataclass
class FinalRun:
    """One run, reduced to the per-run values the analysis consumes."""

    run_id: str
    scenario: str
    strategy: str
    seed: int
    condition: str
    campaign: str
    device_count: int
    metrics: dict[str, Any]
    confusion: dict[str, int]
    actions: dict[str, int]
    resources: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)


def _dist(metrics: dict[str, Any], key: str, field_name: str = "median") -> float | None:
    entry = metrics.get("distributions", {}).get(key)
    if not entry:
        return None
    value = entry.get(field_name)
    return float(value) if value is not None else None


def _rate(confusion: dict[str, Any], numerator: str, denominator: str) -> float | None:
    """A run-level rate, or None when the run had no events of that class.

    None rather than zero: a run that presented no adversarial event has no false
    acceptance rate to report, and recording it as a perfect zero would credit the
    strategy for a test it never took.
    """
    total = confusion.get(denominator, 0)
    if not total:
        return None
    return float(confusion.get(numerator, 0)) / float(total)


def load_final_runs(root: Path) -> list[FinalRun]:
    """Read every VALID run named by the ledger. The ledger is the authority."""
    ledger_path = root / "run_ledger.csv"
    runs: list[FinalRun] = []
    with ledger_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["status"] != "VALID" or not row["result_path"]:
                continue
            raw = root / row["result_path"]
            metrics_path = raw / "metrics.json"
            if not metrics_path.is_file():
                continue
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            resources_path = raw / "resources.json"
            resources = (
                json.loads(resources_path.read_text(encoding="utf-8")).get("process", {})
                if resources_path.is_file()
                else {}
            )
            meta_path = root / "metadata" / f"{row['run_id']}.json"
            metadata = (
                json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
            )
            counters = metrics.get("counters", {})
            runs.append(
                FinalRun(
                    run_id=row["run_id"],
                    scenario=row["scenario"],
                    strategy=row["strategy"],
                    seed=int(row["seed"]),
                    condition=row["condition"],
                    campaign=row["campaign"],
                    device_count=int(metadata.get("device_count", 1)),
                    metrics={
                        "decision_latency_ms_median": _dist(metrics, "M3"),
                        "decision_latency_ms_p95": _dist(metrics, "M3", "p95"),
                        "engine_time_us_median": _dist(metrics, "M12"),
                        "nr_context_ms_median": _dist(metrics, "M1_NR"),
                        "wlan_context_ms_median": _dist(metrics, "M1_EAP"),
                        "transition_ms_median": _dist(metrics, "M2"),
                        "app_recovery_ms_median": _dist(metrics, "M4"),
                        "reauthentications": int(counters.get("M5", 0)),
                        "step_ups": int(counters.get("M6", 0)),
                        "state_changes": int(counters.get("M7", 0)),
                        "messages": int(counters.get("M8", 0)),
                        "bytes": int(counters.get("M9", 0)),
                        "app_operations": int(counters.get("M19", 0)),
                        "cpu_seconds": resources.get("cpu_seconds_total"),
                        "cpu_percent": resources.get("cpu_percent_mean_over_run"),
                        "memory_mib_peak": resources.get("memory_mib_peak_rss"),
                        "wall_seconds": resources.get("wall_seconds"),
                        # Run-level security rates. The protocol calls for paired
                        # analysis of run-level rates, and they are what carries the
                        # comparison where "did this run produce any false
                        # acceptance" is the same for every strategy.
                        "false_acceptance_rate": _rate(
                            metrics.get("confusion_raw", {}),
                            "false_acceptance",
                            "illegitimate_total",
                        ),
                        "false_rejection_rate": _rate(
                            metrics.get("confusion_raw", {}),
                            "false_rejection",
                            "legitimate_total",
                        ),
                    },
                    confusion=metrics.get("confusion_raw", {}),
                    actions=metrics.get("policy_action_distribution", {}),
                    resources=resources,
                    metadata=metadata,
                )
            )
    return runs


def index_by(runs: list[FinalRun], *, campaign: str) -> dict[tuple, dict[str, FinalRun]]:
    """(scenario, condition, seed) -> strategy -> run. The pairing structure."""
    table: dict[tuple, dict[str, FinalRun]] = defaultdict(dict)
    for run in runs:
        if run.campaign != campaign:
            continue
        table[(run.scenario, run.condition, run.seed)][run.strategy] = run
    return table


def paired_series(
    runs: list[FinalRun],
    scenario: str,
    metric: str,
    strategies: list[str],
    *,
    condition: str = "default",
    campaign: str = "primary",
) -> dict[str, list[float]]:
    """One value per seed per strategy, aligned by seed so pairs stay pairs."""
    by_seed: dict[int, dict[str, float | None]] = defaultdict(dict)
    for run in runs:
        if (run.campaign, run.scenario, run.condition) != (campaign, scenario, condition):
            continue
        by_seed[run.seed][run.strategy] = run.metrics.get(metric)
    series: dict[str, list[float]] = {s: [] for s in strategies}
    for seed in sorted(by_seed):
        values = by_seed[seed]
        if any(values.get(s) is None for s in strategies):
            continue  # a pair is only a pair when every condition supplied a value
        for s in strategies:
            series[s].append(float(values[s]))  # type: ignore[arg-type]
    return series


# ---------------------------------------------------------------------------
# Processed tables
# ---------------------------------------------------------------------------


def _write_csv(path: Path, rows: list[dict[str, Any]], banner: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(f"# {banner}\n")
        if rows:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    return path


BANNER = (
    "FINAL THESIS EXPERIMENTAL EVIDENCE. Tier-2 live software-based testbed: real "
    "5G NAS/NGAP/GTP-U via Open5GS and UERANSIM, and a real IEEE 802.11 "
    "association and EAP-TLS exchange via mac80211_hwsim, over simulated radios. "
    "Not an RF, propagation, interference, channel-quality, spectrum-coexistence "
    "or physical-handover measurement. Generated from results/final/raw/; no value "
    "was typed by hand."
)


def build_processed(runs: list[FinalRun], root: Path) -> dict[str, Path]:
    processed = root / "processed"
    outputs: dict[str, Path] = {}

    per_run = [
        {
            "run_id": r.run_id,
            "campaign": r.campaign,
            "scenario": r.scenario,
            "strategy": r.strategy,
            "strategy_label": LABELS.get(r.strategy, r.strategy),
            "seed": r.seed,
            "condition": r.condition,
            "device_count": r.device_count,
            **{k: ("" if v is None else v) for k, v in r.metrics.items()},
            **{f"confusion_{k}": v for k, v in sorted(r.confusion.items())},
        }
        for r in sorted(runs, key=lambda x: (x.campaign, x.scenario, x.strategy, x.seed))
    ]
    outputs["per_run"] = _write_csv(processed / "per_run_metrics.csv", per_run, BANNER)

    action_rows = [
        {
            "campaign": r.campaign,
            "scenario": r.scenario,
            "strategy": r.strategy,
            "seed": r.seed,
            "condition": r.condition,
            "action": action,
            "count": count,
        }
        for r in runs
        for action, count in sorted(r.actions.items())
    ]
    outputs["actions"] = _write_csv(processed / "policy_actions.csv", action_rows, BANNER)

    confusion_rows: list[dict[str, Any]] = []
    grouped: dict[tuple[str, str, str], Counter] = defaultdict(Counter)
    for r in runs:
        grouped[(r.campaign, r.scenario, r.strategy)].update(
            {k: v for k, v in r.confusion.items() if isinstance(v, int)}
        )
    for (campaign, scenario, strategy), totals in sorted(grouped.items()):
        rates = confusion_rates(dict(totals))
        confusion_rows.append(
            {
                "campaign": campaign,
                "scenario": scenario,
                "strategy": strategy,
                "strategy_label": LABELS.get(strategy, strategy),
                "runs": 30,
                **rates["counts"],
                **rates["totals"],
                "false_acceptance_rate": rates["false_acceptance_rate"],
                "false_acceptance_denominator": rates["false_acceptance_denominator"],
                "false_rejection_rate": rates["false_rejection_rate"],
                "false_rejection_denominator": rates["false_rejection_denominator"],
                "detection_rate_recall": rates["detection_rate_recall"],
                "precision": rates["precision"],
                "accuracy": rates["accuracy"],
                "f1": rates["f1"],
            }
        )
    outputs["confusion"] = _write_csv(processed / "confusion_raw.csv", confusion_rows, BANNER)

    scal_rows = [
        {
            "device_count": r.device_count,
            "strategy": r.strategy,
            "seed": r.seed,
            **{k: ("" if v is None else v) for k, v in r.metrics.items()},
        }
        for r in runs
        if r.scenario == "E13" and r.campaign == "primary"
    ]
    outputs["scalability"] = _write_csv(
        processed / "scalability_e13.csv",
        sorted(scal_rows, key=lambda x: (x["device_count"], x["strategy"], x["seed"])),
        BANNER,
    )
    return outputs


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

CONTINUOUS_COMPARISONS = [
    ("P1", "false_acceptance_rate", "false acceptance rate per run", ADVERSARIAL_SCENARIOS),
    ("P1", "false_rejection_rate", "false rejection rate per run", None),
    ("P2", "transition_ms_median", "transition duration (ms)", TRANSITION_SCENARIOS),
    ("P2", "app_recovery_ms_median", "application recovery (ms)", TRANSITION_SCENARIOS),
    ("P3", "reauthentications", "full re-authentications (count)", None),
    ("P3", "step_ups", "step-up authentications (count)", None),
    ("P4", "decision_latency_ms_median", "decision latency, median per run (ms)", None),
    ("P4", "engine_time_us_median", "trust engine evaluation, median per run (us)", None),
    ("P5", "cpu_seconds", "CPU seconds per run", None),
    ("P5", "memory_mib_peak", "peak resident memory (MiB)", None),
    ("P5", "messages", "MQTT control packets (count)", None),
    ("P5", "bytes", "bytes exchanged", None),
]


def build_statistics(runs: list[FinalRun], root: Path) -> dict[str, Any]:
    stats_dir = root / "statistics"
    stats_dir.mkdir(parents=True, exist_ok=True)
    scenarios = sorted({r.scenario for r in runs if r.campaign == "primary"})

    continuous: list[dict[str, Any]] = []
    for dimension, metric, label, limit in CONTINUOUS_COMPARISONS:
        for scenario in scenarios:
            if limit is not None and scenario not in limit:
                continue
            condition = "devices=25" if scenario == "E13" else "default"
            series = paired_series(runs, scenario, metric, PRIMARY, condition=condition)
            if not series[PRIMARY[0]]:
                continue
            outcome = compare_three_paired(
                PairedComparison(
                    metric=metric,
                    scenario=scenario,
                    conditions=PRIMARY,
                    samples=series,
                    notes=[
                        f"dimension {dimension}: {label}",
                        "experimental unit is the run; one value per seed per strategy",
                    ],
                )
            )
            outcome["dimension"] = dimension
            outcome["metric_label"] = label
            outcome["condition"] = condition
            continuous.append(outcome)
    (stats_dir / "primary_continuous.json").write_text(
        json.dumps({"banner": BANNER, "comparisons": continuous}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    # P1: security outcome, per scenario, as raw counts plus a paired binary test on
    # "did this run produce any false acceptance / any false rejection".
    security: list[dict[str, Any]] = []
    for scenario in ADVERSARIAL_SCENARIOS:
        by_seed: dict[int, dict[str, FinalRun]] = defaultdict(dict)
        for run in runs:
            if run.campaign == "primary" and run.scenario == scenario:
                by_seed[run.seed][run.strategy] = run
        seeds = [s for s in sorted(by_seed) if all(k in by_seed[s] for k in PRIMARY)]
        totals = {s: Counter() for s in PRIMARY}
        fa_binary = {s: [] for s in PRIMARY}
        fr_binary = {s: [] for s in PRIMARY}
        for seed in seeds:
            for strategy in PRIMARY:
                run = by_seed[seed][strategy]
                totals[strategy].update(
                    {k: v for k, v in run.confusion.items() if isinstance(v, int)}
                )
                fa_binary[strategy].append(1 if run.confusion.get("false_acceptance", 0) else 0)
                fr_binary[strategy].append(1 if run.confusion.get("false_rejection", 0) else 0)
        entry: dict[str, Any] = {
            "dimension": "P1",
            "scenario": scenario,
            "n_paired_runs": len(seeds),
            "per_strategy": {
                s: {
                    "label": LABELS[s],
                    "aggregate": confusion_rates(dict(totals[s])),
                    "runs_with_any_false_acceptance": int(sum(fa_binary[s])),
                    "runs_with_any_false_rejection": int(sum(fr_binary[s])),
                }
                for s in PRIMARY
            },
            "paired_binary_false_acceptance": cochran_q(PRIMARY, fa_binary),
            "paired_binary_false_rejection": cochran_q(PRIMARY, fr_binary),
            "note": (
                "Counts are summed over runs and are NOT independent observations; "
                "the paired tests use one binary outcome per run, which is the "
                "experimental unit."
            ),
        }
        security.append(entry)
    (stats_dir / "primary_security.json").write_text(
        json.dumps({"banner": BANNER, "scenarios": security}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    # P6: scalability, descriptive only. No extrapolation.
    scalability: dict[str, Any] = {
        "banner": BANNER,
        "levels": {},
        "qualification": (
            "Logical devices. Each has a distinct service-domain identity, 5G address "
            "and binding, WLAN logical address and binding, MQTT session and audit "
            "trail. The WLAN addresses share ONE 802.11 association, so this is "
            "CA-ZTCF logical/service-domain scalability, NOT independent WiFi-radio "
            "association scalability. Levels above 25 were not run and nothing is "
            "claimed about them."
        ),
    }
    for level in E13_LEVELS:
        per_strategy = {}
        for strategy in PRIMARY:
            selected = [
                r
                for r in runs
                if r.scenario == "E13"
                and r.strategy == strategy
                and r.device_count == level
                and r.campaign == "primary"
            ]
            per_strategy[strategy] = {
                "label": LABELS[strategy],
                "n_runs": len(selected),
                "decision_latency_ms_median": describe(
                    [
                        r.metrics["decision_latency_ms_median"]
                        for r in selected
                        if r.metrics["decision_latency_ms_median"] is not None
                    ]
                ),
                "decision_latency_ms_p95": describe(
                    [
                        r.metrics["decision_latency_ms_p95"]
                        for r in selected
                        if r.metrics["decision_latency_ms_p95"] is not None
                    ]
                ),
                "cpu_seconds": describe(
                    [
                        r.metrics["cpu_seconds"]
                        for r in selected
                        if r.metrics["cpu_seconds"] is not None
                    ]
                ),
                "memory_mib_peak": describe(
                    [
                        r.metrics["memory_mib_peak"]
                        for r in selected
                        if r.metrics["memory_mib_peak"] is not None
                    ]
                ),
                "messages": describe([float(r.metrics["messages"]) for r in selected]),
                "app_operations": describe([float(r.metrics["app_operations"]) for r in selected]),
                "errors": sum(1 for r in selected if r.confusion.get("false_rejection", 0)),
            }
        scalability["levels"][str(level)] = per_strategy
    (stats_dir / "scalability.json").write_text(
        json.dumps(scalability, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    # TTL sensitivity, descriptive plus the same paired machinery.
    sensitivity: list[dict[str, Any]] = []
    sens_runs = [r for r in runs if r.campaign == "sensitivity"] + [
        r for r in runs if r.campaign == "primary" and r.strategy == "static_continuity"
    ]
    sens_scenarios = sorted({r.scenario for r in runs if r.campaign == "sensitivity"})
    for scenario in sens_scenarios:
        by_seed: dict[int, dict[str, FinalRun]] = defaultdict(dict)
        for run in sens_runs:
            if run.scenario == scenario:
                by_seed[run.seed][run.strategy] = run
        seeds = [s for s in sorted(by_seed) if all(k in by_seed[s] for k in SENSITIVITY)]
        totals = {s: Counter() for s in SENSITIVITY}
        fa_binary = {s: [] for s in SENSITIVITY}
        for seed in seeds:
            for strategy in SENSITIVITY:
                run = by_seed[seed][strategy]
                totals[strategy].update(
                    {k: v for k, v in run.confusion.items() if isinstance(v, int)}
                )
                fa_binary[strategy].append(1 if run.confusion.get("false_acceptance", 0) else 0)
        sensitivity.append(
            {
                "scenario": scenario,
                "n_paired_runs": len(seeds),
                "token_lifetimes_s": {
                    "static_continuity_ttl30": 30,
                    "static_continuity": 300,
                    "static_continuity_ttl1800": 1800,
                },
                "per_lifetime": {
                    s: {
                        "label": LABELS[s],
                        "aggregate": confusion_rates(dict(totals[s])),
                        "runs_with_any_false_acceptance": int(sum(fa_binary[s])),
                        "reauthentications": describe(
                            [float(by_seed[seed][s].metrics["reauthentications"]) for seed in seeds]
                        ),
                        "step_ups": describe(
                            [float(by_seed[seed][s].metrics["step_ups"]) for seed in seeds]
                        ),
                    }
                    for s in SENSITIVITY
                },
                "paired_binary_false_acceptance": cochran_q(SENSITIVITY, fa_binary),
            }
        )
    (stats_dir / "ttl_sensitivity.json").write_text(
        json.dumps(
            {
                "banner": BANNER,
                "note": (
                    "Sensitivity analysis of baseline B's token lifetime. "
                    "NOT part of the primary three-way comparison."
                ),
                "scenarios": sensitivity,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    return {
        "continuous": continuous,
        "security": security,
        "scalability": scalability,
        "sensitivity": sensitivity,
    }
