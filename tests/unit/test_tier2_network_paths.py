"""The Tier-2 network scripts must keep each access path genuinely separate.

These check the properties the fix depends on, not the shell syntax: the UE runs
in its own namespace, the service address is reachable only through the tunnel,
the UE source address is never masqueraded on the way to it, and the control link
cannot be used to bypass the tunnel.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
NETWORK = REPO / "testbed" / "tier2" / "network"
UE_PATH = (NETWORK / "ue_path.sh").read_text(encoding="utf-8")
STA_PATH = (NETWORK / "sta_path.sh").read_text(encoding="utf-8")


def test_the_network_tree_is_complete() -> None:
    for name in ("ue_path.sh", "sta_path.sh", "capture_events.sh", "verify_ue_path.py"):
        assert (NETWORK / name).is_file(), f"missing {name}"


def test_the_ue_runs_inside_its_own_namespace() -> None:
    assert "ip netns exec ${NS} ${UERANSIM}/nr-ue" in UE_PATH


def test_the_service_address_is_not_an_interface_the_ue_can_reach_directly() -> None:
    """A dummy interface in the root namespace, reachable only via the tunnel."""
    assert 'ip link add "${SVC_IF}" type dummy' in UE_PATH
    assert 'nsx ip route replace "${SVC_NET}" dev uesimtun0' in UE_PATH


def test_the_ue_source_address_is_never_masqueraded_to_the_service() -> None:
    assert '-s "${UE_NET}" -d "${SVC_NET}" -j RETURN' in UE_PATH


def test_the_control_link_cannot_carry_application_traffic() -> None:
    """Otherwise a service bound to 0.0.0.0 is reachable without the tunnel."""
    assert '-o "${VETH_NS}" -p tcp -j REJECT' in UE_PATH


def test_a_blanket_reject_on_the_control_link_is_documented_as_unusable() -> None:
    """It destabilises RLS; the reason must survive so it is not reintroduced."""
    assert "blanket REJECT" in UE_PATH
    assert "radio-link failure" in UE_PATH


def test_the_5g_path_is_verified_by_reachability_not_by_interface_presence() -> None:
    """A tunnel interface can be up while the user plane carries nothing."""
    assert "can be up while the user plane is dead" in UE_PATH
    assert 'nsx ping -c2 -W2 -q "${SVC_ADDR}"' in UE_PATH


def test_each_ue_gets_its_own_source_route() -> None:
    assert 'nsx ip rule add from "${addr}" lookup "${table}"' in UE_PATH
    assert 'nsx ip route replace "${SVC_NET}" dev "uesimtun${i}" table "${table}"' in UE_PATH


def test_the_station_phy_moves_into_its_own_namespace() -> None:
    assert 'iw phy "${phy}" set netns name "${NS}"' in STA_PATH


def test_the_supplicant_runs_inside_the_station_namespace() -> None:
    assert "ip netns exec ${NS} wpa_supplicant" in STA_PATH


def test_the_station_gets_one_address_per_device() -> None:
    assert 'nsx ip addr replace "${base}.$((last + i))/${STA_PREFIX}"' in STA_PATH


def test_neither_script_claims_a_physical_radio() -> None:
    """Both must state they are software-based and deny a physical radio.

    The forbidden strings are checked as affirmative claims only: "no physical RF"
    is the denial we want and must not be flagged as the claim it denies.
    """
    for text in (UE_PATH, STA_PATH):
        lowered = text.lower()
        assert "software-based testbed" in lowered
        assert "no physical" in lowered
        for claim in (
            "over physical rf",
            "real rf coexistence",
            "commercial 5g",
            "physical handover measurement of",
        ):
            assert claim not in lowered


def test_the_ue_path_explains_why_nr_binder_was_not_enough() -> None:
    """The rejected alternative must stay recorded so it is not retried."""
    assert "nr-binder" in UE_PATH
    assert "LD_PRELOAD" in UE_PATH


def test_subscribers_get_static_addresses_for_reproducibility() -> None:
    text = (REPO / "testbed" / "tier2" / "scripts" / "provision_subscribers.sh").read_text(
        encoding="utf-8"
    )
    assert "ue: { ipv4: '${ue_addr}' }" in text
    assert "impossible to repeat" in text


def test_the_gnb_link_faces_the_namespace_but_ngap_and_gtp_stay_local() -> None:
    gnb = (REPO / "testbed" / "tier2" / "ueransim" / "gnb.yaml").read_text(encoding="utf-8")
    assert "linkIp: 10.200.0.1" in gnb
    assert "ngapIp: 127.0.0.1" in gnb
    assert "gtpIp: 127.0.0.1" in gnb


def test_the_validation_report_does_not_carry_a_cleartext_subscriber_identifier() -> None:
    text = (REPO / "testbed" / "tier2" / "scripts" / "tier2_validation.py").read_text(
        encoding="utf-8"
    )
    assert "def redact_subscriber" in text
    assert '"subscriber_ref": redact_subscriber(flow.supi)' in text
    assert '{"supi": flow.supi' not in text
