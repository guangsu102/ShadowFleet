from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Lock

from database.connection import PostgresConnectionPool
from database.sqlite_connection import SqliteConnectionManager
from models.config_models import AppConfig
from models.message_models import TelegramMessage, TelegramNotificationType
from utils.config_parser import load_config, save_raw_config, sanitize_config_for_logging
from utils.logger import configure_logging, generate_correlation_id, set_correlation_id, set_event_type
from utils.tg_reporter import TelegramReporter


class ConfigHolder:
    """
    Mutable container for AppConfig that supports hot-reload.
    Services can hold a reference to this holder and always get fresh config.
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._lock = Lock()

    @property
    def config(self) -> AppConfig:
        return self._config

    def update_config(self, config: AppConfig) -> None:
        """Atomically replace the config with a new version."""
        with self._lock:
            self._config = config


@dataclass(frozen=True)
class RuntimeContext:
    config: AppConfig
    logger: logging.Logger
    tg_reporter: TelegramReporter
    correlation_id: str
    db_pool: PostgresConnectionPool | None = None
    sqlite_manager: SqliteConnectionManager | None = None
    config_holder: ConfigHolder | None = None
    daemon_artifact_base_url: str | None = None
    daemon_ipv6: str | None = None


def get_daemon_public_ipv6() -> str | None:
    import socket as _socket
    try:
        s = _socket.socket(_socket.AF_INET6, _socket.SOCK_DGRAM)
        s.connect(("2001:4860:4860::8888", 80), timeout=3)
        addr = s.getsockname()[0]
        s.close()
        return addr
    except Exception:
        return None


def _build_artifact_base_url(config: AppConfig, known_ipv6: str | None = None) -> str | None:
    override = config.app.artifact_cache_base_url_override
    if override:
        return override.strip()
    ipv6 = known_ipv6 if known_ipv6 is not None else get_daemon_public_ipv6()
    if not ipv6:
        return None
    return f"http://[{ipv6}]:{config.app.artifact_cache_listen_port}"


def build_runtime_context(config_path: str | Path | None = None) -> RuntimeContext:
    config = load_config(config_path)
    logger = configure_logging(
        level=config.logging.level,
        log_format=config.logging.format,
        logs_dir=config.logging.logs_dir,
        log_retention_days=config.logging.log_retention_days,
    )

    correlation_id = generate_correlation_id()
    set_correlation_id(correlation_id)

    reporter = TelegramReporter(
        enabled=config.telegram.enabled,
        bot_token=config.telegram.bot_token,
        chat_id=config.telegram.chat_id,
        message_prefix=config.telegram.message_prefix,
        timeout_seconds=config.app.request_timeout_seconds,
        max_retries=config.app.max_retries,
        retry_backoff_seconds=config.app.retry_backoff_seconds,
        logger=logger,
    )

    set_event_type("config_loaded")
    logger.info(
        "Configuration loaded successfully: %s",
        sanitize_config_for_logging(config),
    )

    # Create mutable config holder for hot-reload support
    config_holder = ConfigHolder(config)

    runtime_context = RuntimeContext(
        config=config,
        config_holder=config_holder,
        logger=logger,
        tg_reporter=reporter,
        correlation_id=correlation_id,
        db_pool=None,
        sqlite_manager=None,
    )
    sqlite_manager = SqliteConnectionManager(runtime_context=runtime_context)
    runtime_context = replace(runtime_context, sqlite_manager=sqlite_manager)
    # Only initialize PostgreSQL pool if Xboard is properly configured (has password)
    if config.xboard is not None and config.xboard.password is not None:
        db_pool = PostgresConnectionPool(runtime_context=runtime_context)
        runtime_context = replace(runtime_context, db_pool=db_pool)
        logger.info("Xboard PostgreSQL connection pool initialized.")
    else:
        logger.info("Xboard PostgreSQL connection disabled (no password configured).")

    daemon_ipv6 = get_daemon_public_ipv6()
    runtime_context = replace(runtime_context, daemon_ipv6=daemon_ipv6)
    if daemon_ipv6:
        logger.info("Daemon public IPv6 detected: %s", daemon_ipv6)
    else:
        logger.warning("Daemon has no public IPv6 address (cloud provider may not support it)")

    artifact_base_url = _build_artifact_base_url(config, known_ipv6=daemon_ipv6)
    if artifact_base_url:
        runtime_context = replace(runtime_context, daemon_artifact_base_url=artifact_base_url)
        logger.info("Artifact cache base URL: %s", artifact_base_url)
    else:
        logger.info("No public IPv6 detected, nodes will download install.sh from GitHub.")

    set_event_type("runtime_initialized")
    logger.info("Runtime context initialized successfully.")

    if reporter.enabled:
        import threading

        def _send_tg_startup() -> None:
            try:
                reporter.send(
                    TelegramMessage(
                        type=TelegramNotificationType.SYSTEM_STARTUP,
                        level="INFO",
                        title="ShadowFleet 运行时已初始化",
                        body="Foundation runtime context is ready.",
                    )
                )
            except Exception:
                logger.exception("Failed to send Telegram startup notification.")

        threading.Thread(target=_send_tg_startup, daemon=True).start()

    return runtime_context
