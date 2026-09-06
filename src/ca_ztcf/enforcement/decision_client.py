"""How the MQTT enforcement point obtains decisions.

The enforcement point never decides anything itself. It asks the trust function
and applies the answer, which keeps the PE/PEP separation of NIST SP 800-207
intact and means the MQTT path cannot bypass the trust engine.

Two transports implement one protocol:

``LocalDecisionClient``
    Calls the in-process component graph directly. Used by tests and by a
    single-process deployment.

``HttpDecisionClient``
    Calls the CA-ZTCF core service over HTTP. Used when the enforcement point
    runs as its own container, which is the deployed arrangement.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

from ca_ztcf.collectors.base import AccessDomain
from ca_ztcf.errors import EnforcementError
from ca_ztcf.identity.models import ProofOfPossession
from ca_ztcf.policy.models import AccessScope, Decision, PolicyAction
from ca_ztcf.trust_engine.states import TrustState

if TYPE_CHECKING:  # pragma: no cover - import cycle avoided at runtime
    from ca_ztcf.api.state import AppState


@dataclass(frozen=True)
class DecisionRequest:
    """What the enforcement point knows about an access attempt."""

    device_id: str
    peer_address: str
    domain: AccessDomain | None = None
    """The access domain, when the caller genuinely knows it.

    The enforcement point does not: it sees a TCP peer address and nothing about
    the access network the connection crossed. Leaving this unset makes the
    service derive the domain from the access binding that matches the address,
    which is the only evidence-based answer. A fixed default here silently
    mislabels every connection arriving over the other access.
    """
    session_identity: str | None = None
    proof: ProofOfPossession | None = None
    resource: str | None = None
    strategy: str | None = None
    at: datetime | None = None


@dataclass
class DecisionResult:
    """A decision plus the raw response, so audit correlation stays possible."""

    decision: Decision
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def action(self) -> PolicyAction:
        return self.decision.action

    @property
    def scope(self) -> AccessScope:
        return self.decision.scope


class DecisionClient(Protocol):
    """Obtains an access decision, and issues step-up challenges."""

    async def decide(self, request: DecisionRequest) -> DecisionResult: ...

    async def issue_nonce(self, device_id: str) -> tuple[str, datetime]: ...

    async def close(self) -> None: ...


def decision_from_payload(payload: dict[str, Any]) -> Decision:
    """Rebuild a :class:`Decision` from the API's JSON representation."""
    try:
        scope_payload = payload["scope"]
        return Decision(
            decision_id=payload["decision_id"],
            device_id=payload["device_id"],
            strategy=payload["strategy"],
            trust_state=TrustState(payload["trust_state"]),
            transition_context=payload["transition_context"],
            action=PolicyAction(payload["action"]),
            scope=AccessScope(
                name=scope_payload["name"],
                allow=tuple(scope_payload.get("allow", ())),
                deny=tuple(scope_payload.get("deny", ())),
            ),
            ttl_ms=int(payload["ttl_ms"]),
            reason_codes=tuple(payload.get("reason_codes", ())),
            rule_id=payload.get("policy_rule_id", ""),
            predicate_trace_id=payload.get("predicate_trace_id"),
            evidence_record_id=payload.get("evidence_record_id"),
            created_at=datetime.fromisoformat(payload["created_at"]),
            config_hash=payload["config_hash"],
            decision_duration_ns=int(payload.get("decision_duration_ns", 0)),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise EnforcementError(f"malformed decision payload: {exc}") from exc


class LocalDecisionClient:
    """Calls the in-process CA-ZTCF component graph."""

    def __init__(self, app_state: AppState, *, default_strategy: str = "ca_ztcf") -> None:
        self._state = app_state
        self._default_strategy = default_strategy

    async def decide(self, request: DecisionRequest) -> DecisionResult:
        from ca_ztcf.strategies.interface import AccessRequest

        strategy = self._state.strategy(request.strategy or self._default_strategy)
        domain = request.domain or self._state.binding_store.domain_for(request.peer_address)
        outcome = strategy.decide(
            AccessRequest(
                device_id=request.device_id,
                peer_address=request.peer_address,
                domain=domain or AccessDomain.NR,
                session_identity=request.session_identity,
                proof=request.proof,
                resource=request.resource,
                at=request.at,
            )
        )
        self._state.pep.apply(outcome.decision)
        self._state.audit.write_decision(
            outcome.decision,
            evaluation=outcome.trust_evaluation,
            recorded_at=self._state.clock.now(),
            extra={"enforcement_point": "mqtt", **(outcome.notes or {})},
        )
        return DecisionResult(decision=outcome.decision, raw={})

    async def issue_nonce(self, device_id: str) -> tuple[str, datetime]:
        if not self._state.registry.exists(device_id):
            raise EnforcementError(f"cannot issue a nonce for unregistered device '{device_id}'")
        nonce, expires_at = self._state.nonces.issue(device_id)
        return nonce, expires_at

    async def close(self) -> None:
        return None


class HttpDecisionClient:
    """Calls the CA-ZTCF core service over HTTP."""

    def __init__(
        self, base_url: str, *, timeout_s: float = 5.0, strategy: str | None = None
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_s
        self._strategy = strategy
        self._client: Any | None = None

    async def _http(self) -> Any:
        if self._client is None:
            import httpx

            self._client = httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout)
        return self._client

    async def decide(self, request: DecisionRequest) -> DecisionResult:
        payload: dict[str, Any] = {
            "device_id": request.device_id,
            "peer_address": request.peer_address,
            "session_identity": request.session_identity,
            "strategy": request.strategy or self._strategy,
        }
        if request.domain is not None:
            payload["domain"] = request.domain.value
        if request.resource is not None:
            payload["resource"] = request.resource
        if request.at is not None:
            payload["at"] = request.at.isoformat()
        if request.proof is not None:
            payload["proof"] = {
                "nonce": request.proof.nonce,
                "signature": request.proof.signature,
                "algorithm": request.proof.algorithm,
            }
        payload = {key: value for key, value in payload.items() if value is not None}

        client = await self._http()
        response = await client.post("/v1/decisions/evaluate", json=payload)
        if response.status_code != 200:
            raise EnforcementError(
                f"decision request failed ({response.status_code}): {response.text[:200]}"
            )
        body = json.loads(response.text)
        return DecisionResult(decision=decision_from_payload(body), raw=body)

    async def issue_nonce(self, device_id: str) -> tuple[str, datetime]:
        client = await self._http()
        response = await client.post(f"/v1/devices/{device_id}/nonce")
        if response.status_code != 200:
            raise EnforcementError(
                f"nonce request failed ({response.status_code}): {response.text[:200]}"
            )
        body = json.loads(response.text)
        return str(body["nonce"]), datetime.fromisoformat(str(body["expires_at"]))

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


__all__ = [
    "DecisionClient",
    "DecisionRequest",
    "DecisionResult",
    "HttpDecisionClient",
    "LocalDecisionClient",
    "decision_from_payload",
]
