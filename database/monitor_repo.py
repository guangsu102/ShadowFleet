from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from database.state_repo_helpers import utcnow_iso
from utils.logger import set_event_type

if TYPE_CHECKING:
    from services.runtime_service import RuntimeContext


@dataclass(frozen=True)
class MonitorCycleRecord:
    id: int
    correlation_id: str
    status: str
    candidate_count: int
    confirmed_count: int
    healed_count: int
    failed_count: int
    started_at: str
    finished_at: str | None
    error_message: str | None


class MonitorRepo:
    def __init__(self, runtime_context: RuntimeContext) -> None:
        sqlite_manager = runtime_context.sqlite_manager
        if sqlite_manager is None:
            raise ValueError("RuntimeContext.sqlite_manager is required for MonitorRepo")
        self._sqlite_manager = sqlite_manager
        self._logger = runtime_context.logger.getChild("database.monitor_repo")

    def create_cycle(self, correlation_id: str) -> int:
        with self._sqlite_manager.connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO fleet_monitor_cycles (
                    correlation_id,
                    status,
                    started_at
                )
                VALUES (?, 'running', ?)
                """,
                (correlation_id, utcnow_iso()),
            )
            cycle_id = int(cursor.lastrowid)
        set_event_type("sqlite_monitor_cycle_created")
        self._logger.info("Created monitor cycle id=%s", cycle_id)
        return cycle_id

    def finalize_cycle(
        self,
        *,
        cycle_id: int,
        status: str,
        candidate_count: int,
        confirmed_count: int,
        healed_count: int,
        failed_count: int,
        error_message: str | None = None,
    ) -> None:
        with self._sqlite_manager.connection() as connection:
            connection.execute(
                """
                UPDATE fleet_monitor_cycles
                SET status = ?,
                    candidate_count = ?,
                    confirmed_count = ?,
                    healed_count = ?,
                    failed_count = ?,
                    error_message = ?,
                    finished_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    candidate_count,
                    confirmed_count,
                    healed_count,
                    failed_count,
                    error_message,
                    utcnow_iso(),
                    cycle_id,
                ),
            )
        set_event_type("sqlite_monitor_cycle_finalized")
        self._logger.info("Finalized monitor cycle id=%s status=%s", cycle_id, status)

    def create_detection(
        self,
        *,
        cycle_id: int,
        xboard_node_id: int,
        detection_type: str,
        detection_status: str,
        reason: str | None,
        probe_provider: str | None,
        payload: dict[str, object] | None,
    ) -> int:
        with self._sqlite_manager.connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO fleet_monitor_detections (
                    cycle_id,
                    xboard_node_id,
                    detection_type,
                    detection_status,
                    reason,
                    probe_provider,
                    payload_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cycle_id,
                    xboard_node_id,
                    detection_type,
                    detection_status,
                    reason,
                    probe_provider,
                    json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
                    if payload is not None
                    else None,
                    utcnow_iso(),
                ),
            )
            detection_id = int(cursor.lastrowid)
        set_event_type("sqlite_monitor_detection_created")
        self._logger.info(
            "Created monitor detection id=%s xboard_node_id=%s status=%s",
            detection_id,
            xboard_node_id,
            detection_status,
        )
        return detection_id

    def get_latest_detection_for_node(self, xboard_node_id: int) -> dict[str, object] | None:
        with self._sqlite_manager.connection() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM fleet_monitor_detections
                WHERE xboard_node_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (xboard_node_id,),
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    def get_latest_cycle(self) -> MonitorCycleRecord | None:
        with self._sqlite_manager.connection() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM fleet_monitor_cycles
                ORDER BY started_at DESC, id DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        return MonitorCycleRecord(
            id=int(row["id"]),
            correlation_id=str(row["correlation_id"]),
            status=str(row["status"]),
            candidate_count=int(row["candidate_count"]),
            confirmed_count=int(row["confirmed_count"]),
            healed_count=int(row["healed_count"]),
            failed_count=int(row["failed_count"]),
            started_at=str(row["started_at"]),
            finished_at=row["finished_at"],
            error_message=row["error_message"],
        )

    def list_recent_cycles(self, limit: int = 50) -> list[MonitorCycleRecord]:
        with self._sqlite_manager.connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM fleet_monitor_cycles
                ORDER BY started_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            MonitorCycleRecord(
                id=int(row["id"]),
                correlation_id=str(row["correlation_id"]),
                status=str(row["status"]),
                candidate_count=int(row["candidate_count"]),
                confirmed_count=int(row["confirmed_count"]),
                healed_count=int(row["healed_count"]),
                failed_count=int(row["failed_count"]),
                started_at=str(row["started_at"]),
                finished_at=row["finished_at"],
                error_message=row["error_message"],
            )
            for row in rows
        ]

    def list_detections_by_cycle(self, cycle_id: int) -> list[dict[str, object]]:
        with self._sqlite_manager.connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM fleet_monitor_detections
                WHERE cycle_id = ?
                ORDER BY created_at DESC, id DESC
                """,
                (cycle_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_detections_by_node(self, xboard_node_id: int, limit: int = 50) -> list[dict[str, object]]:
        with self._sqlite_manager.connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM fleet_monitor_detections
                WHERE xboard_node_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (xboard_node_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]
