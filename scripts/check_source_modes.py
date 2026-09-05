#!/usr/bin/env python3
"""Source-mode and results-path safety gate.

Fails the build if Tier-1 output ever misrepresents its own provenance, or if
development output is written where final thesis results belong. These are the
mistakes that would be hardest to notice later and most damaging if they reached
the thesis, so they are checked mechanically rather than by discipline.

The gate fails when:

1. a Tier-1 WLAN authentication event claims `source_mode: live_testbed`;
2. synthetic 5G evidence claims `source_mode: live_testbed`;
3. any Tier-1 run declares a source mode outside the permitted Tier-1 set;
4. a run whose measurement tier is `tier1` is written under a final-results path;
5. a development run is missing its result-class marker or its disclaimer.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from ca_ztcf.collectors.base import SourceMode  # noqa: E402

PERMITTED_TIER1_MODES = {
    SourceMode.SYNTHETIC_FIXTURE.value,
    SourceMode.TIER1_WLAN_AUTH_EMULATION.value,
    SourceMode.REPLAY_CAPTURE.value,
    SourceMode.SERVICE_DOMAIN.value,
}
FORBIDDEN_IN_TIER1 = {SourceMode.LIVE_TESTBED.value}

FINAL_RESULT_PATHS = ("results/final", "results/thesis", "results/publication")
"""Paths reserved for Tier-2 thesis evidence. Development output must never land here."""

WLAN_EVENT_KINDS = {"wlan_session", "wlan", "eap"}
NR_EVENT_KINDS = {"nr_session", "nr"}


def _iter_jsonl(path: Path):
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped:
            try:
                yield json.loads(stripped)
            except json.JSONDecodeError:
                continue


def check_results_tree(root: Path) -> list[str]:
    failures: list[str] = []
    raw = root / "raw"
    if raw.is_dir():
        for events_file in sorted(raw.rglob("events.jsonl")):
            for event in _iter_jsonl(events_file):
                mode = event.get("source_mode")
                kind = str(event.get("kind", ""))
                rel = events_file.relative_to(root)
                if mode is None:
                    continue
                if mode in FORBIDDEN_IN_TIER1:
                    failures.append(
                        f"{rel}: event kind '{kind}' claims source_mode "
                        f"'{mode}', which is reserved for Tier-2 measurements"
                    )
                elif mode not in PERMITTED_TIER1_MODES:
                    failures.append(f"{rel}: unknown source_mode '{mode}'")
                if kind in WLAN_EVENT_KINDS and mode != (
                    SourceMode.TIER1_WLAN_AUTH_EMULATION.value
                ):
                    failures.append(
                        f"{rel}: WLAN event must be "
                        f"'{SourceMode.TIER1_WLAN_AUTH_EMULATION.value}', got '{mode}'"
                    )
                if kind in NR_EVENT_KINDS and mode != SourceMode.SYNTHETIC_FIXTURE.value:
                    failures.append(
                        f"{rel}: Tier-1 NR event must be "
                        f"'{SourceMode.SYNTHETIC_FIXTURE.value}', got '{mode}'"
                    )

    metadata = root / "metadata"
    if metadata.is_dir():
        for meta_file in sorted(metadata.glob("*.json")):
            if meta_file.name.startswith("matrix-"):
                continue
            data = json.loads(meta_file.read_text(encoding="utf-8"))
            rel = meta_file.relative_to(root)
            if data.get("measurement_tier") == "tier1":
                if data.get("result_class") != "development_validation":
                    failures.append(
                        f"{rel}: Tier-1 run must declare result_class 'development_validation'"
                    )
                if not data.get("disclaimer"):
                    failures.append(f"{rel}: Tier-1 run is missing its disclaimer")
            for mode in data.get("source_modes", []):
                if mode in FORBIDDEN_IN_TIER1:
                    failures.append(f"{rel}: run metadata claims source_mode '{mode}'")
    return failures


def check_forbidden_paths(repo: Path) -> list[str]:
    """Development output must never appear under a final-results path."""
    failures: list[str] = []
    for candidate in FINAL_RESULT_PATHS:
        path = repo / candidate
        if not path.exists():
            continue
        for meta_file in path.rglob("*.json"):
            try:
                data = json.loads(meta_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if data.get("measurement_tier") == "tier1" or (
                data.get("result_class") == "development_validation"
            ):
                failures.append(
                    f"{meta_file.relative_to(repo)}: Tier-1 development output found "
                    f"under the final-results path '{candidate}'"
                )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default=str(REPO / "results" / "dev"))
    parser.add_argument("--repo", default=str(REPO))
    args = parser.parse_args()

    root = Path(args.results)
    failures = check_results_tree(root) + check_forbidden_paths(Path(args.repo))

    if failures:
        print(f"source-mode gate: FAILED with {len(failures)} problem(s)")
        for failure in failures:
            print(f"  {failure}")
        return 1

    modes: set[str] = set()
    raw = root / "raw"
    if raw.is_dir():
        for events_file in raw.rglob("events.jsonl"):
            for event in _iter_jsonl(events_file):
                if event.get("source_mode"):
                    modes.add(str(event["source_mode"]))
    print("source-mode gate: PASSED")
    print(f"  source modes observed: {', '.join(sorted(modes)) or 'none'}")
    print("  live_testbed present : no (reserved for Tier 2)")
    print("  final-results paths  : clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
