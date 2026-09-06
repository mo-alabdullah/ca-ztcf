"""The ground-truth taxonomy and how outcomes are scored against it."""

from __future__ import annotations

import pytest
from experiments.runner.metrics import MetricsCollector
from experiments.schemas.scenario import ACCEPTABLE_ACTIONS, GroundTruthLabel


def _collector() -> MetricsCollector:
    return MetricsCollector(run_id="r", scenario_id="EXX", strategy="ca_ztcf", seed=1)


# --- the taxonomy -----------------------------------------------------------


def test_taxonomy_is_small_and_fully_partitioned() -> None:
    labels = set(GroundTruthLabel)
    legitimate = {label for label in labels if label.is_legitimate}
    adversarial = {label for label in labels if label.is_adversarial}
    assert legitimate & adversarial == set()
    assert legitimate | adversarial | {GroundTruthLabel.NOT_APPLICABLE} == labels
    assert len(labels) == 6


def test_every_scored_label_declares_acceptable_actions() -> None:
    for label in GroundTruthLabel:
        if label.scored:
            assert ACCEPTABLE_ACTIONS[label], f"{label} declares no acceptable action"
        else:
            assert label not in ACCEPTABLE_ACTIONS


def test_not_applicable_is_never_scored() -> None:
    assert GroundTruthLabel.NOT_APPLICABLE.scored is False
    assert GroundTruthLabel.NOT_APPLICABLE.is_legitimate is False
    assert GroundTruthLabel.NOT_APPLICABLE.is_adversarial is False


def test_permissive_outcomes_never_satisfy_an_adversarial_label() -> None:
    """The property that makes false acceptance meaningful."""
    for label in (GroundTruthLabel.MALICIOUS_REJECT, GroundTruthLabel.MALICIOUS_QUARANTINE):
        acceptable = ACCEPTABLE_ACTIONS[label]
        assert "ALLOW" not in acceptable
        assert "ALLOW_WITH_RESTRICTIONS" not in acceptable
        assert "STEP_UP_AUTHENTICATION" not in acceptable


def test_denial_never_satisfies_a_legitimate_label() -> None:
    """The property that makes false rejection meaningful."""
    for label in (
        GroundTruthLabel.LEGITIMATE_ALLOW,
        GroundTruthLabel.LEGITIMATE_RESTRICT,
        GroundTruthLabel.LEGITIMATE_STEP_UP,
    ):
        acceptable = ACCEPTABLE_ACTIONS[label]
        assert "DENY" not in acceptable
        assert "QUARANTINE" not in acceptable


def test_expectations_widen_monotonically_for_legitimate_labels() -> None:
    """A stricter expectation must accept everything a looser one accepts.

    LEGITIMATE_ALLOW is the narrowest: only full allow satisfies it. Each step
    down the ladder tolerates one more proportionate response, so being *less*
    restrictive than required is never scored as a rejection.
    """
    allow = ACCEPTABLE_ACTIONS[GroundTruthLabel.LEGITIMATE_ALLOW]
    restrict = ACCEPTABLE_ACTIONS[GroundTruthLabel.LEGITIMATE_RESTRICT]
    step_up = ACCEPTABLE_ACTIONS[GroundTruthLabel.LEGITIMATE_STEP_UP]
    assert allow < restrict < step_up


# --- scoring ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "action", "expected"),
    [
        ("LEGITIMATE_ALLOW", "ALLOW", "correct_acceptance"),
        ("LEGITIMATE_ALLOW", "ALLOW_WITH_RESTRICTIONS", "false_rejection"),
        ("LEGITIMATE_RESTRICT", "ALLOW_WITH_RESTRICTIONS", "correct_acceptance"),
        ("LEGITIMATE_RESTRICT", "ALLOW", "correct_acceptance"),
        ("LEGITIMATE_RESTRICT", "STEP_UP_AUTHENTICATION", "false_rejection"),
        ("LEGITIMATE_STEP_UP", "STEP_UP_AUTHENTICATION", "correct_acceptance"),
        ("LEGITIMATE_STEP_UP", "DENY", "false_rejection"),
        ("MALICIOUS_REJECT", "DENY", "correct_rejection"),
        ("MALICIOUS_REJECT", "REAUTHENTICATE", "correct_rejection"),
        ("MALICIOUS_REJECT", "ALLOW", "false_acceptance"),
        ("MALICIOUS_REJECT", "STEP_UP_AUTHENTICATION", "false_acceptance"),
        ("MALICIOUS_QUARANTINE", "QUARANTINE", "correct_rejection"),
        ("MALICIOUS_QUARANTINE", "ALLOW_WITH_RESTRICTIONS", "false_acceptance"),
    ],
)
def test_scoring_matrix(label: str, action: str, expected: str) -> None:
    collector = _collector()
    collector.record_ground_truth(
        step=0, label=label, action=action, trust_state="STABLE", permitted=True
    )
    assert collector.ground_truth_outcomes[0]["outcome"] == expected


def test_explicit_satisfaction_overrides_action_matching() -> None:
    """Enforcement steps score on whether the operation succeeded, not the action."""
    collector = _collector()
    collector.record_ground_truth(
        step=0,
        label="LEGITIMATE_RESTRICT",
        action="ALLOW_WITH_RESTRICTIONS",
        trust_state="TRANSITIONAL",
        permitted=False,
        satisfied=False,
    )
    assert collector.ground_truth_outcomes[0]["outcome"] == "false_rejection"


def test_confusion_terms_use_the_security_convention() -> None:
    collector = _collector()
    collector.record_ground_truth(
        step=0,
        label="MALICIOUS_REJECT",
        action="DENY",
        trust_state="UNTRUSTED",
        permitted=False,
    )
    confusion = collector.confusion()
    assert confusion["true_positive"] == 1
    assert confusion["adversarial_total"] == 1
    assert confusion["legitimate_total"] == 0


def test_label_distribution_is_reported() -> None:
    collector = _collector()
    for label in ("LEGITIMATE_ALLOW", "LEGITIMATE_ALLOW", "MALICIOUS_REJECT"):
        collector.record_ground_truth(
            step=0, label=label, action="ALLOW", trust_state="STABLE", permitted=True
        )
    assert collector.label_distribution() == {"LEGITIMATE_ALLOW": 2, "MALICIOUS_REJECT": 1}


def test_unknown_label_is_not_silently_scored() -> None:
    collector = _collector()
    collector.record_ground_truth(
        step=0, label="SOMETHING_ELSE", action="ALLOW", trust_state="STABLE", permitted=True
    )
    assert collector.ground_truth_outcomes[0]["outcome"] == "NOT_APPLICABLE"
    assert collector.confusion()["labelled_total"] == 0
