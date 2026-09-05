#!/usr/bin/env python3
"""Development validation flow against a running CA-ZTCF service.

Drives the full trust-continuity sequence end to end and records what happened.

This is a FUNCTIONAL CHECK of the implementation. It is not an experiment, and
its output must never be presented as a thesis result: all access-domain events
it submits are development fixtures carrying ``source_mode: synthetic_fixture``.
Output is written under ``artifacts/dev-validation/``, deliberately separate from
any future ``results/`` tree.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

NR_ADDRESS = "10.45.0.2"
WLAN_ADDRESS = "192.168.60.2"


class ApiError(RuntimeError):
    pass


def call(
    base_url: str, method: str, path: str, payload: dict[str, Any] | None = None
) -> tuple[int, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url=f"{base_url}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8")
            if not body:
                return response.status, None
            try:
                return response.status, json.loads(body)
            except json.JSONDecodeError:
                # Not every endpoint is JSON: /metrics returns Prometheus text.
                return response.status, body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, body
    except urllib.error.URLError as exc:
        raise ApiError(f"cannot reach {base_url}: {exc}") from exc


def public_pem(private: Ed25519PrivateKey) -> str:
    return (
        private.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )


def sign(private: Ed25519PrivateKey, nonce: str) -> str:
    padding = "=" * (-len(nonce) % 4)
    raw = base64.urlsafe_b64decode(nonce + padding)
    return base64.urlsafe_b64encode(private.sign(raw)).rstrip(b"=").decode("ascii")


def proof(base_url: str, private: Ed25519PrivateKey, device_id: str) -> dict[str, str]:
    status, body = call(base_url, "POST", f"/v1/devices/{device_id}/nonce")
    if status != 200:
        raise ApiError(f"nonce request failed ({status}): {body}")
    nonce = body["nonce"]
    return {"nonce": nonce, "signature": sign(private, nonce), "algorithm": "ed25519"}


def ingest(base_url: str, domain: str, address: str, at: datetime, **attrs: Any) -> None:
    status, body = call(
        base_url,
        "POST",
        "/v1/collectors/events",
        {
            "domain": domain,
            "peer_address": address,
            "observed_at": at.isoformat(),
            "source_mode": "synthetic_fixture",
            "attributes": attrs,
        },
    )
    if status != 200:
        raise ApiError(f"collector ingest failed ({status}): {body}")


def decide(
    base_url: str,
    device_id: str,
    address: str,
    domain: str,
    at: datetime,
    proof_payload: dict[str, str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "device_id": device_id,
        "peer_address": address,
        "domain": domain,
        "session_identity": device_id,
        "at": at.isoformat(),
    }
    if proof_payload is not None:
        payload["proof"] = proof_payload
    status, body = call(base_url, "POST", "/v1/decisions/evaluate", payload)
    if status != 200:
        raise ApiError(f"decision failed ({status}): {body}")
    return dict(body)


NR_ATTRS = {
    "subscriber_ref": "devval-subscriber",
    "gnb_id": "gnb-001",
    "pdu_session_id": "1",
    "dnn": "internet",
}
WLAN_ATTRS = {
    "sta_mac": "02:00:00:00:00:01",
    "eap_identity": "devval-device@lab.invalid",
    "eap_success": True,
    "akm": "WPA2-EAP",
    "ssid": "ca-ztcf-lab",
    "ap_bssid": "02:00:00:00:0a:01",
}


def run(base_url: str) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    failures: list[str] = []

    def record(name: str, detail: dict[str, Any], ok: bool, expectation: str) -> None:
        steps.append({"step": name, "expected": expectation, "ok": ok, "detail": detail})
        marker = "PASS" if ok else "FAIL"
        print(f"  [{marker}] {name}: {expectation}")
        if not ok:
            failures.append(name)

    # -- endpoint smoke checks ------------------------------------------
    for path, key, expected in (
        ("/healthz", "status", "ok"),
        ("/readyz", "status", "ready"),
    ):
        status, body = call(base_url, "GET", path)
        record(
            f"GET {path}",
            {"status_code": status, "body": body},
            status == 200 and body.get(key) == expected,
            f"200 and {key}={expected}",
        )

    status, version_body = call(base_url, "GET", "/version")
    record(
        "GET /version",
        {"status_code": status, "body": version_body},
        status == 200 and "version" in version_body,
        "200 with a version",
    )

    status, hash_body = call(base_url, "GET", "/config/hash")
    record(
        "GET /config/hash",
        {"status_code": status, "body": hash_body},
        status == 200 and len(hash_body.get("config_hash", "")) == 64,
        "200 with a 64-character configuration hash",
    )

    status, metrics_body = call(base_url, "GET", "/metrics")
    has_families = isinstance(metrics_body, str) and "ca_ztcf_decisions_total" in metrics_body
    record(
        "GET /metrics",
        {"status_code": status, "families_present": has_families},
        status == 200,
        "200 from the metrics endpoint",
    )

    # -- trust continuity flow -------------------------------------------
    stamp = datetime.now(UTC).strftime("%H%M%S")
    device_id = f"dev-val-{stamp}"
    intruder_id = f"dev-val-intruder-{stamp}"
    private = Ed25519PrivateKey.generate()
    intruder = Ed25519PrivateKey.generate()
    t0 = datetime.now(UTC)

    # 1. register
    status, body = call(
        base_url,
        "POST",
        "/v1/devices",
        {
            "device_id": device_id,
            "public_key_pem": public_pem(private),
            "labels": {"purpose": "development-validation"},
        },
    )
    record(
        "1. register device",
        {"status_code": status, "device_id": device_id},
        status == 201,
        "201 Created",
    )

    # 2-3. valid 5G evidence -> STABLE / ALLOW
    ingest(base_url, "NR", NR_ADDRESS, t0, **NR_ATTRS)
    first = decide(base_url, device_id, NR_ADDRESS, "NR", t0, proof(base_url, private, device_id))
    record(
        "2-3. steady 5G session",
        first,
        first["trust_state"] == "STABLE" and first["action"] == "ALLOW",
        "STABLE / ALLOW",
    )

    # 4-5. NR -> WLAN transition -> TRANSITIONAL / ALLOW_WITH_RESTRICTIONS
    t1 = t0 + timedelta(seconds=5)
    ingest(base_url, "WLAN", WLAN_ADDRESS, t1, **WLAN_ATTRS)
    second = decide(
        base_url, device_id, WLAN_ADDRESS, "WLAN", t1, proof(base_url, private, device_id)
    )
    record(
        "4-5. 5G to WiFi transition",
        second,
        second["trust_state"] == "TRANSITIONAL"
        and second["transition_context"] == "NR_TO_WLAN"
        and second["action"] == "ALLOW_WITH_RESTRICTIONS",
        "TRANSITIONAL / NR_TO_WLAN / ALLOW_WITH_RESTRICTIONS",
    )

    # 6-7. evidence settles -> back to STABLE / ALLOW
    t2 = t1 + timedelta(seconds=25)
    ingest(base_url, "WLAN", WLAN_ADDRESS, t2, **WLAN_ATTRS)
    third = decide(
        base_url, device_id, WLAN_ADDRESS, "WLAN", t2, proof(base_url, private, device_id)
    )
    record(
        "6-7. evidence settles",
        third,
        third["trust_state"] == "STABLE" and third["action"] == "ALLOW",
        "return to STABLE / ALLOW",
    )

    # 8-9. identity mismatch -> UNTRUSTED / DENY
    status, body = call(
        base_url,
        "POST",
        "/v1/devices",
        {"device_id": intruder_id, "public_key_pem": public_pem(intruder)},
    )
    fourth = decide(
        base_url, intruder_id, WLAN_ADDRESS, "WLAN", t2, proof(base_url, intruder, intruder_id)
    )
    record(
        "8-9. identity mismatch",
        fourth,
        fourth["trust_state"] == "UNTRUSTED"
        and fourth["action"] == "DENY"
        and "VALIDATION_FAILED" in fourth["reason_codes"],
        "UNTRUSTED / DENY / VALIDATION_FAILED",
    )

    # 10. an unregistered device is denied for registration, not re-authenticated
    fifth = decide(base_url, f"dev-unenrolled-{stamp}", NR_ADDRESS, "NR", t2)
    record(
        "10. unregistered device",
        fifth,
        fifth["trust_state"] == "UNKNOWN"
        and fifth["action"] == "DENY"
        and "REGISTRATION_REQUIRED" in fifth["reason_codes"],
        "UNKNOWN / DENY / REGISTRATION_REQUIRED",
    )

    return {
        "kind": "development-validation",
        "disclaimer": (
            "Functional check of the implementation. Not an experiment and not a "
            "thesis result. All access-domain events are synthetic_fixture data."
        ),
        "executed_at_utc": datetime.now(UTC).isoformat(),
        "base_url": base_url,
        "service_version": version_body,
        "config_hash": hash_body.get("config_hash") if isinstance(hash_body, dict) else None,
        "steps": steps,
        "passed": len(steps) - len(failures),
        "failed": len(failures),
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--out", default="artifacts/dev-validation")
    args = parser.parse_args()

    print(f"CA-ZTCF development validation flow against {args.base_url}")
    try:
        report = run(args.base_url.rstrip("/"))
    except ApiError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_file = out_dir / f"flow-{stamp}.json"
    out_file.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"\n{report['passed']} passed, {report['failed']} failed")
    print(f"report written to {out_file}")
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
