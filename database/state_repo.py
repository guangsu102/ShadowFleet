from __future__ import annotations

from datetime import timedelta
import sqlite3
from typing import TYPE_CHECKING

from database.state_models import (
    FleetNodeCreateRequest,
    FleetNodeEventCreateRequest,
    FleetNodeNotFoundError,
    FleetNodeRecord,
    FleetNodeStatus,
    FleetOperationLockError,
    FleetOperationLockRequest,
    JsonValue,
    StateRepoError,
)
from database.state_repo_helpers import (
    map_fleet_node_record,
    to_json_text,
    utcnow,
    utcnow_iso,
    validate_create_request,
)

from utils.logger import set_event_type

if TYPE_CHECKING:
    from services.runtime_service import RuntimeContext


__all__ = [
    "FleetNodeCreateRequest",
    "FleetNodeEventCreateRequest",
    "FleetNodeNotFoundError",
    "FleetNodeRecord",
    "FleetNodeStatus",
    "FleetOperationLockError",
    "FleetOperationLockRequest",
    "JsonValue",
    "StateRepo",
    "StateRepoError",
]


class StateRepo:
    def __init__(self, runtime_context: RuntimeContext) -> None:
        sqlite_manager = runtime_context.sqlite_manager
        if sqlite_manager is None:
            raise ValueError("RuntimeContext.sqlite_manager is required for StateRepo")

        self._runtime_context = runtime_context
        self._sqlite_manager = sqlite_manager
        self._logger = runtime_context.logger.getChild("database.state_repo")

    def create_node(self, request: FleetNodeCreateRequest) -> int:
        validate_create_request(request)
        timestamp = utcnow_iso()
        sql = """
            INSERT INTO fleet_nodes (
                xboard_node_id,
                node_name,
                node_type,
                status,
                status_reason,
                aws_account_id,
                aws_region,
                aws_instance_id,
                aws_subnet_id,
                aws_security_group_id,
                cloudflare_record_id,
                domain_name,
                ipv4_address,
                ipv6_address,
                last_known_host,
                last_error,
                created_at,
                updated_at,
                online_at,
                offline_at,
                deleted_at,
                last_healed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        online_at = timestamp if request.status == "online" else None
        offline_at = timestamp if request.status == "offline" else None
        deleted_at = timestamp if request.status == "deleted" else None
        parameters = (
            request.xboard_node_id,
            request.node_name.strip(),
            request.node_type.strip(),
            request.status,
            request.status_reason,
            request.aws_account_id,
            request.aws_region,
            request.aws_instance_id,
            request.aws_subnet_id,
            request.aws_security_group_id,
            request.cloudflare_record_id,
            request.domain_name,
            request.ipv4_address,
            request.ipv6_address,
            request.last_known_host,
            request.last_error,
            timestamp,
            timestamp,
            online_at,
            offline_at,
            deleted_at,
            None,
        )

        try:
            with self._sqlite_manager.connection() as connection:
                cursor = connection.execute(sql, parameters)
                node_id = int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            set_event_type("sqlite_node_create_failed")
            self._logger.exception(
                "Failed to create local fleet node for xboard_node_id=%s",
                request.xboard_node_id,
            )
            raise StateRepoError("Failed to create local fleet node") from exc

        set_event_type("sqlite_node_created")
        self._logger.info(
            "Created local fleet node id=%s xboard_node_id=%s",
            node_id,
            request.xboard_node_id,
        )
        return node_id

    def get_node_by_xboard_node_id(self, xboard_node_id: int) -> FleetNodeRecord | None:
        sql = "SELECT * FROM fleet_nodes WHERE xboard_node_id = ?"
        with self._sqlite_manager.connection() as connection:
            row = connection.execute(sql, (xboard_node_id,)).fetchone()
        if row is None:
            return None
        return map_fleet_node_record(row)

    def get_node_by_node_name(self, node_name: str) -> FleetNodeRecord | None:
        sql = "SELECT * FROM fleet_nodes WHERE node_name = ? AND is_deleted = 0"
        with self._sqlite_manager.connection() as connection:
            row = connection.execute(sql, (node_name.strip(),)).fetchone()
        if row is None:
            return None
        return map_fleet_node_record(row)

    def update_node_xboard_id(
        self,
        node_id: int,
        new_xboard_node_id: int,
        old_xboard_node_id: int,
    ) -> None:
        sql = """
            UPDATE fleet_nodes
            SET xboard_node_id = ?, updated_at = ?
            WHERE id = ?
        """
        timestamp = utcnow_iso()
        with self._sqlite_manager.connection() as connection:
            cursor = connection.execute(sql, (new_xboard_node_id, timestamp, node_id))
            if cursor.rowcount == 0:
                raise FleetNodeNotFoundError(f"Fleet node not found for id={node_id}")
        set_event_type("sqlite_node_xboard_id_updated")
        self._logger.info(
            "Updated local fleet node id=%s xboard_node_id: %s -> %s",
            node_id,
            old_xboard_node_id,
            new_xboard_node_id,
        )

    def list_nodes_by_aws_account_id(
        self,
        aws_account_id: str,
        *,
        include_deleted: bool = False,
    ) -> list[FleetNodeRecord]:
        if not aws_account_id or not aws_account_id.strip():
            raise ValueError("aws_account_id must not be empty")
        conditions = ["aws_account_id = ?"]
        parameters: list[object] = [aws_account_id.strip()]
        if not include_deleted:
            conditions.append("is_deleted = 0")
        where_clause = " AND ".join(conditions)
        sql = f"""
            SELECT *
            FROM fleet_nodes
            WHERE {where_clause}
            ORDER BY id ASC
        """
        with self._sqlite_manager.connection() as connection:
            rows = connection.execute(sql, tuple(parameters)).fetchall()
        return [map_fleet_node_record(row) for row in rows]

    def list_monitorable_nodes(self) -> list[FleetNodeRecord]:
        with self._sqlite_manager.connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM fleet_nodes
                WHERE is_deleted = 0
                  AND status IN ('online', 'offline')
                ORDER BY id ASC
                """
            ).fetchall()
        return [map_fleet_node_record(row) for row in rows]

    def purge_node_record(self, xboard_node_id: int) -> None:
        sql = "DELETE FROM fleet_nodes WHERE xboard_node_id = ?"
        with self._sqlite_manager.connection() as connection:
            cursor = connection.execute(sql, (xboard_node_id,))
            if cursor.rowcount == 0:
                raise FleetNodeNotFoundError(
                    f"Fleet node not found for xboard_node_id={xboard_node_id}"
                )

        set_event_type("sqlite_node_purged")
        self._logger.info("Purged local fleet node record xboard_node_id=%s", xboard_node_id)

    def update_node_status(
        self,
        xboard_node_id: int,
        status: FleetNodeStatus,
        status_reason: str | None = None,
        last_error: str | None = None,
    ) -> None:
        timestamp = utcnow_iso()
        updates: dict[str, object] = {
            "status": status,
            "status_reason": status_reason,
            "last_error": last_error,
            "updated_at": timestamp,
        }
        if status == "online":
            updates["online_at"] = timestamp
            updates["offline_at"] = None
        elif status == "offline":
            updates["offline_at"] = timestamp
        elif status == "deleted":
            updates["deleted_at"] = timestamp
            updates["is_deleted"] = 1
        elif status == "healing":
            updates["last_healed_at"] = timestamp

        self._update_node_fields(xboard_node_id=xboard_node_id, updates=updates)
        set_event_type("sqlite_node_status_updated")
        self._logger.info(
            "Updated local fleet node xboard_node_id=%s status=%s",
            xboard_node_id,
            status,
        )

    def update_node_runtime_metadata(
        self,
        xboard_node_id: int,
        aws_account_id: str | None = None,
        aws_region: str | None = None,
        aws_instance_id: str | None = None,
        aws_subnet_id: str | None = None,
        aws_security_group_id: str | None = None,
        instance_type: str | None = None,
        cloudflare_record_id: str | None = None,
        domain_name: str | None = None,
        ipv4_address: str | None = None,
        ipv6_address: str | None = None,
        last_known_host: str | None = None,
        last_error: str | None = None,
    ) -> None:
        updates: dict[str, object] = {"updated_at": utcnow_iso()}
        optional_fields = {
            "aws_account_id": aws_account_id,
            "aws_region": aws_region,
            "aws_instance_id": aws_instance_id,
            "aws_subnet_id": aws_subnet_id,
            "aws_security_group_id": aws_security_group_id,
            "instance_type": instance_type,
            "cloudflare_record_id": cloudflare_record_id,
            "domain_name": domain_name,
            "ipv4_address": ipv4_address,
            "ipv6_address": ipv6_address,
            "last_known_host": last_known_host,
            "last_error": last_error,
        }
        for field_name, field_value in optional_fields.items():
            if field_value is not None:
                updates[field_name] = field_value

        if len(updates) == 1:
            return

        self._update_node_fields(xboard_node_id=xboard_node_id, updates=updates)
        set_event_type("sqlite_node_metadata_updated")
        self._logger.info(
            "Updated local fleet node metadata for xboard_node_id=%s",
            xboard_node_id,
        )

    def update_node_error_state(
        self,
        xboard_node_id: int,
        *,
        status_reason: str | None,
        last_error: str | None,
    ) -> None:
        self._update_node_fields(
            xboard_node_id=xboard_node_id,
            updates={
                "status_reason": status_reason,
                "last_error": last_error,
                "updated_at": utcnow_iso(),
            },
        )
        set_event_type("sqlite_node_error_updated")
        self._logger.info(
            "Updated local fleet node error state for xboard_node_id=%s",
            xboard_node_id,
        )

    def create_event(self, request: FleetNodeEventCreateRequest) -> int:
        if not request.event_type or not request.event_type.strip():
            raise ValueError("event_type must not be empty")
        if not request.correlation_id or not request.correlation_id.strip():
            raise ValueError("correlation_id must not be empty")

        sql = """
            INSERT INTO fleet_node_events (
                node_id,
                xboard_node_id,
                event_type,
                from_status,
                to_status,
                correlation_id,
                message,
                payload_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        parameters = (
            request.node_id,
            request.xboard_node_id,
            request.event_type.strip(),
            request.from_status,
            request.to_status,
            request.correlation_id.strip(),
            request.message,
            to_json_text(request.payload),
            utcnow_iso(),
        )

        try:
            with self._sqlite_manager.connection() as connection:
                cursor = connection.execute(sql, parameters)
                event_id = int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            set_event_type("sqlite_event_create_failed")
            self._logger.exception(
                "Failed to create fleet node event for node_id=%s",
                request.node_id,
            )
            raise StateRepoError("Failed to create fleet node event") from exc

        set_event_type("sqlite_event_created")
        self._logger.info(
            "Created fleet node event id=%s type=%s node_id=%s",
            event_id,
            request.event_type,
            request.node_id,
        )
        return event_id

    def acquire_operation_lock(self, request: FleetOperationLockRequest) -> bool:
        if not request.lock_key or not request.lock_key.strip():
            raise ValueError("lock_key must not be empty")
        if not request.operation_type or not request.operation_type.strip():
            raise ValueError("operation_type must not be empty")
        if not request.correlation_id or not request.correlation_id.strip():
            raise ValueError("correlation_id must not be empty")
        if request.expires_in_seconds <= 0:
            raise ValueError("expires_in_seconds must be greater than 0")

        self.purge_expired_locks()
        sql = """
            INSERT INTO fleet_operation_locks (
                lock_key,
                node_id,
                operation_type,
                correlation_id,
                expires_at,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """
        now = utcnow()
        parameters = (
            request.lock_key.strip(),
            request.node_id,
            request.operation_type.strip(),
            request.correlation_id.strip(),
            (now + timedelta(seconds=request.expires_in_seconds)).isoformat(),
            now.isoformat(),
        )

        try:
            with self._sqlite_manager.connection() as connection:
                connection.execute(sql, parameters)
        except sqlite3.IntegrityError:
            set_event_type("sqlite_lock_conflict")
            self._logger.warning("Fleet operation lock already exists: %s", request.lock_key)
            return False

        set_event_type("sqlite_lock_acquired")
        self._logger.info("Acquired fleet operation lock: %s", request.lock_key)
        return True

    def release_operation_lock(self, lock_key: str) -> None:
        if not lock_key or not lock_key.strip():
            raise ValueError("lock_key must not be empty")

        with self._sqlite_manager.connection() as connection:
            connection.execute(
                "DELETE FROM fleet_operation_locks WHERE lock_key = ?",
                (lock_key.strip(),),
            )

        set_event_type("sqlite_lock_released")
        self._logger.info("Released fleet operation lock: %s", lock_key.strip())

    def purge_expired_locks(self) -> int:
        sql = "DELETE FROM fleet_operation_locks WHERE expires_at <= ?"
        with self._sqlite_manager.connection() as connection:
            cursor = connection.execute(sql, (utcnow_iso(),))
            deleted_count = int(cursor.rowcount if cursor.rowcount != -1 else 0)

        if deleted_count > 0:
            set_event_type("sqlite_lock_purged")
            self._logger.info("Purged expired fleet operation locks count=%s", deleted_count)
        return deleted_count

    def _update_node_fields(self, xboard_node_id: int, updates: dict[str, object]) -> None:
        if not updates:
            raise ValueError("updates must not be empty")

        assignments = ", ".join(f"{column} = ?" for column in updates)
        parameters = tuple(updates.values()) + (xboard_node_id,)
        sql = f"UPDATE fleet_nodes SET {assignments} WHERE xboard_node_id = ?"
        with self._sqlite_manager.connection() as connection:
            cursor = connection.execute(sql, parameters)
            if cursor.rowcount == 0:
                raise FleetNodeNotFoundError(
                    f"Fleet node not found for xboard_node_id={xboard_node_id}"
                )

    def list_active_nodes(self) -> list[FleetNodeRecord]:
        """List all active (non-deleted) nodes from local SQLite."""
        sql = "SELECT * FROM fleet_nodes WHERE is_deleted = 0 ORDER BY id ASC"
        with self._sqlite_manager.connection() as connection:
            rows = connection.execute(sql).fetchall()
        return [map_fleet_node_record(row) for row in rows]

    def mark_node_deleted(self, xboard_node_id: int, reason: str | None = None) -> None:
        """Mark a node as deleted in local SQLite."""
        sql = """
            UPDATE fleet_nodes
            SET is_deleted = 1, status = 'deleted', updated_at = ?, deleted_at = ?
            WHERE xboard_node_id = ?
        """
        timestamp = utcnow_iso()
        with self._sqlite_manager.connection() as connection:
            cursor = connection.execute(sql, (timestamp, timestamp, xboard_node_id))
            if cursor.rowcount == 0:
                raise FleetNodeNotFoundError(
                    f"Fleet node not found for xboard_node_id={xboard_node_id}"
                )
        set_event_type("sqlite_node_marked_deleted")
        self._logger.info("Marked node deleted locally xboard_node_id=%s", xboard_node_id)

