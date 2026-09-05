"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ca_ztcf.api import routes_admin, routes_research
from ca_ztcf.api.state import AppState, build_app_state
from ca_ztcf.clock import Clock
from ca_ztcf.config import Settings
from ca_ztcf.errors import CaZtcfError
from ca_ztcf.telemetry.logging import configure_logging, get_logger
from ca_ztcf.version import __version__

logger = get_logger(__name__)

DESCRIPTION = """
Research prototype of the Coexistence-Aware Zero Trust Continuity Framework.

A service-domain Zero Trust function that re-evaluates IoT device trust at
5G/WiFi access transitions using only evidence each access domain can
realistically expose, without cross-domain identifier sharing.

This service makes no performance or security claim. Its properties are design
objectives to be evaluated experimentally.
""".strip()


def create_app(
    *,
    settings: Settings | None = None,
    config_dir: Path | str | None = None,
    clock: Clock | None = None,
    audit_base_dir: Path | None = None,
    state: AppState | None = None,
) -> FastAPI:
    """Build the application. Every collaborator can be injected, for testing."""
    app_state = (
        state
        if state is not None
        else build_app_state(
            settings=settings, config_dir=config_dir, clock=clock, audit_base_dir=audit_base_dir
        )
    )
    configure_logging(app_state.settings.logging)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "ca-ztcf starting",
            extra={
                "version": __version__,
                "config_hash": app_state.settings.short_config_hash,
                "strategies": sorted(app_state.strategies),
                "audit_path": str(app_state.audit.path),
            },
        )
        yield
        logger.info("ca-ztcf stopping", extra={"decisions_audited": app_state.audit.written})

    app = FastAPI(
        title="CA-ZTCF",
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
    )
    app.state.ca_ztcf = app_state

    @app.exception_handler(CaZtcfError)
    async def handle_domain_error(_: Request, exc: CaZtcfError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"code": exc.code, "message": exc.message})

    app.include_router(routes_admin.router)
    app.include_router(routes_research.router)
    return app


app = None
"""Module-level application, created lazily by :func:`get_app` for uvicorn."""


def get_app() -> FastAPI:
    """Entry point used by ``uvicorn ca_ztcf.api.app:get_app --factory``."""
    return create_app()


__all__ = ["create_app", "get_app"]
