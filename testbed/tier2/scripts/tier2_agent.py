#!/usr/bin/env python3
"""A single-path device agent run, for the Tier-2 testbed.

Performs one MQTT session over one access path and prints the outcome as JSON.

It exists as a separate process because each access path lives in its own network
namespace: the caller runs this agent with ``ip netns exec`` inside the namespace
that owns the path, so the connection can only reach the enforcement point through
that access technology. Running the agent in the root namespace instead would let
the kernel deliver the traffic locally, and the enforcement point would observe
the host address rather than the device's access-path address.

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
            # Bound to the device's address on this access path. Inside the
            # access namespace it is the only source address that can reach the
            # service, so it is what the enforcement point observes.
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
