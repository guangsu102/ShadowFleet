from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import sqlite3
from typing import Literal, TYPE_CHECKING

from utils.logger import set_event_type

if TYPE_CHECKING:
    from services.runtime_service import RuntimeContext


JsonPrimitive = str | int | float | bool | None
JsonValue = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]
ProvisioningTaskType = Literal["provision_node"]
ProvisioningTaskStatus = Literal["queued", "running", "succeeded", "failed"]


class ProvisioningTaskRepoError(RuntimeError):
    pass


class ProvisioningTaskNotFoundError(ProvisioningTaskRepoError):
    pass


@dataclass(frozen=True)
class ProvisioningTaskCreateRequest:
    correlation_id: str
    request_payload: dict[str, JsonValue]
    max_attempts: int = 1
    task_type: ProvisioningTaskType = "provision_node"


@dataclass(frozen=True)
class ProvisioningTaskRecord:
    id: int
    task_type: ProvisioningTaskType
    status: ProvisioningTaskStatus
    correlation_id: str
    request_payload: dict[str, JsonValue]
    result_payload: JsonValue | None
    last_error: str | None
    attempt_count: int
    max_attempts: int
    locked_by: str | None
    locked_at: str | None
    next_run_at: str
    created_at: str
    updated_at: str
    started_at: str | None
    finished_at: str | None


class ProvisioningTaskRepo:
    def __init__(self, runtime_context: RuntimeContext) -> None:
        sqlite_manager = runtime_context.sqlite_manager
        if sqlite_manager is None:
            raise ValueError("RuntimeContext.sqlite_manager is required for ProvisioningTaskRepo")

        self._runtime_context = runtime_context
        self._sqlite_manager = sqlite_manager
        self._logger = runtime_context.logger.getChild("database.provisioning_task_repo")

    def create_task(self, request: ProvisioningTaskCreateRequest) -> int:
        self._validate_create_request(request)
        timestamp = self._utcnow_iso()
        sql = """
            INSERT INTO fleet_provisioning_tasks (
                task_type,
                status,
                correlation_id,
                request_payload_json,
                result_payload_json,
                last_error,
                attempt_count,
                max_attempts,
                locked_by,
                locked_at,
                next_run_at,
                created_at,
                updated_at,
                started_at,
                finished_at
            )
            VALUES (?, 'queued', ?, ?, NULL, NULL, 0, ?, NULL, NULL, ?, ?, ?, NULL, NULL)
        """
        parameters = (
            request.task_type,
            request.correlation_id.strip(),
            self._to_json_text(request.request_payload),
            request.max_attempts,
            timestamp,
            timestamp,
            timestamp,
        )
        with self._sqlite_manager.connection() as connection:
            cursor = connection.execute(sql, parameters)
            task_id = int(cursor.lastrowid)

        set_event_type("sqlite_provision_task_created")
        self._logger.info("Created provisioning task id=%s type=%s", task_id, request.task_type)
        return task_id

    def get_task_by_id(self, task_id: int) -> ProvisioningTaskRecord:
        with self._sqlite_manager.connection() as connection:
            row = connection.execute(
                "SELECT * FROM fleet_provisioning_tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
        if row is None:
            raise ProvisioningTaskNotFoundError(f"Provisioning task not found: task_id={task_id}")
        return self._map_task_record(row)

    def list_recent_tasks(self, limit: int = 20) -> list[ProvisioningTaskRecord]:
        if limit <= 0:
            raise ValueError("limit must be greater than 0")
        with self._sqlite_manager.connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM fleet_provisioning_tasks
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._map_task_record(row) for row in rows]

    def get_task_stats(self) -> dict[str, int]:
        with self._sqlite_manager.connection() as connection:
            rows = connection.execute(
                """
                SELECT status, COUNT(*) as count
                FROM fleet_provisioning_tasks
                GROUP BY status
                """,
            ).fetchall()
        result = {"total": 0, "queued": 0, "running": 0, "succeeded": 0, "failed": 0}
        for row in rows:
            status = row[0]
            count = row[1]
            if status in result:
                result[status] = count
            result["total"] += count
        return result

    def list_stale_running_tasks(
        self,
        running_timeout_seconds: float,
    ) -> list[ProvisioningTaskRecord]:
        if running_timeout_seconds <= 0:
            raise ValueError("running_timeout_seconds must be greater than 0")

        stale_before = self._utcnow_plus_seconds_iso(-running_timeout_seconds)
        with self._sqlite_manager.connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM fleet_provisioning_tasks
                WHERE status = 'running'
                  AND (locked_at IS NULL OR locked_at <= ?)
                ORDER BY locked_at ASC, id ASC
                """,
                (stale_before,),
            ).fetchall()
        return [self._map_task_record(row) for row in rows]

    def claim_next_task(self, worker_id: str) -> ProvisioningTaskRecord | None:
        if not worker_id or not worker_id.strip():
            raise ValueError("worker_id must not be empty")

        timestamp = self._utcnow_iso()
        with self._sqlite_manager.connection() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM fleet_provisioning_tasks
                WHERE status = 'queued' AND next_run_at <= ?
                ORDER BY next_run_at ASC, created_at ASC, id ASC
                LIMIT 1
                """,
                (timestamp,),
            ).fetchone()
            if row is None:
                return None

            cursor = connection.execute(
                """
                UPDATE fleet_provisioning_tasks
                SET
                    status = 'running',
                    attempt_count = attempt_count + 1,
                    locked_by = ?,
                    locked_at = ?,
                    updated_at = ?,
                    started_at = COALESCE(started_at, ?),
                    finished_at = NULL
                WHERE id = ? AND status = 'queued'
                """,
                (
                    worker_id.strip(),
                    timestamp,
                    timestamp,
                    timestamp,
                    int(row["id"]),
                ),
            )
            if cursor.rowcount == 0:
                return None

            claimed_row = connection.execute(
                "SELECT * FROM fleet_provisioning_tasks WHERE id = ?",
                (int(row["id"]),),
            ).fetchone()
        if claimed_row is None:
            raise ProvisioningTaskRepoError("Failed to load claimed provisioning task")

        task_record = self._map_task_record(claimed_row)
        set_event_type("sqlite_provision_task_claimed")
        self._logger.info(
            "Claimed provisioning task id=%s attempt=%s worker_id=%s",
            task_record.id,
            task_record.attempt_count,
            worker_id,
        )
        return task_record

    def mark_task_succeeded(self, task_id: int, result_payload: JsonValue | None) -> None:
        self._update_task_terminal_state(
            task_id=task_id,
            status="succeeded",
            result_payload=result_payload,
            last_error=None,
        )
        set_event_type("sqlite_provision_task_succeeded")
        self._logger.info("Provisioning task succeeded id=%s", task_id)

    def mark_task_failed(self, task_id: int, error_message: str) -> None:
        if not error_message or not error_message.strip():
            raise ValueError("error_message must not be empty")
        self._update_task_terminal_state(
            task_id=task_id,
            status="failed",
            result_payload=None,
            last_error=error_message.strip(),
        )
        set_event_type("sqlite_provision_task_failed")
        self._logger.info("Provisioning task failed id=%s", task_id)

    def mark_task_for_retry(
        self,
        task_id: int,
        error_message: str,
        retry_after_seconds: float,
    ) -> None:
        if not error_message or not error_message.strip():
            raise ValueError("error_message must not be empty")
        if retry_after_seconds <= 0:
            raise ValueError("retry_after_seconds must be greater than 0")

        timestamp = self._utcnow_iso()
        next_run_at = self._utcnow_plus_seconds_iso(retry_after_seconds)
        with self._sqlite_manager.connection() as connection:
            cursor = connection.execute(
                """
                UPDATE fleet_provisioning_tasks
                SET
                    status = 'queued',
                    result_payload_json = NULL,
                    last_error = ?,
                    locked_by = NULL,
                    locked_at = NULL,
                    next_run_at = ?,
                    updated_at = ?,
                    finished_at = NULL
                WHERE id = ?
                """,
                (
                    error_message.strip(),
                    next_run_at,
                    timestamp,
                    task_id,
                ),
            )
            if cursor.rowcount == 0:
                raise ProvisioningTaskNotFoundError(
                    f"Provisioning task not found for retry: task_id={task_id}"
                )

        set_event_type("sqlite_provision_task_requeued")
        self._logger.info(
            "Re-queued provisioning task id=%s next_run_at=%s",
            task_id,
            next_run_at,
        )

    def reset_for_retry(self, task_id: int) -> ProvisioningTaskRecord:
        timestamp = self._utcnow_iso()
        with self._sqlite_manager.connection() as connection:
            cursor = connection.execute(
                """
                UPDATE fleet_provisioning_tasks
                SET
                    status = 'queued',
                    attempt_count = 0,
                    result_payload_json = NULL,
                    last_error = NULL,
                    locked_by = NULL,
                    locked_at = NULL,
                    next_run_at = ?,
                    updated_at = ?,
                    finished_at = NULL
                WHERE id = ? AND status IN ('failed', 'succeeded')
                """,
                (
                    timestamp,
                    timestamp,
                    task_id,
                ),
            )
            if cursor.rowcount == 0:
                raise ProvisioningTaskNotFoundError(
                    f"No retryable task found: task_id={task_id} (must be failed or succeeded)"
                )

        set_event_type("sqlite_provision_task_manual_retry")
        self._logger.info("Manually reset task for retry id=%s", task_id)
        return self.get_task_by_id(task_id)

    def delete_task(self, task_id: int) -> bool:
        with self._sqlite_manager.connection() as connection:
            cursor = connection.execute(
                "DELETE FROM fleet_provisioning_tasks WHERE id = ?",
                (task_id,),
            )
            if cursor.rowcount == 0:
                raise ProvisioningTaskNotFoundError(
                    f"Provisioning task not found for deletion: task_id={task_id}"
                )

        set_event_type("sqlite_provision_task_deleted")
        self._logger.info("Deleted provisioning task id=%s", task_id)
        return True

    def _update_task_terminal_state(
        self,
        task_id: int,
        status: ProvisioningTaskStatus,
        result_payload: JsonValue | None,
        last_error: str | None,
    ) -> None:
        timestamp = self._utcnow_iso()
        with self._sqlite_manager.connection() as connection:
            cursor = connection.execute(
                """
                UPDATE fleet_provisioning_tasks
                SET
                    status = ?,
                    result_payload_json = ?,
                    last_error = ?,
                    locked_by = NULL,
                    locked_at = NULL,
                    updated_at = ?,
                    finished_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    self._to_json_text(result_payload),
                    last_error,
                    timestamp,
                    timestamp,
                    task_id,
                ),
            )
            if cursor.rowcount == 0:
                raise ProvisioningTaskNotFoundError(
                    f"Provisioning task not found: task_id={task_id}"
                )

    @staticmethod
    def _validate_create_request(request: ProvisioningTaskCreateRequest) -> None:
        if not request.correlation_id or not request.correlation_id.strip():
            raise ValueError("correlation_id must not be empty")
        if request.max_attempts <= 0:
            raise ValueError("max_attempts must be greater than 0")
        if not request.request_payload:
            raise ValueError("request_payload must not be empty")

    def _map_task_record(self, row: sqlite3.Row) -> ProvisioningTaskRecord:
        request_payload = self._from_json_text(str(row["request_payload_json"]))
        if not isinstance(request_payload, dict):
            raise ProvisioningTaskRepoError("Provisioning task request payload must be a JSON object")
        return ProvisioningTaskRecord(
            id=int(row["id"]),
            task_type=row["task_type"],
            status=row["status"],
            correlation_id=str(row["correlation_id"]),
            request_payload=request_payload,
            result_payload=self._from_json_text(row["result_payload_json"]),
            last_error=row["last_error"],
            attempt_count=int(row["attempt_count"]),
            max_attempts=int(row["max_attempts"]),
            locked_by=row["locked_by"],
            locked_at=row["locked_at"],
            next_run_at=str(row["next_run_at"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )

    @staticmethod
    def _to_json_text(value: JsonValue | None) -> str | None:
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"))

    @staticmethod
    def _from_json_text(value: str | None) -> JsonValue | None:
        if value is None:
            return None
        return json.loads(value)

    @staticmethod
    def _utcnow_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _utcnow_plus_seconds_iso(seconds: float) -> str:
        return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
