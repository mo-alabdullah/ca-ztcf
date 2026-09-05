"""Integration tests against the assembled HTTP application."""

from __future__ import annotations

import pytest
from tests.conftest import fake_pem

pytestmark = pytest.mark.integration


def test_healthz(client) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "ca-ztcf"}


def test_readyz_reports_total_policy_coverage(client) -> None:
    response = client.get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["policy_coverage"] == "total"
    assert "ca_ztcf" in body["checks"]["strategies"]


def test_version(client) -> None:
    body = client.get("/version").json()
    assert body["version"] == "0.1.0"
    assert body["schema_version"] == "1"
    assert body["service"] == "ca-ztcf"


def test_config_hash_matches_the_loaded_settings(client, app_state) -> None:
    body = client.get("/config/hash").json()
    assert body["config_hash"] == app_state.settings.config_hash
    assert body["short_config_hash"] == app_state.settings.config_hash[:12]
    assert len(body["config_hash"]) == 64


def test_metrics_exposes_the_declared_metric_families(
    client, app_state, registered, profile, fresh_proof, clock
) -> None:
    client.post(
        "/v1/decisions/evaluate",
        json={
            "device_id": registered,
            "peer_address": profile.nr_address,
            "domain": "NR",
            "at": clock.now().isoformat(),
        },
    )
    text = client.get("/metrics").text
    for family in (
        "ca_ztcf_decisions_total",
        "ca_ztcf_decision_duration_seconds",
        "ca_ztcf_trust_state_total",
        "ca_ztcf_policy_actions_total",
    ):
        assert family in text


def test_register_and_fetch_device(client, device_key) -> None:
    created = client.post(
        "/v1/devices",
        json={
            "device_id": "dev-api-1",
            "public_key_pem": device_key.public_pem,
            "labels": {"scenario": "unit"},
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["device_id"] == "dev-api-1"
    assert body["status"] == "ACTIVE"
    assert body["public_key_fingerprint"]

    fetched = client.get("/v1/devices/dev-api-1")
    assert fetched.status_code == 200
    assert fetched.json()["device_id"] == "dev-api-1"


def test_duplicate_registration_conflicts(client, device_key) -> None:
    payload = {"device_id": "dev-api-2", "public_key_pem": device_key.public_pem}
    assert client.post("/v1/devices", json=payload).status_code == 201
    assert client.post("/v1/devices", json=payload).status_code == 409


def test_api_rejects_private_key_material(client) -> None:
    response = client.post(
        "/v1/devices",
        json={
            "device_id": "dev-api-3",
            "public_key_pem": fake_pem("x"),
        },
    )
    assert response.status_code in (400, 422)


def test_unknown_device_is_not_found(client) -> None:
    assert client.get("/v1/devices/dev-absent").status_code == 404


def test_collector_event_creates_a_binding(client, profile, clock) -> None:
    response = client.post(
        "/v1/collectors/events",
        json={
            "domain": "NR",
            "peer_address": profile.nr_address,
            "observed_at": clock.now().isoformat(),
            "source_mode": "synthetic_fixture",
            "attributes": {
                "subscriber_ref": profile.subscriber_ref,
                "gnb_id": "gnb-001",
                "pdu_session_id": "1",
                "dnn": "internet",
            },
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["domain"] == "NR"
    assert body["source_mode"] == "synthetic_fixture"
    assert profile.subscriber_ref not in str(body["attributes"])

    listed = client.get("/v1/collectors/bindings").json()
    assert len(listed) == 1


def test_transition_endpoint_reports_context(client, profile, clock) -> None:
    base = {"device_id": "dev-t", "peer_address": profile.nr_address}
    client.post("/v1/transitions", json={**base, "domain": "NR", "at": clock.now().isoformat()})
    clock.advance(seconds=3)
    body = client.post(
        "/v1/transitions",
        json={
            "device_id": "dev-t",
            "domain": "WLAN",
            "peer_address": profile.wlan_address,
            "at": clock.now().isoformat(),
        },
    ).json()
    assert body["transition_detected"] is True
    assert body["transition_context"] == "NR_TO_WLAN"
    assert body["from_domain"] == "NR"
    assert body["gap_ms"] == 3000


def test_evidence_evaluate_returns_full_trace(client, registered, profile, clock) -> None:
    client.post(
        "/v1/collectors/events",
        json={
            "domain": "NR",
            "peer_address": profile.nr_address,
            "observed_at": clock.now().isoformat(),
        },
    )
    body = client.post(
        "/v1/evidence/evaluate",
        json={
            "device_id": registered,
            "peer_address": profile.nr_address,
            "domain": "NR",
            "session_identity": registered,
            "at": clock.now().isoformat(),
        },
    ).json()

    assert body["schema_version"] == "1"
    assert body["contains_synthetic_evidence"] is True
    assert len(body["predicates"]) == 11
    assert body["firing_rule"]
    assert body["trust_state"] in {
        "UNKNOWN",
        "STABLE",
        "TRANSITIONAL",
        "DEGRADED",
        "SUSPICIOUS",
        "UNTRUSTED",
    }
    names = {item["name"] for item in body["items"]}
    for required in (
        "identity_registered",
        "binding_present",
        "current_domain",
        "domain_posture_ok",
        "config_hash",
        "schema_version",
    ):
        assert required in names
    for item in body["items"]:
        assert item["source"]
        assert item["source_mode"]
        assert item["observed_at"]


def test_decision_evaluate_selects_the_strategy(client, registered, profile, clock) -> None:
    client.post(
        "/v1/collectors/events",
        json={
            "domain": "NR",
            "peer_address": profile.nr_address,
            "observed_at": clock.now().isoformat(),
        },
    )
    payload = {
        "device_id": registered,
        "peer_address": profile.nr_address,
        "domain": "NR",
        "session_identity": registered,
        "at": clock.now().isoformat(),
    }

    for name in ("ca_ztcf", "independent", "static_continuity"):
        body = client.post("/v1/decisions/evaluate", json={**payload, "strategy": name}).json()
        assert body["strategy"] == name
        assert body["action"] in {
            "ALLOW",
            "ALLOW_WITH_RESTRICTIONS",
            "STEP_UP_AUTHENTICATION",
            "REAUTHENTICATE",
            "QUARANTINE",
            "DENY",
        }
        assert body["config_hash"]


def test_unknown_strategy_is_rejected(client, registered, profile, clock) -> None:
    response = client.post(
        "/v1/decisions/evaluate",
        json={
            "device_id": registered,
            "peer_address": profile.nr_address,
            "domain": "NR",
            "strategy": "does-not-exist",
            "at": clock.now().isoformat(),
        },
    )
    assert response.status_code == 400


def test_unregistered_device_is_denied_with_registration_required(client, profile, clock) -> None:
    body = client.post(
        "/v1/decisions/evaluate",
        json={
            "device_id": "dev-not-enrolled",
            "peer_address": profile.nr_address,
            "domain": "NR",
            "at": clock.now().isoformat(),
        },
    ).json()
    assert body["trust_state"] == "UNKNOWN"
    assert body["action"] == "DENY"
    assert "REGISTRATION_REQUIRED" in body["reason_codes"]


def test_no_endpoint_ever_returns_private_key_material(client, device_key) -> None:
    client.post(
        "/v1/devices",
        json={"device_id": "dev-api-9", "public_key_pem": device_key.public_pem},
    )
    for path in ("/version", "/config/hash", "/v1/devices/dev-api-9", "/v1/collectors/bindings"):
        assert "PRIVATE KEY" not in client.get(path).text.upper()
