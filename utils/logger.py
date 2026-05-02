from __future__ import annotations

import logging
import logging.handlers
import uuid
from pathlib import Path

from contextvars import ContextVar


DEFAULT_EVENT_TYPE = "general"
CORRELATION_ID_CONTEXT: ContextVar[str] = ContextVar("correlation_id", default="-")
EVENT_TYPE_CONTEXT: ContextVar[str] = ContextVar("event_type", default=DEFAULT_EVENT_TYPE)


class ContextEnrichmentFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id()
        record.event_type = get_event_type()
        return True


def configure_logging(
    level: str,
    log_format: str,
    logs_dir: str = "logs",
    log_retention_days: int = 30,
) -> logging.Logger:
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    formatter = logging.Formatter(log_format)
    context_filter = ContextEnrichmentFilter()

    if not root_logger.handlers:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        stream_handler.addFilter(context_filter)
        root_logger.addHandler(stream_handler)

        logs_path = Path(logs_dir).resolve()
        logs_path.mkdir(parents=True, exist_ok=True)
        log_file_path = logs_path / "daemon.log"

        rotating_handler: logging.Handler = logging.handlers.TimedRotatingFileHandler(
            filename=str(log_file_path),
            when="midnight",
            interval=1,
            backupCount=log_retention_days,
            encoding="utf-8",
        )
        rotating_handler.setFormatter(formatter)
        rotating_handler.addFilter(context_filter)
        rotating_handler.namer = _daily_log_namer
        root_logger.addHandler(rotating_handler)
    else:
        for handler in root_logger.handlers:
            handler.setFormatter(formatter)
            handler.addFilter(context_filter)

    return logging.getLogger("shadowfleet")


def _daily_log_namer(filename: str) -> str:
    """Rename rotated log files to include the date suffix."""
    base_path = Path(filename)
    return str(base_path.with_suffix("")) + ".%Y%m%d.log"


def generate_correlation_id() -> str:
    return str(uuid.uuid4())


def set_correlation_id(correlation_id: str) -> None:
    CORRELATION_ID_CONTEXT.set(correlation_id)


def get_correlation_id() -> str:
    return CORRELATION_ID_CONTEXT.get()


def set_event_type(event_type: str) -> None:
    EVENT_TYPE_CONTEXT.set(event_type or DEFAULT_EVENT_TYPE)


def get_event_type() -> str:
    return EVENT_TYPE_CONTEXT.get()
