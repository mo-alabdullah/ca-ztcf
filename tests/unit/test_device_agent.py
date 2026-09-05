"""Device agent and its key handling."""

from __future__ import annotations

from pathlib import Path

import pytest

from ca_ztcf.collectors.base import AccessDomain
from ca_ztcf.device.agent import AgentConfig, DeviceAgent, DeviceAgentError
from ca_ztcf.device.keys import DeviceKeyError, DeviceKeyPair, research_device_id
from ca_ztcf.identity.proof import NonceIssuer, ProofVerifier
from ca_ztcf.identity.registry import DeviceIdentityRegistry


def test_research_device_ids_are_deterministic() -> None:
    assert research_device_id(0) == "dev-res-0000"
    assert research_device_id(42) == "dev-res-0042"
    assert research_device_id(7, prefix="dev-e03") == "dev-e03-0007"
    assert research_device_id(1) == research_device_id(1)


def test_negative_device_index_is_rejected() -> None:
    with pytest.raises(ValueError, match="negative"):
        research_device_id(-1)


def test_generated_key_can_prove_possession(clock) -> None:
    keys = DeviceKeyPair.generate("dev-1")
    registry = DeviceIdentityRegistry(clock)
    identity = registry.register("dev-1", keys.public_key_pem)

    issuer = NonceIssuer(clock, ttl_s=60)
    verifier = ProofVerifier(clock, issuer)
    nonce, _ = issuer.issue("dev-1")

    result = verifier.verify(identity, keys.proof(nonce))
    assert result.valid is True


def test_credential_encodes_nonce_and_signature(clock) -> None:
    keys = DeviceKeyPair.generate("dev-1")
    credential = keys.credential("bm9uY2U")
    assert credential.count(b".") == 1
    nonce, _, signature = credential.decode("ascii").partition(".")
    assert nonce == "bm9uY2U"
    assert signature


def test_private_key_round_trips_through_disk(tmp_path: Path) -> None:
    keys = DeviceKeyPair.generate("dev-1")
    private_path = tmp_path / "dev-1.key.pem"
    keys.write_private_key(private_path)
    keys.write_public_key(tmp_path / "dev-1.pub.pem")

    assert private_path.stat().st_mode & 0o777 == 0o600, "private key must be owner-only"
    loaded = DeviceKeyPair.load("dev-1", private_path)
    assert loaded.public_key_pem == keys.public_key_pem


def test_public_key_file_holds_no_private_material(tmp_path: Path) -> None:
    keys = DeviceKeyPair.generate("dev-1")
    public_path = keys.write_public_key(tmp_path / "dev-1.pub.pem")
    assert "PRIVATE KEY" not in public_path.read_text(encoding="utf-8").upper()


def test_missing_private_key_is_reported_clearly(tmp_path: Path) -> None:
    with pytest.raises(DeviceKeyError, match="not found"):
        DeviceKeyPair.load("dev-1", tmp_path / "absent.pem")


def test_non_ed25519_key_is_rejected(tmp_path: Path) -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path = tmp_path / "rsa.pem"
    path.write_bytes(
        rsa_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    with pytest.raises(DeviceKeyError, match="Ed25519"):
        DeviceKeyPair.load("dev-1", path)


# --- agent behaviour --------------------------------------------------------


def _agent() -> DeviceAgent:
    return DeviceAgent(AgentConfig(device_id="dev-1"), DeviceKeyPair.generate("dev-1"))


def test_agent_records_timestamped_events() -> None:
    agent = _agent()
    event = agent.record("custom", detail="x")
    assert event.event_id.startswith("evt-")
    assert event.at.tzinfo is not None
    assert event.monotonic_ns > 0
    assert agent.drain_events()[0]["kind"] == "custom"
    assert agent.events == []


def test_switching_access_context_is_recorded() -> None:
    agent = _agent()
    event = agent.switch_access_context(AccessDomain.WLAN, "192.168.60.2")
    assert agent.config.domain is AccessDomain.WLAN
    assert agent.config.source_address == "192.168.60.2"
    assert event.detail["from_domain"] == "NR"
    assert event.detail["to_domain"] == "WLAN"


def test_client_id_defaults_to_the_device_id() -> None:
    assert _agent().client_id == "dev-1"
    agent = DeviceAgent(
        AgentConfig(device_id="dev-1", client_id="custom"), DeviceKeyPair.generate("dev-1")
    )
    assert agent.client_id == "custom"


async def test_operations_before_connecting_are_refused() -> None:
    agent = _agent()
    with pytest.raises(DeviceAgentError, match="not connected"):
        await agent.publish("t", {})
    with pytest.raises(DeviceAgentError, match="not connected"):
        await agent.subscribe(["t"])


async def test_connect_failure_is_reported_and_recorded() -> None:
    agent = DeviceAgent(
        AgentConfig(device_id="dev-1", gateway_port=1, connect_timeout_s=0.5),
        DeviceKeyPair.generate("dev-1"),
    )
    with pytest.raises(DeviceAgentError):
        await agent.connect(None)
    assert any(e.kind == "connect_failed" for e in agent.events)


def test_packet_ids_wrap_within_the_protocol_range() -> None:
    agent = _agent()
    agent._packet_id = 65534
    assert agent._next_packet_id() == 65535
    assert agent._next_packet_id() == 1
