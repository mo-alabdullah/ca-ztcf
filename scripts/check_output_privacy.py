#!/usr/bin/env python3
"""Privacy gate over generated research output.

Scans what the experiment runner and validation flows write — not source code.
Source legitimately names the things it redacts; generated output must never
contain them.

Fails if generated output contains key material, credentials, EAP or subscriber
authentication secrets, cleartext subscriber identifiers, or an unredacted local
home path.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

SCANNED_DIRS = ("results", "artifacts/dev-validation")
"""Generated output that is committed. Ignored working directories are excluded."""

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),  # secret-scan: allow
    ("openssh private key", re.compile(r"BEGIN OPENSSH PRIVATE KEY")),  # secret-scan: allow
    ("EAP master session key", re.compile(r"\b(msk|emsk)\s*[:=]\s*[0-9a-f]{16,}", re.I)),
    ("WPA pairwise key", re.compile(r"\b(pmk|ptk|gtk|psk)\s*[:=]\s*[0-9a-f]{16,}", re.I)),
    ("5G key material", re.compile(r"\b(kausf|kseaf|kamf|opc|\bki)\s*[:=]\s*[0-9a-f]{16,}", re.I)),
    ("cleartext IMSI", re.compile(r"\bimsi-?\d{14,15}\b", re.I)),
    ("cleartext SUPI", re.compile(r'"supi"\s*:\s*"(?!\[REDACTED\])[^"]+"', re.I)),
    ("cleartext PEI", re.compile(r'"pei"\s*:\s*"(?!\[REDACTED\])[^"]+"', re.I)),
    ("password assignment", re.compile(r'"?password"?\s*[:=]\s*"[^"]{6,}"', re.I)),
]

SKIP_SUFFIXES = {".png", ".jpg", ".pdf", ".zip"}


def home_pattern() -> re.Pattern[str] | None:
    home = str(Path.home())
    if not home or home == "/":
        return None
    return re.compile(re.escape(home))


def scan(root: Path) -> tuple[list[str], int]:
    findings: list[str] = []
    scanned = 0
    home = home_pattern()

    for directory in SCANNED_DIRS:
        base = root / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix.lower() in SKIP_SUFFIXES:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            scanned += 1
            relative = path.relative_to(root)
            for label, pattern in PATTERNS:
                if pattern.search(text):
                    findings.append(f"{relative}: contains {label}")
            if home is not None and home.search(text):
                findings.append(f"{relative}: contains an unredacted local home path")
    return findings, scanned


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(REPO))
    args = parser.parse_args()

    findings, scanned = scan(Path(args.repo))
    if findings:
        print(f"output privacy gate: FAILED with {len(findings)} problem(s)")
        for finding in findings:
            print(f"  {finding}")
        return 1
    print(f"output privacy gate: PASSED ({scanned} generated file(s) scanned)")
    print("  no key material, credentials, cleartext subscriber ids or home paths")
    return 0


if __name__ == "__main__":
    sys.exit(main())
