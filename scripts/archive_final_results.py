#!/usr/bin/env python3
"""Package the raw final results into a deterministic archive.

The raw runs and the audit trail are 109 MB uncompressed and compress to a few
megabytes, so they ship as one archive rather than as 10 000 files in the working
tree. The archive is the research data: it is committed alongside the repository
and uploaded to the archival record, and its checksum is recorded so a copy can be
shown to be the same data.

Deterministic: entries are sorted, timestamps and ownership are normalised, so the
same inputs produce the same bytes and the checksum means something.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import sys
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
INCLUDED = ("raw", "audit")
FIXED_MTIME = 0


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default=str(REPO / "results" / "final"))
    parser.add_argument("--out", default=None)
    parser.add_argument("--version", default=None)
    args = parser.parse_args()

    root = Path(args.results).resolve()
    version = (
        args.version
        or (REPO / "src" / "ca_ztcf" / "version.py")
        .read_text(encoding="utf-8")
        .split('__version__ = "')[1]
        .split('"')[0]
    )
    destination = (
        Path(args.out)
        if args.out
        else (root / "manifests" / f"ca-ztcf-v{version}-final-results.tar")
    )
    destination.parent.mkdir(parents=True, exist_ok=True)

    members: list[Path] = []
    for name in INCLUDED:
        directory = root / name
        if directory.is_dir():
            members.extend(p for p in directory.rglob("*") if p.is_file())
    members.sort()
    if not members:
        print(f"nothing to archive under {root}", file=sys.stderr)
        return 1

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.GNU_FORMAT) as tar:
        for path in members:
            info = tar.gettarinfo(str(path), arcname=str(path.relative_to(root.parent)))
            # Normalised so the archive depends only on its contents.
            info.mtime = FIXED_MTIME
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mode = 0o644
            with path.open("rb") as handle:
                tar.addfile(info, handle)

    raw_bytes = buffer.getvalue()
    try:
        import zstandard

        compressed = zstandard.ZstdCompressor(level=19).compress(raw_bytes)
        final = destination.with_suffix(".tar.zst")
    except ImportError:
        import lzma

        compressed = lzma.compress(raw_bytes, preset=9)
        final = destination.with_suffix(".tar.xz")
    final.write_bytes(compressed)

    digest = sha256(final)
    (final.parent / f"{final.name}.sha256").write_text(
        f"{digest}  {final.name}\n", encoding="utf-8"
    )
    print(f"archive      : {final.relative_to(REPO)}")
    print(f"files        : {len(members)}")
    print(f"uncompressed : {len(raw_bytes) / 1024 / 1024:.1f} MiB")
    print(f"compressed   : {len(compressed) / 1024 / 1024:.1f} MiB")
    print(f"sha256       : {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
