#!/usr/bin/env python3
"""Run every scenario against every strategy.

Output is DEVELOPMENT VALIDATION and is written under results/dev/. It is not
final thesis experimental evidence.

``--access-source tier1`` (default) uses the synthetic 5G fixture and the WLAN
authentication-path emulation. ``--access-source tier2`` reads evidence from the
live software-based testbed instead, and fails the run rather than falling back to
a fixture if the testbed cannot supply a device's access path.
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

from experiments.runner.access_sources import build_access_source  # noqa: E402
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
    parser.add_argument("--access-source", choices=["tier1", "tier2"], default="tier1")
    parser.add_argument(
        "--repetitions",
        type=int,
        default=1,
        help="repetitions per scenario-strategy pair; each uses seed + repetition",
    )
    parser.add_argument("--scenario", action="append", help="limit to these scenario ids")
    args = parser.parse_args()

    scenarios = load_scenarios(Path(args.scenarios_dir))
    if args.scenario:
        wanted = {s.upper() for s in args.scenario}
        scenarios = [s for s in scenarios if s.scenario_id.upper() in wanted]
    output_root = Path(args.out)
    index: list[dict[str, object]] = []
    failures = 0

    # The access source is built once. On Tier 2 that snapshots the live testbed,
    # so a run cannot silently straddle two different states of it.
    def make_source(scenario):
        return build_access_source(
            args.access_source,
            nr_address_prefix=scenario.setup.nr_address_prefix,
            wlan_address_prefix=scenario.setup.wlan_address_prefix,
            address_offset=scenario.setup.address_offset,
            address_stride=scenario.setup.address_stride,
        )

    shared_source = make_source(scenarios[0]) if args.access_source == "tier2" else None

    print(
        f"running {len(scenarios)} scenario(s) x strategies x {args.repetitions} "
        f"repetition(s) from {args.access_source} -> {output_root}"
    )
    for scenario in scenarios:
        strategies = args.strategy or scenario.strategies(ALL_STRATEGIES)
        for strategy in strategies:
            for repetition in range(args.repetitions):
                source = shared_source or make_source(scenario)
                result, _ = run_scenario(
                    scenario,
                    strategy,
                    config_dir=Path(args.config_dir),
                    output_root=output_root,
                    sample_resources=args.resources,
                    access_source=source,
                    repetition=repetition,
                )
                index.append(
                    {
                        "run_id": result.run_id,
                        "scenario_id": result.scenario_id,
                        "strategy": result.strategy,
                        "seed": result.seed,
                        "repetition": repetition,
                        "access_source": args.access_source,
                        "measurement_tier": result.metadata.get("measurement_tier"),
                        "ok": result.ok,
                        "errors": result.errors,
                        "policy_action_distribution": result.metrics.get(
                            "policy_action_distribution", {}
                        ),
                        "confusion_raw": result.metrics.get("confusion_raw", {}),
                    }
                )
                marker = "ok " if result.ok else "ERR"
                print(
                    f"  [{marker}] {scenario.scenario_id} {strategy:<18} "
                    f"r{repetition} {result.run_id}"
                )
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
                "access_source": args.access_source,
                "repetitions": args.repetitions,
                "disclaimer": (
                    "Tier-2 development validation on the live software-based "
                    "testbed. Real 5G NAS/NGAP/GTP-U and a real 802.11/EAP-TLS "
                    "stack over simulated radios. Not an RF, propagation, "
                    "interference, channel-quality or physical-handover "
                    "measurement, and not final thesis experimental evidence."
                    if args.access_source == "tier2"
                    else "Tier-1 development validation. Not a WiFi, RF, 802.11 or "
                    "5G measurement, and not final thesis experimental evidence."
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
