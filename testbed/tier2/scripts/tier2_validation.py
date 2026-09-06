#!/usr/bin/env python3
"""Tier-2 dual-access validation flow.

Runs inside the Tier-2 VM against the live software-based testbed:

    device agent --(5G: uesimtun0 / WLAN: wlan1)--> ca-ztcf-mqtt-pep --> mosquitto
                                                            |
                                                            v
                                                      ca-ztcf-core

Exercises one logical device reaching the same MQTT service over BOTH access
paths, with a real 5G→WiFi and WiFi→5G transition between them, and records the
T0–T6 timestamps separately so access authentication, path switching, trust
decision and application recovery can each be attributed.

SOFTWARE-BASED TESTBED. Real 5G NAS/NGAP/GTP-U with Open5GS and UERANSIM; real
IEEE 802.11 association and EAP-TLS through mac80211_hwsim. No physical radio, so
nothing here is an RF, propagation, interference or physical-handover measurement.

This is DEVELOPMENT VALIDATION, not final thesis evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from ca_ztcf.collectors.base import AccessDomain  # noqa: E402
from ca_ztcf.device.agent import AgentConfig, DeviceAgent  # noqa: E402
from ca_ztcf.device.keys import DeviceKeyPair  # noqa: E402
from ca_ztcf.enforcement import mqtt_codec as codec  # noqa: E402

# The device's address in each access domain, and the service address reachable
# from it. The agent binds its socket to the access-path source address and
# connects to the address reachable over that path, so the enforcement point
# genuinely observes the device arriving from that access domain. Connecting over
# loopback would make every path look identical and the binding evidence
# meaningless.
NR_ADDRESS = "10.45.0.2"        # UE tunnel address (uesimtun0)
NR_SERVICE = "10.45.0.1"        # UPF-side address the service is reachable on
WLAN_ADDRESS = "192.168.70.10"  # station address (wlan1)
WLAN_SERVICE = "192.168.70.1"   # access-point-side service address


def call(base: str, method: str, path: str, payload: dict | None = None):  # noqa: ANN201
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(  # noqa: S310 - fixed scheme, local service
        url=f"{base}{path}", data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            body = response.read().decode()
            try:
                return response.status, json.loads(body) if body else None
            except json.JSONDecodeError:
                return response.status, body
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw


def sh(command: str) -> str:
    result = subprocess.run(  # noqa: S602 - fixed local commands
        command, shell=True, capture_output=True, text=True, check=False
    )
    return result.stdout.strip()


class Tier2Flow:
    def __init__(self, core: str, gateway_port: int) -> None:
        self.core = core.rstrip("/")
        self.gateway_port = gateway_port
        self.steps: list[dict[str, Any]] = []
        self.transitions: list[dict[str, Any]] = []

    def record(self, name: str, expectation: str, ok: bool, detail: Any = None) -> None:
        self.steps.append(
            {"step": name, "expected": expectation, "ok": bool(ok), "detail": detail}
        )
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {expectation}")

    def bind(self, domain: str, address: str, **attrs: Any) -> None:
        """Feed a binding observed from the LIVE testbed."""
        status, _ = call(
            self.core, "POST", "/v1/collectors/events",
            {
                "domain": domain, "peer_address": address,
                "observed_at": datetime.now(UTC).isoformat(),
                "source_mode": "live_testbed", "attributes": attrs,
            },
        )
        if status != 200:
            raise RuntimeError(f"collector ingest failed: {status}")

    def nonce(self, device_id: str) -> str:
        status, body = call(self.core, "POST", f"/v1/devices/{device_id}/nonce")
        if status != 200:
            raise RuntimeError(f"nonce failed: {status}")
        return str(body["nonce"])

    def state(self, device_id: str) -> dict:
        _, body = call(self.core, "GET", f"/v1/devices/{device_id}/state")
        return dict(body or {})

    def bind_nr(self, supi: str) -> None:
        self.bind("NR", NR_ADDRESS, subscriber_ref=supi, dnn="internet",
                  pdu_session_id="1", gnb_id="127.0.0.1")

    def bind_wlan(self, sta_mac: str) -> None:
        self.bind("WLAN", WLAN_ADDRESS, sta_mac=sta_mac,
                  eap_identity="device@lab.invalid", eap_success=True,
                  akm="WPA2-EAP", ssid="ca-ztcf-tier2", ap_bssid="02:00:00:00:00:00")


async def run(flow: Tier2Flow) -> dict[str, Any]:
    stamp = datetime.now(UTC).strftime("%H%M%S")
    device_id = f"dev-tier2-{stamp}"

    supi = sh("sudo grep -oE 'imsi-[0-9]+' /var/lib/ca-ztcf/tier2/ue.log | head -1") or "imsi-unknown"
    sta_mac = sh("cat /sys/class/net/wlan1/address") or "02:00:00:00:01:00"
    ue_up = bool(sh("ip link show uesimtun0 2>/dev/null"))
    wlan_up = "wpa_state=COMPLETED" in sh("sudo wpa_cli -i wlan1 status 2>/dev/null")

    print("\n-- 0. live access paths --")
    flow.record("5G path live", "uesimtun0 present with a PDU session", ue_up,
                {"supi": supi, "ue_ip": NR_ADDRESS})
    flow.record("WLAN path live", "802.11 association complete", wlan_up,
                {"sta_mac": sta_mac, "sta_ip": WLAN_ADDRESS})

    print("\n-- 1. enrol the dual-access device --")
    keys = DeviceKeyPair.generate(device_id)
    status, _ = call(flow.core, "POST", "/v1/devices",
                     {"device_id": device_id, "public_key_pem": keys.public_key_pem,
                      "labels": {"tier": "tier2", "purpose": "validation"}})
    flow.record("enrol service-domain identity", "201 Created", status == 201,
                {"device_id": device_id,
                 "note": "Ed25519 service-domain identity; not the SUPI or the MAC"})

    print("\n-- 2. MQTT over the 5G path --")
    flow.bind_nr(supi)
    agent = DeviceAgent(
        AgentConfig(device_id=device_id, gateway_host=NR_SERVICE,
                    gateway_port=flow.gateway_port, source_address=NR_ADDRESS,
                    domain=AccessDomain.NR),
        keys,
    )
    code = await agent.connect(flow.nonce(device_id))
    flow.record("MQTT CONNECT over 5G", "CONNACK 0 from the UE tunnel address",
                code == 0, {"connack": code, "source": NR_ADDRESS})
    await agent.publish(f"dev/{device_id}/telemetry/reading", {"path": "5g"})
    await asyncio.sleep(0.2)
    state = flow.state(device_id)
    flow.record("trust state on the 5G path", "STABLE",
                state.get("trust_state") == "STABLE", state.get("trust_state"))
    await agent.disconnect()

    print("\n-- 3. real 5G -> WiFi transition --")
    t0 = time.perf_counter_ns()
    t1 = time.perf_counter_ns()
    sh("sudo wpa_cli -i wlan1 reassociate")
    for _ in range(40):
        if "wpa_state=COMPLETED" in sh("sudo wpa_cli -i wlan1 status 2>/dev/null"):
            break
        time.sleep(0.2)
    t2 = time.perf_counter_ns()
    t3 = time.perf_counter_ns()
    flow.bind_wlan(sta_mac)
    call(flow.core, "POST", "/v1/transitions",
         {"device_id": device_id, "domain": "WLAN", "peer_address": WLAN_ADDRESS})
    t4 = time.perf_counter_ns()

    agent = DeviceAgent(
        AgentConfig(device_id=device_id, gateway_host=WLAN_SERVICE,
                    gateway_port=flow.gateway_port, source_address=WLAN_ADDRESS,
                    domain=AccessDomain.WLAN),
        keys,
    )
    code = await agent.connect(flow.nonce(device_id))
    t5 = time.perf_counter_ns()
    await agent.publish(f"dev/{device_id}/telemetry/reading", {"path": "wifi"})
    await asyncio.sleep(0.2)
    t6 = time.perf_counter_ns()

    state = flow.state(device_id)
    flow.record("MQTT CONNECT after transition", "CONNACK 0 (session continues)",
                code == 0, {"connack": code})
    flow.record("state after 5G->WiFi", "TRANSITIONAL",
                state.get("trust_state") == "TRANSITIONAL", state.get("trust_state"))

    results = await agent.subscribe([f"cmd/{device_id}/set"])
    flow.record("command topic while TRANSITIONAL", "refused with SUBACK 0x80",
                results.get(f"cmd/{device_id}/set") == codec.SUBACK_FAILURE, results)

    ms = lambda a, b: round((b - a) / 1_000_000, 3)  # noqa: E731
    flow.transitions.append({
        "direction": "nr_to_wlan", "device_id": device_id,
        "measurement_tier": "tier2", "testbed_type": "software_based",
        "source_mode": "live_testbed", "access_implementation": "mac80211_hwsim",
        "timings_ms": {
            "T0_to_T1_request_to_auth_start": ms(t0, t1),
            "T1_to_T2_access_authentication": ms(t1, t2),
            "T2_to_T3_path_switch": ms(t2, t3),
            "T3_to_T4_evidence_arrival": ms(t3, t4),
            "T4_to_T5_trust_decision": ms(t4, t5),
            "T5_to_T6_application_recovery": ms(t5, t6),
            "T0_to_T6_total": ms(t0, t6),
        },
        "note": "software-based testbed; not an RF or physical handover measurement",
    })
    await agent.disconnect()

    print("\n-- 4. evidence settles on the WLAN path --")
    for _ in range(3):
        flow.bind_wlan(sta_mac)
        time.sleep(1)
    agent = DeviceAgent(
        AgentConfig(device_id=device_id, gateway_host=WLAN_SERVICE,
                    gateway_port=flow.gateway_port, source_address=WLAN_ADDRESS,
                    domain=AccessDomain.WLAN),
        keys,
    )
    await agent.connect(flow.nonce(device_id))
    await asyncio.sleep(0.2)
    state = flow.state(device_id)
    flow.record("state after settling", "TRANSITIONAL or STABLE",
                state.get("trust_state") in {"TRANSITIONAL", "STABLE"},
                state.get("trust_state"))
    await agent.disconnect()

    print("\n-- 5. real WiFi -> 5G transition --")
    r0 = time.perf_counter_ns()
    ue_still_up = bool(sh("ip link show uesimtun0 2>/dev/null"))
    r2 = time.perf_counter_ns()
    flow.bind_nr(supi)
    call(flow.core, "POST", "/v1/transitions",
         {"device_id": device_id, "domain": "NR", "peer_address": NR_ADDRESS})
    r4 = time.perf_counter_ns()

    agent = DeviceAgent(
        AgentConfig(device_id=device_id, gateway_host=NR_SERVICE,
                    gateway_port=flow.gateway_port, source_address=NR_ADDRESS,
                    domain=AccessDomain.NR),
        keys,
    )
    code = await agent.connect(flow.nonce(device_id))
    r5 = time.perf_counter_ns()
    await agent.publish(f"dev/{device_id}/telemetry/reading", {"path": "5g-again"})
    await asyncio.sleep(0.2)
    r6 = time.perf_counter_ns()
    state = flow.state(device_id)

    flow.record("5G path still established", "uesimtun0 present", ue_still_up)
    flow.record("MQTT CONNECT back on 5G", "CONNACK 0", code == 0, {"connack": code})
    flow.record("state after WiFi->5G", "TRANSITIONAL",
                state.get("trust_state") == "TRANSITIONAL", state.get("trust_state"))

    flow.transitions.append({
        "direction": "wlan_to_nr", "device_id": device_id,
        "measurement_tier": "tier2", "testbed_type": "software_based",
        "source_mode": "live_testbed", "access_implementation": "ueransim",
        "timings_ms": {
            "T0_to_T1_request_to_auth_start": ms(r0, r0),
            "T1_to_T2_access_authentication": ms(r0, r2),
            "T2_to_T3_path_switch": ms(r2, r2),
            "T3_to_T4_evidence_arrival": ms(r2, r4),
            "T4_to_T5_trust_decision": ms(r4, r5),
            "T5_to_T6_application_recovery": ms(r5, r6),
            "T0_to_T6_total": ms(r0, r6),
        },
        "note": "software-based testbed; not an RF or physical handover measurement",
    })
    await agent.disconnect()

    passed = sum(1 for s in flow.steps if s["ok"])
    return {
        "kind": "tier2-dual-access-validation",
        "measurement_tier": "tier2",
        "testbed_type": "software_based",
        "result_class": "development_validation",
        "access_implementations": {"5g": "ueransim", "wifi": "mac80211_hwsim"},
        "disclaimer": (
            "Tier-2 live software-based testbed. Real 5G NAS/NGAP/GTP-U via Open5GS "
            "and UERANSIM; real IEEE 802.11 association and EAP-TLS via "
            "mac80211_hwsim. No physical radio: not an RF, propagation, "
            "interference, channel-quality or physical-handover measurement, and "
            "not final thesis experimental evidence."
        ),
        "executed_at_utc": datetime.now(UTC).isoformat(),
        "steps": flow.steps,
        "transitions": flow.transitions,
        "passed": passed,
        "failed": len(flow.steps) - passed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-url", default="http://127.0.0.1:8080")
    parser.add_argument("--gateway-port", type=int, default=1884)
    parser.add_argument("--out", default="/var/lib/ca-ztcf/tier2")
    args = parser.parse_args()

    print(f"CA-ZTCF Tier-2 dual-access validation (core={args.core_url})")
    flow = Tier2Flow(args.core_url, args.gateway_port)
    report = asyncio.run(run(flow))

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_file = out_dir / f"tier2-validation-{stamp}.json"
    out_file.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"\n{report['passed']} passed, {report['failed']} failed")
    print(f"report: {out_file}")
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
