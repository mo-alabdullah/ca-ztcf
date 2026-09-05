"""Configuration loading, validation and hashing."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from tests.conftest import CONFIG_DIR

from ca_ztcf.config import load_settings
from ca_ztcf.errors import ConfigurationError


def test_loads_every_section(settings) -> None:
    assert settings.service.name == "ca-ztcf"
    assert settings.evidence.binding_freshness_max_s > 0
    assert settings.transition.transition_window_s > 0
    assert settings.security.max_authn_failures > 0
    assert settings.posture.wlan.allowed_akms
    assert settings.policy.ttl_ms["ALLOW"] > 0
    assert set(settings.strategies) == {"ca_ztcf", "independent", "static_continuity"}
    assert "full" in settings.scopes
    assert settings.policy_matrix.rules


def test_config_hash_is_stable_and_excludes_paths(settings) -> None:
    first = settings.config_hash
    second = load_settings(CONFIG_DIR).config_hash
    assert first == second
    assert len(first) == 64
    assert settings.short_config_hash == first[:12]
    assert "config_dir" not in settings.canonical_dict()


def test_config_hash_changes_when_a_threshold_changes(tmp_path: Path) -> None:
    target = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, target)
    baseline = load_settings(target).config_hash

    core = target / "ca_ztcf.yaml"
    core.write_text(
        core.read_text(encoding="utf-8").replace(
            "binding_freshness_max_s: 30", "binding_freshness_max_s: 45"
        ),
        encoding="utf-8",
    )
    assert load_settings(target).config_hash != baseline


def test_missing_directory_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError):
        load_settings(tmp_path / "absent")


def test_repeat_threshold_above_rate_limit_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, target)
    core = target / "ca_ztcf.yaml"
    core.write_text(
        core.read_text(encoding="utf-8").replace("repeat_threshold: 3", "repeat_threshold: 9"),
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError):
        load_settings(target)


def test_policy_rule_with_unknown_scope_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, target)
    matrix = target / "policy" / "policy_matrix.yaml"
    matrix.write_text(
        matrix.read_text(encoding="utf-8").replace("scope: none", "scope: does_not_exist", 1),
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError):
        load_settings(target)
