#!/usr/bin/env python3
"""Regenerate every final artefact from results/final/raw/.

Processed data, statistics, tables, figures, findings, non-findings and the
limitations record all come from the raw runs the ledger names. No research value
is typed by hand, so the whole set can be deleted and rebuilt.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from experiments.analysis import final_figures, final_findings, final_tables  # noqa: E402
from experiments.analysis.final_report import (  # noqa: E402
    build_processed,
    build_statistics,
    load_final_runs,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default=str(REPO / "results" / "final"))
    parser.add_argument("--no-figures", action="store_true")
    args = parser.parse_args()
    root = Path(args.results).resolve()

    runs = load_final_runs(root)
    print(f"loaded {len(runs)} valid run(s) from {root}")
    if not runs:
        print("no runs to process", file=sys.stderr)
        return 1

    for name, path in build_processed(runs, root).items():
        print(f"  processed   {name:<12} {path.name}")

    statistics = build_statistics(runs, root)
    print(
        f"  statistics  {len(statistics['continuous'])} continuous comparison(s), "
        f"{len(statistics['security'])} security scenario(s), "
        f"{len(statistics['sensitivity'])} sensitivity scenario(s)"
    )

    for path in final_tables.generate_all(runs, root):
        print(f"  table       {path.name}")

    for path in final_findings.generate_all(runs, statistics, root):
        print(f"  finding     {path.name}")

    if not args.no_figures:
        try:
            for path in final_figures.generate_all(runs, statistics, root):
                print(f"  figure      {path.name}")
        except ImportError as exc:
            print(f"figures skipped (matplotlib unavailable): {exc}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
