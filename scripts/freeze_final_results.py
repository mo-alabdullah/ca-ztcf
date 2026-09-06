#!/usr/bin/env python3
"""Freeze the final results: checksums and a manifest describing the campaign.

The manifest is what a reader checks a copy of these results against. It records
what was run, under which commit and configuration, with which seeds, and the
checksum of every file, so a later copy can be shown to be the same evidence
rather than merely similar.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

import yaml  # noqa: E402

from ca_ztcf.config import load_settings  # noqa: E402
from ca_ztcf.version import __version__  # noqa: E402

COVERED = ("raw", "processed", "metadata", "figures", "tables", "statistics", "logs")
EXTRA_FILES = ("run_ledger.csv",)
PROTOCOL = "docs/experiments/final_experiment_protocol.md"
SEEDS = "experiments/final/seeds.yaml"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=False
    ).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default=str(REPO / "results" / "final"))
    args = parser.parse_args()
    root = Path(args.results).resolve()
    manifests = root / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)

    files: list[Path] = []
    for name in COVERED:
        directory = root / name
        if directory.is_dir():
            files.extend(p for p in sorted(directory.rglob("*")) if p.is_file())
    files.extend(root / name for name in EXTRA_FILES if (root / name).is_file())
    for extra in (REPO / PROTOCOL, REPO / SEEDS):
        if extra.is_file():
            files.append(extra)

    lines = []
    checksums: dict[str, str] = {}
    for path in files:
        try:
            label = str(path.relative_to(root))
        except ValueError:
            label = str(path.relative_to(REPO))
        digest = sha256(path)
        checksums[label] = digest
        lines.append(f"{digest}  {label}")
    sums_path = manifests / "SHA256SUMS"
    sums_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    ledger = list(csv.DictReader((root / "run_ledger.csv").open(encoding="utf-8")))
    statuses = Counter(row["status"] for row in ledger)
    valid = [row for row in ledger if row["status"] == "VALID"]
    starts = sorted(row["start"] for row in valid)
    seeds = yaml.safe_load((REPO / SEEDS).read_text(encoding="utf-8"))
    environment_path = root / "metadata" / "environment.json"
    environment = (
        json.loads(environment_path.read_text(encoding="utf-8"))
        if environment_path.is_file()
        else {}
    )

    manifest = {
        "research_title": (
            "A Zero Trust Authentication Framework for IoT Devices in 5G/WiFi "
            "Coexistence Environments"
        ),
        "framework": "CA-ZTCF (Coexistence-Aware Zero Trust Continuity Framework)",
        "version": __version__,
        "commit_sha": git("rev-parse", "HEAD"),
        "campaign_commit_sha": sorted({row["git_sha"] for row in valid}),
        "config_hash": load_settings(REPO / "config").config_hash,
        "campaign_config_hash": sorted({row["config_hash"] for row in valid}),
        "protocol": PROTOCOL,
        "protocol_sha256": checksums.get(PROTOCOL),
        "seeds_file": SEEDS,
        "seeds": seeds["seeds"],
        "seed_rule": seeds["rule"],
        "repetitions": 30,
        "run_count_attempted": len(ledger),
        "run_count_valid": len(valid),
        "run_count_invalid": len(ledger) - len(valid),
        "status_counts": dict(statuses),
        "campaigns": dict(Counter(row["campaign"] for row in valid)),
        "date_range_utc": {"first_run": starts[0], "last_run": starts[-1]} if starts else {},
        "testbed_type": "software_based",
        "measurement_tier": "tier2",
        "environment": environment,
        "scenarios": sorted({row["scenario"] for row in valid}),
        "strategies_primary": ["independent", "static_continuity", "ca_ztcf"],
        "strategies_sensitivity": [
            "static_continuity_ttl30",
            "static_continuity_ttl1800",
        ],
        "e13_device_levels": [1, 5, 10, 25],
        "e14_transition_rates_per_s": [1.0, 5.0, 10.0, 25.0],
        "scope": {
            "supports": [
                "authentication and session behaviour",
                "access transitions",
                "trust continuity",
                "policy enforcement",
                "MQTT application continuity",
                "software and testbed latency",
                "decision latency",
                "message and byte overhead",
                "CPU and memory of the measured process",
                "controlled security scenarios",
                "logical-device scalability",
            ],
            "does_not_support": [
                "physical RF propagation",
                "physical radio handover performance",
                "interference",
                "signal strength",
                "spectrum efficiency",
                "channel-quality behaviour",
                "production mobile-network performance",
                "independent WiFi-radio association scalability",
                "logical-device counts above 25",
                "transition rates above 25 per second",
                "resource cost on a constrained IoT device",
            ],
        },
        "amendments": sorted(
            p.name for p in (REPO / "docs" / "experiments" / "amendments").glob("AMEND-*.md")
        ),
        "generated_at": datetime.now(UTC).isoformat(),
        "file_count": len(files),
        "checksums_file": "manifests/SHA256SUMS",
        "checksums_sha256": sha256(sums_path),
        "file_checksums": checksums,
    }
    manifest_path = manifests / "final_results_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(f"files covered      : {len(files)}")
    print(f"valid runs         : {len(valid)} of {len(ledger)} attempted")
    print(f"campaign commit    : {', '.join(manifest['campaign_commit_sha'])}")
    print(f"campaign config    : {', '.join(h[:16] for h in manifest['campaign_config_hash'])}")
    print(f"SHA256SUMS sha256  : {manifest['checksums_sha256']}")
    print(f"manifest sha256    : {sha256(manifest_path)}")
    print(f"manifest           : {manifest_path.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
