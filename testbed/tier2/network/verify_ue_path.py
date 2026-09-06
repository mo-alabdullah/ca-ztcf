#!/usr/bin/env python3
"""Prove that the Tier-2 5G application path is deterministic.

Independent of CA-ZTCF. A plain TCP server binds the service address in the root
namespace; a plain TCP client connects from inside the UE namespace; the server
records the source address it actually observes. Packet captures on both ends of
the tunnel corroborate that the traffic really traversed GTP-U rather than taking
a local short cut.

DEVELOPMENT VALIDATION of the network path. Not an experiment, not a result.

SOFTWARE-BASED TESTBED. Real 5G user plane over a synthesised radio; no physical
RF, and none of this is an RF measurement.
"""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

NS = "ca-ztcf-ue"
SERVICE_ADDR = "10.99.0.1"
SERVICE_PORT = 19099


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class Observer(threading.Thread):
    """Accepts connections and records the source address of each one."""

    def __init__(self, addr: str, port: int, expected: int) -> None:
        super().__init__(daemon=True)
        self.expected = expected
        self.observed: list[str] = []
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((addr, port))
        self.sock.listen(16)
        self.sock.settimeout(1.0)
        self._halt = threading.Event()

    def run(self) -> None:
        while not self._halt.is_set() and len(self.observed) < self.expected:
            try:
                conn, peer = self.sock.accept()
            except socket.timeout:
                continue
            self.observed.append(peer[0])
            try:
                conn.sendall(b"ok\n")
            finally:
                conn.close()
        self.sock.close()

    def stop(self) -> None:
        self._halt.set()


def ue_address(ns: str) -> str:
    out = subprocess.run(
        ["ip", "netns", "exec", ns, "ip", "-4", "addr", "show", "uesimtun0"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("inet "):
            return line.split()[1].split("/")[0]
    raise RuntimeError("uesimtun0 has no IPv4 address")


def start_capture(args: list[str], out: Path) -> subprocess.Popen | None:
    if shutil.which("tcpdump") is None:
        return None
    handle = out.open("wb")
    return subprocess.Popen(args, stdout=handle, stderr=subprocess.DEVNULL)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=10)
    parser.add_argument("--namespace", default=NS)
    parser.add_argument("--service-address", default=SERVICE_ADDR)
    parser.add_argument("--service-port", type=int, default=SERVICE_PORT)
    parser.add_argument("--out", default="/opt/ca-ztcf/artifacts/dev-validation")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    expected = ue_address(args.namespace)

    ue_cap = out_dir / "ue-path-uesimtun0.txt"
    gw_cap = out_dir / "ue-path-ogstun.txt"
    filt = f"tcp port {args.service_port}"
    cap_ue = start_capture(
        ["ip", "netns", "exec", args.namespace, "tcpdump", "-l", "-n", "-i",
         "uesimtun0", filt],
        ue_cap,
    )
    cap_gw = start_capture(["tcpdump", "-l", "-n", "-i", "ogstun", filt], gw_cap)
    time.sleep(1.5)

    observer = Observer(args.service_address, args.service_port, args.repetitions)
    observer.start()
    time.sleep(0.3)

    attempts: list[dict] = []
    for index in range(args.repetitions):
        started = time.perf_counter_ns()
        proc = subprocess.run(
            [
                "ip", "netns", "exec", args.namespace,
                "bash", "-c",
                f"exec 3<>/dev/tcp/{args.service_address}/{args.service_port} "
                f"&& head -c3 <&3",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        attempts.append(
            {
                "index": index,
                "connected": proc.returncode == 0,
                "elapsed_ms": round((time.perf_counter_ns() - started) / 1e6, 3),
                "stderr": proc.stderr.strip()[:200],
            }
        )
        time.sleep(0.1)

    time.sleep(1.0)
    observer.stop()
    observer.join(timeout=5)
    for cap in (cap_ue, cap_gw):
        if cap is not None:
            cap.terminate()
            cap.wait(timeout=5)

    def cap_lines(path: Path) -> int:
        try:
            return sum(1 for line in path.read_text().splitlines() if line.strip())
        except OSError:
            return 0

    observed = observer.observed
    unique = sorted(set(observed))
    report = {
        "kind": "dev-validation",
        "purpose": "deterministic 5G application source address",
        "generated_at": utc_now(),
        "measurement_tier": "tier2",
        "source_mode": "live_testbed",
        "testbed_type": "software_based",
        "access_implementation": "ueransim",
        "namespace": args.namespace,
        "service_address": f"{args.service_address}:{args.service_port}",
        "expected_source": expected,
        "repetitions": args.repetitions,
        "connections_observed": len(observed),
        "unique_sources_observed": unique,
        "all_sources_are_ue": bool(observed) and unique == [expected],
        "deterministic": (
            len(observed) == args.repetitions and unique == [expected]
        ),
        "corroboration": {
            "uesimtun0_packets": cap_lines(ue_cap),
            "ogstun_packets": cap_lines(gw_cap),
            "uesimtun0_capture": str(ue_cap),
            "ogstun_capture": str(gw_cap),
        },
        "attempts": attempts,
        "note": (
            "software-based testbed; proves the network path, not RF behaviour"
        ),
    }
    (out_dir / "ue-path-proof.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "attempts"}, indent=2))
    return 0 if report["deterministic"] else 1


if __name__ == "__main__":
    sys.exit(main())
