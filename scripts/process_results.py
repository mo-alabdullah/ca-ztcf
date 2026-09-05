#!/usr/bin/env python3
"""Generate processed tables and development figures from raw run output.

Everything is derived from files under results/dev/raw/. Nothing is typed by hand.
Output is DEVELOPMENT VALIDATION, not final thesis evidence.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from experiments.analysis import process, tables  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default=str(REPO / "results" / "dev"))
    parser.add_argument("--no-figures", action="store_true")
    args = parser.parse_args()
    root = Path(args.results)

    outputs = process.process(root)
    print("processed tables:")
    for name, path in outputs.items():
        print(f"  {name:<12} {path.relative_to(REPO)}")

    written = tables.generate_all(root)
    print("markdown tables:")
    for path in written:
        print(f"  {path.relative_to(REPO)}")

    if not args.no_figures:
        try:
            from experiments.analysis import figures

            produced = figures.generate_all(root)
            print("development figures:")
            for path in produced:
                print(f"  {path.relative_to(REPO)}")
        except ImportError as exc:
            print(f"figures skipped (matplotlib unavailable): {exc}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
