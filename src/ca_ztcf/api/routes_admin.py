"""Operational endpoints: health, readiness, version, configuration hash, metrics."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from ca_ztcf.api.schemas import (
    ConfigHashResponse,
    HealthResponse,
    ReadyResponse,
    VersionResponse,
)
from ca_ztcf.api.state import AppState
from ca_ztcf.telemetry.metrics import CONTENT_TYPE
from ca_ztcf.version import SCHEMA_VERSION, __version__

router = APIRouter(tags=["admin"])


def _state(request: Request) -> AppState:
    state: AppState = request.app.state.ca_ztcf
    return state


@router.get("/healthz", response_model=HealthResponse)
def healthz(request: Request) -> HealthResponse:
    """Liveness. Succeeds whenever the process can serve a request."""
    return HealthResponse(status="ok", service=_state(request).settings.service.name)


@router.get("/readyz", response_model=ReadyResponse)
def readyz(request: Request) -> ReadyResponse:
    """Readiness. Verifies that the component graph is actually usable."""
    state = _state(request)
    checks: dict[str, str] = {}

    checks["configuration"] = "ok" if state.settings.config_hash else "missing"
    checks["policy_matrix"] = "ok" if state.policy_matrix.entries else "empty"
    checks["strategies"] = ",".join(sorted(state.strategies)) or "none"
    checks["audit"] = "enabled" if state.audit.enabled else "disabled"
    checks["registry"] = f"{len(state.registry)} device(s)"

    coverage = state.policy_matrix.coverage()
    unmatched = [key for key, rule in coverage.items() if rule == "DEFAULT"]
    checks["policy_coverage"] = "total" if not unmatched else f"{len(unmatched)} pair(s) default"

    ready = state.policy_matrix.entries and state.strategies and not unmatched
    return ReadyResponse(status="ready" if ready else "not-ready", checks=checks)


@router.get("/version", response_model=VersionResponse)
def version(request: Request) -> VersionResponse:
    state = _state(request)
    return VersionResponse(
        service=state.settings.service.name,
        version=__version__,
        schema_version=SCHEMA_VERSION,
        environment=state.settings.service.environment,
    )


@router.get("/config/hash", response_model=ConfigHashResponse)
def config_hash(request: Request) -> ConfigHashResponse:
    """The hash recorded in every decision, so results stay attributable."""
    settings = _state(request).settings
    return ConfigHashResponse(
        config_hash=settings.config_hash,
        short_config_hash=settings.short_config_hash,
        config_dir=settings.config_dir,
    )


@router.get("/metrics")
def metrics(request: Request) -> Response:
    return Response(content=_state(request).metrics.render(), media_type=CONTENT_TYPE)


__all__ = ["router"]
