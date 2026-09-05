"""Structured JSON logging.

Implemented on the standard library so that the runtime dependency set stays
minimal. Records are one JSON object per line, which is what the research audit
pipeline and the experiment controller consume.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from ca_ztcf.config import LoggingSettings

_RESERVED = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
    }
)


class JsonFormatter(logging.Formatter):
    """Formats a log record as a single JSON object."""

    def __init__(self, static_fields: dict[str, str] | None = None) -> None:
        super().__init__()
        self._static = dict(static_fields or {})

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(self._static)
        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            if key in payload:
                continue
            payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_logging(settings: LoggingSettings) -> None:
    """Install the configured formatter on the root logger. Idempotent."""
    handler = logging.StreamHandler(stream=sys.stdout)
    if settings.format == "json":
        handler.setFormatter(JsonFormatter(settings.static_fields))
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s %(message)s"))

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(settings.level.upper())

    for logger_name, level in settings.logger_levels.items():
        logging.getLogger(logger_name).setLevel(level.upper())


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


__all__ = ["JsonFormatter", "configure_logging", "get_logger"]
