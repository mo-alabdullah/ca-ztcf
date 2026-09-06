#!/usr/bin/env python3
"""A single-path device agent run, for the Tier-2 testbed.

Performs one MQTT session over one access path and prints the outcome as JSON.

It exists as a separate process because the 5G path must be entered through
UERANSIM's ``nr-binder``, which uses LD_PRELOAD to force a process's sockets onto
the UE tunnel. The UE and the core are co-located in this testbed, so without it
the kernel routes traffic straight out of the host interface and it never
traverses GTP-U at all — the enforcement point would then observe the host
address and the 5G access binding would never match.

SOFTWARE-BASED TESTBED. No physical radio.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, "/opt/ca-ztcf/src")

from ca_ztcf.collectors.base import AccessDomain  # noqa: E402
from ca_ztcf.device.agent import AgentConfig, DeviceAgent  # noqa: E402
from ca_ztcf.device.keys import DeviceKeyPair  # noqa: E402
from ca_ztcf.enforcement import mqtt_codec as codec  # noqa: E402


async def run(args: argparse.Namespace) -> dict:
    keys = DeviceKeyPair.load(args.device_id, Path(args.key_file))
    agent = DeviceAgent(
        AgentConfig(
            device_id=args.device_id,
            gateway_host=args.host,
            gateway_port=args.port,
            # nr-binder already forces the socket onto the tunnel for the 5G path,
            # so an explicit source bind would be redundant there and is left to
            # the caller.
            source_address=args.source or None,
            domain=AccessDomain(args.domain),
        ),
        keys,
    )
    result: dict = {"device_id": args.device_id, "domain": args.domain}
    try:
        result["connack"] = await agent.connect(args.nonce or None)
        await agent.pump(duration_s=0.6)
        result["decision"] = agent.last_decision
        result["observed_peer_address"] = (agent.last_decision or {}).get(
            "observed_peer_address"
        )
        if result["connack"] == 0:
            await agent.publish(
                f"dev/{args.device_id}/telemetry/reading", {"path": args.domain}
            )
            subs = await agent.subscribe([f"cmd/{args.device_id}/set"])
            result["command_topic_refused"] = (
                subs.get(f"cmd/{args.device_id}/set") == codec.SUBACK_FAILURE
            )
            telemetry = await agent.subscribe([f"dev/{args.device_id}/telemetry/x"])
            result["telemetry_topic_granted"] = (
                telemetry.get(f"dev/{args.device_id}/telemetry/x") != codec.SUBACK_FAILURE
            )
        await agent.disconnect()
        result["ok"] = True
    except Exception as exc:  # noqa: BLE001 - the caller needs the failure, not a traceback
        result["ok"] = False
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["events"] = agent.drain_events()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--key-file", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=1884)
    parser.add_argument("--source", default="")
    parser.add_argument("--domain", choices=["NR", "WLAN"], required=True)
    parser.add_argument("--nonce", default="")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
