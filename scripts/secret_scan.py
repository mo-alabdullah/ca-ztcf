#!/usr/bin/env python3
"""Heuristic secret scan over content that git tracks or would track.

Not a substitute for a dedicated scanner; it is a fast, dependency-free gate that
fails the build if obvious credential material reaches the index.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # secret-scan: allow - these are the scanner's own detection patterns.
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),  # secret-scan: allow
    (
        "openssh private key",
        re.compile(r"-----BEGIN OPENSSH PRIVATE KEY-----"),  # secret-scan: allow
    ),
    ("aws access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    (
        "generic api key assignment",
        re.compile(r"(?i)\b(api[_-]?key|secret[_-]?key)\s*[:=]\s*['\"][A-Za-z0-9/+_-]{16,}['\"]"),
    ),
    (
        "password assignment",
        re.compile(r"(?i)\bpassword\s*[:=]\s*['\"][^'\"\s]{8,}['\"]"),
    ),
]

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "secrets",
}
SKIP_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".pdf",
    ".zip",
    ".whl",
    ".so",
    ".dylib",
}
ALLOWLIST_MARKER = "secret-scan: allow"


def tracked_files(root: Path) -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        return [root / line for line in out.stdout.splitlines() if line.strip()]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return [p for p in root.rglob("*") if p.is_file()]


def should_scan(path: Path, root: Path) -> bool:
    if not path.is_file():
        return False
    rel = path.relative_to(root) if path.is_absolute() else path
    if any(part in SKIP_DIRS for part in rel.parts):
        return False
    return path.suffix.lower() not in SKIP_SUFFIXES


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="repository root")
    args = parser.parse_args()
    root = Path(args.root).resolve()

    findings: list[str] = []
    scanned = 0
    for path in tracked_files(root):
        if not should_scan(path, root):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        scanned += 1
        for number, line in enumerate(text.splitlines(), start=1):
            if ALLOWLIST_MARKER in line:
                continue
            for label, pattern in PATTERNS:
                if pattern.search(line):
                    rel = path.relative_to(root)
                    findings.append(f"{rel}:{number}: possible {label}")

    if findings:
        print(f"secret scan: {len(findings)} finding(s) across {scanned} file(s)")
        for finding in findings:
            print(f"  {finding}")
        return 1
    print(f"secret scan: clean ({scanned} files scanned)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
