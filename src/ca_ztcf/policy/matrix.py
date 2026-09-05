"""The Transition-Aware Policy Matrix.

Loaded entirely from ``config/policy/policy_matrix.yaml``. The matrix has two
axes: the trust continuity state, and the transition context. Making the
transition an explicit axis is the point of the framework, so it is a first-class
input rather than an attribute buried in the evidence.

Rules are evaluated in declaration order; the first match wins. A configuration
that produces no match falls back to the configured default, which denies.
"""

from __future__ import annotations

from dataclasses import dataclass

from ca_ztcf.collectors.transition import TransitionContext
from ca_ztcf.config import Settings
from ca_ztcf.errors import PolicyError
from ca_ztcf.policy.models import AccessScope, PolicyAction
from ca_ztcf.trust_engine.states import TrustState

WILDCARD = "*"


@dataclass(frozen=True)
class MatrixEntry:
    """One resolved policy rule."""

    rule_id: str
    state: TrustState
    transition_contexts: frozenset[TransitionContext] | None
    action: PolicyAction
    scope_name: str
    reason_codes: tuple[str, ...]
    note: str = ""

    def matches(self, state: TrustState, context: TransitionContext) -> bool:
        if self.state is not state:
            return False
        return self.transition_contexts is None or context in self.transition_contexts


@dataclass(frozen=True)
class MatrixOutcome:
    """What the matrix decided, before scope resolution and TTL lookup."""

    rule_id: str
    action: PolicyAction
    scope: AccessScope
    reason_codes: tuple[str, ...]
    matched: bool


class PolicyMatrix:
    """Immutable, configuration-driven policy matrix."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._scopes = self._load_scopes(settings)
        self._entries = self._load_entries(settings)
        self._default = self._load_default(settings)

    # -- loading ---------------------------------------------------------

    @staticmethod
    def _load_scopes(settings: Settings) -> dict[str, AccessScope]:
        scopes: dict[str, AccessScope] = {}
        for name, definition in settings.scopes.items():
            scopes[name] = AccessScope(
                name=name,
                description=definition.description,
                allow=definition.allow,
                deny=definition.deny,
            )
        return scopes

    @staticmethod
    def _load_entries(settings: Settings) -> tuple[MatrixEntry, ...]:
        entries: list[MatrixEntry] = []
        seen: set[str] = set()
        for rule in settings.policy_matrix.rules:
            if rule.id in seen:
                raise PolicyError(f"duplicate policy rule id '{rule.id}'")
            seen.add(rule.id)
            try:
                state = TrustState(rule.state)
            except ValueError as exc:
                raise PolicyError(f"policy rule {rule.id}: unknown state '{rule.state}'") from exc
            try:
                action = PolicyAction(rule.action)
            except ValueError as exc:
                raise PolicyError(f"policy rule {rule.id}: unknown action '{rule.action}'") from exc

            if WILDCARD in rule.transition_contexts:
                contexts: frozenset[TransitionContext] | None = None
            else:
                try:
                    contexts = frozenset(TransitionContext(c) for c in rule.transition_contexts)
                except ValueError as exc:
                    raise PolicyError(f"policy rule {rule.id}: unknown transition context") from exc

            entries.append(
                MatrixEntry(
                    rule_id=rule.id,
                    state=state,
                    transition_contexts=contexts,
                    action=action,
                    scope_name=rule.scope,
                    reason_codes=rule.reason_codes,
                    note=rule.note,
                )
            )
        if not entries:
            raise PolicyError("policy matrix contains no rules")
        return tuple(entries)

    @staticmethod
    def _load_default(settings: Settings) -> MatrixEntry:
        matrix = settings.policy_matrix
        try:
            action = PolicyAction(matrix.default_action)
        except ValueError as exc:
            raise PolicyError(f"unknown default_action '{matrix.default_action}'") from exc
        return MatrixEntry(
            rule_id="DEFAULT",
            state=TrustState.UNTRUSTED,
            transition_contexts=None,
            action=action,
            scope_name=matrix.default_scope,
            reason_codes=matrix.default_reason_codes,
        )

    # -- lookup ----------------------------------------------------------

    @property
    def entries(self) -> tuple[MatrixEntry, ...]:
        return self._entries

    def scope(self, name: str) -> AccessScope:
        scope = self._scopes.get(name)
        if scope is None:
            raise PolicyError(f"undefined access scope '{name}'")
        return scope

    def ttl_ms(self, action: PolicyAction) -> int:
        ttl = self._settings.policy.ttl_ms.get(action.value)
        if ttl is None:
            raise PolicyError(f"no policy.ttl_ms entry for action '{action.value}'")
        return ttl

    def lookup(self, state: TrustState, context: TransitionContext) -> MatrixOutcome:
        for entry in self._entries:
            if entry.matches(state, context):
                return MatrixOutcome(
                    rule_id=entry.rule_id,
                    action=entry.action,
                    scope=self.scope(entry.scope_name),
                    reason_codes=entry.reason_codes,
                    matched=True,
                )
        default = self._default
        return MatrixOutcome(
            rule_id=default.rule_id,
            action=default.action,
            scope=self.scope(default.scope_name),
            reason_codes=default.reason_codes,
            matched=False,
        )

    def coverage(self) -> dict[tuple[str, str], str]:
        """Map every (state, context) pair to the rule that would fire.

        Used by tests to assert that the matrix is total: no pair may fall through
        to the default rule.
        """
        table: dict[tuple[str, str], str] = {}
        for state in TrustState:
            for context in TransitionContext:
                outcome = self.lookup(state, context)
                table[(state.value, context.value)] = outcome.rule_id
        return table


__all__ = ["MatrixEntry", "MatrixOutcome", "PolicyMatrix"]
