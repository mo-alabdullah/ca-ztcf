#!/usr/bin/env python3
"""Run every scenario against every strategy.

Output is TIER-1 DEVELOPMENT VALIDATION and is written under results/dev/.
It is not final thesis experimental evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from experiments.runner.controller import run_scenario  # noqa: E402
from experiments.schemas.scenario import load_scenarios  # noqa: E402

ALL_STRATEGIES = ["ca_ztcf", "independent", "static_continuity"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenarios-dir", default=str(REPO / "experiments" / "scenarios"))
    parser.add_argument("--config-dir", default=str(REPO / "config"))
    parser.add_argument("--out", default=str(REPO / "results" / "dev"))
    parser.add_argument("--strategy", action="append")
    parser.add_argument("--resources", action="store_true")
    args = parser.parse_args()

    scenarios = load_scenarios(Path(args.scenarios_dir))
    output_root = Path(args.out)
    index: list[dict[str, object]] = []
    failures = 0

    print(f"running {len(scenarios)} scenario(s) x strategies -> {output_root}")
    for scenario in scenarios:
        strategies = args.strategy or scenario.strategies(ALL_STRATEGIES)
        for strategy in strategies:
            result, _ = run_scenario(
                scenario,
                strategy,
                config_dir=Path(args.config_dir),
                output_root=output_root,
                sample_resources=args.resources,
            )
            index.append(
                {
                    "run_id": result.run_id,
                    "scenario_id": result.scenario_id,
                    "strategy": result.strategy,
                    "seed": result.seed,
                    "measurement_tier": result.measurement_tier.value,
                    "ok": result.ok,
                    "errors": result.errors,
                    "policy_action_distribution": result.metrics.get(
                        "policy_action_distribution", {}
                    ),
                    "confusion_raw": result.metrics.get("confusion_raw", {}),
                }
            )
            marker = "ok " if result.ok else "ERR"
            print(f"  [{marker}] {scenario.scenario_id} {strategy:<18} {result.run_id}")
            if not result.ok:
                failures += 1

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    index_path = output_root / "metadata" / f"matrix-{stamp}.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "result_class": "development_validation",
                "disclaimer": (
                    "Tier-1 development validation. Not a WiFi, RF, 802.11 or 5G "
                    "measurement, and not final thesis experimental evidence."
                ),
                "runs": index,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nmatrix index: {index_path}")
    print(f"{len(index) - failures}/{len(index)} runs completed without error")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
