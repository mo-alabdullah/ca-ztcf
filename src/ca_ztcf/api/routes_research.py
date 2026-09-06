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
    AuditRecordResponse,
    BindingResponse,
    CollectorEventRequest,
    DecisionEvaluateRequest,
    DecisionResponse,
    DeviceResponse,
    DeviceStateResponse,
    DeviceStatusRequest,
    EvaluateRequest,
    EvidenceEvaluateResponse,
    EvidenceItemResponse,
    NonceResponse,
    PredicateResponse,
    RegisterDeviceRequest,
    ScopeResponse,
    StepUpRequest,
    StepUpResponse,
    TransitionDetailResponse,
    TransitionRequest,
    TransitionResponse,
)
from ca_ztcf.api.state import AppState
from ca_ztcf.collectors.base import AccessBinding, AccessDomain
from ca_ztcf.collectors.nr import NrAccessEvent, NrEventType
from ca_ztcf.collectors.wlan import WlanAccessEvent, WlanEventType
from ca_ztcf.errors import CaZtcfError, DeviceAlreadyRegisteredError, StrategyError
from ca_ztcf.identity.models import DeviceIdentity, ProofOfPossession
from ca_ztcf.policy.models import Decision, PolicyAction
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


def _to_access_request(payload: EvaluateRequest, state: AppState) -> AccessRequest:
    proof = None
    if payload.proof is not None:
        proof = ProofOfPossession(
            device_id=payload.device_id,
            nonce=payload.proof.nonce,
            signature=payload.proof.signature,
            algorithm=payload.proof.algorithm,
        )
    # The access domain is derived from the binding that matches the observed
    # address whenever the caller does not state one. An enforcement point cannot
    # know which access a connection arrived over, and a device must not be
    # believed about it, so the evidence answers. With no binding there is nothing
    # to derive from; the request keeps its declared domain, and the missing
    # binding is what predicate C3 will then fail on.
    domain = payload.domain or state.binding_store.domain_for(payload.peer_address)
    return AccessRequest(
        device_id=payload.device_id,
        peer_address=payload.peer_address,
        domain=domain or AccessDomain.NR,
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
    outcome = strategy.decide(_to_access_request(payload, state))

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

    access_request = _to_access_request(payload, state)
    outcome = strategy.decide(access_request)
    state.pep.apply(outcome.decision)
    _record_metrics(state, outcome)
    state.audit.write_decision(
        outcome.decision,
        evaluation=outcome.trust_evaluation,
        recorded_at=state.clock.now(),
        extra={
            # The address the decision was made about. An access binding must
            # exist for this exact address, so recording it makes a "no binding"
            # outcome diagnosable after the fact.
            "peer_address": payload.peer_address,
            # The domain the decision actually used, and whether it came from the
            # evidence or from the caller. Recording only the caller's value would
            # hide a derivation that disagreed with it.
            "domain": access_request.domain.value,
            "domain_source": "declared" if payload.domain else "derived_from_binding",
            **(outcome.notes or {}),
        },
    )
    return _decision_response(outcome.decision)


# --- research state, step-up, transitions and audit ------------------------


@router.get("/devices/{device_id}/state", response_model=DeviceStateResponse)
def get_device_state(request: Request, device_id: str) -> DeviceStateResponse:
    """Current trust state and recent history. Carries no credential material."""
    state = _state(request)
    identity = state.registry.get(device_id)
    now = state.clock.now()
    return DeviceStateResponse(
        device_id=device_id,
        registered=identity is not None,
        status=identity.status if identity is not None else None,
        trust_state=state.state_manager.current(device_id),
        state_entered_at=state.state_manager.entered_at(device_id),
        history=state.state_manager.history(device_id),
        transitions_in_window=state.transitions.transitions_in_window(device_id, at=now),
        current_domain=state.transitions.current_domain(device_id),
        previous_domain=state.transitions.previous_domain(device_id),
        transition_context=state.transitions.context_for(device_id, at=now),
    )


@router.get("/devices/{device_id}/decision", response_model=DecisionResponse)
def get_active_decision(request: Request, device_id: str) -> DecisionResponse:
    """The device's active, unexpired decision at the enforcement point."""
    decision = _state(request).pep.active_decision(device_id)
    if decision is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"no active decision for '{device_id}'"
        )
    return _decision_response(decision)


@router.post("/devices/{device_id}/step-up", response_model=StepUpResponse)
def step_up(request: Request, device_id: str, payload: StepUpRequest) -> StepUpResponse:
    """Answer a step-up challenge and re-evaluate.

    Verification happens through the normal decision path, so a step-up cannot
    grant anything the trust engine would not grant on its own.
    """
    state = _state(request)
    identity = state.registry.get(device_id)
    if identity is None:
        return StepUpResponse(device_id=device_id, accepted=False, reason="DEVICE_NOT_REGISTERED")

    proof = ProofOfPossession(
        device_id=device_id,
        nonce=payload.proof.nonce,
        signature=payload.proof.signature,
        algorithm=payload.proof.algorithm,
    )
    outcome = state.strategy("ca_ztcf").decide(
        AccessRequest(
            device_id=device_id,
            peer_address=payload.peer_address,
            domain=payload.domain,
            session_identity=payload.session_identity,
            proof=proof,
            at=payload.at,
        )
    )
    state.pep.apply(outcome.decision)
    _record_metrics(state, outcome)
    state.audit.write_decision(
        outcome.decision,
        evaluation=outcome.trust_evaluation,
        recorded_at=state.clock.now(),
        extra={"trigger": "step_up"},
    )
    accepted = outcome.decision.action not in {
        PolicyAction.DENY,
        PolicyAction.REAUTHENTICATE,
        PolicyAction.STEP_UP_AUTHENTICATION,
    }
    return StepUpResponse(
        device_id=device_id,
        accepted=accepted,
        reason=outcome.decision.reason_codes[0] if outcome.decision.reason_codes else "NO_REASON",
        decision=_decision_response(outcome.decision),
    )


@router.get("/transitions/{transition_id}", response_model=TransitionDetailResponse)
def get_transition(request: Request, transition_id: str) -> TransitionDetailResponse:
    """A recorded transition, including whether collectors corroborated it."""
    event = _state(request).transitions.transition(transition_id)
    if event is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"transition '{transition_id}' not found"
        )
    return TransitionDetailResponse(
        transition_id=event.transition_id,
        device_id=event.device_id,
        from_domain=event.from_domain,
        to_domain=event.to_domain,
        started_at=event.started_at,
        completed_at=event.completed_at,
        detected_at=event.detected_at,
        reason=event.reason.value,
        sequence_number=event.sequence_number,
        gap_ms=event.gap_ms,
        transitions_in_window=event.transitions_in_window,
        repeated=event.repeated,
        cross_domain=event.cross_domain,
        corroborated=event.corroborated,
        source_event_refs=list(event.source_event_refs),
        source_modes=list(event.source_modes),
    )


@router.get("/audit/{decision_id}", response_model=AuditRecordResponse)
def get_audit_record(request: Request, decision_id: str) -> AuditRecordResponse:
    """Look up the audit record a decision produced.

    The record is already redacted on write; this only reads it back.
    """
    record = _state(request).audit.find_decision(decision_id)
    return AuditRecordResponse(decision_id=decision_id, found=record is not None, record=record)


__all__ = ["router"]
