#!/usr/bin/env python3
"""Verify that every processed artefact can be regenerated from raw output.

Re-derives the processed tables into a scratch location and compares them with the
committed ones. A difference means a table was edited by hand, or the pipeline
changed without the outputs being regenerated. Either way the artefacts no longer
follow from the raw data, and that must fail loudly.

Also runs the source-mode safety gate over the same tree.
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from experiments.analysis import process, tables  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default=str(REPO / "results" / "dev"))
    args = parser.parse_args()
    root = Path(args.results)

    if not (root / "raw").is_dir():
        print("verify-results: no raw output to verify", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp) / "dev"
        scratch.mkdir(parents=True)
        shutil.copytree(root / "raw", scratch / "raw")
        if (root / "metadata").is_dir():
            shutil.copytree(root / "metadata", scratch / "metadata")

        process.process(scratch)
        tables.generate_all(scratch)

        mismatches: list[str] = []
        checked = 0
        for subdir in ("processed", "tables"):
            for regenerated in sorted((scratch / subdir).rglob("*")):
                if not regenerated.is_file():
                    continue
                relative = regenerated.relative_to(scratch)
                committed = root / relative
                checked += 1
                if not committed.is_file():
                    mismatches.append(f"{relative}: missing from the committed tree")
                elif relative.name == "index.json":
                    # index.json embeds absolute paths, which differ by construction.
                    continue
                elif not filecmp.cmp(regenerated, committed, shallow=False):
                    mismatches.append(f"{relative}: differs from the regenerated output")

    gate = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "check_source_modes.py"), "--results", str(root)],
        check=False,
    )

    if mismatches:
        print(f"verify-results: FAILED, {len(mismatches)} artefact(s) do not follow from raw data")
        for mismatch in mismatches:
            print(f"  {mismatch}")
        return 1
    if gate.returncode != 0:
        print("verify-results: FAILED, source-mode gate did not pass")
        return 1

    print(f"verify-results: PASSED, {checked} artefact(s) regenerate identically from raw data")
    return 0


if __name__ == "__main__":
    sys.exit(main())
