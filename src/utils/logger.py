"""Structured logging configuration with graceful fallback.

If ``structlog`` is installed, this module uses structured logging.
If it is missing, it transparently falls back to stdlib logging while
still supporting the ``logger.info("msg", key=value)`` call style used
throughout the codebase.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from src.config.settings import Environment, get_settings

try:  # pragma: no cover - runtime dependency gate
    import structlog  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - exercised in lean envs
    structlog = None  # type: ignore[assignment]


class _FallbackLogger:
    """Minimal logger adapter that mimics structlog's kwarg style."""

    def __init__(self, logger: logging.Logger, context: dict[str, Any] | None = None) -> None:
        self._logger = logger
        self._context = context or {}

    def bind(self, **kwargs: Any) -> _FallbackLogger:
        merged = dict(self._context)
        merged.update(kwargs)
        return _FallbackLogger(self._logger, merged)

    def _format(self, event: str, **kwargs: Any) -> str:
        payload = dict(self._context)
        payload.update(kwargs)
        if not payload:
            return event
        kv = " ".join(f"{k}={v!r}" for k, v in payload.items())
        return f"{event} | {kv}"

    def debug(self, event: str, *args: Any, **kwargs: Any) -> None:
        self._logger.debug(self._format(event, **kwargs), *args)

    def info(self, event: str, *args: Any, **kwargs: Any) -> None:
        self._logger.info(self._format(event, **kwargs), *args)

    def warning(self, event: str, *args: Any, **kwargs: Any) -> None:
        self._logger.warning(self._format(event, **kwargs), *args)

    def error(self, event: str, *args: Any, **kwargs: Any) -> None:
        self._logger.error(self._format(event, **kwargs), *args)

    def critical(self, event: str, *args: Any, **kwargs: Any) -> None:
        self._logger.critical(self._format(event, **kwargs), *args)

    def exception(self, event: str, *args: Any, **kwargs: Any) -> None:
        self._logger.exception(self._format(event, **kwargs), *args)


def setup_logging() -> None:
    """Configure application logging."""
    settings = get_settings()

    if structlog is None:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
        handler.setFormatter(formatter)

        root_logger = logging.getLogger()
        root_logger.handlers.clear()
        root_logger.addHandler(handler)
        root_logger.setLevel(settings.app_log_level.upper())

        for name in ("uvicorn.access", "httpx", "asyncio"):
            logging.getLogger(name).setLevel(logging.WARNING)
        return

    shared_processors: list[structlog.types.Processor] = [  # type: ignore[union-attr]
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if settings.app_env == Environment.PRODUCTION:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()  # type: ignore[union-attr]
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(settings.app_log_level.upper())

    for name in ("uvicorn.access", "httpx", "asyncio"):
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> Any:
    """Return a logger that supports structlog-style keyword arguments."""
    if structlog is not None:
        return structlog.get_logger(name)
    return _FallbackLogger(logging.getLogger(name))
