"""Final figures, drawn from the raw runs.

Kept to the set a thesis chapter can actually use. Every caption states what the
testbed is, because a figure travels away from its surrounding text and the
qualification has to travel with it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from experiments.analysis.final_report import (
    ADVERSARIAL_SCENARIOS,
    E13_LEVELS,
    LABELS,
    PRIMARY,
    TRANSITION_SCENARIOS,
    FinalRun,
)
from experiments.analysis.statistics import describe

CAPTION = (
    "Tier-2 software-based testbed (Open5GS + UERANSIM; mac80211_hwsim). "
    "Simulated radios: not an RF, interference or physical-handover measurement."
)
COLOURS = {"independent": "#4C72B0", "static_continuity": "#DD8452", "ca_ztcf": "#55A868"}
SHORT = {"independent": "A", "static_continuity": "B300", "ca_ztcf": "C"}


def _finish(fig, ax_or_axes, path: Path, caption: str = CAPTION) -> Path:  # noqa: ANN001
    fig.text(0.5, 0.005, caption, ha="center", fontsize=6.5, style="italic", wrap=True)
    fig.tight_layout(rect=(0, 0.045, 1, 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def _series(
    runs: list[FinalRun], scenario: str, strategy: str, metric: str, condition: str = "default"
) -> list[float]:
    return [
        r.metrics[metric]
        for r in runs
        if (r.campaign, r.scenario, r.strategy, r.condition)
        == ("primary", scenario, strategy, condition)
        and r.metrics.get(metric) is not None
    ]


def decision_latency(runs: list[FinalRun], out: Path) -> Path:
    scenarios = sorted({r.scenario for r in runs if r.campaign == "primary"})
    fig, ax = plt.subplots(figsize=(9, 4.2))
    width = 0.26
    for index, strategy in enumerate(PRIMARY):
        positions, medians, errs = [], [], []
        for s_index, scenario in enumerate(scenarios):
            condition = "devices=25" if scenario == "E13" else "default"
            values = _series(runs, scenario, strategy, "decision_latency_ms_median", condition)
            if not values:
                continue
            d = describe(values)
            positions.append(s_index + (index - 1) * width)
            medians.append(d["median"])
            errs.append(max(0.0, d["p95"] - d["median"]))
        ax.bar(
            positions,
            medians,
            width,
            yerr=errs,
            capsize=2,
            label=LABELS[strategy],
            color=COLOURS[strategy],
            alpha=0.9,
        )
    ax.set_xticks(range(len(scenarios)))
    ax.set_xticklabels(scenarios, fontsize=8)
    ax.set_ylabel("Decision latency (ms)")
    ax.set_title("Per-run median decision latency, error bar to p95 (n = 30 runs)")
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    return _finish(fig, ax, out / "fig05_decision_latency.png")


def transition_latency(runs: list[FinalRun], out: Path) -> Path:
    fig, ax = plt.subplots(figsize=(8, 4.2))
    data, labels, colours = [], [], []
    for scenario in TRANSITION_SCENARIOS:
        for strategy in PRIMARY:
            values = _series(runs, scenario, strategy, "transition_ms_median")
            if values:
                data.append(values)
                labels.append(f"{scenario}\n{SHORT[strategy]}")
                colours.append(COLOURS[strategy])
    if not data:
        ax.text(0.5, 0.5, "no transition duration recorded", ha="center")
        return _finish(fig, ax, out / "fig06_transition_latency.png")
    box = ax.boxplot(data, patch_artist=True, showfliers=False)
    for patch, colour in zip(box["boxes"], colours, strict=True):
        patch.set_facecolor(colour)
        patch.set_alpha(0.75)
    ax.set_xticklabels(labels, fontsize=7)
    ax.set_ylabel("Transition duration (ms)")
    ax.set_title("Transition duration per run, by scenario and strategy")
    ax.grid(axis="y", alpha=0.3)
    return _finish(fig, ax, out / "fig06_transition_latency.png")


def authentication_actions(runs: list[FinalRun], out: Path) -> Path:
    scenarios = sorted({r.scenario for r in runs if r.campaign == "primary"})
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for ax, metric, title in (
        (axes[0], "reauthentications", "Full re-authentications"),
        (axes[1], "step_ups", "Step-up authentications"),
    ):
        width = 0.26
        for index, strategy in enumerate(PRIMARY):
            totals = []
            for scenario in scenarios:
                condition = "devices=25" if scenario == "E13" else "default"
                totals.append(sum(_series(runs, scenario, strategy, metric, condition)))
            ax.bar(
                [i + (index - 1) * width for i in range(len(scenarios))],
                totals,
                width,
                label=LABELS[strategy],
                color=COLOURS[strategy],
                alpha=0.9,
            )
        ax.set_xticks(range(len(scenarios)))
        ax.set_xticklabels(scenarios, fontsize=7, rotation=45)
        ax.set_ylabel("count over 30 runs")
        ax.set_title(title, fontsize=10)
        ax.grid(axis="y", alpha=0.3)
    axes[0].legend(fontsize=8)
    return _finish(fig, axes, out / "fig07_authentication_actions.png")


def policy_actions(runs: list[FinalRun], out: Path) -> Path:
    from collections import Counter

    order = [
        "ALLOW",
        "ALLOW_WITH_RESTRICTIONS",
        "STEP_UP_AUTHENTICATION",
        "REAUTHENTICATE",
        "QUARANTINE",
        "DENY",
    ]
    fig, ax = plt.subplots(figsize=(8.5, 4))
    bottoms = [0.0] * len(PRIMARY)
    palette = plt.get_cmap("viridis")
    for index, action in enumerate(order):
        counts = []
        for strategy in PRIMARY:
            tally: Counter = Counter()
            for run in runs:
                if run.campaign == "primary" and run.strategy == strategy:
                    tally.update(run.actions)
            counts.append(float(tally.get(action, 0)))
        ax.bar(
            [LABELS[s] for s in PRIMARY],
            counts,
            bottom=bottoms,
            label=action,
            color=palette(index / max(1, len(order) - 1)),
        )
        bottoms = [b + c for b, c in zip(bottoms, counts, strict=True)]
    ax.set_ylabel("decisions across the primary campaign")
    ax.set_title("Policy action distribution")
    ax.legend(fontsize=7, ncol=2)
    ax.grid(axis="y", alpha=0.3)
    return _finish(fig, ax, out / "fig08_policy_actions.png")


def confusion_matrices(runs: list[FinalRun], out: Path) -> Path:
    from collections import Counter

    fig, axes = plt.subplots(1, len(PRIMARY), figsize=(11, 3.6))
    for ax, strategy in zip(axes, PRIMARY, strict=True):
        tally: Counter = Counter()
        for run in runs:
            if (run.campaign, run.scenario, run.strategy) == ("primary", "E15", strategy):
                tally.update({k: v for k, v in run.confusion.items() if isinstance(v, int)})
        matrix = [
            [tally.get("true_positive", 0), tally.get("false_negative", 0)],
            [tally.get("false_positive", 0), tally.get("true_negative", 0)],
        ]
        ax.imshow(matrix, cmap="Blues", vmin=0)
        for i in range(2):
            for j in range(2):
                ax.text(j, i, str(matrix[i][j]), ha="center", va="center", fontsize=12)
        ax.set_xticks([0, 1])
        ax.set_xticklabels(["rejected", "permitted"], fontsize=8)
        ax.set_yticks([0, 1])
        ax.set_yticklabels(["adversarial", "legitimate"], fontsize=8)
        ax.set_title(LABELS[strategy], fontsize=9)
    fig.suptitle("E15 mixed workload: raw counts over 30 runs", fontsize=11)
    return _finish(fig, axes, out / "fig09_e15_confusion.png")


def scalability(runs: list[FinalRun], out: Path) -> Path:
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.8))
    for ax, metric, ylabel in (
        (axes[0], "decision_latency_ms_median", "Decision latency median (ms)"),
        (axes[1], "cpu_seconds", "CPU seconds per run"),
        (axes[2], "memory_mib_peak", "Peak resident memory (MiB)"),
    ):
        for strategy in PRIMARY:
            medians = []
            for level in E13_LEVELS:
                values = [
                    r.metrics[metric]
                    for r in runs
                    if r.campaign == "primary"
                    and r.scenario == "E13"
                    and r.strategy == strategy
                    and r.device_count == level
                    and r.metrics.get(metric) is not None
                ]
                medians.append(describe(values)["median"] if values else None)
            ax.plot(
                E13_LEVELS, medians, marker="o", label=LABELS[strategy], color=COLOURS[strategy]
            )
        ax.set_xlabel("logical devices")
        ax.set_ylabel(ylabel, fontsize=9)
        ax.set_xticks(E13_LEVELS)
        ax.grid(alpha=0.3)
    axes[0].legend(fontsize=8)
    fig.suptitle("E13 logical-device scalability (validated to 25; no extrapolation)", fontsize=11)
    return _finish(
        fig,
        axes,
        out / "fig10_logical_device_scalability.png",
        caption=CAPTION + " LOGICAL devices sharing one 802.11 association: not "
        "independent radio scalability.",
    )


def false_outcomes(runs: list[FinalRun], out: Path) -> Path:
    from collections import Counter

    fig, ax = plt.subplots(figsize=(9, 4))
    width = 0.26
    for index, strategy in enumerate(PRIMARY):
        fa, fr = [], []
        for scenario in ADVERSARIAL_SCENARIOS:
            tally: Counter = Counter()
            for run in runs:
                if (run.campaign, run.scenario, run.strategy) == ("primary", scenario, strategy):
                    tally.update({k: v for k, v in run.confusion.items() if isinstance(v, int)})
            fa.append(tally.get("false_acceptance", 0))
            fr.append(-tally.get("false_rejection", 0))
        positions = [i + (index - 1) * width for i in range(len(ADVERSARIAL_SCENARIOS))]
        ax.bar(
            positions,
            fa,
            width,
            color=COLOURS[strategy],
            alpha=0.95,
            label=f"{LABELS[strategy]} false acceptance",
        )
        ax.bar(
            positions,
            fr,
            width,
            color=COLOURS[strategy],
            alpha=0.45,
            hatch="//",
            label=f"{LABELS[strategy]} false rejection",
        )
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xticks(range(len(ADVERSARIAL_SCENARIOS)))
    ax.set_xticklabels(ADVERSARIAL_SCENARIOS)
    ax.set_ylabel("events over 30 runs\n(up: false acceptance, down: false rejection)", fontsize=9)
    ax.set_title("Raw false acceptance and false rejection counts")
    ax.legend(fontsize=6.5, ncol=3)
    ax.grid(axis="y", alpha=0.3)
    return _finish(fig, ax, out / "fig14_false_outcomes.png")


def transition_rate(runs: list[FinalRun], out: Path) -> Path:
    fig, ax = plt.subplots(figsize=(7.5, 4))
    data, labels, colours = [], [], []
    for strategy in PRIMARY:
        values = _series(runs, "E14", strategy, "decision_latency_ms_median")
        if values:
            data.append(values)
            labels.append(LABELS[strategy])
            colours.append(COLOURS[strategy])
    if data:
        box = ax.boxplot(data, patch_artist=True, showfliers=False)
        for patch, colour in zip(box["boxes"], colours, strict=True):
            patch.set_facecolor(colour)
            patch.set_alpha(0.75)
        ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylabel("Decision latency median per run (ms)")
    ax.set_title("E14: decision latency across the validated rates (1, 5, 10, 25 /s)")
    ax.grid(axis="y", alpha=0.3)
    return _finish(
        fig,
        ax,
        out / "fig13_transition_rate.png",
        caption=CAPTION + " Only validated rates are shown; no extrapolation beyond 25/s.",
    )


FIGURES = (
    decision_latency,
    transition_latency,
    authentication_actions,
    policy_actions,
    confusion_matrices,
    scalability,
    false_outcomes,
    transition_rate,
)


def generate_all(runs: list[FinalRun], statistics: dict[str, Any], root: Path) -> list[Path]:
    out = root / "figures"
    out.mkdir(parents=True, exist_ok=True)
    return [builder(runs, out) for builder in FIGURES]
