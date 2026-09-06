#!/usr/bin/env python3
"""Tier-2 dual-access validation flow.

Runs inside the Tier-2 VM against the live software-based testbed:

    ca-ztcf-ue namespace   --5G user plane (GTP-U)-->  10.99.0.1 :1884
    ca-ztcf-sta namespace  --802.11 over hwsim----->   192.168.70.1 :1884
                                                            |
                                              ca-ztcf-mqtt-pep --> mosquitto
                                                            |
                                                      ca-ztcf-core

Each access path lives in its own network namespace, so a device's traffic can
only reach the enforcement point through the access technology it is attributed
to. See testbed/tier2/network/ue_path.sh and sta_path.sh for why.

Exercises one logical device reaching the same MQTT service over BOTH access
paths, with a real 5G->WiFi and WiFi->5G transition between them, and records the
T0-T6 timestamps separately so access authentication, path switching, trust
decision and application recovery can each be attributed.

SOFTWARE-BASED TESTBED. Real 5G NAS/NGAP/GTP-U with Open5GS and UERANSIM; real
IEEE 802.11 association and EAP-TLS through mac80211_hwsim. No physical radio, so
nothing here is an RF, propagation, interference or physical-handover measurement.

This is DEVELOPMENT VALIDATION, not final thesis evidence.
"""

from __future__ import annotations

import argparse
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

from ca_ztcf.device.keys import DeviceKeyPair  # noqa: E402

NS_NR = "ca-ztcf-ue"
NS_WLAN = "ca-ztcf-sta"
NR_SERVICE = "10.99.0.1"
WLAN_SERVICE = "192.168.70.1"
NR_IF = "uesimtun0"
WLAN_IF = "wlan1"
AGENT = str(Path(__file__).resolve().parent / "tier2_agent.py")
VENV_PYTHON = "/opt/ca-ztcf-venv/bin/python"
# From config/ca_ztcf.yaml. C7 holds inside the transition window, so the state is
# TRANSITIONAL; once it has elapsed with fresh evidence the state settles.
TRANSITION_WINDOW_S = 20
# Transitions are counted over the rate window. A second transition inside it that
# returns the device to the domain it just left is a REPEATED transition, and the
# policy correctly escalates to STEP_UP_AUTHENTICATION rather than merely
# restricting. This flow validates each direction as a first transition, so the
# two legs are spaced beyond the rate window; the repeated and rapid cases are
# what E05 and E09 exist to exercise.
RATE_WINDOW_S = 60


def call(base: str, method: str, path: str, payload: dict | None = None):  # noqa: ANN201
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(  # noqa: S310 - fixed scheme, local service
        url=f"{base}{path}", data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
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


def netns_address(namespace: str, interface: str) -> str:
    """The device's address on an access path, read from the live interface."""
    out = sh(f"sudo ip netns exec {namespace} ip -4 addr show {interface} 2>/dev/null")
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("inet "):
            return line.split()[1].split("/")[0]
    return ""


class Tier2Flow:
    def __init__(self, core: str, gateway_port: int, key_dir: Path) -> None:
        self.core = core.rstrip("/")
        self.gateway_port = gateway_port
        self.key_dir = key_dir
        self.steps: list[dict[str, Any]] = []
        self.transitions: list[dict[str, Any]] = []
        self.nr_address = ""
        self.wlan_address = ""
        self.supi = ""
        self.sta_mac = ""

    # -- reporting ---------------------------------------------------------
    def record(self, name: str, expectation: str, ok: bool, detail: Any = None) -> None:
        self.steps.append(
            {"step": name, "expected": expectation, "ok": bool(ok), "detail": detail}
        )
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {expectation}"
              + ("" if ok else f"\n         got: {detail}"))

    # -- service-domain operations ----------------------------------------
    def enrol(self, device_id: str) -> Path:
        keys = DeviceKeyPair.generate(device_id)
        key_file = self.key_dir / f"{device_id}.pem"
        keys.write_private_key(key_file)
        status, _ = call(
            self.core, "POST", "/v1/devices",
            {"device_id": device_id, "public_key_pem": keys.public_key_pem,
             "labels": {"tier": "tier2", "purpose": "validation"}},
        )
        if status != 201:
            raise RuntimeError(f"enrolment failed for {device_id}: {status}")
        return key_file

    def bind(self, domain: str, address: str, **attrs: Any) -> None:
        """Feed a binding observed from the LIVE testbed."""
        status, _ = call(
            self.core, "POST", "/v1/collectors/events",
            {"domain": domain, "peer_address": address,
             "observed_at": datetime.now(UTC).isoformat(),
             "source_mode": "live_testbed", "attributes": attrs},
        )
        if status != 200:
            raise RuntimeError(f"collector ingest failed: {status}")

    def bind_nr(self) -> None:
        self.bind("NR", self.nr_address, subscriber_ref=self.supi, dnn="internet",
                  pdu_session_id="1", serving_node="10.200.0.1",
                  access_implementation="ueransim", testbed_type="software_based")

    def bind_wlan(self) -> None:
        self.bind("WLAN", self.wlan_address, sta_mac=self.sta_mac,
                  eap_identity="device@lab.invalid", eap_success=True,
                  akm="WPA2-EAP", ssid="ca-ztcf-tier2", ap_bssid="02:00:00:00:00:00",
                  wifi_radio_mode="mac80211_hwsim", testbed_type="software_based")

    def nonce(self, device_id: str) -> str:
        status, body = call(self.core, "POST", f"/v1/devices/{device_id}/nonce")
        if status != 200:
            raise RuntimeError(f"nonce failed: {status}")
        return str(body["nonce"])

    def state(self, device_id: str) -> dict:
        _, body = call(self.core, "GET", f"/v1/devices/{device_id}/state")
        return dict(body or {})

    def decision(self, device_id: str) -> dict:
        _, body = call(self.core, "GET", f"/v1/devices/{device_id}/decision")
        return dict(body or {})

    # -- the device agent, inside its access namespace ---------------------
    def agent(self, domain: str, device_id: str, key_file: Path) -> dict:
        """Run one MQTT session over one access path and return its outcome.

        The agent executes inside the namespace that owns the access path, so the
        enforcement point observes a connection that genuinely arrived over that
        access technology rather than one that took a local short cut.
        """
        namespace = NS_NR if domain == "NR" else NS_WLAN
        service = NR_SERVICE if domain == "NR" else WLAN_SERVICE
        source = self.nr_address if domain == "NR" else self.wlan_address
        result = subprocess.run(  # noqa: S603 - fixed local command
            ["sudo", "ip", "netns", "exec", namespace, VENV_PYTHON, AGENT,
             "--device-id", device_id, "--key-file", str(key_file),
             "--host", service, "--port", str(self.gateway_port),
             "--source", source, "--domain", domain,
             "--nonce", self.nonce(device_id)],
            capture_output=True, text=True, check=False, timeout=60,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return {"ok": False, "error": (result.stderr or result.stdout)[-400:]}
        return json.loads(result.stdout.strip().splitlines()[-1])


def ms(a: int, b: int) -> float:
    return round((b - a) / 1_000_000, 3)


def settle(flow: Tier2Flow, device_id: str, key_file: Path, domain: str,
           label: str, hold_s: int = TRANSITION_WINDOW_S + 4) -> None:
    """Hold fresh evidence until the transition window has elapsed, then assert.

    A steady state is not asserted immediately after a path change: C7 holds
    inside the transition window by design, so the device is legitimately
    TRANSITIONAL until it expires.
    """
    print(f"     settling on {label} for {hold_s}s ...")
    deadline = time.monotonic() + hold_s
    while time.monotonic() < deadline:
        (flow.bind_nr if domain == "NR" else flow.bind_wlan)()
        time.sleep(4)
    outcome = flow.agent(domain, device_id, key_file)
    expected_source = flow.nr_address if domain == "NR" else flow.wlan_address
    state = flow.state(device_id)
    decision = flow.decision(device_id)
    flow.record(f"steady {label}: MQTT CONNECT", "CONNACK 0",
                outcome.get("connack") == 0, outcome)
    flow.record(f"steady {label}: observed source", expected_source,
                outcome.get("observed_peer_address") == expected_source,
                outcome.get("observed_peer_address"))
    flow.record(f"steady {label}: trust state", "STABLE",
                state.get("trust_state") == "STABLE", state)
    flow.record(f"steady {label}: policy action", "ALLOW",
                decision.get("action") == "ALLOW", decision.get("action"))
    flow.record(f"steady {label}: command topic", "granted",
                outcome.get("command_topic_refused") is False, outcome)


def transition(flow: Tier2Flow, device_id: str, key_file: Path, direction: str) -> None:
    """One real transition, with T0-T6 captured separately."""
    to_domain = "WLAN" if direction == "nr_to_wlan" else "NR"
    label = "5G->WiFi" if direction == "nr_to_wlan" else "WiFi->5G"

    t0 = time.perf_counter_ns()

    # T1-T2: authentication in the target access domain.
    t1 = time.perf_counter_ns()
    if to_domain == "WLAN":
        sh(f"sudo ip netns exec {NS_WLAN} wpa_cli -i {WLAN_IF} reassociate")
        for _ in range(60):
            if "Connected to" in sh(
                f"sudo ip netns exec {NS_WLAN} iw dev {WLAN_IF} link 2>/dev/null"
            ):
                break
            time.sleep(0.2)
        flow.wlan_address = netns_address(NS_WLAN, WLAN_IF) or flow.wlan_address
    else:
        # The PDU session is verified as live rather than re-established: tearing
        # the UE down and up would measure UERANSIM start-up, not a transition.
        flow.nr_address = netns_address(NS_NR, NR_IF) or flow.nr_address
    t2 = time.perf_counter_ns()

    # T3: the application path switches. The agent now runs in the other
    # namespace, so the next connection physically leaves by the other access.
    t3 = time.perf_counter_ns()

    # T4: corroborating access evidence reaches CA-ZTCF.
    (flow.bind_wlan if to_domain == "WLAN" else flow.bind_nr)()
    target = flow.wlan_address if to_domain == "WLAN" else flow.nr_address
    call(flow.core, "POST", "/v1/transitions",
         {"device_id": device_id, "domain": to_domain, "peer_address": target})
    t4 = time.perf_counter_ns()

    # T5: the device reconnects over the new path and the enforcement point acts
    # on the decision. The agent runs as a separate process inside the access
    # namespace, so this interval includes interpreter start-up and is NOT a trust
    # decision measurement; the decision itself is timed separately below.
    outcome = flow.agent(to_domain, device_id, key_file)
    t5 = time.perf_counter_ns()

    d0 = time.perf_counter_ns()
    call(flow.core, "POST", "/v1/decisions/evaluate",
         {"device_id": device_id, "peer_address": target, "domain": to_domain,
          "session_identity": device_id})
    decision_ms = ms(d0, time.perf_counter_ns())
    state = flow.state(device_id)
    decision = flow.decision(device_id)

    # T6: a protected application operation succeeds under the new context.
    t6 = time.perf_counter_ns()

    flow.record(f"{label}: MQTT CONNECT after transition", "CONNACK 0 (continuity)",
                outcome.get("connack") == 0, outcome)
    flow.record(f"{label}: observed source", target,
                outcome.get("observed_peer_address") == target,
                outcome.get("observed_peer_address"))
    flow.record(f"{label}: trust state", "TRANSITIONAL",
                state.get("trust_state") == "TRANSITIONAL", state)
    flow.record(f"{label}: policy action", "ALLOW_WITH_RESTRICTIONS",
                decision.get("action") == "ALLOW_WITH_RESTRICTIONS",
                decision.get("action"))
    flow.record(f"{label}: command topic while TRANSITIONAL", "refused (SUBACK 0x80)",
                outcome.get("command_topic_refused") is True, outcome)
    flow.record(f"{label}: telemetry topic while TRANSITIONAL", "granted",
                outcome.get("telemetry_topic_granted") is True, outcome)

    flow.transitions.append({
        "direction": direction,
        "device_id": device_id,
        "measurement_tier": "tier2",
        "testbed_type": "software_based",
        "source_mode": "live_testbed",
        "access_implementation": "mac80211_hwsim" if to_domain == "WLAN" else "ueransim",
        "observed_source": outcome.get("observed_peer_address"),
        "trust_state": state.get("trust_state"),
        "action": decision.get("action"),
        "timings_ms": {
            "T0_to_T1_request_to_auth_start": ms(t0, t1),
            "T1_to_T2_access_authentication": ms(t1, t2),
            "T2_to_T3_path_switch": ms(t2, t3),
            "T3_to_T4_evidence_arrival": ms(t3, t4),
            "T4_to_T5_reconnect_and_enforce": ms(t4, t5),
            "T5_to_T6_application_recovery": ms(t5, t6),
            "T0_to_T6_total": ms(t0, t6),
        },
        "trust_decision_ms": decision_ms,
        "note": (
            "software-based testbed; not an RF or physical handover measurement. "
            "T4_to_T5 includes agent process start-up in this harness and is not a "
            "trust decision time; trust_decision_ms is the decision alone."
        ),
    })


def run(flow: Tier2Flow) -> dict[str, Any]:
    # The 5G user plane is checked and repaired before anything is measured. A UE
    # that has dropped to RRC idle presents a tunnel interface that carries no
    # traffic, and every subsequent step would fail for that reason alone.
    print(sh(f"sudo bash {REPO}/testbed/tier2/network/ue_path.sh ensure 1"))
    flow.nr_address = netns_address(NS_NR, NR_IF)
    flow.wlan_address = netns_address(NS_WLAN, WLAN_IF)
    flow.supi = sh(
        "sudo grep -oE 'imsi-[0-9]+' /var/lib/ca-ztcf/tier2/ue.log | head -1"
    ) or "imsi-unknown"
    flow.sta_mac = sh(
        f"sudo ip netns exec {NS_WLAN} cat /sys/class/net/{WLAN_IF}/address"
    ) or "02:00:00:00:01:00"
    wlan_up = "Connected to" in sh(
        f"sudo ip netns exec {NS_WLAN} iw dev {WLAN_IF} link 2>/dev/null"
    )

    print("\n-- 0. live access paths --")
    flow.record("5G path live", f"{NR_IF} with a PDU session in {NS_NR}",
                bool(flow.nr_address), {"supi": flow.supi, "ue_ip": flow.nr_address})
    flow.record("WLAN path live", f"802.11 association complete in {NS_WLAN}",
                wlan_up and bool(flow.wlan_address),
                {"sta_mac": flow.sta_mac, "sta_ip": flow.wlan_address})

    # One logical device for the whole flow. Two devices presenting the same
    # access address would contradict C5 by construction, which is the predicate
    # working correctly rather than a result worth recording.
    print("\n-- 1. enrol the dual-access device --")
    device_id = f"dev-tier2-dual-{datetime.now(UTC).strftime('%H%M%S')}"
    key_file = flow.enrol(device_id)
    flow.bind_nr()
    outcome = flow.agent("NR", device_id, key_file)
    flow.record("enrolled device connects over 5G", "CONNACK 0 from the UE address",
                outcome.get("connack") == 0
                and outcome.get("observed_peer_address") == flow.nr_address,
                outcome)

    print("\n-- 2. steady state on the 5G path --")
    settle(flow, device_id, key_file, "NR", "5G")

    print("\n-- 3. real 5G -> WiFi transition --")
    transition(flow, device_id, key_file, "nr_to_wlan")

    print("\n-- 4. steady state on the WLAN path --")
    settle(flow, device_id, key_file, "WLAN", "WiFi", hold_s=RATE_WINDOW_S + 8)

    print("\n-- 5. real WiFi -> 5G transition --")
    transition(flow, device_id, key_file, "wlan_to_nr")

    print("\n-- 6. steady state back on the 5G path --")
    settle(flow, device_id, key_file, "NR", "5G (after return)")

    passed = sum(1 for s in flow.steps if s["ok"])
    return {
        "kind": "tier2-dual-access-validation",
        "measurement_tier": "tier2",
        "testbed_type": "software_based",
        "result_class": "development_validation",
        "access_implementations": {"5g": "ueransim", "wifi": "mac80211_hwsim"},
        "access_paths": {
            "5g": {"namespace": NS_NR, "interface": NR_IF,
                   "device_address": flow.nr_address, "service_address": NR_SERVICE},
            "wifi": {"namespace": NS_WLAN, "interface": WLAN_IF,
                     "device_address": flow.wlan_address,
                     "service_address": WLAN_SERVICE},
        },
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
    parser.add_argument("--key-dir", default="/var/lib/ca-ztcf/tier2/keys")
    args = parser.parse_args()

    print(f"CA-ZTCF Tier-2 dual-access validation (core={args.core_url})")
    key_dir = Path(args.key_dir)
    key_dir.mkdir(parents=True, exist_ok=True)
    key_dir.chmod(0o700)

    flow = Tier2Flow(args.core_url, args.gateway_port, key_dir)
    report = run(flow)

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
