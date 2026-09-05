"""Collectors: normalisation, privacy separation, bindings and transitions."""

from __future__ import annotations

from datetime import timedelta

import pytest

from ca_ztcf.clock import FrozenClock
from ca_ztcf.collectors.base import AccessDomain, BindingStore, SourceMode
from ca_ztcf.collectors.fixtures import FixtureProfile, nr_event, wlan_event
from ca_ztcf.collectors.nr import NRCollector, NrEventType, SyntheticFixtureProvider
from ca_ztcf.collectors.transition import TransitionCollector, TransitionContext
from ca_ztcf.collectors.wlan import WLANCollector, WlanEventType
from ca_ztcf.errors import CollectorError


@pytest.fixture
def store(clock: FrozenClock) -> BindingStore:
    return BindingStore(clock)


def test_nr_event_produces_a_binding(
    clock: FrozenClock, store: BindingStore, profile: FixtureProfile
) -> None:
    collector = NRCollector(clock, store)
    binding = collector.ingest(nr_event(profile, clock.now()))
    assert binding is not None
    assert binding.domain is AccessDomain.NR
    assert binding.peer_address == profile.nr_address
    assert binding.source_mode is SourceMode.SYNTHETIC_FIXTURE
    assert binding.attributes["registration_state"] == "REGISTERED"
    assert binding.device_ref is None


def test_raw_subscriber_reference_is_never_stored(
    clock: FrozenClock, store: BindingStore, profile: FixtureProfile
) -> None:
    collector = NRCollector(clock, store)
    binding = collector.ingest(nr_event(profile, clock.now()))
    assert binding is not None
    assert profile.subscriber_ref not in str(binding.attributes)
    assert "subscriber_ref_hash" in binding.attributes


def test_raw_wlan_identifiers_are_never_stored(
    clock: FrozenClock, store: BindingStore, profile: FixtureProfile
) -> None:
    collector = WLANCollector(clock, store)
    binding = collector.ingest(wlan_event(profile, clock.now()))
    assert binding is not None
    assert profile.sta_mac not in str(binding.attributes)
    assert profile.eap_identity not in str(binding.attributes)
    assert {"sta_mac_hash", "eap_identity_hash"} <= set(binding.attributes)


def test_collector_salts_are_independent_so_digests_never_collide(
    clock: FrozenClock, store: BindingStore
) -> None:
    """The same raw identifier must hash differently in each collector.

    This is what makes cross-domain identifier comparison impossible rather than
    merely forbidden by convention.
    """
    nr = NRCollector(clock, store)
    wlan = WLANCollector(clock, store)
    shared_raw = "identical-raw-identifier"
    assert nr.hash_identifier(shared_raw) != wlan.hash_identifier(shared_raw)


def test_collector_rejects_foreign_event_types(clock: FrozenClock, store: BindingStore) -> None:
    nr = NRCollector(clock, store)
    with pytest.raises(CollectorError):
        nr.ingest(wlan_event(FixtureProfile(), clock.now()))


def test_release_removes_the_binding(
    clock: FrozenClock, store: BindingStore, profile: FixtureProfile
) -> None:
    collector = NRCollector(clock, store)
    collector.ingest(nr_event(profile, clock.now()))
    assert store.get(profile.nr_address) is not None
    collector.ingest(nr_event(profile, clock.now(), event_type=NrEventType.SESSION_RELEASED))
    assert store.get(profile.nr_address) is None


def test_wlan_disconnect_removes_the_binding(
    clock: FrozenClock, store: BindingStore, profile: FixtureProfile
) -> None:
    collector = WLANCollector(clock, store)
    collector.ingest(wlan_event(profile, clock.now()))
    collector.ingest(wlan_event(profile, clock.now(), event_type=WlanEventType.STA_DISCONNECTED))
    assert store.get(profile.wlan_address) is None


def test_binding_expires(clock: FrozenClock, store: BindingStore, profile: FixtureProfile) -> None:
    collector = NRCollector(clock, store)
    collector.ingest(nr_event(profile, clock.now()))
    clock.advance(seconds=profile.binding_lifetime_s + 1)
    assert store.get(profile.nr_address) is None


def test_claim_attributes_then_detects_a_competing_claim(
    clock: FrozenClock, store: BindingStore, profile: FixtureProfile
) -> None:
    NRCollector(clock, store).ingest(nr_event(profile, clock.now()))

    binding, consistent = store.claim(profile.nr_address, "dev-a")
    assert consistent is True
    assert binding is not None and binding.device_ref == "dev-a"

    again, still = store.claim(profile.nr_address, "dev-a")
    assert still is True and again is not None and again.device_ref == "dev-a"

    conflict, ok = store.claim(profile.nr_address, "dev-b")
    assert ok is False
    assert conflict is not None and conflict.device_ref == "dev-a"


def test_refresh_preserves_attribution_and_first_seen(
    clock: FrozenClock, store: BindingStore, profile: FixtureProfile
) -> None:
    collector = NRCollector(clock, store)
    first = collector.ingest(nr_event(profile, clock.now()))
    assert first is not None
    store.claim(profile.nr_address, "dev-a")

    clock.advance(seconds=10)
    refreshed = collector.ingest(
        nr_event(profile, clock.now(), event_type=NrEventType.SESSION_REFRESHED)
    )
    assert refreshed is not None
    assert refreshed.device_ref == "dev-a"
    assert refreshed.first_seen == first.first_seen
    assert refreshed.last_seen == first.last_seen + timedelta(seconds=10)


def test_synthetic_provider_rejects_non_fixture_events(
    clock: FrozenClock, profile: FixtureProfile
) -> None:
    provider = SyntheticFixtureProvider()
    live = nr_event(profile, clock.now()).model_copy(
        update={"source_mode": SourceMode.LIVE_TESTBED}
    )
    with pytest.raises(CollectorError):
        provider.add(live)


# --- transitions -----------------------------------------------------------


@pytest.fixture
def transitions(clock: FrozenClock, settings) -> TransitionCollector:
    return TransitionCollector(
        clock,
        rate_window_s=settings.transition.rate_window_s,
        repeat_threshold=settings.transition.repeat_threshold,
        transition_window_s=settings.transition.transition_window_s,
    )


def test_first_observation_is_not_a_transition(
    transitions: TransitionCollector, clock: FrozenClock
) -> None:
    assert transitions.observe("dev-a", AccessDomain.NR, at=clock.now()) is None
    assert transitions.context_for("dev-a", at=clock.now()) is TransitionContext.NONE


def test_cross_domain_change_is_detected_with_direction(
    transitions: TransitionCollector, clock: FrozenClock
) -> None:
    transitions.observe("dev-a", AccessDomain.NR, at=clock.now())
    clock.advance(seconds=5)
    event = transitions.observe("dev-a", AccessDomain.WLAN, at=clock.now())

    assert event is not None
    assert event.from_domain is AccessDomain.NR
    assert event.to_domain is AccessDomain.WLAN
    assert event.cross_domain is True
    assert event.gap_ms == 5000
    assert transitions.context_for("dev-a", at=clock.now()) is TransitionContext.NR_TO_WLAN


def test_reverse_direction(transitions: TransitionCollector, clock: FrozenClock) -> None:
    transitions.observe("dev-a", AccessDomain.WLAN, at=clock.now())
    clock.advance(seconds=2)
    transitions.observe("dev-a", AccessDomain.NR, at=clock.now())
    assert transitions.context_for("dev-a", at=clock.now()) is TransitionContext.WLAN_TO_NR


def test_address_change_within_a_domain_is_intra(
    transitions: TransitionCollector, clock: FrozenClock
) -> None:
    transitions.observe("dev-a", AccessDomain.WLAN, peer_address="10.0.0.1", at=clock.now())
    clock.advance(seconds=1)
    event = transitions.observe("dev-a", AccessDomain.WLAN, peer_address="10.0.0.2", at=clock.now())
    assert event is not None and event.cross_domain is False
    assert transitions.context_for("dev-a", at=clock.now()) is TransitionContext.INTRA


def test_context_returns_to_none_after_the_transition_window(
    transitions: TransitionCollector, clock: FrozenClock, settings
) -> None:
    transitions.observe("dev-a", AccessDomain.NR, at=clock.now())
    clock.advance(seconds=1)
    transitions.observe("dev-a", AccessDomain.WLAN, at=clock.now())
    assert transitions.is_transition_recent("dev-a", at=clock.now()) is True

    clock.advance(seconds=settings.transition.transition_window_s + 1)
    assert transitions.is_transition_recent("dev-a", at=clock.now()) is False
    assert transitions.context_for("dev-a", at=clock.now()) is TransitionContext.NONE


def test_repeated_transitions_reach_the_repeat_context(
    transitions: TransitionCollector, clock: FrozenClock, settings
) -> None:
    domains = [AccessDomain.NR, AccessDomain.WLAN]
    transitions.observe("dev-a", domains[0], at=clock.now())
    for index in range(1, settings.transition.repeat_threshold + 1):
        clock.advance(seconds=1)
        transitions.observe("dev-a", domains[index % 2], at=clock.now())
    assert transitions.context_for("dev-a", at=clock.now()) is TransitionContext.REPEATED


def test_transition_count_falls_out_of_the_rate_window(
    transitions: TransitionCollector, clock: FrozenClock, settings
) -> None:
    transitions.observe("dev-a", AccessDomain.NR, at=clock.now())
    clock.advance(seconds=1)
    transitions.observe("dev-a", AccessDomain.WLAN, at=clock.now())
    assert transitions.transitions_in_window("dev-a", at=clock.now()) == 1

    clock.advance(seconds=settings.transition.rate_window_s + 1)
    assert transitions.transitions_in_window("dev-a", at=clock.now()) == 0
