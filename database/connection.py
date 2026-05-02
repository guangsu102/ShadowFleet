from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Iterator, cast

import psycopg2
from dbutils.pooled_db import PooledDB
from psycopg2 import InterfaceError, OperationalError
from psycopg2.extensions import connection as PgConnection
from psycopg2.extensions import cursor as PgCursor

from utils.logger import set_event_type
from utils.resilience import execute_with_backoff

if TYPE_CHECKING:
    from services.runtime_service import RuntimeContext


DEFAULT_MIN_CONNECTIONS = 1
DEFAULT_MAX_CONNECTIONS = 10


class PostgresConnectionPool:
    def __init__(
        self,
        runtime_context: RuntimeContext,
        min_connections: int = DEFAULT_MIN_CONNECTIONS,
        max_connections: int = DEFAULT_MAX_CONNECTIONS,
    ) -> None:
        if min_connections <= 0:
            raise ValueError("min_connections must be greater than 0")
        if max_connections <= 0:
            raise ValueError("max_connections must be greater than 0")
        if min_connections > max_connections:
            raise ValueError("min_connections must not exceed max_connections")
        if runtime_context.config.xboard is None:
            raise ValueError("xboard configuration is required for PostgreSQL pool")

        self._runtime_context = runtime_context
        self._logger = runtime_context.logger.getChild("database.connection")
        self._request_timeout_seconds = runtime_context.config.app.request_timeout_seconds
        self._max_retries = runtime_context.config.app.max_retries
        self._retry_backoff_seconds = runtime_context.config.app.retry_backoff_seconds
        self._pool = PooledDB(
            creator=psycopg2,
            mincached=0,
            maxcached=max_connections,
            maxconnections=max_connections,
            blocking=True,
            ping=1,
            **self._build_connection_kwargs(),
        )

        set_event_type("db_pool_initialized")
        self._logger.info(
            "Initialized PostgreSQL connection pool for host=%s database=%s",
            runtime_context.config.xboard.host,
            runtime_context.config.xboard.database,
        )

    @contextmanager
    def connection(self) -> Iterator[PgConnection]:
        connection = self._acquire_connection()
        connection.autocommit = False
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            set_event_type("db_transaction_failed")
            self._logger.exception("PostgreSQL transaction failed and was rolled back")
            raise
        finally:
            connection.close()

    @contextmanager
    def cursor(self) -> Iterator[PgCursor]:
        with self.connection() as connection:
            cursor = cast(PgCursor, connection.cursor())
            try:
                yield cursor
            finally:
                cursor.close()

    def close(self) -> None:
        self._pool.close()
        set_event_type("db_pool_closed")
        self._logger.info("Closed PostgreSQL connection pool")

    def _acquire_connection(self) -> PgConnection:
        def _get_connection() -> PgConnection:
            pooled_connection = self._pool.connection()
            return cast(PgConnection, pooled_connection)

        try:
            set_event_type("db_connection_acquire")
            return execute_with_backoff(
                operation_name="postgresql_connection_acquire",
                max_retries=self._max_retries,
                base_delay_seconds=self._retry_backoff_seconds,
                logger=self._logger,
                event_type_prefix="db_connection",
                func=_get_connection,
                should_retry=self._should_retry_connection_error,
            )
        except (OperationalError, InterfaceError):
            set_event_type("db_connection_failed")
            self._logger.exception("Failed to acquire PostgreSQL connection from pool")
            raise

    def _build_connection_kwargs(self) -> dict[str, object]:
        xboard_config = self._runtime_context.config.xboard
        if xboard_config is None:
            raise ValueError("xboard configuration is required for PostgreSQL pool")

        connection_kwargs: dict[str, object] = {
            "host": xboard_config.host,
            "port": xboard_config.port,
            "dbname": xboard_config.database,
            "user": xboard_config.user,
            "sslmode": xboard_config.ssl_mode,
            "connect_timeout": self._request_timeout_seconds,
            "application_name": "shadowfleet",
        }
        if xboard_config.password is not None:
            connection_kwargs["password"] = xboard_config.password
        return connection_kwargs

    @staticmethod
    def _should_retry_connection_error(exc: BaseException) -> bool:
        if isinstance(exc, (OperationalError, InterfaceError)):
            return True
        return False
