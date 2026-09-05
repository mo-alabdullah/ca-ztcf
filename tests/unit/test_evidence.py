"""Evidence model, assembler and freshness."""

from __future__ import annotations

import pytest

from ca_ztcf.clock import FrozenClock
from ca_ztcf.collectors.base import AccessDomain, SourceMode
from ca_ztcf.collectors.fixtures import nr_event, wlan_event
from ca_ztcf.evidence import models as m
from ca_ztcf.evidence.assembler import AssemblerInputs, evaluate_posture
from ca_ztcf.evidence.freshness import age_seconds, freshness_status, is_fresh
from ca_ztcf.version import SCHEMA_VERSION


def test_freshness_boundary_is_inclusive(clock: FrozenClock) -> None:
    start = clock.now()
    clock.advance(seconds=30)
    assert is_fresh(start, clock.now(), 30) is True
    clock.advance(milliseconds=1)
    assert is_fresh(start, clock.now(), 30) is False


def test_freshness_status_classification(clock: FrozenClock) -> None:
    start = clock.now()
    assert freshness_status(None, clock.now(), 30) is m.ValidationStatus.MISSING
    assert freshness_status(start, clock.now(), 30) is m.ValidationStatus.VALID
    clock.advance(seconds=31)
    assert freshness_status(start, clock.now(), 30) is m.ValidationStatus.STALE
    assert age_seconds(start, clock.now()) == pytest.approx(31.0)


def test_negative_ttl_is_rejected(clock: FrozenClock) -> None:
    with pytest.raises(ValueError, match="negative"):
        is_fresh(clock.now(), clock.now(), -1)


def _assemble(app_state, **kwargs):
    return app_state.assembler.assemble(AssemblerInputs(**kwargs))


def test_every_item_carries_provenance(app_state, registered, profile, clock) -> None:
    app_state.nr_collector.ingest(nr_event(profile, clock.now()))
    binding = app_state.binding_store.get(profile.nr_address)

    record = _assemble(
        app_state,
        device_id=registered,
        identity=app_state.registry.get(registered),
        binding=binding,
        current_domain=AccessDomain.NR,
        evaluated_at=clock.now(),
    )

    assert record.schema_version == SCHEMA_VERSION
    assert record.config_hash == app_state.settings.config_hash
    for name, item in record.items.items():
        assert item.name == name
        assert item.source, f"{name} has no source"
        assert item.source_mode is not None, f"{name} has no source mode"
        assert item.observed_at is not None, f"{name} has no observation time"
        assert item.category is m.ITEM_CATEGORIES[name]


def test_all_six_categories_are_populated(app_state, registered, profile, clock) -> None:
    app_state.nr_collector.ingest(nr_event(profile, clock.now()))
    record = _assemble(
        app_state,
        device_id=registered,
        identity=app_state.registry.get(registered),
        binding=app_state.binding_store.get(profile.nr_address),
        current_domain=AccessDomain.NR,
        evaluated_at=clock.now(),
    )
    for category in m.EvidenceCategory:
        assert record.by_category(category), f"category {category} is empty"


def test_synthetic_provenance_is_visible_on_the_record(
    app_state, registered, profile, clock
) -> None:
    app_state.nr_collector.ingest(nr_event(profile, clock.now()))
    record = _assemble(
        app_state,
        device_id=registered,
        identity=app_state.registry.get(registered),
        binding=app_state.binding_store.get(profile.nr_address),
        current_domain=AccessDomain.NR,
        evaluated_at=clock.now(),
    )
    assert record.contains_synthetic() is True
    assert SourceMode.SYNTHETIC_FIXTURE in record.source_modes()


def test_missing_binding_produces_missing_not_invalid(app_state, registered, clock) -> None:
    record = _assemble(
        app_state,
        device_id=registered,
        identity=app_state.registry.get(registered),
        binding=None,
        evaluated_at=clock.now(),
    )
    assert record.flag(m.BINDING_PRESENT) is False
    item = record.item(m.BINDING_PRESENT)
    assert item is not None and item.validation is m.ValidationStatus.MISSING
    assert record.flag(m.IDENTITY_MISMATCH) is False


def test_stale_binding_is_marked_stale(app_state, registered, profile, clock, settings) -> None:
    app_state.nr_collector.ingest(nr_event(profile, clock.now()))
    binding = app_state.binding_store.get(profile.nr_address)
    clock.advance(seconds=settings.evidence.binding_freshness_max_s + 1)

    record = _assemble(
        app_state,
        device_id=registered,
        identity=app_state.registry.get(registered),
        binding=binding,
        current_domain=AccessDomain.NR,
        evaluated_at=clock.now(),
    )
    assert record.flag(m.BINDING_FRESH) is False
    item = record.item(m.BINDING_FRESH)
    assert item is not None and item.validation is m.ValidationStatus.STALE


def test_posture_allows_when_allow_list_is_empty(app_state, profile, clock, settings) -> None:
    app_state.nr_collector.ingest(nr_event(profile, clock.now()))
    binding = app_state.binding_store.get(profile.nr_address)
    outcome = evaluate_posture(binding, settings)
    assert outcome.ok is True
    assert outcome.unauthorized is False


def test_posture_rejects_a_disallowed_akm(app_state, profile, clock, settings) -> None:
    app_state.wlan_collector.ingest(wlan_event(profile, clock.now(), akm="OPEN"))
    binding = app_state.binding_store.get(profile.wlan_address)
    outcome = evaluate_posture(binding, settings)
    assert outcome.ok is False
    assert outcome.unauthorized is True
    assert outcome.reason == "WLAN_AKM_NOT_ALLOWED"


def test_posture_rejects_failed_eap_without_flagging_unauthorised(
    app_state, profile, clock, settings
) -> None:
    app_state.wlan_collector.ingest(wlan_event(profile, clock.now(), eap_success=False))
    binding = app_state.binding_store.get(profile.wlan_address)
    outcome = evaluate_posture(binding, settings)
    assert outcome.ok is False
    assert outcome.reason == "WLAN_EAP_NOT_SUCCESSFUL"


def test_posture_without_binding_is_not_evaluable(settings) -> None:
    outcome = evaluate_posture(None, settings)
    assert outcome.ok is False
    assert outcome.reason == "NO_BINDING_TO_EVALUATE"
    assert outcome.unauthorized is False
