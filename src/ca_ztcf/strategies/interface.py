"""The decision-strategy interface.

All three approaches under study implement this interface and share the same
collectors, enforcement point, workload and metrics. Only the decision logic
differs, which is what keeps the eventual comparison fair.

No claim is made here about how the strategies compare. Their relative cost and
security behaviour are hypotheses to be evaluated experimentally.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from ca_ztcf.clock import Clock
from ca_ztcf.collectors.base import AccessDomain, BindingStore
from ca_ztcf.collectors.transition import TransitionCollector
from ca_ztcf.config import Settings, StrategyDefinition
from ca_ztcf.evidence.assembler import EvidenceAssembler
from ca_ztcf.evidence.counters import SecurityCounters
from ca_ztcf.evidence.models import EvidenceRecord
from ca_ztcf.evidence.predicates import PredicateEvaluator, PredicateVector
from ca_ztcf.identity.models import ProofOfPossession
from ca_ztcf.identity.proof import ProofStore, ProofVerifier
from ca_ztcf.identity.registry import DeviceIdentityRegistry
from ca_ztcf.policy.evaluator import PolicyEvaluator
from ca_ztcf.policy.models import Decision
from ca_ztcf.trust_engine.decision_trace import TrustEvaluation
from ca_ztcf.trust_engine.engine import TrustEngine, TrustStateManager


@dataclass
class AccessRequest:
    """A device's request to access a resource, as seen by the service domain."""

    device_id: str
    peer_address: str
    domain: AccessDomain
    session_identity: str | None = None
    proof: ProofOfPossession | None = None
    resource: str | None = None
    at: datetime | None = None
    """Explicit evaluation instant.

    A research affordance: it lets a scenario or a test express "thirty seconds
    later" without sleeping. When omitted the injected clock is used.
    """


@dataclass
class StrategyOutcome:
    """A decision plus whatever trace the strategy produced.

    Baselines produce no evidence record or trust evaluation, by definition. The
    fields are therefore optional and their absence is itself informative.
    """

    decision: Decision
    evidence: EvidenceRecord | None = None
    predicates: PredicateVector | None = None
    trust_evaluation: TrustEvaluation | None = None
    notes: dict[str, str] = field(default_factory=dict)


@dataclass
class StrategyDeps:
    """Shared services handed to every strategy."""

    settings: Settings
    clock: Clock
    registry: DeviceIdentityRegistry
    proof_verifier: ProofVerifier
    binding_store: BindingStore
    transitions: TransitionCollector
    assembler: EvidenceAssembler
    predicates: PredicateEvaluator
    trust_engine: TrustEngine
    state_manager: TrustStateManager
    policy: PolicyEvaluator
    counters: SecurityCounters
    proofs: ProofStore


class DecisionStrategy(ABC):
    """Produces an access decision for a request."""

    kind: str = "abstract"

    def __init__(self, definition: StrategyDefinition, deps: StrategyDeps) -> None:
        self.definition = definition
        self.deps = deps

    @property
    def name(self) -> str:
        return self.definition.name

    def now(self, request: AccessRequest) -> datetime:
        return request.at if request.at is not None else self.deps.clock.now()

    @abstractmethod
    def decide(self, request: AccessRequest) -> StrategyOutcome:
        """Produce a decision for the request."""


__all__ = [
    "AccessRequest",
    "DecisionStrategy",
    "StrategyDeps",
    "StrategyOutcome",
]
