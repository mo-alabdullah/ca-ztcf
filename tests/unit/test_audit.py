"""Audit output: completeness and unconditional redaction."""

from __future__ import annotations

import json
from pathlib import Path

from tests.conftest import fake_pem

from ca_ztcf.telemetry.audit import REDACTED, AuditWriter, redact

SECRET_KEYS = frozenset({"private_key", "password", "token", "supi", "imsi", "psk", "pmk", "kausf"})


def test_redact_replaces_denylisted_keys_at_any_depth() -> None:
    payload = {
        "device_id": "dev-1",
        "password": "hunter2",
        "nested": {"token": "abc", "keep": 1, "deeper": [{"supi": "imsi-001"}]},
    }
    cleaned = redact(payload, SECRET_KEYS)
    assert cleaned["password"] == REDACTED
    assert cleaned["nested"]["token"] == REDACTED
    assert cleaned["nested"]["deeper"][0]["supi"] == REDACTED
    assert cleaned["nested"]["keep"] == 1
    assert cleaned["device_id"] == "dev-1"


def test_redact_catches_key_material_under_an_innocent_key() -> None:
    payload = {"harmless_field": fake_pem("AAAA")}
    assert redact(payload, SECRET_KEYS)["harmless_field"] == REDACTED


def test_writer_appends_jsonl(app_state, tmp_path: Path) -> None:
    writer = app_state.audit
    writer.write({"record_type": "test", "n": 1})
    writer.write({"record_type": "test", "n": 2})

    lines = writer.path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["n"] == 1
    assert json.loads(lines[1])["n"] == 2
    assert writer.written == 2


def test_decision_record_contains_everything_needed_to_replay(
    app_state, registered, profile, clock, fresh_proof
) -> None:
    from ca_ztcf.collectors.base import AccessDomain
    from ca_ztcf.strategies.interface import AccessRequest

    app_state.nr_collector.ingest(
        __import__("ca_ztcf.collectors.fixtures", fromlist=["nr_event"]).nr_event(
            profile, clock.now()
        )
    )
    outcome = app_state.strategy("ca_ztcf").decide(
        AccessRequest(
            device_id=registered,
            peer_address=profile.nr_address,
            domain=AccessDomain.NR,
            session_identity=registered,
            proof=fresh_proof(registered),
            at=clock.now(),
        )
    )
    record = app_state.audit.write_decision(
        outcome.decision, evaluation=outcome.trust_evaluation, recorded_at=clock.now()
    )

    for field in (
        "config_hash",
        "evidence_record_id",
        "predicate_trace_id",
        "trust_state",
        "transition_context",
        "action",
        "reason_codes",
        "created_at",
        "recorded_at",
        "decision_duration_ns",
        "decision_id",
        "device_id",
        "strategy",
        "scope",
        "ttl_ms",
        "policy_rule_id",
    ):
        assert field in record, f"audit record is missing {field}"

    trace = record["trust_evaluation"]
    assert trace["firing_rule"]
    assert len(trace["predicates"]) == 11
    assert all(p["reason"] for p in trace["predicates"])
    assert trace["engine_duration_ns"] >= 0


def test_audit_never_writes_key_material(app_state, device_key) -> None:
    record = app_state.audit.write(
        {
            "record_type": "test",
            "public_key_pem": device_key.public_pem,
            "private_key": fake_pem("not-a-real-key"),
            "supi": "imsi-999990000000001",
        }
    )
    assert record["private_key"] == REDACTED
    assert record["supi"] == REDACTED
    # The public key is not secret, but it still trips the PEM heuristic, which is
    # the safe direction to fail.
    assert record["public_key_pem"] == REDACTED

    on_disk = app_state.audit.path.read_text(encoding="utf-8")
    assert "PRIVATE KEY" not in on_disk
    assert "imsi-999990000000001" not in on_disk


def test_disabled_writer_still_redacts_but_writes_nothing(app_state, tmp_path: Path) -> None:
    from ca_ztcf.config import AuditSettings

    writer = AuditWriter(
        AuditSettings(enabled=False, path="artifacts/off.jsonl", redact_keys=("token",)),
        base_dir=tmp_path,
    )
    cleaned = writer.write({"token": "abc"})
    assert cleaned["token"] == REDACTED
    assert writer.written == 0
    assert not writer.path.exists()
