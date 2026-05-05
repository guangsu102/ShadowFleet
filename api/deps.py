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
            from models.message_models import TelegramMessage, TelegramNotificationType
            import threading
            def _send_tg_startup() -> None:
                try:
                    _runtime_context.tg_reporter.send(
                        TelegramMessage(type=TelegramNotificationType.SYSTEM_STARTUP, level="INFO", title="ShadowFleet API 已启动", body="FastAPI 后端已就绪。")
                    )
                except Exception:
                    _runtime_context.logger.exception("Failed to send Telegram startup notification.")
            threading.Thread(target=_send_tg_startup, daemon=True).start()
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
