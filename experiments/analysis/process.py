"""Turn raw run output into processed tables.

Everything is derived from files under ``results/dev/raw/``. No number is ever
typed by hand, and this module is the only path by which a raw measurement
becomes a table or a figure.

Descriptive statistics only. No inferential test, no p-value and no significance
claim is produced at this stage: the formal analysis waits on the final experiment
design once Tier 2 is operational.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TIER1_DISCLAIMER = (
    "DEVELOPMENT VALIDATION - NOT FINAL THESIS RESULT. "
    "Tier-1 only: the 5G access context is a synthetic fixture and the WLAN side "
    "is 802.1X/EAP-TLS authentication-path emulation. Not a WiFi, RF, 802.11 or "
    "5G measurement."
)

TIER2_DISCLAIMER = (
    "DEVELOPMENT VALIDATION - NOT FINAL THESIS RESULT. "
    "Tier-2 live software-based testbed: real 5G NAS/NGAP/GTP-U via Open5GS and "
    "UERANSIM, and a real IEEE 802.11 association and EAP-TLS exchange via "
    "mac80211_hwsim, over simulated radios. Not an RF, propagation, interference, "
    "channel-quality, spectrum-coexistence or physical-handover measurement."
)

MIXED_DISCLAIMER = (
    "DEVELOPMENT VALIDATION - NOT FINAL THESIS RESULT. "
    "Mixed Tier-1 and Tier-2 runs; read each run's own metadata for its "
    "provenance. No physical radio exists in either tier, so nothing here is an "
    "RF, propagation, interference, channel-quality or physical-handover "
    "measurement."
)

DEV_DISCLAIMER = TIER1_DISCLAIMER
"""Default when the tier is not known. Kept as the conservative Tier-1 wording."""


def disclaimer_for(runs: list[RunRecord]) -> str:
    """The disclaimer that matches the evidence actually present.

    A Tier-2 table labelled as a synthetic fixture would understate what the run
    was, and a Tier-1 table labelled as a live testbed would overstate it. Both are
    misrepresentations, so the wording follows the runs rather than a constant.
    """
    tiers = {run.measurement_tier for run in runs}
    if not tiers:
        return DEV_DISCLAIMER
    if tiers == {"tier2"}:
        return TIER2_DISCLAIMER
    if tiers == {"tier1"}:
        return TIER1_DISCLAIMER
    return MIXED_DISCLAIMER


@dataclass
class RunRecord:
    """One run, loaded from disk."""

    run_id: str
    scenario_id: str
    strategy: str
    seed: int
    measurement_tier: str
    metrics: dict[str, Any]
    metadata: dict[str, Any]
    decisions: list[dict[str, Any]]
    events: list[dict[str, Any]]

    @property
    def source_modes(self) -> set[str]:
        return {str(event["source_mode"]) for event in self.events if event.get("source_mode")}


def scrub(value: str) -> str:
    """Replace the user's home directory with "~" in a path written to disk."""
    home = str(Path.home())
    return value.replace(home, "~") if home and home != "/" else value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped:
            rows.append(json.loads(stripped))
    return rows


def load_runs(results_root: Path) -> list[RunRecord]:
    """Load every run under ``<results_root>/raw/``."""
    raw_root = results_root / "raw"
    metadata_root = results_root / "metadata"
    runs: list[RunRecord] = []
    if not raw_root.is_dir():
        return runs

    for run_dir in sorted(raw_root.iterdir()):
        if not run_dir.is_dir():
            continue
        metrics_path = run_dir / "metrics.json"
        if not metrics_path.is_file():
            continue
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        metadata_path = metadata_root / f"{run_dir.name}.json"
        metadata = (
            json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.is_file() else {}
        )
        runs.append(
            RunRecord(
                run_id=run_dir.name,
                scenario_id=str(metrics.get("scenario_id", "")),
                strategy=str(metrics.get("strategy", "")),
                seed=int(metrics.get("seed", 0)),
                measurement_tier=str(metrics.get("measurement_tier", "tier1")),
                metrics=metrics,
                metadata=metadata,
                decisions=_read_jsonl(run_dir / "decisions.jsonl"),
                events=_read_jsonl(run_dir / "events.jsonl"),
            )
        )
    return runs


def summary_rows(runs: list[RunRecord]) -> list[dict[str, Any]]:
    """One row per run: counts and descriptive latency statistics."""
    rows: list[dict[str, Any]] = []
    for run in runs:
        confusion = run.metrics.get("confusion_raw", {})
        distributions = run.metrics.get("distributions", {})
        decision_latency = distributions.get("M3", {})
        engine_time = distributions.get("M12", {})
        counters = run.metrics.get("counters", {})
        rows.append(
            {
                "run_id": run.run_id,
                "scenario_id": run.scenario_id,
                "strategy": run.strategy,
                "seed": run.seed,
                "measurement_tier": run.measurement_tier,
                "decisions": len(run.decisions),
                "decision_latency_ms_median": decision_latency.get("median"),
                "decision_latency_ms_iqr": decision_latency.get("iqr"),
                "decision_latency_ms_p95": decision_latency.get("p95"),
                "decision_latency_ms_min": decision_latency.get("min"),
                "decision_latency_ms_max": decision_latency.get("max"),
                "engine_time_us_median": engine_time.get("median"),
                "reauthentications_M5": counters.get("M5", 0),
                "step_ups_M6": counters.get("M6", 0),
                "state_transitions_M7": counters.get("M7", 0),
                "messages_M8": counters.get("M8", 0),
                "legitimate_transitions_M13": counters.get("M13", 0),
                "denied_restricted_M14": counters.get("M14", 0),
                "false_acceptance_M15": confusion.get("false_acceptance", 0),
                "false_rejection_M16": confusion.get("false_rejection", 0),
                "correct_acceptance": confusion.get("correct_acceptance", 0),
                "correct_rejection": confusion.get("correct_rejection", 0),
                "legitimate_total": confusion.get("legitimate_total", 0),
                "illegitimate_total": confusion.get("illegitimate_total", 0),
                "labelled_total": confusion.get("labelled_total", 0),
                "config_hash": run.metadata.get("config_hash"),
                "git_commit": (run.metadata.get("git") or {}).get("commit_sha"),
                "source_modes": ";".join(sorted(run.source_modes)),
                "result_class": run.metadata.get("result_class", "development_validation"),
            }
        )
    return rows


def action_rows(runs: list[RunRecord]) -> list[dict[str, Any]]:
    """Policy action distribution, one row per run and action."""
    rows: list[dict[str, Any]] = []
    for run in runs:
        for action, count in sorted(run.metrics.get("policy_action_distribution", {}).items()):
            rows.append(
                {
                    "run_id": run.run_id,
                    "scenario_id": run.scenario_id,
                    "strategy": run.strategy,
                    "action": action,
                    "count": count,
                }
            )
    return rows


def state_transition_rows(runs: list[RunRecord]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run in runs:
        for pair, count in sorted(run.metrics.get("trust_state_transitions", {}).items()):
            source, _, target = pair.partition("->")
            rows.append(
                {
                    "run_id": run.run_id,
                    "scenario_id": run.scenario_id,
                    "strategy": run.strategy,
                    "from_state": source,
                    "to_state": target,
                    "count": count,
                }
            )
    return rows


def confusion_rows(runs: list[RunRecord]) -> list[dict[str, Any]]:
    """Raw confusion counts with their denominators, never ratios alone."""
    rows: list[dict[str, Any]] = []
    for run in runs:
        confusion = run.metrics.get("confusion_raw", {})
        rows.append(
            {
                "run_id": run.run_id,
                "scenario_id": run.scenario_id,
                "strategy": run.strategy,
                "correct_acceptance": confusion.get("correct_acceptance", 0),
                "false_rejection": confusion.get("false_rejection", 0),
                "correct_rejection": confusion.get("correct_rejection", 0),
                "false_acceptance": confusion.get("false_acceptance", 0),
                "legitimate_total": confusion.get("legitimate_total", 0),
                "illegitimate_total": confusion.get("illegitimate_total", 0),
                "labelled_total": confusion.get("labelled_total", 0),
                "note": ("raw counts only; any ratio must be reported with these denominators"),
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]], disclaimer: str = DEV_DISCLAIMER) -> Path:
    """Write rows as CSV, with the development disclaimer as a leading comment."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text(f"# {disclaimer}\n", encoding="utf-8")
        return path
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(f"# {disclaimer}\n")
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


def process(results_root: Path) -> dict[str, Path]:
    """Generate every processed table from raw output."""
    runs = load_runs(results_root)
    disclaimer = disclaimer_for(runs)
    processed = results_root / "processed"
    outputs = {
        "summary": write_csv(processed / "run_summary.csv", summary_rows(runs), disclaimer),
        "actions": write_csv(processed / "policy_actions.csv", action_rows(runs), disclaimer),
        "transitions": write_csv(
            processed / "trust_state_transitions.csv", state_transition_rows(runs), disclaimer
        ),
        "confusion": write_csv(processed / "confusion_raw.csv", confusion_rows(runs), disclaimer),
    }
    index = processed / "index.json"
    index.write_text(
        json.dumps(
            {
                "disclaimer": disclaimer,
                "run_count": len(runs),
                "runs": [r.run_id for r in runs],
                "source_modes_observed": sorted(
                    {mode for run in runs for mode in run.source_modes}
                ),
                "outputs": {k: scrub(str(v)) for k, v in outputs.items()},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    outputs["index"] = index
    return outputs


__all__ = [
    "DEV_DISCLAIMER",
    "MIXED_DISCLAIMER",
    "TIER1_DISCLAIMER",
    "TIER2_DISCLAIMER",
    "RunRecord",
    "action_rows",
    "confusion_rows",
    "disclaimer_for",
    "load_runs",
    "process",
    "state_transition_rows",
    "summary_rows",
    "write_csv",
]
