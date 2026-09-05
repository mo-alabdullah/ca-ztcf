#!/usr/bin/env python3
"""Capture reproducibility metadata for the current environment.

Written for every development validation run and, later, for every experiment
run. Anything that could change a measurement is recorded here so that a result
can always be attributed to the environment that produced it.
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def scrub(value: str | None) -> str | None:
    """Replace the user's home directory with "~".

    Reproducibility metadata is committed and later published, so it must not
    carry a personal absolute path. The path is not research-relevant; the
    versions, hashes and hardware details around it are.
    """
    if value is None:
        return None
    home = str(Path.home())
    return value.replace(home, "~") if home and home != "/" else value


def _run(command: list[str], cwd: Path | None = None) -> str | None:
    executable = shutil.which(command[0])
    if executable is None:
        return None
    try:
        result = subprocess.run(
            [executable, *command[1:]], cwd=cwd, capture_output=True, text=True, timeout=30
        )
    except (subprocess.SubprocessError, OSError):
        return None
    if result.returncode != 0:
        return None
    return scrub(result.stdout.strip()) or None


def git_metadata(root: Path) -> dict[str, Any]:
    commit = _run(["git", "rev-parse", "HEAD"], root)
    status = _run(["git", "status", "--porcelain"], root)
    return {
        "commit_sha": commit,
        "dirty": bool(status) if status is not None else None,
        "dirty_files": status.splitlines() if status else [],
        "branch": _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], root),
        "describe": _run(["git", "describe", "--tags", "--always", "--dirty"], root),
    }


def cpu_metadata() -> dict[str, Any]:
    info: dict[str, Any] = {"processor": platform.processor() or None}
    if sys.platform == "darwin":
        info["model"] = _run(["sysctl", "-n", "machdep.cpu.brand_string"])
        cores = _run(["sysctl", "-n", "hw.ncpu"])
        info["logical_cores"] = int(cores) if cores and cores.isdigit() else None
    else:
        try:
            for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
                if line.startswith("model name"):
                    info["model"] = line.split(":", 1)[1].strip()
                    break
        except OSError:
            info["model"] = None
        try:
            import os

            info["logical_cores"] = os.cpu_count()
        except Exception:
            info["logical_cores"] = None
    return info


def package_versions() -> dict[str, str]:
    try:
        from importlib.metadata import distributions
    except ImportError:  # pragma: no cover
        return {}
    return {
        dist.metadata["Name"]: dist.version for dist in distributions() if dist.metadata.get("Name")
    }


def config_hash(config_dir: Path) -> str | None:
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
        from ca_ztcf.config import load_settings

        return load_settings(config_dir).config_hash
    except Exception as exc:
        return f"unavailable: {exc}"


def docker_image_digest(image: str) -> str | None:
    raw = _run(["docker", "image", "inspect", image, "--format", "{{index .RepoDigests 0}}"])
    if raw:
        return raw
    return _run(["docker", "image", "inspect", image, "--format", "{{.Id}}"])


def collect(root: Path, config_dir: Path, image: str | None) -> dict[str, Any]:
    return {
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "purpose": "development validation metadata; not a thesis experimental result",
        "git": git_metadata(root),
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable": scrub(sys.executable),
        },
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "architecture": platform.architecture()[0],
        },
        "kernel": _run(["uname", "-a"]),
        "cpu": cpu_metadata(),
        "docker": {
            "version": _run(["docker", "--version"]),
            "compose_version": _run(["docker", "compose", "version", "--short"]),
            "image": image,
            "image_digest": docker_image_digest(image) if image else None,
        },
        "config": {"config_dir": scrub(str(config_dir)), "config_hash": config_hash(config_dir)},
        "packages": package_versions(),
    }


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(root))
    parser.add_argument("--config-dir", default=str(root / "config"))
    parser.add_argument("--image", default="ca-ztcf:0.2.0")
    parser.add_argument("--out", default=str(root / "artifacts" / "dev-validation"))
    args = parser.parse_args()

    payload = collect(Path(args.root), Path(args.config_dir), args.image)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_file = out_dir / f"env-{stamp}.json"
    out_file.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"environment metadata written to {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
