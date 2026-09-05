"""Policy matrix, decisions and the in-memory enforcement point."""

from __future__ import annotations

import pytest

from ca_ztcf.collectors.transition import TransitionContext
from ca_ztcf.enforcement.interface import topic_matches
from ca_ztcf.enforcement.models import EnforcementRequest, ResourceOperation
from ca_ztcf.policy.models import PolicyAction
from ca_ztcf.trust_engine.states import TrustState

# Short aliases used throughout this module's parametrised tables.
S = TrustState
TC = TransitionContext
A = PolicyAction

EXPECTED_MATRIX: dict[tuple[S, TC], A] = {
    (S.UNKNOWN, TC.NONE): A.DENY,
    (S.UNKNOWN, TC.NR_TO_WLAN): A.DENY,
    (S.UNKNOWN, TC.WLAN_TO_NR): A.DENY,
    (S.UNKNOWN, TC.INTRA): A.DENY,
    (S.UNKNOWN, TC.REPEATED): A.DENY,
    (S.UNTRUSTED, TC.NONE): A.DENY,
    (S.UNTRUSTED, TC.NR_TO_WLAN): A.DENY,
    (S.UNTRUSTED, TC.WLAN_TO_NR): A.DENY,
    (S.UNTRUSTED, TC.INTRA): A.DENY,
    (S.UNTRUSTED, TC.REPEATED): A.DENY,
    (S.SUSPICIOUS, TC.NONE): A.REAUTHENTICATE,
    (S.SUSPICIOUS, TC.INTRA): A.REAUTHENTICATE,
    (S.SUSPICIOUS, TC.NR_TO_WLAN): A.QUARANTINE,
    (S.SUSPICIOUS, TC.WLAN_TO_NR): A.QUARANTINE,
    (S.SUSPICIOUS, TC.REPEATED): A.QUARANTINE,
    (S.DEGRADED, TC.NONE): A.STEP_UP_AUTHENTICATION,
    (S.DEGRADED, TC.NR_TO_WLAN): A.STEP_UP_AUTHENTICATION,
    (S.DEGRADED, TC.WLAN_TO_NR): A.STEP_UP_AUTHENTICATION,
    (S.DEGRADED, TC.INTRA): A.STEP_UP_AUTHENTICATION,
    (S.DEGRADED, TC.REPEATED): A.STEP_UP_AUTHENTICATION,
    (S.TRANSITIONAL, TC.NONE): A.ALLOW_WITH_RESTRICTIONS,
    (S.TRANSITIONAL, TC.NR_TO_WLAN): A.ALLOW_WITH_RESTRICTIONS,
    (S.TRANSITIONAL, TC.WLAN_TO_NR): A.ALLOW_WITH_RESTRICTIONS,
    (S.TRANSITIONAL, TC.INTRA): A.ALLOW_WITH_RESTRICTIONS,
    (S.TRANSITIONAL, TC.REPEATED): A.STEP_UP_AUTHENTICATION,
    (S.STABLE, TC.NONE): A.ALLOW,
    (S.STABLE, TC.INTRA): A.ALLOW,
    (S.STABLE, TC.NR_TO_WLAN): A.ALLOW_WITH_RESTRICTIONS,
    (S.STABLE, TC.WLAN_TO_NR): A.ALLOW_WITH_RESTRICTIONS,
    (S.STABLE, TC.REPEATED): A.ALLOW_WITH_RESTRICTIONS,
}


@pytest.mark.parametrize(("key", "expected"), sorted(EXPECTED_MATRIX.items(), key=str))
def test_policy_matrix_entry(app_state, key, expected) -> None:
    state, context = key
    outcome = app_state.policy_matrix.lookup(state, context)
    assert outcome.action is expected, (
        f"{state}/{context} -> {outcome.action}, rule {outcome.rule_id}"
    )


def test_matrix_is_total(app_state) -> None:
    """Every (state, context) pair must match a declared rule, never the default."""
    coverage = app_state.policy_matrix.coverage()
    assert len(coverage) == len(S) * len(TC)
    assert [key for key, rule in coverage.items() if rule == "DEFAULT"] == []


def test_unknown_and_untrusted_deny_for_different_reasons(app_state) -> None:
    unknown = app_state.policy_matrix.lookup(S.UNKNOWN, TC.NONE)
    untrusted = app_state.policy_matrix.lookup(S.UNTRUSTED, TC.NONE)
    assert unknown.action is untrusted.action is A.DENY
    assert unknown.reason_codes == ("REGISTRATION_REQUIRED",)
    assert untrusted.reason_codes == ("VALIDATION_FAILED",)
    assert unknown.rule_id != untrusted.rule_id


def test_scope_substitutes_the_device_id(app_state) -> None:
    scope = app_state.policy_matrix.scope("full").resolve("dev-042")
    assert "dev/dev-042/#" in scope.allow
    assert "{device_id}" not in "".join(scope.allow)


def test_decision_carries_every_replay_field(app_state) -> None:
    decision = app_state.policy.direct(
        "dev-042", S.STABLE, TC.NONE, strategy="ca_ztcf", reason_codes=("X",)
    )
    assert decision.decision_id.startswith("dec-")
    assert decision.device_id == "dev-042"
    assert decision.strategy == "ca_ztcf"
    assert decision.trust_state is S.STABLE
    assert decision.transition_context is TC.NONE
    assert decision.action is A.ALLOW
    assert decision.scope.name == "full"
    assert decision.ttl_ms == app_state.settings.policy.ttl_ms["ALLOW"]
    assert "EVIDENCE_CONSISTENT" in decision.reason_codes
    assert "X" in decision.reason_codes
    assert decision.rule_id == "P10"
    assert decision.config_hash == app_state.settings.config_hash
    assert decision.created_at is not None


def test_terminating_actions_have_zero_ttl(app_state) -> None:
    for action in (A.DENY, A.REAUTHENTICATE):
        assert app_state.policy_matrix.ttl_ms(action) == 0


# --- topic matching --------------------------------------------------------


@pytest.mark.parametrize(
    ("pattern", "topic", "expected"),
    [
        ("#", "anything/at/all", True),
        ("dev/d1/#", "dev/d1/telemetry/temp", True),
        ("dev/d1/#", "dev/d2/telemetry", False),
        ("dev/+/status", "dev/d1/status", True),
        ("dev/+/status", "dev/d1/d2/status", False),
        ("dev/d1/status", "dev/d1/status", True),
        ("dev/d1/status", "dev/d1/status/extra", False),
        ("cmd/#", "cmd/d1", True),
    ],
)
def test_topic_matching(pattern: str, topic: str, expected: bool) -> None:
    assert topic_matches(pattern, topic) is expected


# --- enforcement -----------------------------------------------------------


def _request(device_id: str, resource: str, op=ResourceOperation.PUBLISH):
    return EnforcementRequest(device_id=device_id, operation=op, resource=resource)


def test_allow_grants_the_full_scope(app_state) -> None:
    decision = app_state.policy.direct("dev-1", S.STABLE, TC.NONE, strategy="ca_ztcf")
    app_state.pep.apply(decision)
    assert app_state.pep.check(_request("dev-1", "dev/dev-1/telemetry/t")).permitted is True
    assert app_state.pep.check(_request("dev-1", "cmd/dev-1/reboot")).permitted is True


def test_restricted_scope_withholds_command_topics(app_state) -> None:
    decision = app_state.policy.direct("dev-1", S.TRANSITIONAL, TC.NR_TO_WLAN, strategy="ca_ztcf")
    app_state.pep.apply(decision)
    assert decision.action is A.ALLOW_WITH_RESTRICTIONS
    assert app_state.pep.check(_request("dev-1", "dev/dev-1/telemetry/t")).permitted is True
    denied = app_state.pep.check(_request("dev-1", "cmd/dev-1/reboot"))
    assert denied.permitted is False
    assert denied.reason.startswith("DENIED_BY_SCOPE")


def test_deny_installs_no_decision(app_state) -> None:
    decision = app_state.policy.direct("dev-1", S.UNKNOWN, TC.NONE, strategy="ca_ztcf")
    app_state.pep.apply(decision)
    assert app_state.pep.active_decision("dev-1") is None
    result = app_state.pep.check(_request("dev-1", "dev/dev-1/x"))
    assert result.permitted is False
    assert result.reason == "ACTION_DENY"


def test_reauthenticate_revokes_an_existing_grant(app_state) -> None:
    app_state.pep.apply(app_state.policy.direct("dev-1", S.STABLE, TC.NONE, strategy="ca_ztcf"))
    assert app_state.pep.check(_request("dev-1", "dev/dev-1/x")).permitted is True

    app_state.pep.apply(app_state.policy.direct("dev-1", S.SUSPICIOUS, TC.NONE, strategy="ca_ztcf"))
    result = app_state.pep.check(_request("dev-1", "dev/dev-1/x"))
    assert result.permitted is False
    assert result.reason == "ACTION_REAUTHENTICATE"


def test_quarantine_confines_the_device(app_state) -> None:
    decision = app_state.policy.direct("dev-1", S.SUSPICIOUS, TC.NR_TO_WLAN, strategy="ca_ztcf")
    assert decision.action is A.QUARANTINE
    app_state.pep.apply(decision)
    assert app_state.pep.check(_request("dev-1", "q/dev-1/observe")).permitted is True
    assert app_state.pep.check(_request("dev-1", "dev/dev-1/telemetry")).permitted is False


def test_step_up_holds_resources_but_keeps_the_control_channel(app_state) -> None:
    decision = app_state.policy.direct("dev-1", S.DEGRADED, TC.NONE, strategy="ca_ztcf")
    app_state.pep.apply(decision)
    assert app_state.pep.check(_request("dev-1", "ctl/dev-1/challenge")).permitted is True
    assert app_state.pep.check(_request("dev-1", "dev/dev-1/telemetry")).permitted is False


def test_decision_expires_after_its_ttl(app_state, clock) -> None:
    decision = app_state.policy.direct("dev-1", S.STABLE, TC.NONE, strategy="ca_ztcf")
    app_state.pep.apply(decision)
    assert app_state.pep.active_decision("dev-1") is not None

    clock.advance(milliseconds=decision.ttl_ms + 1)
    assert app_state.pep.active_decision("dev-1") is None
    result = app_state.pep.check(_request("dev-1", "dev/dev-1/x"))
    assert result.permitted is False
    assert result.reason == "DECISION_EXPIRED"


def test_enforcement_is_default_deny(app_state) -> None:
    """A resource matching neither list is refused.

    This is why no scope needs a catch-all "#" deny entry: such an entry would be
    evaluated first and would shadow that scope's own allow patterns.
    """
    for scope_name in ("full", "restricted", "step_up_pending", "quarantine", "none"):
        scope = app_state.policy_matrix.scope(scope_name)
        assert "#" not in scope.deny, f"scope {scope_name} has a catch-all deny"

    app_state.pep.apply(app_state.policy.direct("dev-1", S.STABLE, TC.NONE, strategy="ca_ztcf"))
    result = app_state.pep.check(_request("dev-1", "some/unlisted/topic"))
    assert result.permitted is False
    assert result.reason == "NOT_IN_SCOPE:full"


def test_none_scope_permits_nothing(app_state) -> None:
    scope = app_state.policy_matrix.scope("none").resolve("dev-1")
    assert scope.allow == ()
    assert scope.deny == ()


def test_no_decision_at_all_is_refused(app_state) -> None:
    result = app_state.pep.check(_request("dev-never-seen", "dev/x/y"))
    assert result.permitted is False
    assert result.reason == "NO_ACTIVE_DECISION"


def test_connect_is_permitted_under_non_terminating_actions(app_state) -> None:
    app_state.pep.apply(app_state.policy.direct("dev-1", S.DEGRADED, TC.NONE, strategy="ca_ztcf"))
    result = app_state.pep.check(_request("dev-1", "", op=ResourceOperation.CONNECT))
    assert result.permitted is True
    assert result.reason == "CONNECT_UNDER_STEP_UP_AUTHENTICATION"
