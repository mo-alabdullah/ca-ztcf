"""CPU and memory sampling.

Two samplers, because the framework is exercised in two shapes.

``ResourceSampler`` reads ``docker stats`` for the container deployment. It uses
the same cgroup accounting the kernel does and needs no agent inside the
containers.

``ProcessResourceSampler`` reads ``/proc/<pid>/stat`` and ``/proc/<pid>/status``
for a running process. The experiment runner builds the CA-ZTCF core in process,
so in that shape there is no container to read and the runner process itself is
what executes the trust function.

Sampling interval is a declared parameter, recorded with every sample set, so a
resource figure can never be read without knowing how it was sampled.

**What is NOT measured.** Neither sampler measures an IoT device. The device agent
is a separate process and, on Tier 2, lives in another network namespace. Nothing
here may be presented as a device's resource consumption. The process sampler
measures the experiment process, which runs the trust function together with the
scenario driver, and its figures must be labelled that way.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
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


# ---------------------------------------------------------------------------
# Process sampling
# ---------------------------------------------------------------------------


@dataclass
class ProcessSample:
    """One observation of a process's CPU time and resident memory."""

    at: datetime
    pid: int
    cpu_percent: float
    memory_mib: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "at": self.at.isoformat(),
            "pid": self.pid,
            "cpu_percent": self.cpu_percent,
            "memory_mib": self.memory_mib,
        }


def _clock_ticks() -> float:
    try:
        import os

        return float(os.sysconf("SC_CLK_TCK"))
    except (ValueError, OSError, AttributeError):
        return 100.0


def read_process_cpu_seconds(pid: int) -> float | None:
    """Total CPU seconds (user + system) a process has consumed, or None."""
    try:
        fields = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").rsplit(")", 1)[1].split()
    except (OSError, IndexError):
        return None
    try:
        # After the comm field: state is index 0, utime index 11, stime index 12.
        utime, stime = float(fields[11]), float(fields[12])
    except (IndexError, ValueError):
        return None
    return (utime + stime) / _clock_ticks()


def read_process_rss_mib(pid: int) -> float | None:
    """Resident set size in MiB, or None where /proc is unavailable."""
    try:
        for line in Path(f"/proc/{pid}/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return float(line.split()[1]) / 1024.0
    except (OSError, IndexError, ValueError):
        return None
    return None


class ProcessResourceSampler:
    """Samples one process's CPU and resident memory on a fixed interval.

    Silently produces no samples where ``/proc`` is unavailable, which is missing
    evidence rather than a zero: the summary reports ``available: false`` so a
    reader cannot mistake an unmeasured run for an idle one.
    """

    def __init__(
        self, pid: int | None = None, interval_s: float = DEFAULT_SAMPLE_INTERVAL_S
    ) -> None:
        import os

        self.pid = pid if pid is not None else os.getpid()
        self.interval_s = interval_s
        self.samples: list[ProcessSample] = []
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._started_at: datetime | None = None
        self._cpu_at_start: float | None = None
        self._rusage_at_start: float | None = None

    @property
    def available(self) -> bool:
        """Whether interval sampling is possible; /proc is Linux-only."""
        return read_process_cpu_seconds(self.pid) is not None

    def _rusage_cpu_seconds(self) -> float:
        """CPU seconds for this process, portably.

        ``resource.getrusage`` works where ``/proc`` does not, so a total is
        always available even when interval samples are not. It measures the
        calling process, so it is only meaningful for the default pid.
        """
        import resource as _resource

        usage = _resource.getrusage(_resource.RUSAGE_SELF)
        return float(usage.ru_utime + usage.ru_stime)

    def _rusage_peak_rss_mib(self) -> float:
        import platform
        import resource as _resource

        peak = float(_resource.getrusage(_resource.RUSAGE_SELF).ru_maxrss)
        # ru_maxrss is kilobytes on Linux and bytes on macOS.
        return peak / 1024.0 if platform.system() == "Linux" else peak / (1024.0 * 1024.0)

    def start(self) -> None:
        self._started_at = datetime.now(UTC)
        self._cpu_at_start = read_process_cpu_seconds(self.pid)
        self._rusage_at_start = self._rusage_cpu_seconds()
        if not self.available:
            # No interval samples, but the CPU total and peak RSS still are.
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        previous_cpu = read_process_cpu_seconds(self.pid)
        previous_at = datetime.now(UTC)
        while not self._stop_event.wait(self.interval_s):
            cpu = read_process_cpu_seconds(self.pid)
            rss = read_process_rss_mib(self.pid)
            now = datetime.now(UTC)
            if cpu is None or previous_cpu is None:
                previous_at = now
                continue
            elapsed = (now - previous_at).total_seconds()
            percent = ((cpu - previous_cpu) / elapsed * 100.0) if elapsed > 0 else 0.0
            self.samples.append(
                ProcessSample(at=now, pid=self.pid, cpu_percent=percent, memory_mib=rss or 0.0)
            )
            previous_cpu, previous_at = cpu, now

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval_s * 3)
            self._thread = None

    def summary(self) -> dict[str, Any]:
        """Resource use over the sampled window, plus how it was sampled."""
        cpu_now = read_process_cpu_seconds(self.pid)
        if cpu_now is not None and self._cpu_at_start is not None:
            cpu_total = round(cpu_now - self._cpu_at_start, 6)
            cpu_source = "proc_stat"
        elif self._rusage_at_start is not None:
            cpu_total = round(self._rusage_cpu_seconds() - self._rusage_at_start, 6)
            cpu_source = "getrusage"
        else:
            cpu_total, cpu_source = None, "unavailable"
        percents = [s.cpu_percent for s in self.samples]
        memory = [s.memory_mib for s in self.samples if s.memory_mib > 0]
        return {
            "available": cpu_total is not None,
            "subject": "experiment_process",
            "note": (
                "the experiment process, which runs the CA-ZTCF trust function "
                "together with the scenario driver. NOT an IoT device measurement."
            ),
            "pid": self.pid,
            "sample_interval_s": self.interval_s,
            "sample_count": len(self.samples),
            "cpu_seconds_total": cpu_total,
            "cpu_source": cpu_source,
            "interval_sampling_available": self.available,
            "cpu_percent_mean": round(sum(percents) / len(percents), 3) if percents else None,
            "cpu_percent_max": round(max(percents), 3) if percents else None,
            "memory_mib_mean": round(sum(memory) / len(memory), 3) if memory else None,
            "memory_mib_max": round(max(memory), 3) if memory else None,
            "memory_mib_peak_rss": read_process_rss_mib(self.pid) or self._rusage_peak_rss_mib(),
        }
