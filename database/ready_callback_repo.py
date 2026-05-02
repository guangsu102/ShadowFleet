from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import secrets
import sqlite3
import time
from typing import Literal, TYPE_CHECKING

from utils.logger import set_event_type

if TYPE_CHECKING:
    from services.runtime_service import RuntimeContext


JsonPrimitive = str | int | float | bool | None
JsonValue = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]
ReadyCallbackStatus = Literal["pending", "received", "completed"]
CALLBACK_TOKEN_BYTES = 24


class ReadyCallbackRepoError(RuntimeError):
    pass


class ReadyCallbackNotFoundError(ReadyCallbackRepoError):
    pass


@dataclass(frozen=True)
class ReadyCallbackCreateRequest:
    task_id: int
    xboard_node_id: int
    correlation_id: str


@dataclass(frozen=True)
class ReadyCallbackRecord:
    id: int
    task_id: int
    xboard_node_id: int
    correlation_id: str
    callback_token: str
    status: ReadyCallbackStatus
    payload: JsonValue | None
    created_at: str
    updated_at: str
    received_at: str | None
    completed_at: str | None


class ReadyCallbackRepo:
    def __init__(self, runtime_context: RuntimeContext) -> None:
        sqlite_manager = runtime_context.sqlite_manager
        if sqlite_manager is None:
            raise ValueError("RuntimeContext.sqlite_manager is required for ReadyCallbackRepo")

        self._runtime_context = runtime_context
        self._sqlite_manager = sqlite_manager
        self._logger = runtime_context.logger.getChild("database.ready_callback_repo")

    def create_callback(self, request: ReadyCallbackCreateRequest) -> ReadyCallbackRecord:
        if request.task_id <= 0:
            raise ValueError("task_id must be greater than 0")
        if request.xboard_node_id <= 0:
            raise ValueError("xboard_node_id must be greater than 0")
        if not request.correlation_id or not request.correlation_id.strip():
            raise ValueError("correlation_id must not be empty")

        timestamp = self._utcnow_iso()
        callback_token = secrets.token_urlsafe(CALLBACK_TOKEN_BYTES)
        with self._sqlite_manager.connection() as connection:
            connection.execute(
                "DELETE FROM fleet_ready_callbacks WHERE task_id = ?",
                (request.task_id,),
            )
            connection.execute(
                """
                INSERT INTO fleet_ready_callbacks (
                    task_id,
                    xboard_node_id,
                    correlation_id,
                    callback_token,
                    status,
                    payload_json,
                    created_at,
                    updated_at,
                    received_at,
                    completed_at
                )
                VALUES (?, ?, ?, ?, 'pending', NULL, ?, ?, NULL, NULL)
                """,
                (
                    request.task_id,
                    request.xboard_node_id,
                    request.correlation_id.strip(),
                    callback_token,
                    timestamp,
                    timestamp,
                ),
            )
            row = connection.execute(
                "SELECT * FROM fleet_ready_callbacks WHERE task_id = ?",
                (request.task_id,),
            ).fetchone()
        if row is None:
            raise ReadyCallbackRepoError("Failed to load created ready callback")

        callback_record = self._map_record(row)
        set_event_type("sqlite_ready_callback_created")
        self._logger.info(
            "Created ready callback id=%s task_id=%s xboard_node_id=%s",
            callback_record.id,
            callback_record.task_id,
            callback_record.xboard_node_id,
        )
        return callback_record

    def get_by_task_id(self, task_id: int) -> ReadyCallbackRecord:
        with self._sqlite_manager.connection() as connection:
            row = connection.execute(
                "SELECT * FROM fleet_ready_callbacks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        if row is None:
            raise ReadyCallbackNotFoundError(f"Ready callback not found for task_id={task_id}")
        return self._map_record(row)

    def get_by_token(self, callback_token: str) -> ReadyCallbackRecord:
        normalized_token = callback_token.strip()
        if not normalized_token:
            raise ValueError("callback_token must not be empty")

        with self._sqlite_manager.connection() as connection:
            row = connection.execute(
                "SELECT * FROM fleet_ready_callbacks WHERE callback_token = ?",
                (normalized_token,),
            ).fetchone()
        if row is None:
            raise ReadyCallbackNotFoundError("Ready callback token not found")
        return self._map_record(row)

    def mark_received(
        self,
        callback_token: str,
        payload: JsonValue | None,
    ) -> ReadyCallbackRecord:
        callback_record = self.get_by_token(callback_token)
        timestamp = self._utcnow_iso()
        with self._sqlite_manager.connection() as connection:
            connection.execute(
                """
                UPDATE fleet_ready_callbacks
                SET
                    status = 'received',
                    payload_json = ?,
                    updated_at = ?,
                    received_at = COALESCE(received_at, ?)
                WHERE id = ?
                """,
                (
                    self._to_json_text(payload),
                    timestamp,
                    timestamp,
                    callback_record.id,
                ),
            )
            row = connection.execute(
                "SELECT * FROM fleet_ready_callbacks WHERE id = ?",
                (callback_record.id,),
            ).fetchone()
        if row is None:
            raise ReadyCallbackRepoError("Failed to load received ready callback")

        updated_record = self._map_record(row)
        set_event_type("sqlite_ready_callback_received")
        self._logger.info(
            "Marked ready callback received id=%s task_id=%s",
            updated_record.id,
            updated_record.task_id,
        )
        return updated_record

    def mark_completed(self, task_id: int) -> ReadyCallbackRecord:
        callback_record = self.get_by_task_id(task_id)
        timestamp = self._utcnow_iso()
        with self._sqlite_manager.connection() as connection:
            connection.execute(
                """
                UPDATE fleet_ready_callbacks
                SET
                    status = 'completed',
                    updated_at = ?,
                    completed_at = ?,
                    received_at = COALESCE(received_at, ?)
                WHERE id = ?
                """,
                (
                    timestamp,
                    timestamp,
                    timestamp,
                    callback_record.id,
                ),
            )
            row = connection.execute(
                "SELECT * FROM fleet_ready_callbacks WHERE id = ?",
                (callback_record.id,),
            ).fetchone()
        if row is None:
            raise ReadyCallbackRepoError("Failed to load completed ready callback")

        updated_record = self._map_record(row)
        set_event_type("sqlite_ready_callback_completed")
        self._logger.info(
            "Marked ready callback completed id=%s task_id=%s",
            updated_record.id,
            updated_record.task_id,
        )
        return updated_record

    def wait_until_received(
        self,
        task_id: int,
        timeout_seconds: float,
        poll_interval_seconds: float,
    ) -> ReadyCallbackRecord:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than 0")
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be greater than 0")

        deadline = time.monotonic() + timeout_seconds
        while True:
            callback_record = self.get_by_task_id(task_id)
            if callback_record.status in {"received", "completed"}:
                return callback_record
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Timed out waiting for ready callback: task_id={task_id}"
                )
            time.sleep(poll_interval_seconds)

    def _map_record(self, row: sqlite3.Row) -> ReadyCallbackRecord:
        return ReadyCallbackRecord(
            id=int(row["id"]),
            task_id=int(row["task_id"]),
            xboard_node_id=int(row["xboard_node_id"]),
            correlation_id=str(row["correlation_id"]),
            callback_token=str(row["callback_token"]),
            status=row["status"],
            payload=self._from_json_text(row["payload_json"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            received_at=row["received_at"],
            completed_at=row["completed_at"],
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
