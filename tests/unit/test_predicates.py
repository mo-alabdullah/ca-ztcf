"""The eleven predicates C1-C11."""

from __future__ import annotations

from ca_ztcf.collectors.base import AccessDomain
from ca_ztcf.collectors.fixtures import nr_event, wlan_event
from ca_ztcf.evidence.assembler import AssemblerInputs
from ca_ztcf.evidence.predicates import PREDICATE_NAMES
from ca_ztcf.evidence.predicates import PredicateId as P
from ca_ztcf.identity.models import DeviceStatus


def _vector(app_state, **kwargs):
    record = app_state.assembler.assemble(AssemblerInputs(**kwargs))
    return record, app_state.predicates.evaluate(record)


def _healthy(app_state, device_id, profile, clock, fresh_proof):
    app_state.nr_collector.ingest(nr_event(profile, clock.now()))
    binding, consistent = app_state.binding_store.claim(profile.nr_address, device_id)
    identity = app_state.registry.get(device_id)
    proof = fresh_proof(device_id)
    pop = app_state.proof_verifier.verify(identity, proof)
    return {
        "device_id": device_id,
        "identity": identity,
        "pop_result": pop,
        "binding": binding,
        "binding_consistent": consistent,
        "current_domain": AccessDomain.NR,
        "evaluated_at": clock.now(),
    }


def test_all_eleven_predicates_are_always_evaluated(app_state, registered) -> None:
    _, vector = _vector(app_state, device_id=registered)
    assert len(vector.results) == 11
    assert {r.predicate_id for r in vector.results} == set(P)
    for result in vector.results:
        assert result.name == PREDICATE_NAMES[result.predicate_id]
        assert result.reason, f"{result.predicate_id} returned no reason"


def test_predicates_report_evidence_references(app_state, registered) -> None:
    _, vector = _vector(app_state, device_id=registered)
    for result in vector.results:
        assert result.evidence_refs, f"{result.predicate_id} cites no evidence"


def test_healthy_device_satisfies_the_positive_predicates(
    app_state, registered, profile, clock, fresh_proof
) -> None:
    _, vector = _vector(app_state, **_healthy(app_state, registered, profile, clock, fresh_proof))
    for pid in (P.C1, P.C2, P.C3, P.C4, P.C5, P.C6, P.C8, P.C9, P.C10, P.C11):
        assert vector.ok(pid) is True, f"{pid} failed: {vector.get(pid).reason}"
    assert vector.ok(P.C7) is False


def test_c1_fails_for_unregistered_device(app_state) -> None:
    _, vector = _vector(app_state, device_id="dev-absent")
    assert vector.ok(P.C1) is False
    assert vector.get(P.C1).reason == "DEVICE_NOT_REGISTERED"


def test_c1_fails_for_revoked_device(app_state, registered, profile, clock, fresh_proof) -> None:
    inputs = _healthy(app_state, registered, profile, clock, fresh_proof)
    app_state.registry.set_status(registered, DeviceStatus.REVOKED)
    inputs["identity"] = app_state.registry.get(registered)
    _, vector = _vector(app_state, **inputs)
    assert vector.ok(P.C1) is False
    assert "DEVICE_NOT_ENABLED" in vector.get(P.C1).reason


def test_c2_fails_when_no_proof_is_presented(app_state, registered) -> None:
    identity = app_state.registry.get(registered)
    _, vector = _vector(app_state, device_id=registered, identity=identity)
    assert vector.ok(P.C2) is False
    assert vector.get(P.C2).reason == "POP_NOT_PRESENTED"


def test_c2_fails_when_proof_is_stale(
    app_state, registered, profile, clock, fresh_proof, settings
) -> None:
    inputs = _healthy(app_state, registered, profile, clock, fresh_proof)
    clock.advance(seconds=settings.evidence.proof_of_possession_ttl_s + 1)
    inputs["evaluated_at"] = clock.now()
    _, vector = _vector(app_state, **inputs)
    assert vector.ok(P.C2) is False
    assert vector.get(P.C2).reason == "POP_STALE"


def test_c3_and_c4_fail_without_a_binding(app_state, registered) -> None:
    identity = app_state.registry.get(registered)
    _, vector = _vector(app_state, device_id=registered, identity=identity)
    assert vector.ok(P.C3) is False
    assert vector.ok(P.C4) is False
    assert vector.get(P.C4).reason == "NO_ACCESS_BINDING_FOR_PEER_ADDRESS"


def test_c4_fails_when_the_binding_is_stale(
    app_state, registered, profile, clock, fresh_proof, settings
) -> None:
    inputs = _healthy(app_state, registered, profile, clock, fresh_proof)
    clock.advance(seconds=settings.evidence.binding_freshness_max_s + 1)
    inputs["evaluated_at"] = clock.now()
    _, vector = _vector(app_state, **inputs)
    assert vector.ok(P.C3) is True
    assert vector.ok(P.C4) is False
    assert vector.get(P.C4).reason.startswith("BINDING_STALE")


def test_c5_fails_on_a_competing_claim(
    app_state, registered, profile, clock, fresh_proof, device_key
) -> None:
    _healthy(app_state, registered, profile, clock, fresh_proof)
    app_state.registry.register("dev-intruder", device_key.public_pem)
    binding, consistent = app_state.binding_store.claim(profile.nr_address, "dev-intruder")
    assert consistent is False

    _, vector = _vector(
        app_state,
        device_id="dev-intruder",
        identity=app_state.registry.get("dev-intruder"),
        binding=binding,
        binding_consistent=False,
        current_domain=AccessDomain.NR,
        evaluated_at=clock.now(),
    )
    assert vector.ok(P.C5) is False
    assert vector.get(P.C5).reason == "BINDING_CLAIMED_BY_ANOTHER_DEVICE"


def test_c6_and_c7_are_complementary(app_state, registered, profile, clock, fresh_proof) -> None:
    inputs = _healthy(app_state, registered, profile, clock, fresh_proof)
    inputs["transition_recent"] = True
    _, vector = _vector(app_state, **inputs)
    assert vector.ok(P.C7) is True
    assert vector.ok(P.C6) is False


def test_c8_fails_above_the_transition_rate_limit(
    app_state, registered, profile, clock, fresh_proof, settings
) -> None:
    inputs = _healthy(app_state, registered, profile, clock, fresh_proof)
    inputs["transitions_in_window"] = settings.transition.max_transitions_per_window + 1
    _, vector = _vector(app_state, **inputs)
    assert vector.ok(P.C8) is False
    assert vector.get(P.C8).reason.startswith("TRANSITION_RATE_EXCEEDED")


def test_c9_fails_above_the_authentication_failure_limit(
    app_state, registered, profile, clock, fresh_proof, settings
) -> None:
    inputs = _healthy(app_state, registered, profile, clock, fresh_proof)
    inputs["authentication_failure_count"] = settings.security.max_authn_failures + 1
    _, vector = _vector(app_state, **inputs)
    assert vector.ok(P.C9) is False
    assert vector.get(P.C9).reason.startswith("AUTHN_FAILURES_EXCEEDED")


def test_c10_fails_on_session_mismatch(app_state, registered, profile, clock, fresh_proof) -> None:
    inputs = _healthy(app_state, registered, profile, clock, fresh_proof)
    inputs["session_consistent"] = False
    _, vector = _vector(app_state, **inputs)
    assert vector.ok(P.C10) is False
    assert vector.get(P.C10).reason == "SESSION_IDENTITY_MISMATCH"


def test_c11_fails_on_disallowed_akm(app_state, registered, profile, clock) -> None:
    app_state.wlan_collector.ingest(wlan_event(profile, clock.now(), akm="OPEN"))
    binding = app_state.binding_store.get(profile.wlan_address)
    _, vector = _vector(
        app_state,
        device_id=registered,
        identity=app_state.registry.get(registered),
        binding=binding,
        current_domain=AccessDomain.WLAN,
        evaluated_at=clock.now(),
    )
    assert vector.ok(P.C11) is False
    assert vector.get(P.C11).reason == "WLAN_AKM_NOT_ALLOWED"
