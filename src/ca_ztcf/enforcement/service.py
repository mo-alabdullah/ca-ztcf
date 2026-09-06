"""Entrypoint for the MQTT enforcement point when it runs as its own service.

Run with::

    python -m ca_ztcf.enforcement.service

Configuration comes from the environment, because this process is a deployment
artefact rather than a research parameter: it holds no thresholds of its own and
makes no decisions. Every threshold that affects a decision lives in the core
service's ``config/`` and is covered by its configuration hash.
"""

from __future__ import annotations

import asyncio
import os
import signal

from ca_ztcf.clock import SystemClock
from ca_ztcf.collectors.base import AccessDomain
from ca_ztcf.config import LoggingSettings
from ca_ztcf.enforcement.decision_client import HttpDecisionClient
from ca_ztcf.enforcement.mqtt_gateway import GatewayConfig, MqttEnforcementGateway
from ca_ztcf.telemetry.logging import configure_logging, get_logger

logger = get_logger(__name__)


def config_from_env() -> tuple[GatewayConfig, str]:
    gateway = GatewayConfig(
        listen_host=os.environ.get("CA_ZTCF_PEP_HOST", "0.0.0.0"),  # noqa: S104
        listen_port=int(os.environ.get("CA_ZTCF_PEP_PORT", "1884")),
        broker_host=os.environ.get("CA_ZTCF_BROKER_HOST", "mosquitto"),
        broker_port=int(os.environ.get("CA_ZTCF_BROKER_PORT", "1883")),
        # Unset by default: the domain is derived from the access binding that
        # matches the observed address. CA_ZTCF_DECLARED_DOMAIN forces one, and is
        # only for a deployment that really does serve a single access network.
        declared_domain=(
            AccessDomain(os.environ["CA_ZTCF_DECLARED_DOMAIN"])
            if os.environ.get("CA_ZTCF_DECLARED_DOMAIN")
            else None
        ),
        strategy=os.environ.get("CA_ZTCF_STRATEGY") or None,
    )
    core_url = os.environ.get("CA_ZTCF_CORE_URL", "http://ca-ztcf-core:8080")
    return gateway, core_url


async def main() -> None:
    configure_logging(LoggingSettings(static_fields={"service": "ca-ztcf-mqtt-pep"}))
    gateway_config, core_url = config_from_env()

    client = HttpDecisionClient(core_url, strategy=gateway_config.strategy)
    gateway = MqttEnforcementGateway(gateway_config, client, SystemClock())

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with __import__("contextlib").suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)

    await gateway.start()
    logger.info(
        "mqtt enforcement point ready",
        extra={
            "core_url": core_url,
            "broker": f"{gateway_config.broker_host}:{gateway_config.broker_port}",
            "listen_port": gateway.port,
        },
    )
    try:
        await stop.wait()
    finally:
        await gateway.stop()
        logger.info("mqtt enforcement point stopped")


if __name__ == "__main__":
    asyncio.run(main())
