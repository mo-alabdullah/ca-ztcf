#!/usr/bin/env python3
"""Run one scenario against one or more strategies.

Output is TIER-1 DEVELOPMENT VALIDATION and is written under results/dev/.
It is not final thesis experimental evidence.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from experiments.runner.controller import run_scenario  # noqa: E402
from experiments.schemas.scenario import load_scenario  # noqa: E402

ALL_STRATEGIES = ["ca_ztcf", "independent", "static_continuity"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", help="scenario id (E01) or path to a YAML file")
    parser.add_argument("--strategy", action="append", help="strategy name; repeatable")
    parser.add_argument("--config-dir", default=str(REPO / "config"))
    parser.add_argument("--out", default=str(REPO / "results" / "dev"))
    parser.add_argument("--resources", action="store_true", help="sample container resources")
    args = parser.parse_args()

    path = Path(args.scenario)
    if not path.is_file():
        path = REPO / "experiments" / "scenarios" / f"{args.scenario}.yaml"
    if not path.is_file():
        print(f"error: scenario not found: {args.scenario}", file=sys.stderr)
        return 2

    scenario = load_scenario(path)
    strategies = args.strategy or scenario.strategies(ALL_STRATEGIES)
    output_root = Path(args.out)

    print(f"{scenario.scenario_id}  {scenario.name}")
    print(
        f"  tier={scenario.measurement_tier.value} seed={scenario.seed} "
        f"devices={scenario.device_count} steps={len(scenario.event_sequence)}"
    )

    failures = 0
    for strategy in strategies:
        result, _written = run_scenario(
            scenario,
            strategy,
            config_dir=Path(args.config_dir),
            output_root=output_root,
            sample_resources=args.resources,
        )
        confusion = result.metrics.get("confusion_raw", {})
        actions = result.metrics.get("policy_action_distribution", {})
        status = "ok" if result.ok else "ERRORS"
        print(f"  [{status}] {strategy:<18} run_id={result.run_id}")
        print(f"      actions={actions}")
        print(f"      confusion_raw={confusion}")
        if result.errors:
            failures += 1
            for error in result.errors:
                print(f"      error: {error}", file=sys.stderr)

    print(f"\nraw output under {output_root}/raw/")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
