#!/usr/bin/env python3
"""End-to-end integration flow through the running Tier-1 testbed.

    device agent  ->  ca-ztcf-mqtt-pep  ->  mosquitto
                             |
                             v
                       ca-ztcf-core (decisions)

Exercises the full path: enrolment, proof-of-possession over MQTT CONNECT,
allowed publish, restricted scope after a transition, refused subscription,
step-up challenge and answer, quarantine, and refusal of unknown and untrusted
devices.

TIER-1 DEVELOPMENT VALIDATION. The 5G access context is a synthetic fixture and
the WLAN side is 802.1X/EAP-TLS authentication-path emulation. Not a WiFi, RF,
802.11 or 5G measurement, and not final thesis experimental evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from ca_ztcf.collectors.base import AccessDomain  # noqa: E402
from ca_ztcf.device.agent import AgentConfig, DeviceAgent  # noqa: E402
from ca_ztcf.device.keys import DeviceKeyPair  # noqa: E402
from ca_ztcf.enforcement import mqtt_codec as codec  # noqa: E402


class FlowError(RuntimeError):
    pass


def call(base: str, method: str, path: str, payload: dict[str, Any] | None = None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url=f"{base}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8")
            try:
                return response.status, json.loads(body) if body else None
            except json.JSONDecodeError:
                return response.status, body
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw
    except urllib.error.URLError as exc:
        raise FlowError(f"cannot reach {base}: {exc}") from exc


class Flow:
    def __init__(self, core: str, host: str, port: int) -> None:
        self.core = core.rstrip("/")
        self.host = host
        self.port = port
        self.steps: list[dict[str, Any]] = []

    def record(self, name: str, expectation: str, ok: bool, detail: Any = None) -> None:
        self.steps.append({"step": name, "expected": expectation, "ok": bool(ok), "detail": detail})
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {expectation}")

    def enrol(self, device_id: str) -> DeviceKeyPair:
        keys = DeviceKeyPair.generate(device_id)
        status, _ = call(
            self.core,
            "POST",
            "/v1/devices",
            {
                "device_id": device_id,
                "public_key_pem": keys.public_key_pem,
                "labels": {"purpose": "integration-flow"},
            },
        )
        self.record(f"enrol {device_id}", "201 Created", status == 201, {"status": status})
        return keys

    def bind(self, domain: str, address: str, at: datetime, **attrs: Any) -> None:
        source_mode = "synthetic_fixture" if domain == "NR" else "tier1_wlan_auth_emulation"
        status, _ = call(
            self.core,
            "POST",
            "/v1/collectors/events",
            {
                "domain": domain,
                "peer_address": address,
                "observed_at": at.isoformat(),
                "source_mode": source_mode,
                "attributes": attrs,
            },
        )
        if status != 200:
            raise FlowError(f"collector ingest failed: {status}")

    def release(self, domain: str, address: str, at: datetime) -> None:
        """Release an access binding through the collector's own event path.

        Needed because every host-side agent reaches the enforcement point from
        the same Docker bridge address, so bindings are shared between them. In a
        real deployment each device has its own address; here the binding is
        released explicitly so a scenario can start from "no binding".
        """
        event_type = "SESSION_RELEASED" if domain == "NR" else "STA_DISCONNECTED"
        source_mode = "synthetic_fixture" if domain == "NR" else "tier1_wlan_auth_emulation"
        status, _ = call(
            self.core,
            "POST",
            "/v1/collectors/events",
            {
                "domain": domain,
                "peer_address": address,
                "observed_at": at.isoformat(),
                "source_mode": source_mode,
                "event_type": event_type,
                "attributes": {},
            },
        )
        if status != 200:
            raise FlowError(f"collector release failed: {status}")

    def reset_bindings(self) -> int:
        """Release every access binding the core currently holds.

        Test setup, not a framework operation. Every host-side agent reaches the
        enforcement point from the same Docker bridge address, so a binding left
        by an earlier run would be attributed to a different device and this run's
        devices would correctly be judged UNTRUSTED. Clearing first makes the flow
        independent of what ran before it.
        """
        _, bindings = call(self.core, "GET", "/v1/collectors/bindings")
        released = 0
        for binding in bindings or []:
            self.release(str(binding["domain"]), str(binding["peer_address"]), datetime.now(UTC))
            released += 1
        return released

    def nonce(self, device_id: str) -> str:
        status, body = call(self.core, "POST", f"/v1/devices/{device_id}/nonce")
        if status != 200:
            raise FlowError(f"nonce request failed: {status}")
        return str(body["nonce"])

    def state(self, device_id: str) -> dict[str, Any]:
        _, body = call(self.core, "GET", f"/v1/devices/{device_id}/state")
        return dict(body or {})

    def agent(self, device_id: str, keys: DeviceKeyPair) -> DeviceAgent:
        return DeviceAgent(
            AgentConfig(
                device_id=device_id,
                gateway_host=self.host,
                gateway_port=self.port,
                domain=AccessDomain.NR,
            ),
            keys,
        )


async def discover_peer_address(flow: Flow, stamp: str) -> str:
    """Ask the enforcement point which address it actually sees for our connections.

    A probe device connects with no access binding, which yields a step-up and an
    announcement carrying the observed address. Assuming 127.0.0.1 would be wrong
    behind Docker port publishing, and silently wrong in a way that looks like a
    framework fault.
    """
    probe_id = f"dev-probe-{stamp}"
    keys = DeviceKeyPair.generate(probe_id)
    status, _ = call(
        flow.core,
        "POST",
        "/v1/devices",
        {"device_id": probe_id, "public_key_pem": keys.public_key_pem},
    )
    if status != 201:
        raise FlowError(f"probe enrolment failed: {status}")
    agent = flow.agent(probe_id, keys)
    if await agent.connect(None) != 0:
        raise FlowError("probe device could not connect")
    await agent.pump(duration_s=1.0)
    await agent.disconnect()
    address = (agent.last_decision or {}).get("observed_peer_address")
    if not address:
        raise FlowError("the enforcement point did not report an observed peer address")
    return str(address)


async def run(flow: Flow) -> dict[str, Any]:
    stamp = datetime.now(UTC).strftime("%H%M%S")
    device_id = f"dev-flow-{stamp}"
    now = datetime.now(UTC)

    # The enforcement point observes the real socket peer address, which through
    # Docker port publishing is the bridge address, not 127.0.0.1. Discover it by
    # connecting once and reading it back, rather than assuming.
    _, probe = call(flow.core, "GET", "/config/hash")
    cleared = flow.reset_bindings()
    print(f"  cleared {cleared} pre-existing access binding(s) before starting")
    peer = await discover_peer_address(flow, stamp)
    print(f"  observed peer address at the enforcement point: {peer}")

    print("\n-- 1. enrolment and steady 5G-domain session --")
    keys = flow.enrol(device_id)
    flow.bind(
        "NR",
        peer,
        now,
        subscriber_ref=f"fixture-{device_id}",
        gnb_id="gnb-001",
        pdu_session_id="1",
        dnn="internet",
    )

    agent = flow.agent(device_id, keys)
    code = await agent.connect(flow.nonce(device_id))
    flow.record(
        "MQTT CONNECT with proof-of-possession",
        "CONNACK 0 (accepted)",
        code == 0,
        {"connack": code},
    )

    await agent.publish(f"dev/{device_id}/telemetry/reading", {"v": 1})
    await asyncio.sleep(0.2)
    state = flow.state(device_id)
    flow.record(
        "steady 5G session",
        "trust state STABLE",
        state.get("trust_state") == "STABLE",
        state.get("trust_state"),
    )

    results = await agent.subscribe([f"cmd/{device_id}/set"])
    flow.record(
        "command subscription while STABLE",
        "granted (SUBACK != 0x80)",
        results.get(f"cmd/{device_id}/set") != codec.SUBACK_FAILURE,
        results,
    )
    await agent.disconnect()

    print("\n-- 2. transition to the Tier-1 WLAN authentication path --")
    later = now + timedelta(seconds=5)
    flow.bind(
        "WLAN",
        peer,
        later,
        sta_mac="02:00:00:00:00:11",
        eap_identity=f"{device_id}@lab.invalid",
        eap_success=True,
        akm="WPA2-EAP",
        ssid="ca-ztcf-tier1",
        ap_bssid="02:00:00:00:0a:01",
    )
    call(
        flow.core,
        "POST",
        "/v1/transitions",
        {"device_id": device_id, "domain": "WLAN", "peer_address": peer, "at": later.isoformat()},
    )

    agent = flow.agent(device_id, keys)
    agent.config.domain = AccessDomain.WLAN
    code = await agent.connect(flow.nonce(device_id))
    flow.record(
        "MQTT CONNECT after transition",
        "CONNACK 0 (session continues)",
        code == 0,
        {"connack": code},
    )
    await asyncio.sleep(0.2)

    state = flow.state(device_id)
    flow.record(
        "state after transition",
        "TRANSITIONAL",
        state.get("trust_state") == "TRANSITIONAL",
        state.get("trust_state"),
    )

    results = await agent.subscribe([f"cmd/{device_id}/set"])
    refused = results.get(f"cmd/{device_id}/set") == codec.SUBACK_FAILURE
    flow.record(
        "command subscription while TRANSITIONAL",
        "refused with SUBACK 0x80 (restricted scope)",
        refused,
        results,
    )

    telemetry = await agent.subscribe([f"dev/{device_id}/telemetry/x"])
    flow.record(
        "telemetry subscription while TRANSITIONAL",
        "granted",
        telemetry.get(f"dev/{device_id}/telemetry/x") != codec.SUBACK_FAILURE,
        telemetry,
    )
    await agent.disconnect()

    print("\n-- 3. step-up authentication --")
    stepup_id = f"dev-stepup-{stamp}"
    stepup_keys = flow.enrol(stepup_id)
    # Clear the shared binding so this device genuinely starts with no access
    # evidence. Missing evidence is DEGRADED, which is what step-up responds to.
    flow.release("WLAN", peer, datetime.now(UTC))
    flow.release("NR", peer, datetime.now(UTC))
    agent = flow.agent(stepup_id, stepup_keys)
    code = await agent.connect(None)
    flow.record(
        "CONNECT with no access binding",
        "accepted, protected operations held",
        code == 0,
        {"connack": code},
    )
    await agent.pump(duration_s=1.0)
    flow.record(
        "step-up challenge",
        "challenge delivered and answered by the device",
        agent.challenges_answered >= 1,
        {"answered": agent.challenges_answered, "decision": agent.last_decision},
    )
    await agent.disconnect()

    print("\n-- 4. refusals --")
    unknown_keys = DeviceKeyPair.generate("dev-unenrolled")
    agent = flow.agent("dev-unenrolled", unknown_keys)
    code = await agent.connect(None)
    flow.record(
        "unregistered device CONNECT",
        "refused with CONNACK 5",
        code == int(codec.ConnackReturnCode.NOT_AUTHORIZED),
        {"connack": code},
    )
    await agent.disconnect()

    revoke_status, _ = call(
        flow.core, "POST", f"/v1/devices/{device_id}/status", {"status": "REVOKED"}
    )
    if revoke_status != 200:
        raise FlowError(f"could not revoke {device_id}: {revoke_status}")
    agent = flow.agent(device_id, keys)
    code = await agent.connect(flow.nonce(device_id))
    flow.record(
        "revoked device CONNECT",
        "refused with CONNACK 5",
        code == int(codec.ConnackReturnCode.NOT_AUTHORIZED),
        {"connack": code},
    )
    await agent.disconnect()

    print("\n-- 5. quarantine --")
    quarantine_id = f"dev-quar-{stamp}"
    quarantine_keys = flow.enrol(quarantine_id)
    base = datetime.now(UTC)
    flow.bind("NR", peer, base, subscriber_ref="fixture-q", gnb_id="gnb-001")
    call(
        flow.core,
        "POST",
        "/v1/transitions",
        {"device_id": quarantine_id, "domain": "NR", "peer_address": peer, "at": base.isoformat()},
    )
    # A disallowed key-management suite is contradictory evidence, not missing
    # evidence: SUSPICIOUS, and across a transition that means QUARANTINE.
    flow.bind(
        "WLAN",
        peer,
        base + timedelta(seconds=2),
        sta_mac="02:00:00:00:00:22",
        eap_identity=f"{quarantine_id}@lab.invalid",
        eap_success=True,
        akm="OPEN",
        ssid="ca-ztcf-tier1",
        ap_bssid="02:00:00:00:0a:01",
    )
    call(
        flow.core,
        "POST",
        "/v1/transitions",
        {
            "device_id": quarantine_id,
            "domain": "WLAN",
            "peer_address": peer,
            "at": (base + timedelta(seconds=2)).isoformat(),
        },
    )

    agent = flow.agent(quarantine_id, quarantine_keys)
    agent.config.domain = AccessDomain.WLAN
    code = await agent.connect(flow.nonce(quarantine_id))
    await asyncio.sleep(0.2)
    state = flow.state(quarantine_id)
    quarantined = state.get("trust_state") == "SUSPICIOUS"
    flow.record(
        "unauthorised context across a transition",
        "SUSPICIOUS -> QUARANTINE",
        quarantined,
        state.get("trust_state"),
    )

    production = await agent.subscribe([f"dev/{quarantine_id}/telemetry/x"])
    quarantine_ns = await agent.subscribe([f"q/{quarantine_id}/observed"])
    flow.record(
        "production topic while quarantined",
        "refused",
        production.get(f"dev/{quarantine_id}/telemetry/x") == codec.SUBACK_FAILURE,
        production,
    )
    flow.record(
        "quarantine namespace while quarantined",
        "granted",
        quarantine_ns.get(f"q/{quarantine_id}/observed") != codec.SUBACK_FAILURE,
        quarantine_ns,
    )
    await agent.disconnect()

    print("\n-- 6. audit traceability --")
    _, decision = call(flow.core, "GET", f"/v1/devices/{quarantine_id}/decision")
    decision_id = (decision or {}).get("decision_id")
    found = False
    if decision_id:
        _, audit = call(flow.core, "GET", f"/v1/audit/{decision_id}")
        found = bool((audit or {}).get("found"))
    flow.record(
        "audit lookup by decision id",
        "the decision that produced enforcement is retrievable",
        found,
        {"decision_id": decision_id},
    )

    passed = sum(1 for s in flow.steps if s["ok"])
    return {
        "kind": "mqtt-integration-flow",
        "measurement_tier": "tier1",
        "result_class": "development_validation",
        "disclaimer": (
            "Tier-1 development validation. The 5G access context is a synthetic "
            "fixture and the WLAN side is 802.1X/EAP-TLS authentication-path "
            "emulation. Not a WiFi, RF, 802.11 or 5G measurement, and not final "
            "thesis experimental evidence."
        ),
        "executed_at_utc": datetime.now(UTC).isoformat(),
        "core_url": flow.core,
        "gateway": f"{flow.host}:{flow.port}",
        "config_hash": (probe or {}).get("config_hash"),
        "steps": flow.steps,
        "passed": passed,
        "failed": len(flow.steps) - passed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-url", default="http://127.0.0.1:8080")
    parser.add_argument("--gateway-host", default="127.0.0.1")
    parser.add_argument("--gateway-port", type=int, default=1884)
    parser.add_argument("--out", default=str(REPO / "artifacts" / "dev-validation"))
    args = parser.parse_args()

    print(
        f"CA-ZTCF MQTT integration flow: core={args.core_url} "
        f"gateway={args.gateway_host}:{args.gateway_port}"
    )
    flow = Flow(args.core_url, args.gateway_host, args.gateway_port)
    try:
        report = asyncio.run(run(flow))
    except FlowError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_file = out_dir / f"mqtt-flow-{stamp}.json"
    out_file.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"\n{report['passed']} passed, {report['failed']} failed")
    print(f"report written to {out_file}")
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
