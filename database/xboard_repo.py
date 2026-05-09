from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import json
from typing import TYPE_CHECKING

from psycopg2 import Error as PsycopgError
from psycopg2 import InterfaceError, OperationalError

from utils.logger import set_event_type
from utils.resilience import execute_with_backoff

# ShadowFleet node name prefix — used to isolate ShadowFleet-managed nodes
# from manually created nodes in the Xboard v2_server table.
SHADOWFLEET_NODE_NAME_PREFIX = "sf-"

# Xboard v2_server.name column maximum length. Prefix (3 chars) is included.
MAX_NODE_NAME_LENGTH = 64

if TYPE_CHECKING:
    from services.runtime_service import RuntimeContext


JsonPrimitive = str | int | float | bool | None
JsonValue = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]


class XboardRepoError(RuntimeError):
    pass


class XboardNodeNotFoundError(XboardRepoError):
    pass


@dataclass(frozen=True)
class XboardNodeCreateRequest:
    node_type: str
    name: str
    host: str
    port: str
    server_port: int
    rate: Decimal
    code: str | None = None
    parent_id: int | None = None
    group_ids: list[int] | None = None
    route_ids: list[int] | None = None
    tags: list[JsonValue] | None = None
    protocol_settings: dict[str, JsonValue] | None = None
    show: bool = True
    sort: int | None = None
    rate_time_enable: bool = False
    rate_time_ranges: list[JsonValue] | dict[str, JsonValue] | None = None


@dataclass(frozen=True)
class XboardServerMinuteStatRecord:
    server_id: int
    server_type: str
    uplink_bytes: int
    downlink_bytes: int
    total_bytes: int
    active_user_count: int
    sample_minute: int


@dataclass(frozen=True)
class XboardNodeRuntimeRecord:
    node_id: int
    node_name: str
    node_type: str
    host: str
    port: str
    server_port: int
    show: bool


@dataclass(frozen=True)
class XboardServerGroup:
    id: int
    name: str


class XboardRepo:
    def __init__(self, runtime_context: RuntimeContext) -> None:
        db_pool = runtime_context.db_pool
        if db_pool is None:
            raise ValueError(
                "Xboard PostgreSQL connection is not initialized. "
                "Please ensure config.xboard.password is properly configured in config.yaml."
            )

        self._runtime_context = runtime_context
        self._db_pool = db_pool
        self._logger = runtime_context.logger.getChild("database.xboard_repo")
        self._max_retries = runtime_context.config.app.max_retries
        self._retry_backoff_seconds = runtime_context.config.app.retry_backoff_seconds

    @staticmethod
    def _enforce_sf_name(name: str) -> str:
        """Ensure name starts with sf- prefix and fits within MAX_NODE_NAME_LENGTH."""
        if name.startswith(SHADOWFLEET_NODE_NAME_PREFIX):
            return name[:MAX_NODE_NAME_LENGTH]
        prefixed = f"{SHADOWFLEET_NODE_NAME_PREFIX}{name}"
        return prefixed[:MAX_NODE_NAME_LENGTH]

    @staticmethod
    def _normalize_node_type(node_type: str) -> str:
        """将用户友好的协议名称转换为 Xboard 内部类型（小写）"""
        type_mapping = {
            'AnyTLS': 'anytls',
            'Hysteria2': 'hysteria',
            'hysteria2': 'hysteria',
        }
        return type_mapping.get(node_type, node_type.lower())

    def register_node(self, request: XboardNodeCreateRequest) -> int:
        self._validate_create_request(request)
        now = self._utcnow()
        node_name = self._enforce_sf_name(request.name)
        normalized_node_type = self._normalize_node_type(request.node_type)
        sql = """
            INSERT INTO public.v2_server (
                type,
                code,
                parent_id,
                group_ids,
                route_ids,
                name,
                rate,
                tags,
                host,
                port,
                server_port,
                protocol_settings,
                show,
                sort,
                created_at,
                updated_at,
                rate_time_enable,
                rate_time_ranges
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            RETURNING id
        """
        parameters = (
            normalized_node_type,
            request.code,
            request.parent_id,
            self._to_json_text(request.group_ids if request.group_ids is not None else []),
            self._to_json_text(request.route_ids if request.route_ids is not None else []),
            node_name,
            request.rate,
            self._to_json_text(request.tags if request.tags is not None else []),
            request.host,
            request.port,
            request.server_port,
            self._to_json_text(request.protocol_settings if request.protocol_settings is not None else {}),
            request.show,
            request.sort,
            now,
            now,
            request.rate_time_enable,
            self._to_json_text(request.rate_time_ranges if request.rate_time_ranges is not None else []),
        )

        def _operation() -> int:
            with self._db_pool.cursor() as cursor:
                cursor.execute(sql, parameters)
                row = cursor.fetchone()
                if not row:
                    raise XboardRepoError("Xboard register_node returned no id")
                return int(row[0])

        try:
            node_id = execute_with_backoff(
                operation_name="xboard_register_node",
                max_retries=self._max_retries,
                base_delay_seconds=self._retry_backoff_seconds,
                logger=self._logger,
                event_type_prefix="db_query",
                func=_operation,
                should_retry=self._should_retry_database_error,
            )
        except IndexError:
            raise
        except PsycopgError as exc:
            set_event_type("db_query_failed")
            self._logger.exception("Failed to register Xboard node name=%s", node_name)
            raise XboardRepoError("Failed to register Xboard node") from exc

        set_event_type("db_node_registered")
        self._logger.info("Registered Xboard node id=%s name=%s", node_id, node_name)
        return node_id

    def mark_node_online(self, node_id: int) -> None:
        self._update_node_visibility(node_id=node_id, visible=True)

    def mark_node_offline(self, node_id: int) -> None:
        self._update_node_visibility(node_id=node_id, visible=False)

    def delete_node(self, node_id: int) -> None:
        if node_id is None or node_id <= 0:
            set_event_type("db_node_delete_skipped")
            self._logger.warning("Skipped delete_node: node_id=%s (invalid)", node_id)
            return
        sql = "DELETE FROM public.v2_server WHERE id = %s AND name LIKE 'sf-%%'"

        def _operation() -> None:
            with self._db_pool.cursor() as cursor:
                cursor.execute(sql, (node_id,))
                if cursor.rowcount == 0:
                    raise XboardNodeNotFoundError(f"Xboard node not found: node_id={node_id}")

        try:
            execute_with_backoff(
                operation_name="xboard_delete_node",
                max_retries=self._max_retries,
                base_delay_seconds=self._retry_backoff_seconds,
                logger=self._logger,
                event_type_prefix="db_query",
                func=_operation,
                should_retry=self._should_retry_database_error,
            )
        except XboardNodeNotFoundError:
            raise
        except IndexError:
            raise
        except PsycopgError as exc:
            set_event_type("db_query_failed")
            self._logger.exception("Failed to delete Xboard node id=%s", node_id)
            raise XboardRepoError("Failed to delete Xboard node") from exc

        set_event_type("db_node_deleted")
        self._logger.info("Deleted Xboard node id=%s", node_id)

    def update_node_host(self, node_id: int, host: str) -> None:
        if not host or not host.strip():
            raise ValueError("host must not be empty")

        sql = """
            UPDATE public.v2_server
            SET host = %s, updated_at = %s
            WHERE id = %s AND name LIKE 'sf-%%'
        """
        parameters = (host.strip(), self._utcnow(), node_id)

        def _operation() -> None:
            with self._db_pool.cursor() as cursor:
                cursor.execute(sql, parameters)
                if cursor.rowcount == 0:
                    raise XboardNodeNotFoundError(f"Xboard node not found: node_id={node_id}")

        try:
            execute_with_backoff(
                operation_name="xboard_update_node_host",
                max_retries=self._max_retries,
                base_delay_seconds=self._retry_backoff_seconds,
                logger=self._logger,
                event_type_prefix="db_query",
                func=_operation,
                should_retry=self._should_retry_database_error,
            )
        except XboardNodeNotFoundError:
            raise
        except PsycopgError as exc:
            set_event_type("db_query_failed")
            self._logger.exception("Failed to update Xboard node host id=%s", node_id)
            raise XboardRepoError("Failed to update Xboard node host") from exc

        set_event_type("db_node_host_updated")
        self._logger.info("Updated Xboard node host id=%s host=%s", node_id, host.strip())

    def get_node_runtime(self, node_id: int) -> XboardNodeRuntimeRecord:
        if node_id <= 0:
            raise ValueError("node_id must be greater than 0")
        sql = """
            SELECT
                id,
                name,
                type,
                host,
                port,
                server_port,
                show
            FROM public.v2_server
            WHERE id = %s AND name LIKE 'sf-%%'
        """

        def _operation() -> XboardNodeRuntimeRecord:
            with self._db_pool.cursor() as cursor:
                cursor.execute(sql, (node_id,))
                row = cursor.fetchone()
            if row is None:
                raise XboardNodeNotFoundError(f"Xboard node not found: node_id={node_id}")
            return XboardNodeRuntimeRecord(
                node_id=int(row[0]),
                node_name=str(row[1]),
                node_type=str(row[2]),
                host=str(row[3]),
                port=str(row[4]),
                server_port=int(row[5]),
                show=bool(row[6]),
            )

        try:
            return execute_with_backoff(
                operation_name="xboard_get_node_runtime",
                max_retries=self._max_retries,
                base_delay_seconds=self._retry_backoff_seconds,
                logger=self._logger,
                event_type_prefix="db_query",
                func=_operation,
                should_retry=self._should_retry_database_error,
            )
        except XboardNodeNotFoundError:
            raise
        except PsycopgError as exc:
            set_event_type("db_query_failed")
            self._logger.exception("Failed to query Xboard node runtime id=%s", node_id)
            raise XboardRepoError("Failed to query Xboard node runtime") from exc

    def list_server_minute_stats(
        self,
        server_id: int,
        server_type: str,
        since_minute: int,
    ) -> list[XboardServerMinuteStatRecord]:
        if server_id <= 0:
            raise ValueError("server_id must be greater than 0")
        if not server_type or not server_type.strip():
            raise ValueError("server_type must not be empty")
        sql = """
            SELECT
                server_id,
                server_type,
                uplink_bytes,
                downlink_bytes,
                total_bytes,
                active_user_count,
                sample_minute
            FROM public.v2_stat_server_minute
            WHERE server_id = %s
              AND server_type = %s
              AND sample_minute >= %s
            ORDER BY sample_minute ASC
        """

        def _operation() -> list[XboardServerMinuteStatRecord]:
            with self._db_pool.cursor() as cursor:
                cursor.execute(sql, (server_id, server_type.strip(), since_minute))
                rows = cursor.fetchall()
            records: list[XboardServerMinuteStatRecord] = []
            for row in rows:
                records.append(
                    XboardServerMinuteStatRecord(
                        server_id=int(row[0]),
                        server_type=str(row[1]),
                        uplink_bytes=int(row[2]),
                        downlink_bytes=int(row[3]),
                        total_bytes=int(row[4]),
                        active_user_count=int(row[5]),
                        sample_minute=int(row[6]),
                    )
                )
            return records

        try:
            return execute_with_backoff(
                operation_name="xboard_list_server_minute_stats",
                max_retries=self._max_retries,
                base_delay_seconds=self._retry_backoff_seconds,
                logger=self._logger,
                event_type_prefix="db_query",
                func=_operation,
                should_retry=self._should_retry_database_error,
            )
        except PsycopgError as exc:
            set_event_type("db_query_failed")
            self._logger.exception(
                "Failed to list Xboard minute stats server_id=%s server_type=%s",
                server_id,
                server_type,
            )
            raise XboardRepoError(
                "Failed to query Xboard minute stats; ensure v2_stat_server_minute is implemented"
            ) from exc

    def list_groups(self) -> list[XboardServerGroup]:
        sql = "SELECT id, name FROM public.v2_server_group ORDER BY id ASC"

        def _operation() -> list[XboardServerGroup]:
            with self._db_pool.cursor() as cursor:
                cursor.execute(sql)
                rows = cursor.fetchall()
            return [XboardServerGroup(id=int(row[0]), name=str(row[1])) for row in rows]

        try:
            return execute_with_backoff(
                operation_name="xboard_list_groups",
                max_retries=self._max_retries,
                base_delay_seconds=self._retry_backoff_seconds,
                logger=self._logger,
                event_type_prefix="db_query",
                func=_operation,
                should_retry=self._should_retry_database_error,
            )
        except PsycopgError as exc:
            set_event_type("db_query_failed")
            self._logger.exception("Failed to list Xboard server groups")
            raise XboardRepoError("Failed to list Xboard server groups") from exc

    def list_all_shadowfleet_nodes(self) -> list[XboardNodeRuntimeRecord]:
        """List all ShadowFleet-managed nodes from Xboard (name starts with sf-)."""
        sql = """
            SELECT
                id,
                name,
                type,
                host,
                port,
                server_port,
                show
            FROM public.v2_server
            WHERE name LIKE 'sf-%%'
            ORDER BY id ASC
        """

        def _operation() -> list[XboardNodeRuntimeRecord]:
            with self._db_pool.cursor() as cursor:
                cursor.execute(sql)
                rows = cursor.fetchall()
            return [
                XboardNodeRuntimeRecord(
                    node_id=int(row[0]),
                    node_name=str(row[1]),
                    node_type=str(row[2]),
                    host=str(row[3]),
                    port=str(row[4]),
                    server_port=int(row[5]),
                    show=bool(row[6]),
                )
                for row in rows
            ]

        try:
            return execute_with_backoff(
                operation_name="xboard_list_all_nodes",
                max_retries=self._max_retries,
                base_delay_seconds=self._retry_backoff_seconds,
                logger=self._logger,
                event_type_prefix="db_query",
                func=_operation,
                should_retry=self._should_retry_database_error,
            )
        except PsycopgError as exc:
            set_event_type("db_query_failed")
            self._logger.exception("Failed to list all ShadowFleet nodes from Xboard")
            raise XboardRepoError("Failed to list all ShadowFleet nodes from Xboard") from exc

    def _update_node_visibility(self, node_id: int, visible: bool) -> None:
        sql = """
            UPDATE public.v2_server
            SET show = %s, updated_at = %s
            WHERE id = %s AND name LIKE 'sf-%%'
        """
        parameters = (visible, self._utcnow(), node_id)

        def _operation() -> None:
            with self._db_pool.cursor() as cursor:
                cursor.execute(sql, parameters)
                if cursor.rowcount == 0:
                    raise XboardNodeNotFoundError(f"Xboard node not found: node_id={node_id}")

        try:
            execute_with_backoff(
                operation_name="xboard_update_node_visibility",
                max_retries=self._max_retries,
                base_delay_seconds=self._retry_backoff_seconds,
                logger=self._logger,
                event_type_prefix="db_query",
                func=_operation,
                should_retry=self._should_retry_database_error,
            )
        except XboardNodeNotFoundError:
            raise
        except PsycopgError as exc:
            set_event_type("db_query_failed")
            self._logger.exception(
                "Failed to update Xboard node visibility id=%s visible=%s",
                node_id,
                visible,
            )
            raise XboardRepoError("Failed to update Xboard node visibility") from exc

        event_type = "db_node_online" if visible else "db_node_offline"
        state = "online" if visible else "offline"
        set_event_type(event_type)
        self._logger.info("Marked Xboard node id=%s as %s", node_id, state)

    @staticmethod
    def _validate_create_request(request: XboardNodeCreateRequest) -> None:
        if not request.node_type or not request.node_type.strip():
            raise ValueError("node_type must not be empty")
        if not request.name or not request.name.strip():
            raise ValueError("name must not be empty")
        if not request.host or not request.host.strip():
            raise ValueError("host must not be empty")
        if not request.port or not request.port.strip():
            raise ValueError("port must not be empty")
        if request.server_port <= 0:
            raise ValueError("server_port must be greater than 0")
        if request.rate <= Decimal("0"):
            raise ValueError("rate must be greater than 0")

    @staticmethod
    def _to_json_text(value: JsonValue | None) -> str | None:
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"))

    @staticmethod
    def _should_retry_database_error(exc: BaseException) -> bool:
        if isinstance(exc, (OperationalError, InterfaceError)):
            return True
        if isinstance(exc, IndexError):
            return True
        return False

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.utcnow()
