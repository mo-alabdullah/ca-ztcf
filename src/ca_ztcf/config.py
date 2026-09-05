"""Configuration loading, validation and hashing.

Every research threshold lives in ``config/``. Nothing in this module invents a
default that is not also declared, with its unit and purpose, in the YAML files.

The ``config_hash`` is a SHA-256 digest over the canonical JSON form of the fully
resolved settings. It is recorded in every evidence record, trust evaluation,
decision and audit line, so that any result can be attributed to the exact
configuration that produced it.
"""

from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ca_ztcf.errors import ConfigurationError

DEFAULT_CONFIG_DIR = Path(os.environ.get("CA_ZTCF_CONFIG_DIR", "config"))


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ServiceSettings(_Frozen):
    name: str = "ca-ztcf"
    environment: str = "development"
    host: str = "0.0.0.0"  # noqa: S104 - container binds all interfaces by design
    port: int = Field(default=8080, ge=1, le=65535)


class EvidenceSettings(_Frozen):
    proof_of_possession_ttl_s: int = Field(ge=1)
    nonce_ttl_s: int = Field(ge=1)
    binding_freshness_max_s: int = Field(ge=1)
    evidence_completeness_required: tuple[str, ...] = ()


class TransitionSettings(_Frozen):
    transition_window_s: int = Field(ge=1)
    stability_window_s: int = Field(ge=1)
    rate_window_s: int = Field(ge=1)
    max_transitions_per_window: int = Field(ge=1)
    repeat_threshold: int = Field(ge=1)

    @model_validator(mode="after")
    def _repeat_below_rate_limit(self) -> TransitionSettings:
        if self.repeat_threshold > self.max_transitions_per_window:
            raise ValueError(
                "repeat_threshold must not exceed max_transitions_per_window, "
                "otherwise the REPEATED transition context is unreachable "
                "before predicate C8 (RATE_OK) already fails"
            )
        return self


class SecuritySettings(_Frozen):
    authn_failure_window_s: int = Field(ge=1)
    max_authn_failures: int = Field(ge=1)
    cooldown_s: int = Field(ge=0)


class NrPostureSettings(_Frozen):
    allowed_gnb_ids: tuple[str, ...] = ()
    allowed_dnns: tuple[str, ...] = ()
    allowed_rat_types: tuple[str, ...] = ()
    required_registration_states: tuple[str, ...] = ()
    require_active_pdu_session: bool = True


class WlanPostureSettings(_Frozen):
    allowed_ssids: tuple[str, ...] = ()
    allowed_bssids: tuple[str, ...] = ()
    allowed_akms: tuple[str, ...] = ()
    require_eap_success: bool = True


class PostureSettings(_Frozen):
    nr: NrPostureSettings
    wlan: WlanPostureSettings


class PolicySettings(_Frozen):
    ttl_ms: dict[str, int]

    @model_validator(mode="after")
    def _non_negative(self) -> PolicySettings:
        for action, ttl in self.ttl_ms.items():
            if ttl < 0:
                raise ValueError(f"policy.ttl_ms[{action}] must not be negative")
        return self


class PrivacySettings(_Frozen):
    identifier_hash_salt_source: Literal["random_per_process", "env"] = "random_per_process"
    identifier_hash_length: int = Field(default=16, ge=8, le=64)


class AuditSettings(_Frozen):
    enabled: bool = True
    path: str = "artifacts/audit/decisions.jsonl"
    redact_keys: tuple[str, ...] = ()


class LoggingSettings(_Frozen):
    version: int = 1
    format: Literal["json", "text"] = "json"
    level: str = "INFO"
    logger_levels: dict[str, str] = Field(default_factory=dict)
    static_fields: dict[str, str] = Field(default_factory=dict)


class StrategyDefinition(_Frozen):
    name: str
    kind: Literal["ca_ztcf", "independent", "static_continuity"]
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)


class ScopeDefinition(_Frozen):
    description: str = ""
    allow: tuple[str, ...] = ()
    deny: tuple[str, ...] = ()


class PolicyRuleDefinition(_Frozen):
    id: str
    state: str
    transition_contexts: tuple[str, ...]
    action: str
    scope: str
    reason_codes: tuple[str, ...] = ()
    note: str = ""


class PolicyMatrixDefinition(_Frozen):
    version: int = 1
    default_action: str = "DENY"
    default_scope: str = "none"
    default_reason_codes: tuple[str, ...] = ("NO_MATCHING_POLICY_RULE",)
    rules: tuple[PolicyRuleDefinition, ...]


class Settings(_Frozen):
    """Fully resolved CA-ZTCF configuration."""

    service: ServiceSettings
    evidence: EvidenceSettings
    transition: TransitionSettings
    security: SecuritySettings
    posture: PostureSettings
    policy: PolicySettings
    privacy: PrivacySettings
    audit: AuditSettings
    logging: LoggingSettings
    strategies: dict[str, StrategyDefinition]
    scopes: dict[str, ScopeDefinition]
    policy_matrix: PolicyMatrixDefinition
    config_dir: str

    def canonical_dict(self) -> dict[str, Any]:
        """Return the settings as a canonical dictionary for hashing.

        ``config_dir`` is excluded because it is a deployment path, not a
        research parameter; including it would make the hash differ between a
        host run and a container run of an identical configuration.
        """
        data = self.model_dump(mode="json")
        data.pop("config_dir", None)
        return data

    @property
    def config_hash(self) -> str:
        payload = json.dumps(self.canonical_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @property
    def short_config_hash(self) -> str:
        return self.config_hash[:12]


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigurationError(f"configuration file not found: {path}")
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"invalid YAML in {path}: {exc}") from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ConfigurationError(f"expected a mapping at the top level of {path}")
    return loaded


def load_settings(config_dir: Path | str | None = None) -> Settings:
    """Load and validate the full configuration tree. Fails fast on any problem."""
    directory = Path(config_dir) if config_dir is not None else DEFAULT_CONFIG_DIR
    directory = directory.resolve()

    core = _read_yaml(directory / "ca_ztcf.yaml")
    logging_cfg = _read_yaml(directory / "logging.yaml")
    scopes_cfg = _read_yaml(directory / "policy" / "topic_scopes.yaml")
    matrix_cfg = _read_yaml(directory / "policy" / "policy_matrix.yaml")

    strategies: dict[str, Any] = {}
    strategy_dir = directory / "strategies"
    if not strategy_dir.is_dir():
        raise ConfigurationError(f"strategy configuration directory not found: {strategy_dir}")
    for strategy_file in sorted(strategy_dir.glob("*.yaml")):
        block = _read_yaml(strategy_file).get("strategy")
        if not isinstance(block, dict):
            raise ConfigurationError(f"{strategy_file} must contain a 'strategy' mapping")
        name = block.get("name")
        if not isinstance(name, str) or not name:
            raise ConfigurationError(f"{strategy_file} strategy requires a non-empty 'name'")
        if name in strategies:
            raise ConfigurationError(f"duplicate strategy name '{name}' in {strategy_file}")
        strategies[name] = block

    try:
        settings = Settings(
            service=ServiceSettings(**core.get("service", {})),
            evidence=EvidenceSettings(**core["evidence"]),
            transition=TransitionSettings(**core["transition"]),
            security=SecuritySettings(**core["security"]),
            posture=PostureSettings(**core["posture"]),
            policy=PolicySettings(**core["policy"]),
            privacy=PrivacySettings(**core.get("privacy", {})),
            audit=AuditSettings(**core.get("audit", {})),
            logging=LoggingSettings(**logging_cfg),
            strategies={k: StrategyDefinition(**v) for k, v in strategies.items()},
            scopes={k: ScopeDefinition(**v) for k, v in (scopes_cfg.get("scopes") or {}).items()},
            policy_matrix=PolicyMatrixDefinition(**matrix_cfg),
            config_dir=str(directory),
        )
    except KeyError as exc:
        raise ConfigurationError(f"missing required configuration section: {exc}") from exc
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"invalid configuration: {exc}") from exc

    _cross_validate(settings)
    return settings


def _cross_validate(settings: Settings) -> None:
    """Reject configurations that are individually valid but jointly inconsistent."""
    known_scopes = set(settings.scopes)
    if settings.policy_matrix.default_scope not in known_scopes:
        raise ConfigurationError(
            f"policy matrix default_scope '{settings.policy_matrix.default_scope}' is not defined "
            f"in topic_scopes.yaml"
        )
    for rule in settings.policy_matrix.rules:
        if rule.scope not in known_scopes:
            raise ConfigurationError(
                f"policy rule {rule.id} references undefined scope '{rule.scope}'"
            )
        if rule.action not in settings.policy.ttl_ms:
            raise ConfigurationError(
                f"policy rule {rule.id} uses action '{rule.action}' which has no entry in "
                f"policy.ttl_ms"
            )
    if not settings.strategies:
        raise ConfigurationError("at least one strategy must be configured")


@lru_cache(maxsize=8)
def get_settings(config_dir: str | None = None) -> Settings:
    """Cached settings accessor. The cache key is the configuration directory."""
    return load_settings(config_dir)
