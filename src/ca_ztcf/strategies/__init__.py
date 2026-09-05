"""The three interchangeable decision strategies under study."""

from __future__ import annotations

from ca_ztcf.config import StrategyDefinition
from ca_ztcf.errors import StrategyError
from ca_ztcf.strategies.ca_ztcf import CAZTCFStrategy
from ca_ztcf.strategies.independent import IndependentAuthenticationStrategy
from ca_ztcf.strategies.interface import (
    AccessRequest,
    DecisionStrategy,
    StrategyDeps,
    StrategyOutcome,
)
from ca_ztcf.strategies.static_continuity import StaticContinuityStrategy

STRATEGY_KINDS: dict[str, type[DecisionStrategy]] = {
    "ca_ztcf": CAZTCFStrategy,
    "independent": IndependentAuthenticationStrategy,
    "static_continuity": StaticContinuityStrategy,
}


def build_strategy(definition: StrategyDefinition, deps: StrategyDeps) -> DecisionStrategy:
    """Instantiate the strategy named by a configuration block."""
    implementation = STRATEGY_KINDS.get(definition.kind)
    if implementation is None:
        raise StrategyError(f"unknown strategy kind '{definition.kind}'")
    return implementation(definition, deps)


__all__ = [
    "STRATEGY_KINDS",
    "AccessRequest",
    "CAZTCFStrategy",
    "DecisionStrategy",
    "IndependentAuthenticationStrategy",
    "StaticContinuityStrategy",
    "StrategyDeps",
    "StrategyOutcome",
    "build_strategy",
]
