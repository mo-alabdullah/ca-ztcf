"""The Tier-2 provisioning tree: pinned versions, no secrets, honest wording."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
TIER2 = REPO / "testbed" / "tier2"
NETWORK = TIER2 / "network"
SCRIPTS = TIER2 / "scripts"

FORBIDDEN_PHRASES = [
    "physical 5g radio",
    "physical wifi",
    "physical rf",
    "commercial 5g network",
    "real rf",
    "rf coexistence measurement",
]


def test_provisioning_tree_is_complete() -> None:
    assert (TIER2 / "README.md").is_file()
    assert (TIER2 / "ca-ztcf-tier2.yaml").is_file()
    for name in (
        "install_ueransim.sh",
        "provision_subscribers.sh",
        "start_5g.sh",
        "start_wlan.sh",
        "gen_wlan_certs.sh",
        "start_services.sh",
        "transition.sh",
        "reset.sh",
        "tier2_validation.py",
        "tier2_agent.py",
    ):
        assert (SCRIPTS / name).is_file(), f"missing {name}"
    for name in ("gnb.yaml", "ue.yaml"):
        assert (TIER2 / "ueransim" / name).is_file()
    for name in ("hostapd-hwsim.conf", "wpa_supplicant-hwsim.conf"):
        assert (TIER2 / "wlan" / name).is_file()


def test_versions_are_pinned() -> None:
    installer = (SCRIPTS / "install_ueransim.sh").read_text(encoding="utf-8")
    assert re.search(r"UERANSIM_VERSION:-v\d+\.\d+\.\d+", installer), (
        "UERANSIM must be pinned to an explicit tag"
    )
    vm = yaml.safe_load((TIER2 / "ca-ztcf-tier2.yaml").read_text(encoding="utf-8"))
    locations = [image["location"] for image in vm["images"]]
    assert any("24.04" in location for location in locations)


def test_vm_definition_requests_the_module_package_hwsim_needs() -> None:
    """mac80211_hwsim lives in linux-modules-extra, not the base image."""
    vm = (TIER2 / "ca-ztcf-tier2.yaml").read_text(encoding="utf-8")
    assert "linux-modules-extra" in vm
    assert "mac80211_hwsim" in vm


@pytest.mark.parametrize(
    "path",
    sorted(
        [p for p in SCRIPTS.iterdir() if p.suffix in {".sh", ".py"}]
        + [
            TIER2 / "README.md",
            TIER2 / "ueransim" / "gnb.yaml",
            TIER2 / "ueransim" / "ue.yaml",
            TIER2 / "wlan" / "hostapd-hwsim.conf",
        ]
    ),
    ids=lambda p: p.name,
)
def test_no_file_claims_a_physical_radio(path: Path) -> None:
    """The testbed is software-based and every file must say so, or say nothing.

    Text is whitespace-normalised first, so a claim split across a line break is
    still caught and a negation split across one still counts.
    """
    text = " ".join(path.read_text(encoding="utf-8").lower().split())
    for phrase in FORBIDDEN_PHRASES:
        start = 0
        while (index := text.find(phrase, start)) != -1:
            # A negation is fine: "never physical RF" is exactly right.
            preceding = text[max(0, index - 120) : index]
            assert any(
                marker in preceding for marker in ("no ", "not ", "never", "cannot", "rather than")
            ), f"{path.name} claims '{phrase}' without negating it"
            start = index + len(phrase)


def test_readme_states_both_what_tier2_supports_and_what_it_cannot() -> None:
    readme = " ".join((TIER2 / "README.md").read_text(encoding="utf-8").lower().split())
    assert "no physical radio anywhere" in readme
    for permitted in ("authentication", "trust evaluation", "policy enforcement"):
        assert permitted in readme
    for forbidden in ("rf propagation", "interference", "channel quality"):
        assert forbidden in readme


def test_subscriber_identifiers_are_synthetic_research_values() -> None:
    script = (SCRIPTS / "provision_subscribers.sh").read_text(encoding="utf-8")
    assert "MCC:-999" in script and "MNC:-70" in script, (
        "must use the 3GPP-reserved test PLMN 999/70"
    )
    assert "synthetic" in script.lower()
    assert "no production credential" in script.lower()


def test_ue_config_documents_that_supi_is_not_the_device_identity() -> None:
    """The identity discipline has to be visible where the SUPI is configured."""
    ue = (TIER2 / "ueransim" / "ue.yaml").read_text(encoding="utf-8").lower()
    assert "access-domain identifier" in ue
    assert "never the ca-ztcf device identity" in ue
    assert "999" in ue


def test_no_real_key_material_is_committed() -> None:
    for path in TIER2.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert "BEGIN RSA PRIVATE" not in text
        assert "BEGIN OPENSSH PRIVATE" not in text


def test_reset_covers_every_source_of_stale_state() -> None:
    """Reset must reach every source of stale state, directly or by delegation.

    A full reset delegates the access paths to the namespace scripts, so the check
    follows the delegation rather than demanding that one file mention everything.
    """
    reset = (SCRIPTS / "reset.sh").read_text(encoding="utf-8").lower()
    reachable = reset
    for name in ("ue_path.sh", "sta_path.sh"):
        assert name in reset, f"reset does not delegate to {name}"
        reachable += (NETWORK / name).read_text(encoding="utf-8").lower()
    for target in (
        "ueransim",
        "nr-ue",
        "nr-gnb",
        "hostapd",
        "wpa_supplicant",
        "open5gs",
        "mosquitto",
        "mac80211_hwsim",
    ):
        assert target in reachable, f"reset does not handle {target}"
    assert "known state" in reset


def test_reset_has_a_soft_mode_that_keeps_the_access_paths() -> None:
    """Repetitions need service state cleared without paying for a full re-attach."""
    reset = (SCRIPTS / "reset.sh").read_text(encoding="utf-8")
    assert 'MODE="${1:-soft}"' in reset
    assert 'if [ "${MODE}" = "full" ]' in reset


def test_pkill_patterns_cannot_match_the_invoking_shell() -> None:
    """`pkill -f nr-ue` also matches the shell running the script and kills it.

    Every -f pattern must be bracketed or anchored so it cannot match a command
    line that merely mentions the process name.
    """
    for script in sorted(SCRIPTS.glob("*.sh")) + sorted(NETWORK.glob("*.sh")):
        for number, line in enumerate(script.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if "pkill -f" not in stripped or stripped.startswith("#"):
                continue
            assert "[" in stripped, (
                f"{script.name}:{number} uses an unbracketed pkill -f pattern, "
                "which can match the invoking shell"
            )


def test_transition_script_records_all_seven_marks() -> None:
    script = (SCRIPTS / "transition.sh").read_text(encoding="utf-8")
    for mark in ("T0", "T1", "T2", "T3", "T4", "T5", "T6"):
        assert mark in script
    assert "not an RF or physical handover measurement" in script


def test_transition_script_does_more_than_flip_a_field() -> None:
    """A transition must involve real authentication and a real path change."""
    script = (SCRIPTS / "transition.sh").read_text(encoding="utf-8").lower()
    assert "reassociate" in script
    assert "uesimtun0" in script
    assert "/v1/collectors/events" in script
    assert "/v1/decisions/evaluate" in script


def test_transition_is_not_registered_twice() -> None:
    """Every strategy calls transitions.observe() while deciding.

    Announcing the transition to /v1/transitions as well counts it twice and
    inflates the rate window, so a first transition can come back as a repeated
    one and escalate to STEP_UP_AUTHENTICATION.
    """
    for name in ("transition.sh", "tier2_validation.py"):
        text = (SCRIPTS / name).read_text(encoding="utf-8")
        body = "\n".join(
            line for line in text.splitlines() if not line.lstrip().startswith(("#", "//"))
        )
        assert "/v1/transitions" not in body, f"{name} registers the transition twice"


def test_transition_script_follows_the_access_namespaces() -> None:
    script = (SCRIPTS / "transition.sh").read_text(encoding="utf-8")
    assert "ip netns exec" in script
    assert "ca-ztcf-ue" in script
    assert "ca-ztcf-sta" in script


def test_capture_scripts_fix_provenance_at_the_point_of_emission() -> None:
    """A capture script must not be able to emit anything but its own tier."""
    for name, implementation in (
        ("start_5g.sh", "ueransim"),
        ("start_wlan.sh", "mac80211_hwsim"),
    ):
        script = (SCRIPTS / name).read_text(encoding="utf-8")
        assert '"source_mode":"live_testbed"' in script
        assert '"testbed_type":"software_based"' in script
        assert f'"access_implementation":"{implementation}"' in script


def test_gcc13_workaround_is_documented_not_silent() -> None:
    installer = (SCRIPTS / "install_ueransim.sh").read_text(encoding="utf-8")
    assert "GCC 13" in installer
    assert "-include cstring" in installer
    assert "changes no behaviour" in installer
