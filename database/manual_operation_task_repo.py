from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from typing import Literal, TYPE_CHECKING

from services.manual_operation_models import ManualOperationTaskRecord
from utils.logger import set_event_type

if TYPE_CHECKING:
    from services.runtime_service import RuntimeContext


JsonPrimitive = str | int | float | bool | None
JsonValue = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]
ManualOperationTaskType = Literal[
    "force_heal",
    "decommission_node",
    "reprobe_node",
    "mark_manual_review",
]
ManualOperationTaskStatus = Literal["queued", "running", "succeeded", "failed"]


class ManualOperationTaskRepoError(RuntimeError):
    pass


class ManualOperationTaskNotFoundError(ManualOperationTaskRepoError):
    pass


@dataclass(frozen=True)
class ManualOperationTaskCreateRequest:
    correlation_id: str
    task_type: ManualOperationTaskType
    xboard_node_id: int
    request_payload: dict[str, JsonValue]
    operator_name: str | None = None
    max_attempts: int = 1


class ManualOperationTaskRepo:
    def __init__(self, runtime_context: RuntimeContext) -> None:
        sqlite_manager = runtime_context.sqlite_manager
        if sqlite_manager is None:
            raise ValueError("RuntimeContext.sqlite_manager is required for ManualOperationTaskRepo")
        self._sqlite_manager = sqlite_manager
        self._logger = runtime_context.logger.getChild("database.manual_operation_task_repo")

    def create_task(self, request: ManualOperationTaskCreateRequest) -> int:
        timestamp = self._utcnow_iso()
        with self._sqlite_manager.connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO fleet_manual_operation_tasks (
                    task_type,
                    status,
                    correlation_id,
                    operator_name,
                    xboard_node_id,
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
                VALUES (?, 'queued', ?, ?, ?, ?, NULL, NULL, 0, ?, NULL, NULL, ?, ?, ?, NULL, NULL)
                """,
                (
                    request.task_type,
                    request.correlation_id,
                    request.operator_name,
                    request.xboard_node_id,
                    self._to_json_text(request.request_payload),
                    request.max_attempts,
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
            task_id = int(cursor.lastrowid)
        set_event_type("sqlite_manual_task_created")
        self._logger.info("Created manual operation task id=%s type=%s", task_id, request.task_type)
        return task_id

    def list_recent_tasks(self, limit: int = 20) -> list[ManualOperationTaskRecord]:
        with self._sqlite_manager.connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM fleet_manual_operation_tasks
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._map_task_record(row) for row in rows]

    def get_task_by_id(self, task_id: int) -> ManualOperationTaskRecord:
        with self._sqlite_manager.connection() as connection:
            row = connection.execute(
                "SELECT * FROM fleet_manual_operation_tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
        if row is None:
            raise ManualOperationTaskNotFoundError(
                f"Manual operation task not found: task_id={task_id}"
            )
        return self._map_task_record(row)

    def has_pending_task(
        self,
        *,
        xboard_node_id: int,
        task_type: ManualOperationTaskType,
    ) -> bool:
        with self._sqlite_manager.connection() as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM fleet_manual_operation_tasks
                WHERE xboard_node_id = ?
                  AND task_type = ?
                  AND status IN ('queued', 'running')
                LIMIT 1
                """,
                (xboard_node_id, task_type),
            ).fetchone()
        return row is not None

    def claim_next_task(self, worker_id: str) -> ManualOperationTaskRecord | None:
        timestamp = self._utcnow_iso()
        with self._sqlite_manager.connection() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM fleet_manual_operation_tasks
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
                UPDATE fleet_manual_operation_tasks
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
                (worker_id.strip(), timestamp, timestamp, timestamp, int(row["id"])),
            )
            if cursor.rowcount == 0:
                return None
            claimed_row = connection.execute(
                "SELECT * FROM fleet_manual_operation_tasks WHERE id = ?",
                (int(row["id"]),),
            ).fetchone()
        if claimed_row is None:
            raise ManualOperationTaskRepoError("Failed to load claimed manual operation task")
        return self._map_task_record(claimed_row)

    def mark_task_succeeded(self, task_id: int, result_payload: dict[str, JsonValue] | None) -> None:
        self._update_terminal_state(task_id, "succeeded", result_payload, None)
        set_event_type("sqlite_manual_task_succeeded")
        self._logger.info("Manual operation task succeeded id=%s", task_id)

    def mark_task_failed(self, task_id: int, error_message: str) -> None:
        self._update_terminal_state(task_id, "failed", None, error_message.strip())
        set_event_type("sqlite_manual_task_failed")
        self._logger.info("Manual operation task failed id=%s", task_id)

    def mark_task_for_retry(
        self,
        task_id: int,
        error_message: str,
        retry_after_seconds: float,
    ) -> None:
        timestamp = self._utcnow_iso()
        next_run_at = self._utcnow_plus_seconds_iso(retry_after_seconds)
        with self._sqlite_manager.connection() as connection:
            cursor = connection.execute(
                """
                UPDATE fleet_manual_operation_tasks
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
                (error_message.strip(), next_run_at, timestamp, task_id),
            )
            if cursor.rowcount == 0:
                raise ManualOperationTaskNotFoundError(
                    f"Manual operation task not found for retry: task_id={task_id}"
                )

    def _update_terminal_state(
        self,
        task_id: int,
        status: ManualOperationTaskStatus,
        result_payload: dict[str, JsonValue] | None,
        last_error: str | None,
    ) -> None:
        timestamp = self._utcnow_iso()
        with self._sqlite_manager.connection() as connection:
            cursor = connection.execute(
                """
                UPDATE fleet_manual_operation_tasks
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
                raise ManualOperationTaskNotFoundError(
                    f"Manual operation task not found: task_id={task_id}"
                )

    def _map_task_record(self, row: object) -> ManualOperationTaskRecord:
        if not hasattr(row, "__getitem__"):
            raise ManualOperationTaskRepoError("Unexpected row type for manual task mapping")
        request_payload = self._from_json_text(row["request_payload_json"])
        result_payload = self._from_json_text(row["result_payload_json"])
        if not isinstance(request_payload, dict):
            raise ManualOperationTaskRepoError("Manual task request payload must be a JSON object")
        if result_payload is not None and not isinstance(result_payload, dict):
            raise ManualOperationTaskRepoError("Manual task result payload must be a JSON object")
        return ManualOperationTaskRecord(
            id=int(row["id"]),
            task_type=row["task_type"],
            status=row["status"],
            correlation_id=str(row["correlation_id"]),
            operator_name=row["operator_name"],
            xboard_node_id=int(row["xboard_node_id"]),
            request_payload=request_payload,
            result_payload=result_payload,
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
