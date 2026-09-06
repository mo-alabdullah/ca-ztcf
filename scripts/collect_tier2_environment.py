#!/usr/bin/env python3
"""Record the Tier-2 environment the final campaign executed in.

Read from the running VM, not typed. Table A is generated from this file, so a
version in the thesis is a version the machine reported.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

PROBES = {
    "guest_os": '. /etc/os-release && echo "$PRETTY_NAME"',
    "kernel": "uname -r",
    "arch": "uname -m",
    "cpus": "nproc",
    "memory_total": "free -h | awk '/^Mem:/{print $2}'",
    "open5gs": "dpkg-query -W -f='Open5GS ${Version}' open5gs",
    "ueransim": 'echo "UERANSIM $(/opt/UERANSIM/build/nr-gnb --version 2>&1 | head -1)"',
    "hostapd": "hostapd -v 2>&1 | head -1",
    "wpa_supplicant": "wpa_supplicant -v 2>&1 | head -1",
    "mongodb": "mongod --version 2>/dev/null | head -1 | sed 's/db version/MongoDB/'",
    "mosquitto": "mosquitto -h 2>&1 | head -1",
    "python": "/opt/ca-ztcf-venv/bin/python -V",
    "hwsim_module": "lsmod | awk '/^mac80211_hwsim/{print \"mac80211_hwsim loaded\"}'",
    "ue_namespace": "ip netns list | grep -o '^ca-ztcf-ue'",
    "sta_namespace": "ip netns list | grep -o '^ca-ztcf-sta'",
}


def probe(vm: str, command: str) -> str:
    result = subprocess.run(
        ["limactl", "shell", vm, "bash", "-lc", command],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    return result.stdout.strip().splitlines()[-1].strip() if result.stdout.strip() else ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vm", default="ca-ztcf-tier2")
    parser.add_argument("--out", default=str(REPO / "results" / "final" / "metadata"))
    args = parser.parse_args()

    values = {name: probe(args.vm, command) for name, command in PROBES.items()}
    host = subprocess.run(
        ["sw_vers", "-productVersion"], capture_output=True, text=True, check=False
    ).stdout.strip()
    lima = subprocess.run(
        ["limactl", "--version"], capture_output=True, text=True, check=False
    ).stdout.strip()

    record = {
        "collected_at": datetime.now(UTC).isoformat(),
        "host": f"macOS {host}" if host else "macOS",
        "virtualisation": lima or "Lima",
        "guest_os": values["guest_os"],
        "kernel": values["kernel"],
        "arch": values["arch"],
        "resources": f"{values['cpus']} vCPU, {values['memory_total']} RAM",
        "open5gs": values["open5gs"],
        "ueransim": values["ueransim"],
        "wlan": ", ".join(
            v for v in (values["hwsim_module"], values["hostapd"], values["wpa_supplicant"]) if v
        ),
        "mongodb": values["mongodb"],
        "mosquitto": values["mosquitto"],
        "python": values["python"],
        "access_namespaces": ", ".join(
            v for v in (values["ue_namespace"], values["sta_namespace"]) if v
        ),
        "physical_radio": "none: both radios are simulated",
        "note": (
            "Read from the running Tier-2 VM. Software-based testbed; no physical RF exists in it."
        ),
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "environment.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
