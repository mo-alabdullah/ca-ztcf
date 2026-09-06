"""The three interchangeable decision strategies."""

from __future__ import annotations

import pytest

from ca_ztcf.collectors.base import AccessDomain
from ca_ztcf.collectors.fixtures import nr_event, wlan_event
from ca_ztcf.collectors.transition import TransitionContext
from ca_ztcf.policy.models import PolicyAction
from ca_ztcf.strategies.interface import AccessRequest
from ca_ztcf.trust_engine.states import TrustState

# Short aliases used throughout this module's parametrised tables.
S = TrustState
TC = TransitionContext
A = PolicyAction


def _seed_nr(app_state, profile, clock) -> None:
    app_state.nr_collector.ingest(nr_event(profile, clock.now()))


def _seed_wlan(app_state, profile, clock) -> None:
    app_state.wlan_collector.ingest(wlan_event(profile, clock.now()))


def _request(device_id, profile, domain, clock, proof=None, session=None):
    address = profile.nr_address if domain is AccessDomain.NR else profile.wlan_address
    return AccessRequest(
        device_id=device_id,
        peer_address=address,
        domain=domain,
        session_identity=session if session is not None else device_id,
        proof=proof,
        at=clock.now(),
    )


PRIMARY_STRATEGIES = {"ca_ztcf", "independent", "static_continuity"}
SENSITIVITY_STRATEGIES = {"static_continuity_ttl30", "static_continuity_ttl1800"}


def test_all_strategies_share_one_interface(app_state) -> None:
    assert set(app_state.strategies) == PRIMARY_STRATEGIES | SENSITIVITY_STRATEGIES
    for strategy in app_state.strategies.values():
        assert hasattr(strategy, "decide")


def test_sensitivity_variants_differ_only_in_token_lifetime(app_state) -> None:
    """B30 and B1800 must be the same algorithm at a different lifetime.

    Otherwise the TTL sensitivity analysis would be comparing two things at once
    and any difference could not be attributed to the lifetime.
    """
    baseline = app_state.strategy("static_continuity")
    lifetimes = {"static_continuity": baseline.token_ttl_s}
    for name in SENSITIVITY_STRATEGIES:
        variant = app_state.strategy(name)
        assert type(variant) is type(baseline)
        assert variant.definition.kind == baseline.definition.kind
        lifetimes[name] = variant.token_ttl_s
    assert lifetimes == {
        "static_continuity": 300,
        "static_continuity_ttl30": 30,
        "static_continuity_ttl1800": 1800,
    }


# --- CA-ZTCF ---------------------------------------------------------------


def test_ca_ztcf_stable_then_transitional_then_stable(
    app_state, registered, profile, clock, fresh_proof, settings
) -> None:
    strategy = app_state.strategy("ca_ztcf")

    _seed_nr(app_state, profile, clock)
    first = strategy.decide(
        _request(registered, profile, AccessDomain.NR, clock, fresh_proof(registered))
    )
    assert first.decision.trust_state is S.STABLE
    assert first.decision.action is A.ALLOW

    clock.advance(seconds=5)
    _seed_wlan(app_state, profile, clock)
    second = strategy.decide(
        _request(registered, profile, AccessDomain.WLAN, clock, fresh_proof(registered))
    )
    assert second.decision.trust_state is S.TRANSITIONAL
    assert second.decision.transition_context is TC.NR_TO_WLAN
    assert second.decision.action is A.ALLOW_WITH_RESTRICTIONS

    # After the transition window, with refreshed evidence, the device settles.
    clock.advance(seconds=settings.transition.transition_window_s + 1)
    _seed_wlan(app_state, profile, clock)
    third = strategy.decide(
        _request(registered, profile, AccessDomain.WLAN, clock, fresh_proof(registered))
    )
    assert third.decision.trust_state is S.STABLE
    assert third.decision.action is A.ALLOW


def test_ca_ztcf_recovers_from_degraded_to_stable(
    app_state, registered, profile, clock, fresh_proof, settings
) -> None:
    strategy = app_state.strategy("ca_ztcf")
    _seed_nr(app_state, profile, clock)
    assert (
        strategy.decide(
            _request(registered, profile, AccessDomain.NR, clock, fresh_proof(registered))
        ).decision.trust_state
        is S.STABLE
    )

    # Collector outage: no refresh, so the binding goes stale.
    clock.advance(seconds=settings.evidence.binding_freshness_max_s + 1)
    degraded = strategy.decide(
        _request(registered, profile, AccessDomain.NR, clock, fresh_proof(registered))
    )
    assert degraded.decision.trust_state is S.DEGRADED
    assert degraded.decision.action is A.STEP_UP_AUTHENTICATION

    # Collector recovers, evidence refreshes; a legitimate device is never denied.
    _seed_nr(app_state, profile, clock)
    recovered = strategy.decide(
        _request(registered, profile, AccessDomain.NR, clock, fresh_proof(registered))
    )
    assert recovered.decision.trust_state is S.STABLE
    assert recovered.decision.action is A.ALLOW


def test_ca_ztcf_repeated_transitions_escalate_to_step_up(
    app_state, registered, profile, clock, fresh_proof
) -> None:
    strategy = app_state.strategy("ca_ztcf")
    domains = [AccessDomain.NR, AccessDomain.WLAN]

    last = None
    for index in range(5):
        domain = domains[index % 2]
        if domain is AccessDomain.NR:
            _seed_nr(app_state, profile, clock)
        else:
            _seed_wlan(app_state, profile, clock)
        last = strategy.decide(
            _request(registered, profile, domain, clock, fresh_proof(registered))
        )
        clock.advance(seconds=2)

    assert last is not None
    assert last.decision.transition_context is TC.REPEATED
    assert last.decision.action in {A.STEP_UP_AUTHENTICATION, A.QUARANTINE}


def test_ca_ztcf_denies_an_unregistered_device(app_state, profile, clock) -> None:
    outcome = app_state.strategy("ca_ztcf").decide(
        _request("dev-not-enrolled", profile, AccessDomain.NR, clock)
    )
    assert outcome.decision.trust_state is S.UNKNOWN
    assert outcome.decision.action is A.DENY
    assert "REGISTRATION_REQUIRED" in outcome.decision.reason_codes


def test_ca_ztcf_denies_identity_mismatch(
    app_state, registered, profile, clock, fresh_proof, device_key
) -> None:
    strategy = app_state.strategy("ca_ztcf")
    _seed_nr(app_state, profile, clock)
    strategy.decide(_request(registered, profile, AccessDomain.NR, clock, fresh_proof(registered)))

    app_state.registry.register("dev-intruder", device_key.public_pem)
    outcome = strategy.decide(_request("dev-intruder", profile, AccessDomain.NR, clock))
    assert outcome.decision.trust_state is S.UNTRUSTED
    assert outcome.decision.action is A.DENY
    assert "VALIDATION_FAILED" in outcome.decision.reason_codes


def test_ca_ztcf_flags_session_mismatch_as_suspicious(
    app_state, registered, profile, clock, fresh_proof
) -> None:
    _seed_nr(app_state, profile, clock)
    outcome = app_state.strategy("ca_ztcf").decide(
        _request(
            registered,
            profile,
            AccessDomain.NR,
            clock,
            fresh_proof(registered),
            session="someone-elses-session",
        )
    )
    assert outcome.decision.trust_state is S.SUSPICIOUS
    assert outcome.decision.action is A.REAUTHENTICATE


def test_ca_ztcf_produces_a_full_trace(app_state, registered, profile, clock, fresh_proof) -> None:
    _seed_nr(app_state, profile, clock)
    outcome = app_state.strategy("ca_ztcf").decide(
        _request(registered, profile, AccessDomain.NR, clock, fresh_proof(registered))
    )
    assert outcome.evidence is not None
    assert outcome.predicates is not None
    assert outcome.trust_evaluation is not None
    assert outcome.decision.evidence_record_id == outcome.evidence.record_id
    assert outcome.decision.predicate_trace_id == outcome.predicates.trace_id


# --- Baseline A ------------------------------------------------------------


def test_baseline_a_requires_reauthentication_on_transition(
    app_state, registered, profile, clock, fresh_proof
) -> None:
    strategy = app_state.strategy("independent")
    _seed_nr(app_state, profile, clock)
    first = strategy.decide(
        _request(registered, profile, AccessDomain.NR, clock, fresh_proof(registered))
    )
    assert first.decision.action is A.ALLOW

    clock.advance(seconds=5)
    _seed_wlan(app_state, profile, clock)
    second = strategy.decide(
        _request(registered, profile, AccessDomain.WLAN, clock, fresh_proof(registered))
    )
    assert second.decision.action is A.REAUTHENTICATE
    assert "BASELINE_A_TRANSITION_REQUIRES_FULL_REAUTHENTICATION" in second.decision.reason_codes


def test_baseline_a_produces_no_evidence_trace(
    app_state, registered, profile, clock, fresh_proof
) -> None:
    outcome = app_state.strategy("independent").decide(
        _request(registered, profile, AccessDomain.NR, clock, fresh_proof(registered))
    )
    assert outcome.evidence is None
    assert outcome.trust_evaluation is None
    assert outcome.decision.strategy == "independent"


def test_baseline_a_denies_unregistered(app_state, profile, clock) -> None:
    outcome = app_state.strategy("independent").decide(
        _request("dev-nope", profile, AccessDomain.NR, clock)
    )
    assert outcome.decision.action is A.DENY


# --- Baseline B ------------------------------------------------------------


def test_baseline_b_reuses_its_token_across_a_transition(
    app_state, registered, profile, clock, fresh_proof
) -> None:
    """The defining weakness of this baseline, asserted so it stays observable."""
    strategy = app_state.strategy("static_continuity")
    _seed_nr(app_state, profile, clock)
    first = strategy.decide(
        _request(registered, profile, AccessDomain.NR, clock, fresh_proof(registered))
    )
    assert first.decision.action is A.ALLOW
    assert "BASELINE_B_SESSION_TOKEN_ISSUED" in first.decision.reason_codes

    clock.advance(seconds=5)
    second = strategy.decide(_request(registered, profile, AccessDomain.WLAN, clock))
    assert second.decision.action is A.ALLOW
    assert "BASELINE_B_SESSION_TOKEN_VALID" in second.decision.reason_codes


def test_baseline_b_token_expires(app_state, registered, profile, clock, fresh_proof) -> None:
    strategy = app_state.strategy("static_continuity")
    _seed_nr(app_state, profile, clock)
    strategy.decide(_request(registered, profile, AccessDomain.NR, clock, fresh_proof(registered)))
    assert strategy.tokens_outstanding() == 1

    clock.advance(seconds=strategy.token_ttl_s + 1)
    # No proof presented after expiry: the baseline can no longer wave the device through.
    expired = strategy.decide(_request(registered, profile, AccessDomain.NR, clock))
    assert expired.decision.action is not A.ALLOW
    assert expired.decision.trust_state is S.DEGRADED


def test_baseline_b_reissues_after_expiry_with_a_fresh_proof(
    app_state, registered, profile, clock, fresh_proof
) -> None:
    strategy = app_state.strategy("static_continuity")
    _seed_nr(app_state, profile, clock)
    strategy.decide(_request(registered, profile, AccessDomain.NR, clock, fresh_proof(registered)))
    clock.advance(seconds=strategy.token_ttl_s + 1)
    reissued = strategy.decide(
        _request(registered, profile, AccessDomain.NR, clock, fresh_proof(registered))
    )
    assert reissued.decision.action is A.ALLOW
    assert "BASELINE_B_SESSION_TOKEN_ISSUED" in reissued.decision.reason_codes


def test_baseline_b_still_denies_an_unregistered_device(app_state, profile, clock) -> None:
    outcome = app_state.strategy("static_continuity").decide(
        _request("dev-nope", profile, AccessDomain.NR, clock)
    )
    assert outcome.decision.action is A.DENY


@pytest.mark.parametrize("strategy_name", ["ca_ztcf", "independent", "static_continuity"])
def test_every_strategy_emits_the_same_decision_shape(
    app_state, registered, profile, clock, fresh_proof, strategy_name
) -> None:
    _seed_nr(app_state, profile, clock)
    decision = (
        app_state.strategy(strategy_name)
        .decide(_request(registered, profile, AccessDomain.NR, clock, fresh_proof(registered)))
        .decision
    )
    assert decision.strategy == strategy_name
    assert decision.config_hash == app_state.settings.config_hash
    assert decision.decision_id
    assert decision.scope.name
    assert decision.reason_codes
