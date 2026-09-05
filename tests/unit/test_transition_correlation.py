"""Transition correlation: corroboration, and rejection of stale/duplicate events."""

from __future__ import annotations

import pytest

from ca_ztcf.clock import FrozenClock
from ca_ztcf.collectors.base import AccessDomain, BindingStore, SourceMode
from ca_ztcf.collectors.fixtures import FixtureProfile, nr_event, wlan_event
from ca_ztcf.collectors.nr import NRCollector
from ca_ztcf.collectors.transition import (
    ObservationVerdict,
    TransitionCollector,
    TransitionContext,
    TransitionReason,
)
from ca_ztcf.collectors.wlan import WLANCollector

DEVICE = "dev-trn-001"


@pytest.fixture
def store(clock: FrozenClock) -> BindingStore:
    return BindingStore(clock)


@pytest.fixture
def collector(clock: FrozenClock, store: BindingStore, settings) -> TransitionCollector:
    return TransitionCollector(
        clock,
        rate_window_s=settings.transition.rate_window_s,
        repeat_threshold=settings.transition.repeat_threshold,
        transition_window_s=settings.transition.transition_window_s,
        binding_store=store,
    )


@pytest.fixture
def seeded(clock: FrozenClock, store: BindingStore, profile: FixtureProfile):
    NRCollector(clock, store).ingest(nr_event(profile, clock.now()))
    WLANCollector(clock, store).ingest(wlan_event(profile, clock.now()))
    return profile


# --- event completeness -----------------------------------------------------


def test_transition_event_carries_every_required_field(collector, clock, seeded) -> None:
    collector.observe(DEVICE, AccessDomain.NR, peer_address=seeded.nr_address, at=clock.now())
    clock.advance(seconds=4)
    event = collector.observe(
        DEVICE, AccessDomain.WLAN, peer_address=seeded.wlan_address, at=clock.now()
    )

    assert event is not None
    assert event.transition_id.startswith("trn-")
    assert event.device_id == DEVICE
    assert event.from_domain is AccessDomain.NR
    assert event.to_domain is AccessDomain.WLAN
    assert event.started_at is not None
    assert event.completed_at is not None
    assert event.reason is TransitionReason.DOMAIN_CHANGE
    assert event.sequence_number == 1
    assert event.gap_ms == 4000
    assert event.source_event_refs
    assert event.source_modes == (SourceMode.TIER1_WLAN_AUTH_EMULATION,)
    assert event.duration_ms == 4000


def test_sequence_numbers_increase_monotonically(collector, clock, seeded) -> None:
    collector.observe(DEVICE, AccessDomain.NR, peer_address=seeded.nr_address, at=clock.now())
    numbers = []
    for index in range(3):
        clock.advance(seconds=1)
        domain = AccessDomain.WLAN if index % 2 == 0 else AccessDomain.NR
        address = seeded.wlan_address if index % 2 == 0 else seeded.nr_address
        event = collector.observe(DEVICE, domain, peer_address=address, at=clock.now())
        assert event is not None
        numbers.append(event.sequence_number)
    assert numbers == [1, 2, 3]


# --- corroboration ----------------------------------------------------------


def test_transition_is_corroborated_by_an_access_binding(collector, clock, seeded) -> None:
    collector.observe(DEVICE, AccessDomain.NR, peer_address=seeded.nr_address, at=clock.now())
    clock.advance(seconds=1)
    event = collector.observe(
        DEVICE, AccessDomain.WLAN, peer_address=seeded.wlan_address, at=clock.now()
    )
    assert event is not None
    assert event.corroborated is True


def test_uncorroborated_claim_is_recorded_but_marked(collector, clock, seeded) -> None:
    """A transition is never trusted merely because a client claims it."""
    collector.observe(DEVICE, AccessDomain.NR, peer_address=seeded.nr_address, at=clock.now())
    clock.advance(seconds=1)
    event = collector.observe(DEVICE, AccessDomain.WLAN, peer_address="10.99.99.99", at=clock.now())
    assert event is not None
    assert event.corroborated is False
    assert event.completed_at is None
    assert event.source_event_refs == ()
    assert collector.anomaly_counts(DEVICE)["uncorroborated"] == 1


def test_claim_of_the_wrong_domain_is_not_corroborated(collector, clock, seeded) -> None:
    """Claiming WLAN from an address the 5G collector holds is not corroboration."""
    collector.observe(DEVICE, AccessDomain.WLAN, peer_address=seeded.wlan_address, at=clock.now())
    clock.advance(seconds=1)
    event = collector.observe(
        DEVICE, AccessDomain.NR, peer_address=seeded.wlan_address, at=clock.now()
    )
    assert event is not None
    assert event.corroborated is False


# --- stale, duplicate and out-of-order --------------------------------------


def test_stale_observation_is_rejected(collector, clock, seeded) -> None:
    """A replayed event must not move a device into a more permissive context."""
    collector.observe(DEVICE, AccessDomain.NR, peer_address=seeded.nr_address, at=clock.now())
    clock.advance(seconds=10)
    collector.observe(DEVICE, AccessDomain.WLAN, peer_address=seeded.wlan_address, at=clock.now())
    before = collector.last_transition(DEVICE)

    replayed_at = clock.now().replace(microsecond=0)
    clock.advance(seconds=5)
    result = collector.observe_detailed(
        DEVICE,
        AccessDomain.NR,
        peer_address=seeded.nr_address,
        at=replayed_at.replace(year=2025),
    )
    assert result.verdict is ObservationVerdict.STALE
    assert collector.last_transition(DEVICE) == before
    assert collector.anomaly_counts(DEVICE)["stale"] == 1


def test_duplicate_observation_is_rejected(collector, clock, seeded) -> None:
    at = clock.now()
    assert (
        collector.observe_detailed(
            DEVICE, AccessDomain.NR, peer_address=seeded.nr_address, at=at
        ).verdict
        is ObservationVerdict.NO_CHANGE
    )
    result = collector.observe_detailed(
        DEVICE, AccessDomain.NR, peer_address=seeded.nr_address, at=at
    )
    assert result.verdict is ObservationVerdict.DUPLICATE
    assert collector.anomaly_counts(DEVICE)["duplicate"] == 1


def test_unchanged_position_is_not_a_transition(collector, clock, seeded) -> None:
    collector.observe(DEVICE, AccessDomain.NR, peer_address=seeded.nr_address, at=clock.now())
    clock.advance(seconds=5)
    result = collector.observe_detailed(
        DEVICE, AccessDomain.NR, peer_address=seeded.nr_address, at=clock.now()
    )
    assert result.verdict is ObservationVerdict.NO_CHANGE
    assert result.event is None


# --- direction and repetition -----------------------------------------------


def test_both_directions_are_supported(collector, clock, seeded) -> None:
    collector.observe(DEVICE, AccessDomain.NR, peer_address=seeded.nr_address, at=clock.now())
    clock.advance(seconds=1)
    collector.observe(DEVICE, AccessDomain.WLAN, peer_address=seeded.wlan_address, at=clock.now())
    assert collector.context_for(DEVICE, at=clock.now()) is TransitionContext.NR_TO_WLAN

    clock.advance(seconds=1)
    collector.observe(DEVICE, AccessDomain.NR, peer_address=seeded.nr_address, at=clock.now())
    assert collector.context_for(DEVICE, at=clock.now()) is TransitionContext.WLAN_TO_NR


def test_intra_domain_rebinding(collector, clock, seeded) -> None:
    collector.observe(DEVICE, AccessDomain.WLAN, peer_address="192.168.60.2", at=clock.now())
    clock.advance(seconds=1)
    event = collector.observe(
        DEVICE, AccessDomain.WLAN, peer_address="192.168.60.3", at=clock.now()
    )
    assert event is not None
    assert event.reason is TransitionReason.ADDRESS_CHANGE
    assert event.cross_domain is False
    assert collector.context_for(DEVICE, at=clock.now()) is TransitionContext.INTRA


def test_repeated_transitions_are_detected(collector, clock, seeded, settings) -> None:
    collector.observe(DEVICE, AccessDomain.NR, peer_address=seeded.nr_address, at=clock.now())
    for index in range(settings.transition.repeat_threshold):
        clock.advance(seconds=1)
        domain = AccessDomain.WLAN if index % 2 == 0 else AccessDomain.NR
        address = seeded.wlan_address if index % 2 == 0 else seeded.nr_address
        event = collector.observe(DEVICE, domain, peer_address=address, at=clock.now())
    assert event is not None
    assert event.repeated is True
    assert collector.context_for(DEVICE, at=clock.now()) is TransitionContext.REPEATED


def test_transition_is_retrievable_by_id(collector, clock, seeded) -> None:
    collector.observe(DEVICE, AccessDomain.NR, peer_address=seeded.nr_address, at=clock.now())
    clock.advance(seconds=1)
    event = collector.observe(
        DEVICE, AccessDomain.WLAN, peer_address=seeded.wlan_address, at=clock.now()
    )
    assert event is not None
    assert collector.transition(event.transition_id) == event
    assert collector.transition("trn-does-not-exist") is None
