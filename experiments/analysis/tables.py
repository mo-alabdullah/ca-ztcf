"""Development tables, generated from processed CSV.

Markdown tables for review. Every one carries the development banner, and every
ratio is written next to the raw counts it came from.
"""

from __future__ import annotations

import csv
from pathlib import Path

from experiments.analysis.process import disclaimer_for, load_runs

BANNER = "**DEVELOPMENT VALIDATION - NOT FINAL THESIS RESULT**"


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    lines = [
        line for line in path.read_text(encoding="utf-8").splitlines() if not line.startswith("#")
    ]
    return list(csv.DictReader(lines))


def _fmt(value: str | None, digits: int = 3) -> str:
    if value in (None, "", "None"):
        return "-"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def _table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(out)


def run_summary_table(results_root: Path) -> str:
    rows = _read_csv(results_root / "processed" / "run_summary.csv")
    body = [
        [
            r["scenario_id"],
            r["strategy"],
            r["decisions"],
            _fmt(r["decision_latency_ms_median"]),
            _fmt(r["decision_latency_ms_iqr"]),
            _fmt(r["decision_latency_ms_p95"]),
            _fmt(r["engine_time_us_median"], 1),
            r["reauthentications_M5"],
            r["step_ups_M6"],
            r["state_transitions_M7"],
        ]
        for r in sorted(rows, key=lambda x: (x["scenario_id"], x["strategy"]))
    ]
    return _table(
        [
            "scenario",
            "strategy",
            "decisions",
            "latency median (ms)",
            "IQR (ms)",
            "p95 (ms)",
            "engine median (us)",
            "reauth M5",
            "step-up M6",
            "state trans. M7",
        ],
        body,
    )


def confusion_table(results_root: Path) -> str:
    rows = _read_csv(results_root / "processed" / "confusion_raw.csv")
    body = [
        [
            r["scenario_id"],
            r["strategy"],
            r["correct_acceptance"],
            r["false_rejection"],
            r["correct_rejection"],
            r["false_acceptance"],
            r["legitimate_total"],
            r["illegitimate_total"],
        ]
        for r in sorted(rows, key=lambda x: (x["scenario_id"], x["strategy"]))
    ]
    return _table(
        [
            "scenario",
            "strategy",
            "correct accept",
            "false reject (M16)",
            "correct reject",
            "false accept (M15)",
            "legitimate n",
            "illegitimate n",
        ],
        body,
    )


def action_table(results_root: Path) -> str:
    rows = _read_csv(results_root / "processed" / "policy_actions.csv")
    actions = sorted({r["action"] for r in rows})
    keys = sorted({(r["scenario_id"], r["strategy"]) for r in rows})
    body = []
    for scenario, strategy in keys:
        counts = {
            r["action"]: r["count"]
            for r in rows
            if r["scenario_id"] == scenario and r["strategy"] == strategy
        }
        body.append([scenario, strategy, *[counts.get(a, "0") for a in actions]])
    return _table(["scenario", "strategy", *actions], body)


def generate_all(results_root: Path) -> list[Path]:
    tables_dir = results_root / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    header = (
        f"{BANNER}\n\n"
        f"> {disclaimer_for(load_runs(results_root))}\n>\n"
        "> Generated automatically from `results/dev/raw/` by\n"
        "> `scripts/process_results.py`. No value here was typed by hand.\n"
        "> Descriptive statistics only: no inferential test has been performed and\n"
        "> no statistical significance is claimed.\n\n"
    )

    produced: list[Path] = []
    for name, title, builder in [
        ("run_summary.md", "Run summary", run_summary_table),
        ("confusion_raw.md", "Raw acceptance and rejection counts", confusion_table),
        ("policy_actions.md", "Policy action distribution", action_table),
    ]:
        path = tables_dir / name
        path.write_text(f"# {title}\n\n{header}{builder(results_root)}\n", encoding="utf-8")
        produced.append(path)
    return produced


__all__ = ["BANNER", "generate_all"]
