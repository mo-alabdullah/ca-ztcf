#!/usr/bin/env python3
"""Verify that every final artefact follows from the raw runs.

Moves the generated directories aside, regenerates them from
``results/final/raw/`` and compares. A difference means a value was edited by
hand or the pipeline changed without the outputs being regenerated; either way
the artefacts no longer follow from the data.

Figures are compared by content where possible. Matplotlib embeds a creation
timestamp in PNG metadata, so a figure's bytes are not expected to match; that is
reported as what it is rather than dressed up as byte identity.
"""

from __future__ import annotations

import argparse
import filecmp
import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GENERATED = ("processed", "tables", "statistics", "figures")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def png_pixels(path: Path) -> str | None:
    """Hash a PNG's decoded pixels, which carry no creation timestamp."""
    try:
        import matplotlib.image as mpimg
    except ImportError:
        return None
    try:
        return hashlib.sha256(mpimg.imread(path).tobytes()).hexdigest()
    except (OSError, ValueError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default=str(REPO / "results" / "final"))
    args = parser.parse_args()
    root = Path(args.results).resolve()

    with tempfile.TemporaryDirectory() as tmp:
        stash = Path(tmp) / "generated"
        stash.mkdir()
        present = [name for name in GENERATED if (root / name).is_dir()]
        for name in present:
            shutil.move(str(root / name), str(stash / name))

        result = subprocess.run(
            [
                sys.executable,
                str(REPO / "scripts" / "process_final_results.py"),
                "--results",
                str(root),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            print(result.stdout)
            print(result.stderr, file=sys.stderr)
            print("verify-final-results: FAILED, regeneration errored", file=sys.stderr)
            return 2

        identical: list[str] = []
        differing: list[str] = []
        pixel_identical: list[str] = []
        pixel_differing: list[str] = []
        missing: list[str] = []

        for name in present:
            for original in sorted((stash / name).rglob("*")):
                if not original.is_file():
                    continue
                relative = original.relative_to(stash)
                regenerated = root / relative
                if not regenerated.is_file():
                    missing.append(str(relative))
                    continue
                if original.suffix == ".png":
                    before, after = png_pixels(original), png_pixels(regenerated)
                    if before is not None and before == after:
                        pixel_identical.append(str(relative))
                    elif before is None:
                        differing.append(f"{relative} (pixels unreadable)")
                    else:
                        pixel_differing.append(str(relative))
                    continue
                if filecmp.cmp(original, regenerated, shallow=False):
                    identical.append(str(relative))
                else:
                    differing.append(str(relative))

    print("verify-final-results")
    print(f"  byte-identical            : {len(identical)}")
    print(f"  figures pixel-identical   : {len(pixel_identical)}")
    if pixel_differing:
        print(f"  figures differing         : {len(pixel_differing)}")
        for name in pixel_differing:
            print(f"      {name}")
    if missing:
        print(f"  MISSING after regeneration: {len(missing)}")
        for name in missing:
            print(f"      {name}")
    if differing:
        print(f"  DIFFERING                 : {len(differing)}")
        for name in differing:
            print(f"      {name}")
    print(
        "  note: PNG bytes carry a creation timestamp from matplotlib, so figure "
        "binaries are compared by decoded pixels, not by file hash."
    )

    if differing or missing:
        print("verify-final-results: FAILED", file=sys.stderr)
        return 1
    print("verify-final-results: PASSED, every artefact follows from the raw data")
    return 0


if __name__ == "__main__":
    sys.exit(main())
