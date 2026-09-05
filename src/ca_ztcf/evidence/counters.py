"""Security counters computed by CA-ZTCF from observed events.

These are deliberately *computed*, not assumed. The earlier conceptual design had
a vague "risk indicators" evidence category that no real deployment could supply;
it is replaced by counters the service domain derives from what it actually
observes.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta


class SecurityCounters:
    """Sliding-window counters of security-relevant events, per device."""

    def __init__(self, *, authn_failure_window_s: int) -> None:
        self._window = timedelta(seconds=authn_failure_window_s)
        self._authn_failures: dict[str, deque[datetime]] = {}
        self._identity_conflicts: dict[str, int] = {}

    def record_authn_failure(self, device_id: str, at: datetime) -> int:
        bucket = self._authn_failures.setdefault(device_id, deque())
        bucket.append(at)
        self._prune(bucket, at)
        return len(bucket)

    def authn_failures(self, device_id: str, at: datetime) -> int:
        bucket = self._authn_failures.get(device_id)
        if bucket is None:
            return 0
        self._prune(bucket, at)
        return len(bucket)

    def record_identity_conflict(self, device_id: str) -> int:
        total = self._identity_conflicts.get(device_id, 0) + 1
        self._identity_conflicts[device_id] = total
        return total

    def identity_conflicts(self, device_id: str) -> int:
        return self._identity_conflicts.get(device_id, 0)

    def reset(self, device_id: str | None = None) -> None:
        if device_id is None:
            self._authn_failures.clear()
            self._identity_conflicts.clear()
        else:
            self._authn_failures.pop(device_id, None)
            self._identity_conflicts.pop(device_id, None)

    def _prune(self, bucket: deque[datetime], now: datetime) -> None:
        cutoff = now - self._window
        while bucket and bucket[0] < cutoff:
            bucket.popleft()


__all__ = ["SecurityCounters"]
