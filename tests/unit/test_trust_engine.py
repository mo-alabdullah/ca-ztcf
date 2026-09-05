"""The trust engine: six states, ordered rules, determinism."""

from __future__ import annotations

import pytest

from ca_ztcf.collectors.base import AccessDomain
from ca_ztcf.collectors.fixtures import nr_event, wlan_event
from ca_ztcf.evidence.assembler import AssemblerInputs
from ca_ztcf.identity.models import DeviceStatus
from ca_ztcf.trust_engine.engine import RULES
from ca_ztcf.trust_engine.states import STATE_DEFINITIONS, TrustState


def _evaluate(app_state, previous=None, **kwargs):
    record = app_state.assembler.assemble(AssemblerInputs(**kwargs))
    vector = app_state.predicates.evaluate(record)
    return app_state.trust_engine.evaluate(record, vector, previous_state=previous)


def _healthy(app_state, device_id, profile, clock, fresh_proof, domain=AccessDomain.NR):
    if domain is AccessDomain.NR:
        app_state.nr_collector.ingest(nr_event(profile, clock.now()))
        address = profile.nr_address
    else:
        app_state.wlan_collector.ingest(wlan_event(profile, clock.now()))
        address = profile.wlan_address
    binding, consistent = app_state.binding_store.claim(address, device_id)
    identity = app_state.registry.get(device_id)
    pop = app_state.proof_verifier.verify(identity, fresh_proof(device_id))
    return {
        "device_id": device_id,
        "identity": identity,
        "pop_result": pop,
        "binding": binding,
        "binding_consistent": consistent,
        "current_domain": domain,
        "evaluated_at": clock.now(),
    }


# --- state definitions -----------------------------------------------------


def test_every_state_has_a_four_axis_justification() -> None:
    assert set(STATE_DEFINITIONS) == set(TrustState)
    for state, definition in STATE_DEFINITIONS.items():
        assert definition.state is state
        assert definition.evidence_semantics.strip()
        assert definition.recovery_path.strip()
        assert definition.audit_meaning.strip()
        assert definition.policy_consequence.strip()


def test_unknown_and_untrusted_share_an_action_but_differ_elsewhere() -> None:
    """Distinct states may map to the same action; that is by design, not a defect."""
    unknown = STATE_DEFINITIONS[TrustState.UNKNOWN]
    untrusted = STATE_DEFINITIONS[TrustState.UNTRUSTED]
    assert "DENY" in unknown.policy_consequence
    assert "DENY" in untrusted.policy_consequence
    assert unknown.recovery_path != untrusted.recovery_path
    assert unknown.evidence_semantics != untrusted.evidence_semantics
    assert unknown.audit_meaning != untrusted.audit_meaning


def test_rules_are_ordered_and_uniquely_identified() -> None:
    ids = [rule.rule_id for rule in RULES]
    assert ids == ["R0", "R1", "R2", "R3", "R4", "R5"]
    assert len(set(ids)) == len(ids)


# --- state derivation ------------------------------------------------------


def test_unregistered_device_is_unknown_via_r0(app_state) -> None:
    result = _evaluate(app_state, device_id="dev-absent")
    assert result.new_state is TrustState.UNKNOWN
    assert result.firing_rule == "R0"
    assert result.reason_codes == ("DEVICE_NOT_REGISTERED",)


def test_disabled_device_is_untrusted_via_r1(
    app_state, registered, profile, clock, fresh_proof
) -> None:
    inputs = _healthy(app_state, registered, profile, clock, fresh_proof)
    app_state.registry.set_status(registered, DeviceStatus.SUSPENDED)
    inputs["identity"] = app_state.registry.get(registered)
    result = _evaluate(app_state, **inputs)
    assert result.new_state is TrustState.UNTRUSTED
    assert result.firing_rule == "R1"


def test_identity_mismatch_is_untrusted_via_r1(
    app_state, registered, profile, clock, fresh_proof, device_key
) -> None:
    _healthy(app_state, registered, profile, clock, fresh_proof)
    app_state.registry.register("dev-intruder", device_key.public_pem)
    binding, consistent = app_state.binding_store.claim(profile.nr_address, "dev-intruder")
    assert consistent is False

    result = _evaluate(
        app_state,
        device_id="dev-intruder",
        identity=app_state.registry.get("dev-intruder"),
        binding=binding,
        binding_consistent=False,
        current_domain=AccessDomain.NR,
        evaluated_at=clock.now(),
    )
    assert result.new_state is TrustState.UNTRUSTED
    assert result.firing_rule == "R1"
    assert "BINDING_CLAIMED_BY_ANOTHER_DEVICE" in result.reason_codes


def test_session_mismatch_is_suspicious_via_r2(
    app_state, registered, profile, clock, fresh_proof
) -> None:
    inputs = _healthy(app_state, registered, profile, clock, fresh_proof)
    inputs["session_consistent"] = False
    result = _evaluate(app_state, **inputs)
    assert result.new_state is TrustState.SUSPICIOUS
    assert result.firing_rule == "R2"
    assert "SESSION_IDENTITY_MISMATCH" in result.reason_codes


def test_excessive_transition_rate_is_suspicious_via_r2(
    app_state, registered, profile, clock, fresh_proof, settings
) -> None:
    inputs = _healthy(app_state, registered, profile, clock, fresh_proof)
    inputs["transitions_in_window"] = settings.transition.max_transitions_per_window + 1
    result = _evaluate(app_state, **inputs)
    assert result.new_state is TrustState.SUSPICIOUS
    assert result.firing_rule == "R2"


def test_domain_posture_failure_is_suspicious_via_r2(
    app_state, registered, profile, clock, fresh_proof
) -> None:
    app_state.wlan_collector.ingest(wlan_event(profile, clock.now(), akm="OPEN"))
    binding, consistent = app_state.binding_store.claim(profile.wlan_address, registered)
    identity = app_state.registry.get(registered)
    pop = app_state.proof_verifier.verify(identity, fresh_proof(registered))

    result = _evaluate(
        app_state,
        device_id=registered,
        identity=identity,
        pop_result=pop,
        binding=binding,
        binding_consistent=consistent,
        current_domain=AccessDomain.WLAN,
        evaluated_at=clock.now(),
    )
    assert result.new_state is TrustState.SUSPICIOUS
    assert "WLAN_AKM_NOT_ALLOWED" in result.reason_codes


def test_no_binding_is_degraded_not_suspicious(app_state, registered, clock) -> None:
    """A missing binding is absent evidence, so it must never read as a contradiction."""
    result = _evaluate(
        app_state,
        device_id=registered,
        identity=app_state.registry.get(registered),
        binding=None,
        evaluated_at=clock.now(),
    )
    assert result.new_state is TrustState.DEGRADED
    assert result.firing_rule == "R3"


def test_stale_binding_is_degraded_via_r3(
    app_state, registered, profile, clock, fresh_proof, settings
) -> None:
    inputs = _healthy(app_state, registered, profile, clock, fresh_proof)
    clock.advance(seconds=settings.evidence.binding_freshness_max_s + 1)
    inputs["evaluated_at"] = clock.now()
    result = _evaluate(app_state, **inputs)
    assert result.new_state is TrustState.DEGRADED
    assert result.firing_rule == "R3"


def test_stale_proof_is_degraded_via_r3(
    app_state, registered, profile, clock, fresh_proof, settings
) -> None:
    inputs = _healthy(app_state, registered, profile, clock, fresh_proof)
    clock.advance(seconds=settings.evidence.proof_of_possession_ttl_s + 1)
    inputs["evaluated_at"] = clock.now()
    inputs["binding"] = None  # binding would also be stale; isolate the proof
    result = _evaluate(app_state, **inputs)
    assert result.new_state is TrustState.DEGRADED


def test_recent_transition_is_transitional_via_r4(
    app_state, registered, profile, clock, fresh_proof
) -> None:
    inputs = _healthy(app_state, registered, profile, clock, fresh_proof)
    inputs["transition_recent"] = True
    result = _evaluate(app_state, **inputs)
    assert result.new_state is TrustState.TRANSITIONAL
    assert result.firing_rule == "R4"


def test_healthy_device_is_stable_via_r5(
    app_state, registered, profile, clock, fresh_proof
) -> None:
    result = _evaluate(app_state, **_healthy(app_state, registered, profile, clock, fresh_proof))
    assert result.new_state is TrustState.STABLE
    assert result.firing_rule == "R5"
    assert result.reason_codes == ("EVIDENCE_CONSISTENT",)


def test_contradiction_outranks_staleness(
    app_state, registered, profile, clock, fresh_proof, settings, device_key
) -> None:
    """A stale binding must not mask a competing claim."""
    _healthy(app_state, registered, profile, clock, fresh_proof)
    app_state.registry.register("dev-intruder", device_key.public_pem)
    binding, _ = app_state.binding_store.claim(profile.nr_address, "dev-intruder")
    clock.advance(seconds=settings.evidence.binding_freshness_max_s + 1)

    result = _evaluate(
        app_state,
        device_id="dev-intruder",
        identity=app_state.registry.get("dev-intruder"),
        binding=binding,
        binding_consistent=False,
        current_domain=AccessDomain.NR,
        evaluated_at=clock.now(),
    )
    assert result.new_state is TrustState.UNTRUSTED


def test_degradation_outranks_transition(
    app_state, registered, profile, clock, fresh_proof
) -> None:
    """A device mid-transition whose evidence is missing is DEGRADED, not TRANSITIONAL."""
    result = _evaluate(
        app_state,
        device_id=registered,
        identity=app_state.registry.get(registered),
        binding=None,
        transition_recent=True,
        evaluated_at=clock.now(),
    )
    assert result.new_state is TrustState.DEGRADED


# --- determinism -----------------------------------------------------------


def test_repeated_evaluation_of_one_record_is_identical(
    app_state, registered, profile, clock, fresh_proof
) -> None:
    record = app_state.assembler.assemble(
        AssemblerInputs(**_healthy(app_state, registered, profile, clock, fresh_proof))
    )
    outcomes = []
    for _ in range(25):
        vector = app_state.predicates.evaluate(record)
        result = app_state.trust_engine.evaluate(record, vector)
        outcomes.append(
            (
                result.new_state,
                result.firing_rule,
                result.reason_codes,
                tuple(sorted(vector.as_map().items())),
            )
        )
    assert len(set(outcomes)) == 1


def test_evaluation_records_the_configuration_hash(
    app_state, registered, profile, clock, fresh_proof
) -> None:
    result = _evaluate(app_state, **_healthy(app_state, registered, profile, clock, fresh_proof))
    assert result.config_hash == app_state.settings.config_hash
    assert result.engine_duration_ns >= 0
    assert len(result.predicate_vector) == 11


# --- state manager ---------------------------------------------------------


def test_state_manager_tracks_previous_state(
    app_state, registered, profile, clock, fresh_proof
) -> None:
    manager = app_state.state_manager
    first = _evaluate(app_state, **_healthy(app_state, registered, profile, clock, fresh_proof))
    assert manager.record(first) is None
    assert manager.current(registered) is TrustState.STABLE

    second = _evaluate(
        app_state,
        previous=manager.current(registered),
        device_id=registered,
        identity=app_state.registry.get(registered),
        binding=None,
        evaluated_at=clock.now(),
    )
    assert second.previous_state is TrustState.STABLE
    assert second.state_changed is True
    manager.record(second)
    assert manager.current(registered) is TrustState.DEGRADED
    assert len(manager.history(registered)) == 2


@pytest.mark.parametrize("state", list(TrustState))
def test_every_state_is_reachable_in_the_definitions(state: TrustState) -> None:
    assert STATE_DEFINITIONS[state].state is state
