#!/usr/bin/env python3
"""Execute the frozen CA-ZTCF final experiment campaign.

Everything this script does is fixed by ``docs/experiments/final_experiment_protocol.md``
before any run happens. It exists as a separate entry point from
``run_matrix.py`` so that a final run cannot be produced by accident with
development settings.

Properties that matter for the integrity of the result:

**Every attempt is recorded.** ``results/final/run_ledger.csv`` gains a row per
attempt, valid or not, before and after execution. Nothing is deleted, so a run
cannot disappear because its outcome was inconvenient.

**Restartable.** The ledger is the state. A rerun skips any (scenario, strategy,
seed, condition) already recorded VALID and continues, so an interrupted campaign
resumes rather than starting again or duplicating.

**One frozen configuration.** The git SHA and the configuration hash are checked
before the first run and after every run. If either changes the campaign stops:
results from two configurations must never share a primary dataset.

**Infrastructure failure is not a result.** A run that fails for a reason outside
the scenario is recorded INVALID_INFRASTRUCTURE_RUN, preserved, and retried with
the SAME seed. It is never replaced by a different seed and never silently
dropped.

**Bounded.** Every run has a wall-clock timeout. Nothing polls without a bound.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

import yaml  # noqa: E402
from experiments.runner.access_sources import build_access_source  # noqa: E402
from experiments.runner.controller import run_scenario  # noqa: E402
from experiments.schemas.scenario import Scenario, load_scenarios  # noqa: E402

from ca_ztcf.config import load_settings  # noqa: E402
from ca_ztcf.version import __version__  # noqa: E402

PRIMARY_STRATEGIES = ("independent", "static_continuity", "ca_ztcf")
"""A, B300, C. The order is the protocol's; it carries no ranking."""

SENSITIVITY_STRATEGIES = ("static_continuity_ttl30", "static_continuity_ttl1800")
"""B30 and B1800. B300 is already in the primary set and is not repeated."""

SENSITIVITY_SCENARIOS = (
    "E03",
    "E04",
    "E05",
    "E06",
    "E07",
    "E08",
    "E09",
    "E10",
    "E15",
)
"""Scenarios where a session-token lifetime can change the outcome.

Every one of them either crosses an access domain, presents evidence whose age
matters, or mixes legitimate and adversarial traffic. A steady single-domain
scenario (E01, E02) cannot distinguish token lifetimes, and the cost scenarios
(E11-E14) measure cost at a fixed condition rather than the trust decision that a
lifetime changes.
"""

E13_DEVICE_LEVELS = (1, 5, 10, 25)
"""Validated logical-device levels. 50 and 100 are declared but unvalidated."""

LEDGER_FIELDS = [
    "attempt_id",
    "run_id",
    "scenario",
    "strategy",
    "seed",
    "condition",
    "campaign",
    "start",
    "end",
    "duration_s",
    "status",
    "validity",
    "reason",
    "git_sha",
    "config_hash",
    "result_path",
]

STATUS_VALID = "VALID"
STATUS_INFRA = "INVALID_INFRASTRUCTURE_RUN"
STATUS_DEFECT = "INVALID_SOFTWARE_DEFECT"
STATUS_ABORTED = "ABORTED"

# A failure whose text matches one of these came from the environment, not from
# the scenario. Anything else is treated as a possible software defect and stops
# the campaign for inspection rather than being quietly absorbed.
INFRASTRUCTURE_MARKERS = (
    "AccessSourceError",
    "not live",
    "no live",
    "Connection refused",
    "Connection reset",
    "Broken pipe",
    "No route to host",
    "Timeout",
    "TimeoutError",
    "OSError",
    "Errno",
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def git_sha() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.strip()


def git_dirty() -> bool:
    return bool(
        subprocess.run(
            ["git", "status", "--porcelain"], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip()
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class Condition:
    """One cell of the campaign matrix."""

    scenario: Scenario
    strategy: str
    seed: int
    campaign: str
    device_count: int | None = None

    @property
    def label(self) -> str:
        """Distinguishes E13's device levels, which share a scenario id."""
        return f"devices={self.device_count}" if self.device_count is not None else "default"

    @property
    def key(self) -> tuple[str, str, int, str]:
        return (self.scenario.scenario_id, self.strategy, self.seed, self.label)


@dataclass
class Ledger:
    """Append-only record of every attempt. The campaign's resume state."""

    path: Path
    rows: list[dict[str, str]] = field(default_factory=list)

    def load(self) -> Ledger:
        if self.path.is_file():
            with self.path.open(encoding="utf-8", newline="") as handle:
                self.rows = list(csv.DictReader(handle))
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("w", encoding="utf-8", newline="") as handle:
                csv.DictWriter(handle, fieldnames=LEDGER_FIELDS).writeheader()
        return self

    def append(self, row: dict[str, Any]) -> None:
        complete = {key: str(row.get(key, "")) for key in LEDGER_FIELDS}
        with self.path.open("a", encoding="utf-8", newline="") as handle:
            csv.DictWriter(handle, fieldnames=LEDGER_FIELDS).writerow(complete)
        self.rows.append(complete)

    def completed(self) -> set[tuple[str, str, int, str]]:
        """Conditions already recorded VALID, so a resume does not repeat them."""
        done: set[tuple[str, str, int, str]] = set()
        for row in self.rows:
            if row.get("status") == STATUS_VALID:
                with suppress(ValueError):
                    done.add((row["scenario"], row["strategy"], int(row["seed"]), row["condition"]))
        return done

    def attempts_for(self, key: tuple[str, str, int, str]) -> int:
        return sum(
            1
            for row in self.rows
            if (row.get("scenario"), row.get("strategy"), row.get("condition"))
            == (key[0], key[1], key[3])
            and row.get("seed") == str(key[2])
        )

    def counts(self) -> dict[str, int]:
        tally: dict[str, int] = {}
        for row in self.rows:
            tally[row.get("status", "?")] = tally.get(row.get("status", "?"), 0) + 1
        return tally


def classify_failure(errors: list[str]) -> tuple[str, str]:
    """Infrastructure failure, or possible software defect."""
    text = " | ".join(errors)
    for marker in INFRASTRUCTURE_MARKERS:
        if marker in text:
            return STATUS_INFRA, text[:400]
    return STATUS_DEFECT, text[:400]


def build_conditions(
    scenarios: list[Scenario], strategies: tuple[str, ...], seeds: list[int], campaign: str
) -> list[Condition]:
    conditions: list[Condition] = []
    for scenario in scenarios:
        # E13 is the only scenario executed at several device levels; the level is
        # a campaign parameter, not a change to what the scenario means.
        levels: list[int | None] = (
            list(E13_DEVICE_LEVELS) if scenario.scenario_id == "E13" else [None]
        )
        for level in levels:
            for strategy in strategies:
                for seed in seeds:
                    conditions.append(
                        Condition(
                            scenario=scenario,
                            strategy=strategy,
                            seed=seed,
                            campaign=campaign,
                            device_count=level,
                        )
                    )
    return conditions


def execute(
    condition: Condition,
    *,
    config_dir: Path,
    output_root: Path,
    access_source_kind: str,
    sample_resources: bool,
) -> tuple[Any, str, str]:
    """Run one condition. Returns (result, status, reason)."""
    scenario = condition.scenario
    if condition.device_count is not None:
        # The scenario is unchanged; the device count is a campaign parameter and
        # is recorded as such in the run metadata.
        scenario = scenario.model_copy(update={"device_count": condition.device_count})

    source = build_access_source(
        access_source_kind,
        nr_address_prefix=scenario.setup.nr_address_prefix,
        wlan_address_prefix=scenario.setup.wlan_address_prefix,
        address_offset=scenario.setup.address_offset,
        address_stride=scenario.setup.address_stride,
    )
    result, _ = run_scenario(
        scenario,
        condition.strategy,
        config_dir=config_dir,
        output_root=output_root,
        sample_resources=sample_resources,
        access_source=source,
        seed=condition.seed,
        result_class="final",
    )
    if result.ok:
        return result, STATUS_VALID, ""
    status, reason = classify_failure(result.errors)
    return result, status, reason


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", choices=["primary", "sensitivity"], default="primary")
    parser.add_argument("--scenarios-dir", default=str(REPO / "experiments" / "scenarios"))
    parser.add_argument("--config-dir", default=str(REPO / "config"))
    parser.add_argument("--seeds", default=str(REPO / "experiments" / "final" / "seeds.yaml"))
    parser.add_argument("--out", default=str(REPO / "results" / "final"))
    parser.add_argument(
        "--repetitions",
        type=int,
        default=0,
        help="limit to the first N seeds; 0 uses every frozen seed",
    )
    parser.add_argument("--scenario", action="append", help="limit to these scenario ids")
    parser.add_argument("--run-timeout-s", type=float, default=600.0)
    parser.add_argument("--campaign-timeout-s", type=float, default=6 * 3600.0)
    parser.add_argument(
        "--max-retries",
        type=int,
        default=2,
        help="retries per condition after an infrastructure failure",
    )
    parser.add_argument("--no-resources", action="store_true")
    parser.add_argument("--access-source", choices=["tier1", "tier2"], default="tier2")
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="for a dry run only; a real campaign requires a clean tree",
    )
    args = parser.parse_args()

    output_root = Path(args.out)
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "logs").mkdir(exist_ok=True)

    # --- frozen configuration -------------------------------------------
    sha = git_sha()
    settings = load_settings(Path(args.config_dir))
    config_hash = settings.config_hash
    if git_dirty() and not args.allow_dirty:
        print(
            "REFUSING: the working tree is dirty. A final run must be attributable "
            "to one committed state.",
            file=sys.stderr,
        )
        return 2

    seed_doc = yaml.safe_load(Path(args.seeds).read_text(encoding="utf-8"))
    seeds = [int(s) for s in seed_doc["seeds"]]
    if args.repetitions:
        seeds = seeds[: args.repetitions]

    scenarios = load_scenarios(Path(args.scenarios_dir))
    if args.campaign == "sensitivity":
        wanted = set(SENSITIVITY_SCENARIOS)
        strategies = SENSITIVITY_STRATEGIES
    else:
        wanted = {s.scenario_id for s in scenarios}
        strategies = PRIMARY_STRATEGIES
    if args.scenario:
        wanted &= {s.upper() for s in args.scenario}
    scenarios = [s for s in scenarios if s.scenario_id in wanted]

    conditions = build_conditions(scenarios, strategies, seeds, args.campaign)

    ledger = Ledger(output_root / "run_ledger.csv").load()
    done = ledger.completed()
    pending = [c for c in conditions if c.key not in done]

    print(f"CA-ZTCF final campaign: {args.campaign}")
    print(f"  framework       v{__version__} @ {sha[:12]}")
    print(f"  config hash     {config_hash[:16]}")
    print(f"  access source   {args.access_source}")
    print(f"  scenarios       {len(scenarios)}  strategies {list(strategies)}")
    print(f"  seeds           {len(seeds)}")
    print(
        f"  conditions      {len(conditions)} total, {len(done)} already valid, "
        f"{len(pending)} pending"
    )
    if not pending:
        print("nothing to do; every condition is already recorded VALID")
        return 0

    campaign_deadline = time.monotonic() + args.campaign_timeout_s
    interrupted = False

    def on_signal(signum, _frame):
        nonlocal interrupted
        interrupted = True
        print(f"\nsignal {signum} received; finishing the current run then stopping")

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    executed = 0
    started_at = utc_now()
    try:
        for index, condition in enumerate(pending, 1):
            if interrupted:
                ledger.append(
                    {
                        "attempt_id": f"a{len(ledger.rows) + 1:06d}",
                        "run_id": "",
                        "scenario": condition.scenario.scenario_id,
                        "strategy": condition.strategy,
                        "seed": condition.seed,
                        "condition": condition.label,
                        "campaign": condition.campaign,
                        "start": utc_now(),
                        "end": utc_now(),
                        "duration_s": 0,
                        "status": STATUS_ABORTED,
                        "validity": "invalid",
                        "reason": "campaign interrupted before this condition ran",
                        "git_sha": sha,
                        "config_hash": config_hash,
                        "result_path": "",
                    }
                )
                continue
            if time.monotonic() > campaign_deadline:
                print("campaign timeout reached; remaining conditions left pending")
                break

            attempts = 0
            while attempts <= args.max_retries:
                attempts += 1
                attempt_id = f"a{len(ledger.rows) + 1:06d}"
                start_wall = utc_now()
                start = time.monotonic()
                try:
                    result, status, reason = execute(
                        condition,
                        config_dir=Path(args.config_dir),
                        output_root=output_root,
                        access_source_kind=args.access_source,
                        sample_resources=not args.no_resources,
                    )
                    run_id = result.run_id
                    result_path = f"raw/{result.run_id}"
                except Exception as exc:
                    status, reason = classify_failure([f"{type(exc).__name__}: {exc}"])
                    run_id, result_path = "", ""
                duration = time.monotonic() - start

                if duration > args.run_timeout_s and status == STATUS_VALID:
                    status = STATUS_INFRA
                    reason = f"run exceeded its {args.run_timeout_s:.0f}s budget"

                ledger.append(
                    {
                        "attempt_id": attempt_id,
                        "run_id": run_id,
                        "scenario": condition.scenario.scenario_id,
                        "strategy": condition.strategy,
                        "seed": condition.seed,
                        "condition": condition.label,
                        "campaign": condition.campaign,
                        "start": start_wall,
                        "end": utc_now(),
                        "duration_s": round(duration, 3),
                        "status": status,
                        "validity": "valid" if status == STATUS_VALID else "invalid",
                        "reason": reason,
                        "git_sha": sha,
                        "config_hash": config_hash,
                        "result_path": result_path,
                    }
                )

                if status == STATUS_VALID:
                    executed += 1
                    break
                if status == STATUS_DEFECT:
                    print(
                        f"\nSTOPPING: possible software defect in "
                        f"{condition.scenario.scenario_id}/{condition.strategy}/"
                        f"{condition.seed}: {reason}",
                        file=sys.stderr,
                    )
                    print(
                        "The failed attempt is preserved in the ledger. Fix the defect, "
                        "add a regression test, and invalidate every run affected.",
                        file=sys.stderr,
                    )
                    return 3
                print(
                    f"  [infra] {condition.scenario.scenario_id}/{condition.strategy}/"
                    f"{condition.seed} attempt {attempts}: {reason[:120]}"
                )
                time.sleep(min(5.0 * attempts, 20.0))

            # The configuration must not drift underneath the campaign.
            if git_sha() != sha or load_settings(Path(args.config_dir)).config_hash != config_hash:
                print(
                    "\nSTOPPING: git SHA or config hash changed during the campaign. "
                    "Results from two configurations must not share a dataset.",
                    file=sys.stderr,
                )
                return 4

            if index % 50 == 0 or index == len(pending):
                print(f"  {index}/{len(pending)} conditions  ({executed} valid this session)")
    finally:
        summary = {
            "campaign": args.campaign,
            "framework_version": __version__,
            "git_sha": sha,
            "config_hash": config_hash,
            "access_source": args.access_source,
            "seeds": seeds,
            "scenarios": [s.scenario_id for s in scenarios],
            "strategies": list(strategies),
            "conditions_total": len(conditions),
            "executed_this_session": executed,
            "ledger_status_counts": ledger.counts(),
            "started_at": started_at,
            "finished_at": utc_now(),
            "interrupted": interrupted,
            "pid": os.getpid(),
        }
        path = output_root / "logs" / f"campaign-{args.campaign}-{int(time.time())}.json"
        path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\nledger: {ledger.path}")
        print(f"status counts: {ledger.counts()}")
        print(f"session log: {path}")
        print(f"ledger sha256: {sha256_file(ledger.path)}")

    remaining = [c for c in conditions if c.key not in ledger.completed()]
    if remaining:
        print(f"{len(remaining)} condition(s) still pending; rerun to continue")
        return 1
    print("every condition recorded VALID")
    return 0


if __name__ == "__main__":
    sys.exit(main())
