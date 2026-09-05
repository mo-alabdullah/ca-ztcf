"""Container CPU and memory sampling.

Uses ``docker stats``, which reads the same cgroup accounting the kernel uses. It
is reproducible on any host with Docker and requires no agent inside the
containers.

Sampling interval is a declared parameter, recorded with every sample set, so a
resource figure can never be read without knowing how it was sampled.

Only container processes are measured. The device agent runs on the host and is
NOT measured here, so nothing in this module may be presented as an IoT device's
resource consumption.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

DEFAULT_SAMPLE_INTERVAL_S = 1.0
"""Sampling interval, in seconds. Recorded with every sample set."""

MEASURED_CONTAINERS = ("ca-ztcf-core", "ca-ztcf-mqtt-pep", "ca-ztcf-mosquitto")
"""Containers sampled. The host-side device agent is deliberately excluded."""


@dataclass
class ResourceSample:
    at: datetime
    container: str
    cpu_percent: float
    memory_mib: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "at": self.at.isoformat(),
            "container": self.container,
            "cpu_percent": self.cpu_percent,
            "memory_mib": self.memory_mib,
        }


def _parse_percent(raw: str) -> float:
    try:
        return float(raw.strip().rstrip("%"))
    except (ValueError, AttributeError):
        return 0.0


def _parse_memory(raw: str) -> float:
    """Parse the used side of docker's ``123MiB / 456MiB`` memory column."""
    try:
        used = raw.split("/")[0].strip()
    except (AttributeError, IndexError):
        return 0.0
    # Longest suffix first: "B" is a suffix of "MiB", so checking it earlier would
    # match every value and scale it by a million.
    units = (
        ("GIB", 1024.0),
        ("MIB", 1.0),
        ("KIB", 1 / 1024),
        ("B", 1 / (1024 * 1024)),
    )
    for suffix, factor in units:
        if used.upper().endswith(suffix):
            try:
                return float(used[: -len(suffix)]) * factor
            except ValueError:
                return 0.0
    return 0.0


def sample_once(containers: tuple[str, ...] = MEASURED_CONTAINERS) -> list[ResourceSample]:
    """Take one sample of each named container. Returns empty if Docker is absent."""
    docker = shutil.which("docker")
    if docker is None:
        return []
    try:
        # Fixed argument vector with a resolved absolute executable; no part of it
        # comes from user input.
        result = subprocess.run(  # noqa: S603
            [
                docker,
                "stats",
                "--no-stream",
                # A pipe-delimited template, not JSON: docker's Go template engine
                # rejects an inline JSON map, and does so by printing a parse error
                # to stdout with exit status 0, which silently yields no samples.
                "--format",
                "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}",
                *containers,
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (subprocess.SubprocessError, OSError):
        return []
    if result.returncode != 0:
        return []

    now = datetime.now(UTC)
    samples: list[ResourceSample] = []
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line or "|" not in line:
            continue
        parts = line.split("|")
        if len(parts) != 3:
            continue
        name, cpu, mem = parts
        samples.append(
            ResourceSample(
                at=now,
                container=name.strip(),
                cpu_percent=_parse_percent(cpu),
                memory_mib=_parse_memory(mem),
            )
        )
    return samples


@dataclass
class ResourceSampler:
    """Background sampler. Start before a run, stop after it."""

    interval_s: float = DEFAULT_SAMPLE_INTERVAL_S
    containers: tuple[str, ...] = MEASURED_CONTAINERS
    samples: list[ResourceSample] = field(default_factory=list)
    _thread: threading.Thread | None = None
    _stop: threading.Event = field(default_factory=threading.Event)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="resource-sampler", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.samples.extend(sample_once(self.containers))
            # Waiting on the stop event rather than sleeping means stopping is
            # immediate; the interval is a sampling period, never a measurement.
            self._stop.wait(self.interval_s)

    def stop(self) -> list[ResourceSample]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        return self.samples

    def summary(self) -> dict[str, Any]:
        from experiments.runner.metrics import describe

        by_container: dict[str, dict[str, Any]] = {}
        for container in {sample.container for sample in self.samples}:
            rows = [s for s in self.samples if s.container == container]
            by_container[container] = {
                "cpu_percent": describe([s.cpu_percent for s in rows]),
                "memory_mib": describe([s.memory_mib for s in rows]),
                "sample_count": len(rows),
            }
        return {
            "sample_interval_s": self.interval_s,
            "sampling_mechanism": "docker stats --no-stream (cgroup accounting)",
            "measured_containers": list(self.containers),
            "excluded": "host-side device agent and experiment runner are not measured",
            "by_container": by_container,
            "total_samples": len(self.samples),
        }


__all__ = [
    "DEFAULT_SAMPLE_INTERVAL_S",
    "MEASURED_CONTAINERS",
    "ResourceSample",
    "ResourceSampler",
    "sample_once",
]
