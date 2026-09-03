"""Structured Contextual Logging Module for Basalt Workflow Engine.

Provides JSON and ANSI console log formatters, async-safe context variable propagation,
and logger adapters for attaching execution metadata (dag_id, run_id, step_id).
"""

import contextvars
import json
import logging
import sys
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

# Context variable holding task/thread execution metadata dictionary
_LOG_CONTEXT: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "_LOG_CONTEXT", default={}
)


class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter for production log aggregators."""

    def __init__(self, include_timestamp: bool = True) -> None:
        super().__init__()
        self.include_timestamp = include_timestamp

    def format(self, record: logging.LogRecord) -> str:
        """Format log record into a structured JSON string."""
        log_data: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "filename": record.filename,
            "line": record.lineno,
            "thread": record.threadName,
            "process": record.process,
        }

        if self.include_timestamp:
            log_data["timestamp"] = datetime.fromtimestamp(record.created, tz=UTC).isoformat()

        # Include exception information if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Inject contextual variables from record attributes or ContextVar
        ctx = _LOG_CONTEXT.get().copy()
        for key in ("dag_id", "run_id", "step_id", "trigger_id", "duration_ms"):
            if hasattr(record, key):
                log_data[key] = getattr(record, key)
            elif key in ctx:
                log_data[key] = ctx[key]

        # Inject extra arbitrary fields passed in extra={...}
        if hasattr(record, "extra_fields") and isinstance(record.extra_fields, dict):
            log_data.update(record.extra_fields)

        return json.dumps(log_data, default=str)


class ConsoleFormatter(logging.Formatter):
    """Colored ANSI console log formatter for local development."""

    COLOR_CODES: dict[str, str] = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[1;31m",  # Bold Red
    }
    RESET_CODE: str = "\033[0m"

    def __init__(self, use_colors: bool = True) -> None:
        super().__init__()
        self.use_colors = use_colors

    def format(self, record: logging.LogRecord) -> str:
        """Format log record into human-readable console string with context tags."""
        timestamp = datetime.fromtimestamp(record.created, tz=UTC).strftime(
            "%Y-%m-%d %H:%M:%S.%03d"
        )

        level_str = record.levelname
        if self.use_colors and level_str in self.COLOR_CODES:
            level_str = f"{self.COLOR_CODES[level_str]}{level_str:<8}{self.RESET_CODE}"
        else:
            level_str = f"{level_str:<8}"

        # Collect execution context tags
        context_parts = []
        ctx = _LOG_CONTEXT.get()
        for key in ("dag_id", "run_id", "step_id"):
            val = getattr(record, key, ctx.get(key))
            if val:
                context_parts.append(f"{key}={val}")

        context_str = f" [{' '.join(context_parts)}]" if context_parts else ""
        msg = record.getMessage()

        formatted = f"{timestamp} [{level_str}] [{record.name}]{context_str}: {msg}"

        if record.exc_info:
            formatted += f"\n{self.formatException(record.exc_info)}"

        return formatted


# Type alias for process method kwargs compatibility
MutableMapping_or_Dict = Any


class ContextLoggerAdapter(logging.LoggerAdapter):
    """Logger adapter that automatically attaches current ContextVar metadata."""

    def process(self, msg: Any, kwargs: MutableMapping_or_Dict) -> tuple[Any, dict[str, Any]]:
        ctx = _LOG_CONTEXT.get().copy()
        extra = kwargs.get("extra", {})
        if isinstance(extra, dict):
            ctx.update(extra)
            kwargs["extra"] = ctx
        return msg, kwargs


@contextmanager
def log_context(**kwargs: Any) -> Generator[None, None, None]:
    """Context manager for adding temporary execution metadata to logs.

    Usage:
        with log_context(dag_id="etl_flow", run_id="run_123"):
            logger.info("Executing step")
    """
    current_ctx = _LOG_CONTEXT.get().copy()
    new_ctx = {**current_ctx, **{k: v for k, v in kwargs.items() if v is not None}}
    token = _LOG_CONTEXT.set(new_ctx)
    try:
        yield
    finally:
        _LOG_CONTEXT.reset(token)


def get_current_log_context() -> dict[str, Any]:
    """Retrieve current contextual metadata dictionary."""
    return _LOG_CONTEXT.get().copy()


def setup_logging(
    level: str = "INFO",
    json_format: bool = False,
    use_colors: bool = True,
    log_file: str | None = None,
) -> None:
    """Configure system root logger handlers and formatters.

    Args:
        level: Logging level threshold ('DEBUG', 'INFO', etc.).
        json_format: Whether to format logs as structured JSON.
        use_colors: Whether to colorize console output.
        log_file: Optional filepath to write log output.
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Clear existing handlers to prevent duplication
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    # Console stdout handler
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(numeric_level)

    if json_format:
        stream_handler.setFormatter(JSONFormatter())
    else:
        stream_handler.setFormatter(ConsoleFormatter(use_colors=use_colors))

    root_logger.addHandler(stream_handler)

    # Optional file handler
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(JSONFormatter())
        root_logger.addHandler(file_handler)


def get_logger(name: str) -> ContextLoggerAdapter:
    """Retrieve a contextual logger instance for the specified module.

    Args:
        name: Module or logger name (typically __name__).

    Returns:
        ContextLoggerAdapter wrapping standard logging.Logger.
    """
    logger = logging.getLogger(name)
    return ContextLoggerAdapter(logger, extra={})
