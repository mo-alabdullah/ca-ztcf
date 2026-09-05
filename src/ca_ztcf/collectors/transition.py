"""Transition Event Collector.

Derives access-domain transitions by diffing the per-device sequence of observed
access domains. It never inspects domain identifiers, only which domain currently
covers the device, so it introduces no cross-domain identifier comparison.

Durations use wall-clock UTC because they are compared against configured windows
that are also expressed in wall-clock terms and must survive process restarts.
Monotonic time is reserved for measuring engine and request durations.
"""

from __future__ import annotations

import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from ca_ztcf.clock import Clock
from ca_ztcf.collectors.base import AccessDomain


class TransitionContext(StrEnum):
    """How the current request relates to recent access-domain activity."""

    NONE = "NONE"
    """No transition within the configured transition window."""

    NR_TO_WLAN = "NR_TO_WLAN"
    WLAN_TO_NR = "WLAN_TO_NR"

    INTRA = "INTRA"
    """Re-binding within the same access domain, for example a new address."""

    REPEATED = "REPEATED"
    """Transition count within the rate window has reached the repeat threshold."""


class TransitionEvent(BaseModel):
    """A detected change of access domain for one device."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str
    device_id: str
    from_domain: AccessDomain | None
    to_domain: AccessDomain
    detected_at: datetime
    gap_ms: int | None = None
    transitions_in_window: int = 0
    repeated: bool = False
    cross_domain: bool = False

    def age_seconds(self, now: datetime) -> float:
        return max(0.0, (now - self.detected_at).total_seconds())


@dataclass
class _DeviceTrack:
    current_domain: AccessDomain | None = None
    current_address: str | None = None
    last_observed_at: datetime | None = None
    last_transition: TransitionEvent | None = None
    history: deque[datetime] = field(default_factory=deque)


class TransitionCollector:
    """Tracks per-device access domain and produces transition events."""

    def __init__(
        self,
        clock: Clock,
        *,
        rate_window_s: int,
        repeat_threshold: int,
        transition_window_s: int,
    ) -> None:
        self._clock = clock
        self._rate_window = timedelta(seconds=rate_window_s)
        self._repeat_threshold = repeat_threshold
        self._transition_window = timedelta(seconds=transition_window_s)
        self._tracks: dict[str, _DeviceTrack] = {}

    # -- observation -----------------------------------------------------

    def observe(
        self,
        device_id: str,
        domain: AccessDomain,
        *,
        peer_address: str | None = None,
        at: datetime | None = None,
    ) -> TransitionEvent | None:
        """Record where a device is now observed. Returns an event on change."""
        now = at if at is not None else self._clock.now()
        track = self._tracks.setdefault(device_id, _DeviceTrack())

        previous_domain = track.current_domain
        previous_address = track.current_address
        previous_at = track.last_observed_at

        domain_changed = previous_domain is not None and previous_domain != domain
        address_changed = (
            previous_domain == domain
            and previous_address is not None
            and peer_address is not None
            and previous_address != peer_address
        )

        track.current_domain = domain
        track.current_address = peer_address
        track.last_observed_at = now

        if not (domain_changed or address_changed):
            return None

        self._prune_history(track, now)
        track.history.append(now)
        transitions_in_window = len(track.history)

        gap_ms = None
        if previous_at is not None:
            gap_ms = max(0, int((now - previous_at).total_seconds() * 1000))

        event = TransitionEvent(
            event_id=f"trn-{uuid.uuid4().hex[:16]}",
            device_id=device_id,
            from_domain=previous_domain,
            to_domain=domain,
            detected_at=now,
            gap_ms=gap_ms,
            transitions_in_window=transitions_in_window,
            repeated=transitions_in_window >= self._repeat_threshold,
            cross_domain=domain_changed,
        )
        track.last_transition = event
        return event

    # -- queries ---------------------------------------------------------

    def current_domain(self, device_id: str) -> AccessDomain | None:
        track = self._tracks.get(device_id)
        return track.current_domain if track else None

    def previous_domain(self, device_id: str) -> AccessDomain | None:
        track = self._tracks.get(device_id)
        if track is None or track.last_transition is None:
            return None
        return track.last_transition.from_domain

    def last_transition(self, device_id: str) -> TransitionEvent | None:
        track = self._tracks.get(device_id)
        return track.last_transition if track else None

    def transitions_in_window(self, device_id: str, *, at: datetime | None = None) -> int:
        track = self._tracks.get(device_id)
        if track is None:
            return 0
        now = at if at is not None else self._clock.now()
        self._prune_history(track, now)
        return len(track.history)

    def is_transition_recent(self, device_id: str, *, at: datetime | None = None) -> bool:
        """Whether the last transition falls inside the configured transition window."""
        event = self.last_transition(device_id)
        if event is None:
            return False
        now = at if at is not None else self._clock.now()
        return (now - event.detected_at) <= self._transition_window

    def context_for(self, device_id: str, *, at: datetime | None = None) -> TransitionContext:
        """Derive the transition context used as the second axis of the policy matrix."""
        now = at if at is not None else self._clock.now()
        event = self.last_transition(device_id)
        if event is None or (now - event.detected_at) > self._transition_window:
            return TransitionContext.NONE
        if self.transitions_in_window(device_id, at=now) >= self._repeat_threshold:
            return TransitionContext.REPEATED
        if not event.cross_domain:
            return TransitionContext.INTRA
        if event.from_domain is AccessDomain.NR and event.to_domain is AccessDomain.WLAN:
            return TransitionContext.NR_TO_WLAN
        if event.from_domain is AccessDomain.WLAN and event.to_domain is AccessDomain.NR:
            return TransitionContext.WLAN_TO_NR
        return TransitionContext.INTRA

    def reset(self, device_id: str | None = None) -> None:
        if device_id is None:
            self._tracks.clear()
        else:
            self._tracks.pop(device_id, None)

    def _prune_history(self, track: _DeviceTrack, now: datetime) -> None:
        cutoff = now - self._rate_window
        while track.history and track.history[0] < cutoff:
            track.history.popleft()


__all__ = ["TransitionCollector", "TransitionContext", "TransitionEvent"]
