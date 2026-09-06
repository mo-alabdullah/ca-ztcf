#!/usr/bin/env python3
"""Check each run against the expectations its scenario declared.

The expectations are read from the scenario YAML, which was written before
anything ran. They are never derived from observed output: a checker written
against results would confirm whatever happened.

A mismatch is reported, not silently tolerated. Baselines are checked against
their own declared `strategy_specific` expectations, because the baselines are
expected to behave differently and that difference is the measurement.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from experiments.analysis.process import load_runs  # noqa: E402
from experiments.schemas.scenario import load_scenarios  # noqa: E402


def check_run(run, scenario) -> list[str]:
    problems: list[str] = []
    expected = scenario.expected_policy_behavior
    observed_actions = set(run.metrics.get("policy_action_distribution", {}))
    observed_states = set(run.metrics.get("trust_state_distribution", {}))

    override = expected.strategy_specific.get(run.strategy, {})
    must_contain = set(override.get("must_contain_actions", expected.must_contain_actions))
    must_not_contain = set(
        override.get("must_not_contain_actions", expected.must_not_contain_actions)
    )
    must_states = set(override.get("must_contain_states", expected.must_contain_states))
    must_not_states = set(override.get("must_not_contain_states", expected.must_not_contain_states))

    for action in must_contain:
        value = getattr(action, "value", action)
        if value not in observed_actions:
            problems.append(f"expected action '{value}' never occurred")
    for action in must_not_contain:
        value = getattr(action, "value", action)
        if value in observed_actions:
            problems.append(f"forbidden action '{value}' occurred")
    for state in must_states:
        value = getattr(state, "value", state)
        if value not in observed_states:
            problems.append(f"expected trust state '{value}' never occurred")
    for state in must_not_states:
        value = getattr(state, "value", state)
        if value in observed_states:
            problems.append(f"forbidden trust state '{value}' occurred")

    # A scenario is a sequence of access events and the behaviour they must
    # produce; it is not tied to one testbed. What must hold is that the run was
    # executed on a tier the scenario supports, and that the tier is recorded.
    observed_tier = run.metrics.get("measurement_tier")
    supported = {tier.value for tier in scenario.supported_tiers}
    if observed_tier not in supported:
        problems.append(
            f"measurement tier '{observed_tier}' is not one this scenario supports "
            f"({', '.join(sorted(supported))})"
        )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default=str(REPO / "results" / "dev"))
    parser.add_argument("--scenarios-dir", default=str(REPO / "experiments" / "scenarios"))
    args = parser.parse_args()

    scenarios = {s.scenario_id: s for s in load_scenarios(Path(args.scenarios_dir))}
    runs = load_runs(Path(args.results))
    if not runs:
        print("verify-expectations: no runs found", file=sys.stderr)
        return 2

    failures = 0
    for run in sorted(runs, key=lambda r: (r.scenario_id, r.strategy)):
        scenario = scenarios.get(run.scenario_id)
        if scenario is None:
            print(f"  [SKIP] {run.run_id}: no scenario definition")
            continue
        problems = check_run(run, scenario)
        if problems:
            failures += 1
            print(f"  [FAIL] {run.scenario_id} {run.strategy}")
            for problem in problems:
                print(f"         {problem}")
        else:
            print(f"  [ok  ] {run.scenario_id} {run.strategy}")

    total = len(runs)
    print(f"\nverify-expectations: {total - failures}/{total} runs matched their declaration")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
