"""Application state: constructs and holds every long-lived component.

Assembling the object graph in one place keeps the wiring explicit and lets a test
build the same graph with a :class:`~ca_ztcf.clock.FrozenClock`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ca_ztcf.clock import Clock, SystemClock
from ca_ztcf.collectors.base import BindingStore
from ca_ztcf.collectors.nr import NRCollector, SyntheticFixtureProvider
from ca_ztcf.collectors.transition import TransitionCollector
from ca_ztcf.collectors.wlan import WLANCollector
from ca_ztcf.config import Settings, load_settings
from ca_ztcf.enforcement.memory_pep import MemoryPEP
from ca_ztcf.errors import StrategyError
from ca_ztcf.evidence.assembler import EvidenceAssembler
from ca_ztcf.evidence.counters import SecurityCounters
from ca_ztcf.evidence.predicates import PredicateEvaluator
from ca_ztcf.identity.proof import NonceIssuer, ProofStore, ProofVerifier
from ca_ztcf.identity.registry import DeviceIdentityRegistry
from ca_ztcf.policy.evaluator import PolicyEvaluator
from ca_ztcf.policy.matrix import PolicyMatrix
from ca_ztcf.strategies import DecisionStrategy, StrategyDeps, build_strategy
from ca_ztcf.telemetry.audit import AuditWriter
from ca_ztcf.telemetry.metrics import Metrics
from ca_ztcf.trust_engine.engine import TrustEngine, TrustStateManager

DEFAULT_STRATEGY = "ca_ztcf"


@dataclass
class AppState:
    """Every component the API needs, constructed once."""

    settings: Settings
    clock: Clock
    metrics: Metrics
    audit: AuditWriter
    registry: DeviceIdentityRegistry
    nonces: NonceIssuer
    proof_verifier: ProofVerifier
    proofs: ProofStore
    binding_store: BindingStore
    nr_collector: NRCollector
    wlan_collector: WLANCollector
    nr_fixtures: SyntheticFixtureProvider
    transitions: TransitionCollector
    assembler: EvidenceAssembler
    predicates: PredicateEvaluator
    trust_engine: TrustEngine
    state_manager: TrustStateManager
    policy_matrix: PolicyMatrix
    policy: PolicyEvaluator
    counters: SecurityCounters
    pep: MemoryPEP
    strategies: dict[str, DecisionStrategy]

    def strategy(self, name: str | None) -> DecisionStrategy:
        chosen = name or DEFAULT_STRATEGY
        found = self.strategies.get(chosen)
        if found is None:
            raise StrategyError(f"unknown strategy '{chosen}'")
        return found


def build_app_state(
    *,
    settings: Settings | None = None,
    config_dir: Path | str | None = None,
    clock: Clock | None = None,
    audit_base_dir: Path | None = None,
) -> AppState:
    """Construct the full component graph."""
    resolved_settings = settings if settings is not None else load_settings(config_dir)
    resolved_clock = clock if clock is not None else SystemClock()

    metrics = Metrics()
    audit = AuditWriter(resolved_settings.audit, base_dir=audit_base_dir)

    registry = DeviceIdentityRegistry(resolved_clock)
    nonces = NonceIssuer(resolved_clock, resolved_settings.evidence.nonce_ttl_s)
    proof_verifier = ProofVerifier(resolved_clock, nonces)
    proofs = ProofStore(resolved_clock, resolved_settings.evidence.proof_of_possession_ttl_s)

    binding_store = BindingStore(resolved_clock)
    hash_length = resolved_settings.privacy.identifier_hash_length
    # Each collector receives its own independently generated salt. Digests from
    # different collectors are therefore not comparable, which is what makes
    # cross-domain identifier comparison impossible rather than merely forbidden.
    nr_collector = NRCollector(resolved_clock, binding_store, hash_length=hash_length)
    wlan_collector = WLANCollector(resolved_clock, binding_store, hash_length=hash_length)
    nr_fixtures = SyntheticFixtureProvider()

    transitions = TransitionCollector(
        resolved_clock,
        rate_window_s=resolved_settings.transition.rate_window_s,
        repeat_threshold=resolved_settings.transition.repeat_threshold,
        transition_window_s=resolved_settings.transition.transition_window_s,
        binding_store=binding_store,
    )

    assembler = EvidenceAssembler(resolved_settings, resolved_clock)
    predicates = PredicateEvaluator(resolved_settings)
    trust_engine = TrustEngine(resolved_settings, resolved_clock)
    state_manager = TrustStateManager()
    policy_matrix = PolicyMatrix(resolved_settings)
    policy = PolicyEvaluator(resolved_settings, resolved_clock, policy_matrix)
    counters = SecurityCounters(
        authn_failure_window_s=resolved_settings.security.authn_failure_window_s
    )
    pep = MemoryPEP(resolved_clock)

    deps = StrategyDeps(
        settings=resolved_settings,
        clock=resolved_clock,
        registry=registry,
        proof_verifier=proof_verifier,
        binding_store=binding_store,
        transitions=transitions,
        assembler=assembler,
        predicates=predicates,
        trust_engine=trust_engine,
        state_manager=state_manager,
        policy=policy,
        counters=counters,
        proofs=proofs,
    )
    strategies = {
        name: build_strategy(definition, deps)
        for name, definition in resolved_settings.strategies.items()
    }

    return AppState(
        settings=resolved_settings,
        clock=resolved_clock,
        metrics=metrics,
        audit=audit,
        registry=registry,
        nonces=nonces,
        proof_verifier=proof_verifier,
        proofs=proofs,
        binding_store=binding_store,
        nr_collector=nr_collector,
        wlan_collector=wlan_collector,
        nr_fixtures=nr_fixtures,
        transitions=transitions,
        assembler=assembler,
        predicates=predicates,
        trust_engine=trust_engine,
        state_manager=state_manager,
        policy_matrix=policy_matrix,
        policy=policy,
        counters=counters,
        pep=pep,
        strategies=strategies,
    )


__all__ = ["DEFAULT_STRATEGY", "AppState", "build_app_state"]
