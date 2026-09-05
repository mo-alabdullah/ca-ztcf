"""Research endpoints.

These endpoints exist so that scenarios, tests and the development validation flow
can drive the framework end to end. They are not an operational management API.

Two research affordances are deliberate and documented:

* collector-event ingestion accepts an explicit ``observed_at``;
* evaluation accepts an explicit ``at``.

Both let a scenario express elapsed time without sleeping, which is what keeps the
experiments deterministic.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from ca_ztcf.api.schemas import (
    BindingResponse,
    CollectorEventRequest,
    DecisionEvaluateRequest,
    DecisionResponse,
    DeviceResponse,
    DeviceStatusRequest,
    EvaluateRequest,
    EvidenceEvaluateResponse,
    EvidenceItemResponse,
    NonceResponse,
    PredicateResponse,
    RegisterDeviceRequest,
    ScopeResponse,
    TransitionRequest,
    TransitionResponse,
)
from ca_ztcf.api.state import AppState
from ca_ztcf.collectors.base import AccessBinding, AccessDomain
from ca_ztcf.collectors.nr import NrAccessEvent, NrEventType
from ca_ztcf.collectors.wlan import WlanAccessEvent, WlanEventType
from ca_ztcf.errors import CaZtcfError, DeviceAlreadyRegisteredError, StrategyError
from ca_ztcf.identity.models import DeviceIdentity, ProofOfPossession
from ca_ztcf.policy.models import Decision
from ca_ztcf.strategies.interface import AccessRequest, StrategyOutcome

router = APIRouter(prefix="/v1", tags=["research"])


def _state(request: Request) -> AppState:
    state: AppState = request.app.state.ca_ztcf
    return state


def _device_response(identity: DeviceIdentity) -> DeviceResponse:
    return DeviceResponse(
        device_id=identity.device_id,
        public_key_fingerprint=identity.public_key_fingerprint,
        public_key_pem=identity.public_key_pem,
        status=identity.status,
        created_at=identity.created_at,
        updated_at=identity.updated_at,
        labels=identity.labels,
        notes=identity.notes,
    )


def _binding_response(binding: AccessBinding) -> BindingResponse:
    return BindingResponse(**binding.model_dump())


def _decision_response(decision: Decision) -> DecisionResponse:
    return DecisionResponse(
        decision_id=decision.decision_id,
        device_id=decision.device_id,
        strategy=decision.strategy,
        trust_state=decision.trust_state,
        transition_context=decision.transition_context,
        action=decision.action,
        scope=ScopeResponse(
            name=decision.scope.name,
            allow=list(decision.scope.allow),
            deny=list(decision.scope.deny),
        ),
        ttl_ms=decision.ttl_ms,
        reason_codes=list(decision.reason_codes),
        policy_rule_id=decision.rule_id,
        predicate_trace_id=decision.predicate_trace_id,
        evidence_record_id=decision.evidence_record_id,
        created_at=decision.created_at,
        config_hash=decision.config_hash,
        decision_duration_ns=decision.decision_duration_ns,
    )


# --- devices ---------------------------------------------------------------


@router.post("/devices", response_model=DeviceResponse, status_code=status.HTTP_201_CREATED)
def register_device(request: Request, payload: RegisterDeviceRequest) -> DeviceResponse:
    """Enrol a device. Enrolment is administrative and sits outside the access path."""
    state = _state(request)
    try:
        identity = state.registry.register(
            payload.device_id,
            payload.public_key_pem,
            labels=payload.labels,
            notes=payload.notes,
        )
    except DeviceAlreadyRegisteredError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except CaZtcfError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _device_response(identity)


@router.get("/devices/{device_id}", response_model=DeviceResponse)
def get_device(request: Request, device_id: str) -> DeviceResponse:
    identity = _state(request).registry.get(device_id)
    if identity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"device '{device_id}' not found")
    return _device_response(identity)


@router.post("/devices/{device_id}/status", response_model=DeviceResponse)
def set_device_status(
    request: Request, device_id: str, payload: DeviceStatusRequest
) -> DeviceResponse:
    state = _state(request)
    if not state.registry.exists(device_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"device '{device_id}' not found")
    return _device_response(state.registry.set_status(device_id, payload.status))


@router.post("/devices/{device_id}/nonce", response_model=NonceResponse)
def issue_nonce(request: Request, device_id: str) -> NonceResponse:
    """Issue a single-use challenge nonce for proof-of-possession."""
    state = _state(request)
    if not state.registry.exists(device_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"device '{device_id}' not found")
    nonce, expires_at = state.nonces.issue(device_id)
    return NonceResponse(device_id=device_id, nonce=nonce, expires_at=expires_at)


# --- collectors ------------------------------------------------------------


@router.post("/collectors/events", response_model=BindingResponse | None)
def ingest_collector_event(
    request: Request, payload: CollectorEventRequest
) -> BindingResponse | None:
    """Ingest one normalised access-domain event."""
    state = _state(request)
    observed_at = payload.observed_at or state.clock.now()
    attrs: dict[str, Any] = payload.attributes

    if payload.domain is AccessDomain.NR:
        try:
            event_type = NrEventType(payload.event_type or NrEventType.SESSION_ESTABLISHED.value)
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, detail=f"unknown NR event_type: {payload.event_type}"
            ) from exc
        nr_event = NrAccessEvent(
            event_type=event_type,
            peer_address=payload.peer_address,
            observed_at=observed_at,
            source_mode=payload.source_mode,
            subscriber_ref=attrs.get("subscriber_ref"),
            pdu_session_id=attrs.get("pdu_session_id"),
            dnn=attrs.get("dnn"),
            gnb_id=attrs.get("gnb_id"),
            rat_type=str(attrs.get("rat_type", "NR")),
            registration_state=str(attrs.get("registration_state", "REGISTERED")),
            pdu_session_active=bool(attrs.get("pdu_session_active", True)),
            binding_lifetime_s=payload.binding_lifetime_s,
        )
        binding = state.nr_collector.ingest(nr_event)
    else:
        try:
            wlan_type = WlanEventType(payload.event_type or WlanEventType.STA_AUTHENTICATED.value)
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"unknown WLAN event_type: {payload.event_type}",
            ) from exc
        wlan_event = WlanAccessEvent(
            event_type=wlan_type,
            peer_address=payload.peer_address,
            observed_at=observed_at,
            source_mode=payload.source_mode,
            sta_mac=attrs.get("sta_mac"),
            eap_identity=attrs.get("eap_identity"),
            eap_success=bool(attrs.get("eap_success", True)),
            akm=str(attrs.get("akm", "WPA2-EAP")),
            ssid=attrs.get("ssid"),
            ap_bssid=attrs.get("ap_bssid"),
            binding_lifetime_s=payload.binding_lifetime_s,
        )
        binding = state.wlan_collector.ingest(wlan_event)

    return _binding_response(binding) if binding is not None else None


@router.get("/collectors/bindings", response_model=list[BindingResponse])
def list_bindings(request: Request) -> list[BindingResponse]:
    return [_binding_response(b) for b in _state(request).binding_store.all_bindings()]


# --- transitions -----------------------------------------------------------


@router.post("/transitions", response_model=TransitionResponse)
def observe_transition(request: Request, payload: TransitionRequest) -> TransitionResponse:
    """Report where a device is now observed and obtain the derived context."""
    state = _state(request)
    at: datetime = payload.at or state.clock.now()
    event = state.transitions.observe(
        payload.device_id, payload.domain, peer_address=payload.peer_address, at=at
    )
    if event is not None:
        state.metrics.transition_events_total.labels(
            from_domain=event.from_domain.value if event.from_domain else "NONE",
            to_domain=event.to_domain.value,
        ).inc()
    context = state.transitions.context_for(payload.device_id, at=at)
    last = state.transitions.last_transition(payload.device_id)
    return TransitionResponse(
        device_id=payload.device_id,
        transition_detected=event is not None,
        transition_context=context,
        from_domain=last.from_domain if last else None,
        to_domain=last.to_domain if last else None,
        detected_at=last.detected_at if last else None,
        gap_ms=last.gap_ms if last else None,
        transitions_in_window=state.transitions.transitions_in_window(payload.device_id, at=at),
        repeated=last.repeated if last else False,
    )


# --- evaluation ------------------------------------------------------------


def _to_access_request(payload: EvaluateRequest) -> AccessRequest:
    proof = None
    if payload.proof is not None:
        proof = ProofOfPossession(
            device_id=payload.device_id,
            nonce=payload.proof.nonce,
            signature=payload.proof.signature,
            algorithm=payload.proof.algorithm,
        )
    return AccessRequest(
        device_id=payload.device_id,
        peer_address=payload.peer_address,
        domain=payload.domain,
        session_identity=payload.session_identity,
        proof=proof,
        resource=payload.resource,
        at=payload.at,
    )


def _record_metrics(state: AppState, outcome: StrategyOutcome) -> None:
    decision = outcome.decision
    state.metrics.decisions_total.labels(
        strategy=decision.strategy,
        trust_state=decision.trust_state.value,
        transition_context=decision.transition_context.value,
        action=decision.action.value,
    ).inc()
    state.metrics.decision_duration_seconds.labels(strategy=decision.strategy).observe(
        decision.decision_duration_ns / 1_000_000_000
    )
    state.metrics.policy_actions_total.labels(
        action=decision.action.value, rule_id=decision.rule_id or "DEFAULT"
    ).inc()
    if outcome.trust_evaluation is not None:
        evaluation = outcome.trust_evaluation
        state.metrics.trust_state_total.labels(
            trust_state=evaluation.new_state.value, firing_rule=evaluation.firing_rule
        ).inc()
        state.metrics.engine_duration_seconds.observe(evaluation.engine_duration_ns / 1_000_000_000)
    for reason in decision.reason_codes:
        if reason.startswith(("POP_", "AUTHN_FAILURES_EXCEEDED")):
            state.metrics.auth_failures_total.labels(reason=reason).inc()


@router.post("/evidence/evaluate", response_model=EvidenceEvaluateResponse)
def evaluate_evidence(request: Request, payload: EvaluateRequest) -> EvidenceEvaluateResponse:
    """Assemble evidence, evaluate the predicates and derive a trust state.

    Uses the CA-ZTCF pipeline explicitly: the baselines do not produce evidence.
    """
    state = _state(request)
    strategy = state.strategy("ca_ztcf")
    outcome = strategy.decide(_to_access_request(payload))

    if outcome.evidence is None or outcome.predicates is None or outcome.trust_evaluation is None:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, detail="evidence pipeline produced no trace"
        )

    record = outcome.evidence
    evaluation = outcome.trust_evaluation
    return EvidenceEvaluateResponse(
        device_id=record.device_id,
        schema_version=record.schema_version,
        evidence_record_id=record.record_id,
        assembled_at=record.assembled_at,
        config_hash=record.config_hash,
        contains_synthetic_evidence=record.contains_synthetic(),
        items=[
            EvidenceItemResponse(
                name=item.name,
                category=item.category.value,
                value=item.value,
                source=item.source,
                source_mode=item.source_mode,
                observed_at=item.observed_at,
                expires_at=item.expires_at,
                validation=item.validation.value,
                detail=item.detail,
            )
            for item in (record.items[key] for key in sorted(record.items))
        ],
        predicates=[
            PredicateResponse(
                predicate_id=p.predicate_id.value,
                name=p.name,
                result=p.result,
                reason=p.reason,
                evidence_refs=list(p.evidence_refs),
            )
            for p in outcome.predicates.results
        ],
        trust_state=evaluation.new_state,
        previous_state=evaluation.previous_state,
        firing_rule=evaluation.firing_rule,
        reason_codes=list(evaluation.reason_codes),
        engine_duration_ns=evaluation.engine_duration_ns,
        transition_context=outcome.decision.transition_context,
    )


@router.post("/decisions/evaluate", response_model=DecisionResponse)
def evaluate_decision(request: Request, payload: DecisionEvaluateRequest) -> DecisionResponse:
    """Produce an access decision under the selected strategy and enforce it."""
    state = _state(request)
    try:
        strategy = state.strategy(payload.strategy)
    except StrategyError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    outcome = strategy.decide(_to_access_request(payload))
    state.pep.apply(outcome.decision)
    _record_metrics(state, outcome)
    state.audit.write_decision(
        outcome.decision,
        evaluation=outcome.trust_evaluation,
        recorded_at=state.clock.now(),
        extra=outcome.notes or None,
    )
    return _decision_response(outcome.decision)


__all__ = ["router"]
