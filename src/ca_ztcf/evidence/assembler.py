"""Assembles the Dual-Context Evidence Model from collector output.

The assembler is the only place where observations become evidence. It is a pure
function of its inputs plus the injected clock, so the same inputs always produce
the same record apart from the generated record identifier.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ca_ztcf.clock import Clock
from ca_ztcf.collectors.base import AccessBinding, AccessDomain, SourceMode
from ca_ztcf.collectors.transition import TransitionEvent
from ca_ztcf.config import Settings
from ca_ztcf.evidence import models as m
from ca_ztcf.evidence.freshness import age_seconds, is_fresh
from ca_ztcf.identity.models import DeviceIdentity, PoPResult

_SERVICE = "service_domain"


@dataclass(frozen=True)
class PostureOutcome:
    """Result of evaluating access-domain posture against the configured allow-lists."""

    ok: bool
    reason: str
    unauthorized: bool = False


@dataclass
class AssemblerInputs:
    """Everything the assembler needs. Explicit, so nothing is read from ambient state."""

    device_id: str
    identity: DeviceIdentity | None = None
    pop_result: PoPResult | None = None
    binding: AccessBinding | None = None
    binding_consistent: bool = True
    current_domain: AccessDomain | None = None
    previous_domain: AccessDomain | None = None
    transition: TransitionEvent | None = None
    transition_recent: bool = False
    transitions_in_window: int = 0
    authentication_failure_count: int = 0
    session_consistent: bool = True
    collector_available: bool = True
    evaluated_at: datetime | None = None
    extra_labels: dict[str, str] = field(default_factory=dict)


def evaluate_posture(binding: AccessBinding | None, settings: Settings) -> PostureOutcome:
    """Evaluate domain posture for predicate C11 against the configured allow-lists.

    An empty allow-list means the constraint is not exercised in this research
    configuration and therefore permits any value; a scenario enables the
    constraint by populating the list.
    """
    if binding is None:
        return PostureOutcome(ok=False, reason="NO_BINDING_TO_EVALUATE")

    attrs = binding.attributes

    if binding.domain is AccessDomain.NR:
        cfg = settings.posture.nr
        state = attrs.get("registration_state")
        if cfg.required_registration_states and state not in cfg.required_registration_states:
            return PostureOutcome(False, "NR_REGISTRATION_STATE_NOT_ALLOWED", unauthorized=True)
        if cfg.require_active_pdu_session and attrs.get("pdu_session_active") != "true":
            return PostureOutcome(False, "NR_NO_ACTIVE_PDU_SESSION")
        rat = attrs.get("rat_type")
        if cfg.allowed_rat_types and rat not in cfg.allowed_rat_types:
            return PostureOutcome(False, "NR_RAT_TYPE_NOT_ALLOWED", unauthorized=True)
        gnb = attrs.get("gnb_id")
        if cfg.allowed_gnb_ids and gnb not in cfg.allowed_gnb_ids:
            return PostureOutcome(False, "NR_GNB_NOT_ALLOWED", unauthorized=True)
        dnn = attrs.get("dnn")
        if cfg.allowed_dnns and dnn not in cfg.allowed_dnns:
            return PostureOutcome(False, "NR_DNN_NOT_ALLOWED", unauthorized=True)
        return PostureOutcome(True, "NR_POSTURE_OK")

    cfg_w = settings.posture.wlan
    if cfg_w.require_eap_success and attrs.get("eap_success") != "true":
        return PostureOutcome(False, "WLAN_EAP_NOT_SUCCESSFUL")
    akm = attrs.get("akm")
    if cfg_w.allowed_akms and akm not in cfg_w.allowed_akms:
        return PostureOutcome(False, "WLAN_AKM_NOT_ALLOWED", unauthorized=True)
    ssid = attrs.get("ssid")
    if cfg_w.allowed_ssids and ssid not in cfg_w.allowed_ssids:
        return PostureOutcome(False, "WLAN_SSID_NOT_ALLOWED", unauthorized=True)
    bssid = attrs.get("ap_bssid")
    if cfg_w.allowed_bssids and bssid not in cfg_w.allowed_bssids:
        return PostureOutcome(False, "WLAN_BSSID_NOT_ALLOWED", unauthorized=True)
    return PostureOutcome(True, "WLAN_POSTURE_OK")


class EvidenceAssembler:
    """Builds a :class:`~ca_ztcf.evidence.models.EvidenceRecord` from collector output."""

    def __init__(self, settings: Settings, clock: Clock) -> None:
        self._settings = settings
        self._clock = clock

    def assemble(self, inputs: AssemblerInputs) -> m.EvidenceRecord:
        now = inputs.evaluated_at if inputs.evaluated_at is not None else self._clock.now()
        cfg = self._settings
        items: dict[str, m.EvidenceItem] = {}

        def put(
            name: str,
            value: m.EvidenceValue,
            *,
            source: str,
            source_mode: SourceMode,
            observed_at: datetime,
            expires_at: datetime | None = None,
            validation: m.ValidationStatus = m.ValidationStatus.UNVERIFIED,
            detail: str = "",
        ) -> None:
            items[name] = m.EvidenceItem(
                name=name,
                category=m.ITEM_CATEGORIES[name],
                value=value,
                source=source,
                source_mode=source_mode,
                observed_at=observed_at,
                expires_at=expires_at,
                validation=validation,
                detail=detail,
            )

        # --- 1. device identity -------------------------------------------------
        identity = inputs.identity
        put(
            m.IDENTITY_REGISTERED,
            identity is not None,
            source="identity.registry",
            source_mode=SourceMode.SERVICE_DOMAIN,
            observed_at=now,
            validation=m.ValidationStatus.VALID
            if identity is not None
            else m.ValidationStatus.MISSING,
            detail="" if identity is not None else "no registry entry for device_id",
        )
        put(
            m.IDENTITY_ENABLED,
            bool(identity is not None and identity.is_enabled),
            source="identity.registry",
            source_mode=SourceMode.SERVICE_DOMAIN,
            observed_at=identity.updated_at if identity is not None else now,
            validation=m.ValidationStatus.VALID
            if identity is not None
            else m.ValidationStatus.MISSING,
            detail=identity.status.value if identity is not None else "device not registered",
        )
        put(
            m.PUBLIC_KEY_FINGERPRINT,
            identity.public_key_fingerprint if identity is not None else None,
            source="identity.registry",
            source_mode=SourceMode.SERVICE_DOMAIN,
            observed_at=identity.created_at if identity is not None else now,
            validation=m.ValidationStatus.VALID
            if identity is not None
            else m.ValidationStatus.MISSING,
        )

        pop = inputs.pop_result
        pop_ttl = cfg.evidence.proof_of_possession_ttl_s
        if pop is not None and pop.valid and pop.verified_at is not None:
            pop_fresh = is_fresh(pop.verified_at, now, pop_ttl)
            put(
                m.PROOF_OF_POSSESSION_VALID,
                pop_fresh,
                source="identity.proof",
                source_mode=SourceMode.SERVICE_DOMAIN,
                observed_at=pop.verified_at,
                expires_at=pop.verified_at + timedelta(seconds=pop_ttl),
                validation=m.ValidationStatus.VALID if pop_fresh else m.ValidationStatus.STALE,
                detail=pop.reason if pop_fresh else "POP_STALE",
            )
        else:
            put(
                m.PROOF_OF_POSSESSION_VALID,
                False,
                source="identity.proof",
                source_mode=SourceMode.SERVICE_DOMAIN,
                observed_at=now,
                validation=m.ValidationStatus.MISSING
                if pop is None
                else m.ValidationStatus.INVALID,
                detail=pop.reason if pop is not None else "POP_NOT_PRESENTED",
            )

        # --- 2. access binding --------------------------------------------------
        binding = inputs.binding
        binding_source = binding.source if binding is not None else "collector.none"
        binding_mode = binding.source_mode if binding is not None else SourceMode.SERVICE_DOMAIN
        binding_observed = binding.last_seen if binding is not None else now
        binding_fresh = (
            binding is not None
            and is_fresh(binding.last_seen, now, cfg.evidence.binding_freshness_max_s)
            and not binding.is_expired(now)
        )

        put(
            m.BINDING_PRESENT,
            binding is not None,
            source=binding_source,
            source_mode=binding_mode,
            observed_at=binding_observed,
            expires_at=binding.expires_at if binding is not None else None,
            validation=m.ValidationStatus.VALID
            if binding is not None
            else m.ValidationStatus.MISSING,
        )
        put(
            m.BINDING_DOMAIN,
            binding.domain.value if binding is not None else None,
            source=binding_source,
            source_mode=binding_mode,
            observed_at=binding_observed,
            validation=m.ValidationStatus.VALID
            if binding is not None
            else m.ValidationStatus.MISSING,
        )
        put(
            m.BINDING_FRESH,
            binding_fresh,
            source=binding_source,
            source_mode=binding_mode,
            observed_at=binding_observed,
            expires_at=binding.expires_at if binding is not None else None,
            validation=m.ValidationStatus.VALID
            if binding_fresh
            else (m.ValidationStatus.MISSING if binding is None else m.ValidationStatus.STALE),
            detail="" if binding is None else f"age_s={age_seconds(binding.last_seen, now):.3f}",
        )
        put(
            m.BINDING_CONSISTENT,
            inputs.binding_consistent,
            source=binding_source,
            source_mode=binding_mode,
            observed_at=binding_observed,
            validation=m.ValidationStatus.VALID
            if inputs.binding_consistent
            else m.ValidationStatus.INVALID,
            detail=""
            if inputs.binding_consistent
            else "access binding is already attributed to a different device",
        )

        # --- 3. access context --------------------------------------------------
        transition = inputs.transition
        put(
            m.CURRENT_DOMAIN,
            inputs.current_domain.value if inputs.current_domain is not None else None,
            source="collector.transition",
            source_mode=binding_mode,
            observed_at=now,
            validation=m.ValidationStatus.VALID
            if inputs.current_domain is not None
            else m.ValidationStatus.MISSING,
        )
        put(
            m.PREVIOUS_DOMAIN,
            inputs.previous_domain.value if inputs.previous_domain is not None else None,
            source="collector.transition",
            source_mode=binding_mode,
            observed_at=now,
            validation=m.ValidationStatus.VALID
            if inputs.previous_domain is not None
            else m.ValidationStatus.MISSING,
        )
        put(
            m.TRANSITION_DETECTED,
            inputs.transition_recent,
            source="collector.transition",
            source_mode=binding_mode,
            observed_at=transition.detected_at if transition is not None else now,
            validation=m.ValidationStatus.VALID,
            detail=(
                f"{transition.transition_id}"
                f" corroborated={transition.corroborated}"
                f" seq={transition.sequence_number}"
                if transition is not None
                else "no transition on record"
            ),
        )
        put(
            m.TRANSITION_AGE,
            round(transition.age_seconds(now), 3) if transition is not None else None,
            source="collector.transition",
            source_mode=binding_mode,
            observed_at=transition.detected_at if transition is not None else now,
            validation=m.ValidationStatus.VALID
            if transition is not None
            else m.ValidationStatus.MISSING,
            detail="seconds since the last detected access-domain change",
        )
        put(
            m.TRANSITION_COUNT_WINDOW,
            inputs.transitions_in_window,
            source="collector.transition",
            source_mode=SourceMode.SERVICE_DOMAIN,
            observed_at=now,
            validation=m.ValidationStatus.VALID,
            detail=f"window_s={cfg.transition.rate_window_s}",
        )

        # --- 4. security events -------------------------------------------------
        put(
            m.AUTHENTICATION_FAILURE_COUNT,
            inputs.authentication_failure_count,
            source="service_domain.counters",
            source_mode=SourceMode.SERVICE_DOMAIN,
            observed_at=now,
            validation=m.ValidationStatus.VALID,
            detail=f"window_s={cfg.security.authn_failure_window_s}",
        )
        put(
            m.IDENTITY_MISMATCH,
            not inputs.binding_consistent,
            source="service_domain.counters",
            source_mode=SourceMode.SERVICE_DOMAIN,
            observed_at=now,
            validation=m.ValidationStatus.VALID,
            detail="true when the access binding is attributed to a different device",
        )
        put(
            m.SESSION_MISMATCH,
            not inputs.session_consistent,
            source="service_domain.counters",
            source_mode=SourceMode.SERVICE_DOMAIN,
            observed_at=now,
            validation=m.ValidationStatus.VALID,
            detail="true when the service-layer session identity does not match the device",
        )

        posture = evaluate_posture(binding, cfg)
        put(
            m.UNAUTHORIZED_CONTEXT,
            posture.unauthorized,
            source=binding_source,
            source_mode=binding_mode,
            observed_at=binding_observed,
            validation=m.ValidationStatus.VALID,
            detail=posture.reason,
        )

        # --- 5. domain posture --------------------------------------------------
        put(
            m.DOMAIN_POSTURE_OK,
            posture.ok,
            source=binding_source,
            source_mode=binding_mode,
            observed_at=binding_observed,
            validation=m.ValidationStatus.VALID if posture.ok else m.ValidationStatus.INVALID,
            detail=posture.reason,
        )
        put(
            m.COLLECTOR_AVAILABLE,
            inputs.collector_available,
            source="collector.health",
            source_mode=SourceMode.SERVICE_DOMAIN,
            observed_at=now,
            validation=m.ValidationStatus.VALID,
            detail="collector outage is missing evidence, never contradictory evidence",
        )
        required = cfg.evidence.evidence_completeness_required
        complete = all(items[name].value not in (None, False) for name in required if name in items)
        missing = [
            name for name in required if name not in items or items[name].value in (None, False)
        ]
        put(
            m.EVIDENCE_COMPLETE,
            complete,
            source=_SERVICE,
            source_mode=SourceMode.SERVICE_DOMAIN,
            observed_at=now,
            validation=m.ValidationStatus.VALID if complete else m.ValidationStatus.MISSING,
            detail="" if complete else f"missing={','.join(missing)}",
        )

        # --- 6. evidence metadata -----------------------------------------------
        oldest = min(
            (item.observed_at for item in items.values()),
            default=now,
        )
        put(
            m.ASSEMBLED_AT,
            now.isoformat(),
            source=_SERVICE,
            source_mode=SourceMode.SERVICE_DOMAIN,
            observed_at=now,
            validation=m.ValidationStatus.VALID,
        )
        put(
            m.EVIDENCE_AGE,
            round(age_seconds(oldest, now), 3),
            source=_SERVICE,
            source_mode=SourceMode.SERVICE_DOMAIN,
            observed_at=now,
            validation=m.ValidationStatus.VALID,
            detail="age of the oldest observation contributing to this record",
        )
        put(
            m.SCHEMA_VERSION_ITEM,
            m.EvidenceRecord.model_fields["schema_version"].default,
            source=_SERVICE,
            source_mode=SourceMode.SERVICE_DOMAIN,
            observed_at=now,
            validation=m.ValidationStatus.VALID,
        )
        put(
            m.CONFIG_HASH_ITEM,
            cfg.config_hash,
            source=_SERVICE,
            source_mode=SourceMode.SERVICE_DOMAIN,
            observed_at=now,
            validation=m.ValidationStatus.VALID,
        )

        return m.EvidenceRecord(
            device_id=inputs.device_id,
            assembled_at=now,
            config_hash=cfg.config_hash,
            items=items,
        )


__all__ = ["AssemblerInputs", "EvidenceAssembler", "PostureOutcome", "evaluate_posture"]
