"""The injectable clock."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ca_ztcf.clock import FrozenClock, SystemClock, ensure_utc


def test_frozen_clock_does_not_move_on_its_own(clock: FrozenClock) -> None:
    first = clock.now()
    assert clock.now() == first
    assert clock.monotonic_ns() == 0


def test_advance_moves_wall_and_monotonic_together(clock: FrozenClock) -> None:
    start = clock.now()
    clock.advance(seconds=31)
    assert (clock.now() - start).total_seconds() == pytest.approx(31.0)
    assert clock.monotonic_ns() == 31_000_000_000


def test_advance_accepts_milliseconds(clock: FrozenClock) -> None:
    clock.advance(milliseconds=250)
    assert clock.monotonic_ns() == 250_000_000


def test_clock_cannot_move_backwards(clock: FrozenClock) -> None:
    with pytest.raises(ValueError, match="backwards"):
        clock.advance(seconds=-1)


def test_naive_start_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        FrozenClock(start=datetime(2026, 1, 1))


def test_system_clock_is_utc_and_monotonic_increases() -> None:
    system = SystemClock()
    assert system.now().tzinfo is not None
    assert system.monotonic_ns() > 0


def test_ensure_utc_rejects_naive() -> None:
    assert ensure_utc(datetime(2026, 1, 1, tzinfo=UTC)).tzinfo is UTC
    with pytest.raises(ValueError, match="naive"):
        ensure_utc(datetime(2026, 1, 1))
