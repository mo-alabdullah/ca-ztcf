"""Transition Event Collector.

Derives access-domain transitions by diffing the per-device sequence of observed
access domains. It never inspects domain identifiers, only which domain currently
covers the device, so it introduces no cross-domain identifier comparison.

Two properties matter for the trust decision and are enforced here.

**A transition is not trusted because a client says it happened.** The collector
corroborates every observation against the access-context collectors: an
observation is corroborated only when the binding store actually holds a binding
for the claimed peer address in the claimed domain. An uncorroborated transition
is still recorded, but it is marked, and the trust engine treats the resulting
absence of a fresh binding as degraded evidence rather than accepting the claim.

**Late, duplicate and out-of-order observations are rejected, not applied.** Each
device carries a monotonically increasing sequence number and a last-observation
timestamp. An observation older than the last one accepted is stale; an identical
observation repeated is a duplicate. Neither may rewrite the device's state,
because a replayed or reordered event must not be able to move a device back into
a more permissive context.

Durations use wall-clock UTC because they are compared against configured windows
expressed in wall-clock terms and must survive a process restart. The monotonic
counter is reserved for measuring engine and request durations.
"""

from __future__ import annotations

import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ca_ztcf.clock import Clock
from ca_ztcf.collectors.base import AccessDomain, BindingStore, SourceMode


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


class TransitionReason(StrEnum):
    """Why a transition record was produced."""

    DOMAIN_CHANGE = "DOMAIN_CHANGE"
    ADDRESS_CHANGE = "ADDRESS_CHANGE"


class ObservationVerdict(StrEnum):
    """What the collector did with an observation."""

    ACCEPTED = "ACCEPTED"
    NO_CHANGE = "NO_CHANGE"
    DUPLICATE = "DUPLICATE"
    STALE = "STALE"
    OUT_OF_ORDER = "OUT_OF_ORDER"


class TransitionEvent(BaseModel):
    """A detected change of access domain for one device."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    transition_id: str = Field(default_factory=lambda: f"trn-{uuid.uuid4().hex[:16]}")
    device_id: str
    from_domain: AccessDomain | None
    to_domain: AccessDomain
    started_at: datetime
    """When the device was last seen in the previous domain."""
    completed_at: datetime | None = None
    """When corroborating evidence for the new domain was observed."""
    detected_at: datetime
    reason: TransitionReason = TransitionReason.DOMAIN_CHANGE
    sequence_number: int = 0
    gap_ms: int | None = None
    transitions_in_window: int = 0
    repeated: bool = False
    cross_domain: bool = False
    corroborated: bool = False
    """Whether an access-context collector holds a binding supporting this claim."""
    source_event_refs: tuple[str, ...] = ()
    """Identifiers of the access bindings that corroborate this transition."""
    source_modes: tuple[SourceMode, ...] = ()
    """Provenance of the corroborating evidence, so a transition's tier is traceable."""
    from_address: str | None = None
    to_address: str | None = None

    def age_seconds(self, now: datetime) -> float:
        return max(0.0, (now - self.detected_at).total_seconds())

    @property
    def duration_ms(self) -> int | None:
        if self.completed_at is None:
            return None
        return max(0, int((self.completed_at - self.started_at).total_seconds() * 1000))


@dataclass
class ObservationResult:
    """Outcome of offering one observation to the collector."""

    verdict: ObservationVerdict
    event: TransitionEvent | None = None
    detail: str = ""

    @property
    def accepted(self) -> bool:
        return self.verdict is ObservationVerdict.ACCEPTED


@dataclass
class _DeviceTrack:
    current_domain: AccessDomain | None = None
    current_address: str | None = None
    last_observed_at: datetime | None = None
    last_transition: TransitionEvent | None = None
    history: deque[datetime] = field(default_factory=deque)
    sequence: int = 0
    rejected_stale: int = 0
    rejected_duplicate: int = 0
    uncorroborated: int = 0
    transitions: dict[str, TransitionEvent] = field(default_factory=dict)


class TransitionCollector:
    """Tracks per-device access domain and produces corroborated transition events."""

    def __init__(
        self,
        clock: Clock,
        *,
        rate_window_s: int,
        repeat_threshold: int,
        transition_window_s: int,
        binding_store: BindingStore | None = None,
        history_limit: int = 64,
    ) -> None:
        self._clock = clock
        self._rate_window = timedelta(seconds=rate_window_s)
        self._repeat_threshold = repeat_threshold
        self._transition_window = timedelta(seconds=transition_window_s)
        self._bindings = binding_store
        self._history_limit = history_limit
        self._tracks: dict[str, _DeviceTrack] = {}
        self._by_transition_id: dict[str, TransitionEvent] = {}

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
        return self.observe_detailed(device_id, domain, peer_address=peer_address, at=at).event

    def observe_detailed(
        self,
        device_id: str,
        domain: AccessDomain,
        *,
        peer_address: str | None = None,
        at: datetime | None = None,
    ) -> ObservationResult:
        """Offer an observation and report exactly what the collector did with it."""
        now = at if at is not None else self._clock.now()
        track = self._tracks.setdefault(device_id, _DeviceTrack())

        # Reject an observation that predates the last one accepted. A replayed or
        # reordered event must never move a device into a more permissive context.
        if track.last_observed_at is not None and now < track.last_observed_at:
            track.rejected_stale += 1
            return ObservationResult(
                verdict=ObservationVerdict.STALE,
                event=track.last_transition,
                detail=(
                    f"observation at {now.isoformat()} predates the last accepted "
                    f"observation at {track.last_observed_at.isoformat()}"
                ),
            )

        same_position = track.current_domain == domain and track.current_address == peer_address
        if same_position and track.last_observed_at == now:
            track.rejected_duplicate += 1
            return ObservationResult(
                verdict=ObservationVerdict.DUPLICATE,
                event=track.last_transition,
                detail="identical observation at an identical instant",
            )

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
            return ObservationResult(verdict=ObservationVerdict.NO_CHANGE)

        self._prune_history(track, now)
        track.history.append(now)
        track.sequence += 1

        corroborated, refs, modes = self._corroborate(domain, peer_address)
        if not corroborated:
            track.uncorroborated += 1

        event = TransitionEvent(
            device_id=device_id,
            from_domain=previous_domain,
            to_domain=domain,
            started_at=previous_at if previous_at is not None else now,
            completed_at=now if corroborated else None,
            detected_at=now,
            reason=(
                TransitionReason.DOMAIN_CHANGE
                if domain_changed
                else TransitionReason.ADDRESS_CHANGE
            ),
            sequence_number=track.sequence,
            gap_ms=(
                None
                if previous_at is None
                else max(0, int((now - previous_at).total_seconds() * 1000))
            ),
            transitions_in_window=len(track.history),
            repeated=len(track.history) >= self._repeat_threshold,
            cross_domain=domain_changed,
            corroborated=corroborated,
            source_event_refs=refs,
            source_modes=modes,
            from_address=previous_address,
            to_address=peer_address,
        )
        track.last_transition = event
        track.transitions[event.transition_id] = event
        self._by_transition_id[event.transition_id] = event
        if len(track.transitions) > self._history_limit:
            oldest = next(iter(track.transitions))
            removed = track.transitions.pop(oldest)
            self._by_transition_id.pop(removed.transition_id, None)
        return ObservationResult(verdict=ObservationVerdict.ACCEPTED, event=event)

    def _corroborate(
        self, domain: AccessDomain, peer_address: str | None
    ) -> tuple[bool, tuple[str, ...], tuple[SourceMode, ...]]:
        """Check the binding store for evidence supporting a claimed position."""
        if self._bindings is None or peer_address is None:
            return False, (), ()
        binding = self._bindings.get(peer_address)
        if binding is None or binding.domain is not domain:
            return False, (), ()
        return True, (binding.binding_id,), (binding.source_mode,)

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

    def transition(self, transition_id: str) -> TransitionEvent | None:
        return self._by_transition_id.get(transition_id)

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

    def anomaly_counts(self, device_id: str) -> dict[str, int]:
        track = self._tracks.get(device_id)
        if track is None:
            return {"stale": 0, "duplicate": 0, "uncorroborated": 0}
        return {
            "stale": track.rejected_stale,
            "duplicate": track.rejected_duplicate,
            "uncorroborated": track.uncorroborated,
        }

    def reset(self, device_id: str | None = None) -> None:
        if device_id is None:
            self._tracks.clear()
            self._by_transition_id.clear()
        else:
            track = self._tracks.pop(device_id, None)
            if track is not None:
                for transition_id in track.transitions:
                    self._by_transition_id.pop(transition_id, None)

    def _prune_history(self, track: _DeviceTrack, now: datetime) -> None:
        cutoff = now - self._rate_window
        while track.history and track.history[0] < cutoff:
            track.history.popleft()


__all__ = [
    "ObservationResult",
    "ObservationVerdict",
    "TransitionCollector",
    "TransitionContext",
    "TransitionEvent",
    "TransitionReason",
]
