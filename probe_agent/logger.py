from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar


DEFAULT_EVENT_TYPE = "general"
CORRELATION_ID_CONTEXT: ContextVar[str] = ContextVar("correlation_id", default="-")
EVENT_TYPE_CONTEXT: ContextVar[str] = ContextVar("event_type", default=DEFAULT_EVENT_TYPE)


class ContextEnrichmentFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id()
        record.event_type = get_event_type()
        return True


def configure_logging(level: str = "INFO") -> logging.Logger:
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s "
        "| correlation_id=%(correlation_id)s | event_type=%(event_type)s | %(message)s"
    )
    context_filter = ContextEnrichmentFilter()

    if not root_logger.handlers:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        stream_handler.addFilter(context_filter)
        root_logger.addHandler(stream_handler)
    else:
        for handler in root_logger.handlers:
            handler.setFormatter(formatter)
            handler.addFilter(context_filter)

    return logging.getLogger("probe_agent")


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
