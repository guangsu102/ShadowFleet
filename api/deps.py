from __future__ import annotations

import logging

from services.runtime_service import RuntimeContext, build_runtime_context
from utils.logger import set_event_type

_runtime_context: RuntimeContext | None = None


def get_runtime_context() -> RuntimeContext:
    global _runtime_context
    if _runtime_context is None:
        _runtime_context = build_runtime_context()
        set_event_type("api_initialized")
        _runtime_context.logger.info("API runtime context ready.")
        if _runtime_context.tg_reporter.enabled:
            from models.message_models import TelegramMessage
            _runtime_context.tg_reporter.send(
                TelegramMessage(level="INFO", title="ShadowFleet API started", body="FastAPI backend is ready.")
            )
    return _runtime_context


async def lifespan_shutdown() -> None:
    global _runtime_context
    if _runtime_context is not None:
        logger: logging.Logger = _runtime_context.logger
        if _runtime_context.db_pool is not None:
            _runtime_context.db_pool.close()
            logger.info("PostgreSQL connection pool closed.")
        if _runtime_context.sqlite_manager is not None:
            _runtime_context.sqlite_manager.close()
            logger.info("SQLite connection manager closed.")
        _runtime_context = None
