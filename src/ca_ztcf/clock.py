"""Time abstraction.

Two independent time sources are used deliberately and must not be confused:

``now`` (UTC wall clock)
    Used for audit records, evidence observation times, expiry and freshness.
    Comparable across processes; subject to adjustment by the operating system.

``monotonic_ns``
    Used exclusively for measuring durations (engine evaluation time, request
    latency). Never written into an evidence record as a point in time.

Injecting the clock is what makes freshness, staleness and transition-window
behaviour testable without sleeping.

The two are independent even when the wall clock is frozen. A frozen wall clock
lets a scenario say "thirty-one seconds later" without waiting; a duration is a
physical measurement of how long code actually took, and freezing it would not
make the code instantaneous, it would only make the instrument read zero. So
``FrozenClock`` freezes ``now`` and, by default, still measures real durations.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta


class Clock(ABC):
    """Source of wall-clock time and of a monotonic duration counter."""

    @abstractmethod
    def now(self) -> datetime:
        """Return the current time as a timezone-aware UTC ``datetime``."""

    @abstractmethod
    def monotonic_ns(self) -> int:
        """Return a monotonic counter in nanoseconds, for durations only."""


class SystemClock(Clock):
    """Real time. Used in production and in the container."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic_ns(self) -> int:
        return time.monotonic_ns()


class FrozenClock(Clock):
    """Deterministic clock for tests and for reproducible evaluation.

    Time only advances when it is explicitly advanced, so a test can express
    "thirty-one seconds later" without waiting.
    """

    def __init__(
        self,
        start: datetime | None = None,
        monotonic_start_ns: int = 0,
        *,
        real_durations: bool = True,
    ) -> None:
        """``real_durations`` keeps ``monotonic_ns`` measuring actual elapsed time.

        That is the default because anything timing itself through this clock is
        measuring how long it took, and a frozen counter reports zero for work
        that certainly took longer than zero. Pass ``False`` only where a test
        needs the duration counter itself to be deterministic.
        """
        if start is None:
            start = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        if start.tzinfo is None:
            raise ValueError("FrozenClock requires a timezone-aware start time")
        self._now = start.astimezone(UTC)
        self._monotonic_ns = monotonic_start_ns
        self._real_durations = real_durations
        self._real_origin_ns = time.perf_counter_ns()

    def now(self) -> datetime:
        return self._now

    def monotonic_ns(self) -> int:
        if self._real_durations:
            return self._monotonic_ns + (time.perf_counter_ns() - self._real_origin_ns)
        return self._monotonic_ns

    def advance(self, seconds: float = 0.0, *, milliseconds: float = 0.0) -> datetime:
        """Advance both wall clock and monotonic counter by the same interval."""
        total_seconds = seconds + milliseconds / 1000.0
        if total_seconds < 0:
            raise ValueError("FrozenClock cannot move backwards")
        self._now = self._now + timedelta(seconds=total_seconds)
        self._monotonic_ns += int(total_seconds * 1_000_000_000)
        return self._now

    def set(self, moment: datetime) -> datetime:
        """Set the wall clock to an explicit instant without moving monotonic time."""
        if moment.tzinfo is None:
            raise ValueError("FrozenClock requires a timezone-aware instant")
        self._now = moment.astimezone(UTC)
        return self._now


def ensure_utc(moment: datetime) -> datetime:
    """Normalise a datetime to timezone-aware UTC, rejecting naive input."""
    if moment.tzinfo is None:
        raise ValueError("naive datetime is not accepted; supply a timezone-aware value")
    return moment.astimezone(UTC)
