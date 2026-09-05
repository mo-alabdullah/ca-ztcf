"""Development figures.

Every figure is generated from raw run output and carries a visible
DEVELOPMENT VALIDATION banner. No figure asserts a statistical conclusion: no
test is run, no p-value is computed, and no significance is claimed at this stage.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from experiments.analysis.process import DEV_DISCLAIMER, RunRecord, load_runs

BANNER = "DEVELOPMENT VALIDATION - NOT FINAL THESIS RESULT"
STRATEGY_ORDER = ["ca_ztcf", "independent", "static_continuity"]
STRATEGY_LABELS = {
    "ca_ztcf": "CA-ZTCF",
    "independent": "Baseline A: independent",
    "static_continuity": "Baseline B: static continuity",
}


def _finish(fig: Any, path: Path, subtitle: str) -> Path:
    fig.suptitle(BANNER, fontsize=9, color="#a11", y=0.995)
    fig.text(0.5, 0.005, subtitle, ha="center", fontsize=6.5, color="#555", wrap=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(rect=(0, 0.035, 1, 0.965))
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def _tier_note(runs: list[RunRecord]) -> str:
    modes = sorted({mode for run in runs for mode in run.source_modes})
    return f"Tier-1 development data. source_modes: {', '.join(modes)}. {DEV_DISCLAIMER}"


def decision_latency_distribution(runs: list[RunRecord], out: Path) -> Path:
    """Decision latency per strategy. Descriptive only."""
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    data, labels = [], []
    for strategy in STRATEGY_ORDER:
        values = [
            row["decision_latency_ms"]
            for run in runs
            if run.strategy == strategy
            for row in run.decisions
            if row.get("decision_latency_ms") is not None
        ]
        if values:
            data.append(values)
            labels.append(f"{STRATEGY_LABELS[strategy]}\n(n={len(values)})")
    if data:
        ax.boxplot(data, tick_labels=labels, showfliers=True)
    ax.set_ylabel("decision latency (ms)")
    ax.set_title("CA-ZTCF decision latency by strategy (descriptive; no test performed)")
    ax.grid(axis="y", alpha=0.3)
    return _finish(fig, out, _tier_note(runs))


def policy_action_distribution(runs: list[RunRecord], out: Path) -> Path:
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for run in runs:
        for action, count in run.metrics.get("policy_action_distribution", {}).items():
            counts[run.strategy][action] += count

    actions = sorted({action for tally in counts.values() for action in tally})
    fig, ax = plt.subplots(figsize=(8.5, 4.4))
    width = 0.8 / max(1, len(STRATEGY_ORDER))
    for index, strategy in enumerate(STRATEGY_ORDER):
        values = [counts[strategy].get(action, 0) for action in actions]
        positions = [i + index * width for i in range(len(actions))]
        ax.bar(positions, values, width=width, label=STRATEGY_LABELS[strategy])
    ax.set_xticks([i + width for i in range(len(actions))])
    ax.set_xticklabels(actions, rotation=20, ha="right", fontsize=8)
    ax.set_ylabel("decisions (count)")
    ax.set_title("Policy action distribution by strategy")
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    return _finish(fig, out, _tier_note(runs))


def trust_state_transitions(runs: list[RunRecord], out: Path) -> Path:
    tally: Counter[str] = Counter()
    for run in runs:
        if run.strategy != "ca_ztcf":
            continue
        for pair, count in run.metrics.get("trust_state_transitions", {}).items():
            tally[pair] += count

    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    if tally:
        pairs = sorted(tally, key=lambda k: -tally[k])
        ax.barh(pairs[::-1], [tally[p] for p in pairs][::-1], color="#3b6ea5")
    ax.set_xlabel("occurrences (count)")
    ax.set_title("CA-ZTCF trust-state transitions across E01-E05")
    ax.grid(axis="x", alpha=0.3)
    return _finish(fig, out, _tier_note(runs))


def strategy_comparison(runs: list[RunRecord], out: Path) -> Path:
    """Per-scenario counts by strategy. Counts only, no derived rates."""
    scenarios = sorted({run.scenario_id for run in runs})
    metrics = [
        ("reauthentications (M5)", "M5"),
        ("step-ups (M6)", "M6"),
        ("state transitions (M7)", "M7"),
    ]
    fig, axes = plt.subplots(1, len(metrics), figsize=(12.5, 4.0), sharey=False)
    for axis, (title, key) in zip(axes, metrics, strict=True):
        width = 0.8 / max(1, len(STRATEGY_ORDER))
        for index, strategy in enumerate(STRATEGY_ORDER):
            values = []
            for scenario in scenarios:
                total = sum(
                    run.metrics.get("counters", {}).get(key, 0)
                    for run in runs
                    if run.scenario_id == scenario and run.strategy == strategy
                )
                values.append(total)
            axis.bar(
                [i + index * width for i in range(len(scenarios))],
                values,
                width=width,
                label=STRATEGY_LABELS[strategy],
            )
        axis.set_xticks([i + width for i in range(len(scenarios))])
        axis.set_xticklabels(scenarios, fontsize=8)
        axis.set_title(title, fontsize=9)
        axis.grid(axis="y", alpha=0.3)
    axes[0].set_ylabel("count")
    axes[-1].legend(fontsize=7)
    return _finish(fig, out, _tier_note(runs))


def transition_timeline(runs: list[RunRecord], out: Path) -> Path:
    """Decision sequence over scenario steps, for the CA-ZTCF runs."""
    fig, ax = plt.subplots(figsize=(9.0, 4.4))
    states = ["UNKNOWN", "UNTRUSTED", "SUSPICIOUS", "DEGRADED", "TRANSITIONAL", "STABLE"]
    index_of = {state: i for i, state in enumerate(states)}
    for run in runs:
        if run.strategy != "ca_ztcf" or not run.decisions:
            continue
        ys = [index_of.get(row["trust_state"], 0) for row in run.decisions]
        ax.plot(range(len(ys)), ys, marker="o", markersize=4, label=run.scenario_id, alpha=0.8)
    ax.set_yticks(range(len(states)))
    ax.set_yticklabels(states, fontsize=8)
    ax.set_xlabel("decision index within the run")
    ax.set_title("CA-ZTCF trust state across each scenario")
    ax.legend(fontsize=7, ncol=5)
    ax.grid(alpha=0.3)
    return _finish(fig, out, _tier_note(runs))


def resource_usage(runs: list[RunRecord], out: Path) -> Path | None:
    """Container CPU and memory, when resource sampling was enabled."""
    samples: dict[str, list[float]] = defaultdict(list)
    for run in runs:
        for metric_id, key in (("M10", "cpu"), ("M11", "mem")):
            values = run.metrics.get("distributions", {}).get(metric_id, {})
            median = values.get("median")
            if median is not None:
                samples[key].append(float(median))
    if not samples:
        return None

    fig, ax = plt.subplots(figsize=(6.5, 4.0))
    labels = [k for k in ("cpu", "mem") if samples.get(k)]
    ax.boxplot(
        [samples[k] for k in labels],
        tick_labels=[
            "ca-ztcf-core CPU (%)" if k == "cpu" else "ca-ztcf-core memory (MiB)" for k in labels
        ],
    )
    ax.set_title("Container resource usage (docker stats, 1 s sampling)")
    ax.grid(axis="y", alpha=0.3)
    return _finish(
        fig,
        out,
        "Containers only; the host-side device agent is not measured. " + _tier_note(runs),
    )


def generate_all(results_root: Path) -> list[Path]:
    runs = load_runs(results_root)
    figures = results_root / "figures"
    produced: list[Path] = [
        decision_latency_distribution(runs, figures / "decision_latency.png"),
        policy_action_distribution(runs, figures / "policy_actions.png"),
        trust_state_transitions(runs, figures / "trust_state_transitions.png"),
        strategy_comparison(runs, figures / "strategy_comparison.png"),
        transition_timeline(runs, figures / "transition_timeline.png"),
    ]
    resources = resource_usage(runs, figures / "resource_usage.png")
    if resources is not None:
        produced.append(resources)
    return produced


__all__ = ["BANNER", "generate_all"]
