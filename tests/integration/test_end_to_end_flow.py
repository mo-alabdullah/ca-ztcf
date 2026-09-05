"""The end-to-end trust-continuity flow, driven through the HTTP API.

This is the flow the development validation script also runs against a container.
It is a functional check of the implementation, not an experimental result.
"""

from __future__ import annotations

import base64

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

pytestmark = pytest.mark.integration


def _sign(private: Ed25519PrivateKey, nonce: str) -> str:
    padding = "=" * (-len(nonce) % 4)
    raw = base64.urlsafe_b64decode(nonce + padding)
    return base64.urlsafe_b64encode(private.sign(raw)).rstrip(b"=").decode("ascii")


def _proof(client, private: Ed25519PrivateKey, device_id: str) -> dict[str, str]:
    nonce = client.post(f"/v1/devices/{device_id}/nonce").json()["nonce"]
    return {"nonce": nonce, "signature": _sign(private, nonce), "algorithm": "ed25519"}


def _ingest(client, domain: str, address: str, clock, **attrs) -> None:
    payload = {
        "domain": domain,
        "peer_address": address,
        "observed_at": clock.now().isoformat(),
        "source_mode": "synthetic_fixture",
        "attributes": attrs,
    }
    assert client.post("/v1/collectors/events", json=payload).status_code == 200


def _decide(client, device_id, address, domain, clock, proof=None, session=None):
    payload = {
        "device_id": device_id,
        "peer_address": address,
        "domain": domain,
        "session_identity": session if session is not None else device_id,
        "at": clock.now().isoformat(),
    }
    if proof is not None:
        payload["proof"] = proof
    response = client.post("/v1/decisions/evaluate", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_stable_to_transitional_to_stable_then_identity_mismatch(
    client, app_state, clock, profile, settings
) -> None:
    private = Ed25519PrivateKey.generate()
    from cryptography.hazmat.primitives import serialization

    public_pem = (
        private.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )

    device_id = "dev-flow-001"

    # 1. enrol
    assert (
        client.post(
            "/v1/devices", json={"device_id": device_id, "public_key_pem": public_pem}
        ).status_code
        == 201
    )

    # 2. 5G access context observed, device authenticates
    _ingest(
        client,
        "NR",
        profile.nr_address,
        clock,
        subscriber_ref="flow-subscriber",
        gnb_id="gnb-001",
        pdu_session_id="1",
        dnn="internet",
    )
    first = _decide(
        client, device_id, profile.nr_address, "NR", clock, _proof(client, private, device_id)
    )

    # 3. STABLE / ALLOW
    assert first["trust_state"] == "STABLE"
    assert first["action"] == "ALLOW"
    assert first["transition_context"] == "NONE"

    # 4. transition to WLAN
    clock.advance(seconds=5)
    _ingest(
        client,
        "WLAN",
        profile.wlan_address,
        clock,
        sta_mac=profile.sta_mac,
        eap_identity=profile.eap_identity,
        eap_success=True,
        akm="WPA2-EAP",
        ssid=profile.ssid,
        ap_bssid=profile.ap_bssid,
    )
    second = _decide(
        client, device_id, profile.wlan_address, "WLAN", clock, _proof(client, private, device_id)
    )

    # 5. TRANSITIONAL / ALLOW_WITH_RESTRICTIONS
    assert second["trust_state"] == "TRANSITIONAL"
    assert second["transition_context"] == "NR_TO_WLAN"
    assert second["action"] == "ALLOW_WITH_RESTRICTIONS"
    assert second["scope"]["name"] == "restricted"

    # 6. evidence settles: window elapses and the binding is refreshed
    clock.advance(seconds=settings.transition.transition_window_s + 1)
    _ingest(
        client,
        "WLAN",
        profile.wlan_address,
        clock,
        sta_mac=profile.sta_mac,
        eap_identity=profile.eap_identity,
        eap_success=True,
        akm="WPA2-EAP",
        ssid=profile.ssid,
        ap_bssid=profile.ap_bssid,
    )
    third = _decide(
        client, device_id, profile.wlan_address, "WLAN", clock, _proof(client, private, device_id)
    )

    # 7. back to STABLE / ALLOW
    assert third["trust_state"] == "STABLE"
    assert third["action"] == "ALLOW"

    # 8. identity mismatch: a second device claims the same access binding
    intruder = Ed25519PrivateKey.generate()
    intruder_pem = (
        intruder.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )
    assert (
        client.post(
            "/v1/devices", json={"device_id": "dev-flow-intruder", "public_key_pem": intruder_pem}
        ).status_code
        == 201
    )

    fourth = _decide(
        client,
        "dev-flow-intruder",
        profile.wlan_address,
        "WLAN",
        clock,
        _proof(client, intruder, "dev-flow-intruder"),
    )

    # 9. documented outcome: UNTRUSTED / DENY
    assert fourth["trust_state"] == "UNTRUSTED"
    assert fourth["action"] == "DENY"
    assert "VALIDATION_FAILED" in fourth["reason_codes"]

    # The legitimate device is unaffected by the intruder's attempt.
    fifth = _decide(
        client, device_id, profile.wlan_address, "WLAN", clock, _proof(client, private, device_id)
    )
    assert fifth["action"] in {"ALLOW", "ALLOW_WITH_RESTRICTIONS"}


def test_disabled_device_is_denied_for_validation_failure(
    client, app_state, registered, profile, clock
) -> None:
    _ingest(client, "NR", profile.nr_address, clock, subscriber_ref="x")
    assert (
        client.post(f"/v1/devices/{registered}/status", json={"status": "REVOKED"}).status_code
        == 200
    )

    body = _decide(client, registered, profile.nr_address, "NR", clock)
    assert body["trust_state"] == "UNTRUSTED"
    assert body["action"] == "DENY"
    assert "VALIDATION_FAILED" in body["reason_codes"]


def test_every_decision_is_written_to_the_audit_log(
    client, app_state, registered, profile, clock
) -> None:
    before = app_state.audit.written
    _ingest(client, "NR", profile.nr_address, clock, subscriber_ref="x")
    _decide(client, registered, profile.nr_address, "NR", clock)
    assert app_state.audit.written == before + 1

    contents = app_state.audit.path.read_text(encoding="utf-8")
    assert "PRIVATE KEY" not in contents.upper()
    assert '"config_hash"' in contents
