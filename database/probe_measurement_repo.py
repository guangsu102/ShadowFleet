"""Probe measurement repository — handles fleet_probe_measurements and fleet_probe_measurement_results tables."""
from __future__ import annotations

from typing import TYPE_CHECKING

from database.probe_models import (
    JsonValue,
    ProbeMeasurementCreateRequest,
    ProbeMeasurementRecord,
    ProbeMeasurementResultCreateRequest,
    ProbeMeasurementResultRecord,
)
from database.probe_row_mapper import (
    ProbeRepoError,
    map_probe_measurement_record,
    map_probe_measurement_result_record,
    to_json_text,
    utcnow_iso,
)
from utils.logger import set_event_type

if TYPE_CHECKING:
    from services.runtime_service import RuntimeContext


class ProbeMeasurementNotFoundError(ProbeRepoError):
    pass


class ProbeMeasurementRepo:
    def __init__(self, runtime_context: RuntimeContext) -> None:
        sqlite_manager = runtime_context.sqlite_manager
        if sqlite_manager is None:
            raise ValueError("RuntimeContext.sqlite_manager is required for ProbeMeasurementRepo")
        self._sqlite_manager = sqlite_manager
        self._logger = runtime_context.logger.getChild("database.probe_measurement")

    def create_measurement(self, request: ProbeMeasurementCreateRequest) -> ProbeMeasurementRecord:
        timestamp = utcnow_iso()
        with self._sqlite_manager.connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO fleet_probe_measurements (
                    measurement_id,
                    xboard_node_id,
                    correlation_id,
                    control_plane_result_json,
                    final_status,
                    reason,
                    created_at,
                    updated_at,
                    finished_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    request.measurement_id,
                    request.xboard_node_id,
                    request.correlation_id,
                    to_json_text(request.control_plane_result),
                    request.final_status,
                    request.reason,
                    timestamp,
                    timestamp,
                ),
            )
            row_id = int(cursor.lastrowid)
            row = connection.execute(
                "SELECT * FROM fleet_probe_measurements WHERE id = ?",
                (row_id,),
            ).fetchone()
        if row is None:
            raise ProbeRepoError("Failed to load created probe measurement")
        set_event_type("sqlite_probe_measurement_created")
        self._logger.info(
            "Created probe measurement id=%s measurement_id=%s xboard_node_id=%s",
            row_id,
            request.measurement_id,
            request.xboard_node_id,
        )
        return map_probe_measurement_record(row)

    def get_measurement_by_measurement_id(self, measurement_id: str) -> ProbeMeasurementRecord:
        with self._sqlite_manager.connection() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM fleet_probe_measurements
                WHERE measurement_id = ?
                """,
                (measurement_id.strip(),),
            ).fetchone()
        if row is None:
            raise ProbeMeasurementNotFoundError(
                f"Probe measurement not found: measurement_id={measurement_id.strip()}"
            )
        return map_probe_measurement_record(row)

    def finalize_measurement(
        self,
        *,
        measurement_id: str,
        final_status: str,
        reason: str | None,
        control_plane_result: dict[str, JsonValue] | None = None,
    ) -> ProbeMeasurementRecord:
        timestamp = utcnow_iso()
        normalized_measurement_id = measurement_id.strip()
        with self._sqlite_manager.connection() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM fleet_probe_measurements
                WHERE measurement_id = ?
                """,
                (normalized_measurement_id,),
            ).fetchone()
            if row is None:
                raise ProbeMeasurementNotFoundError(
                    f"Probe measurement not found: measurement_id={normalized_measurement_id}"
                )
            cursor = connection.execute(
                """
                UPDATE fleet_probe_measurements
                SET final_status = ?,
                    reason = ?,
                    control_plane_result_json = COALESCE(?, control_plane_result_json),
                    updated_at = ?,
                    finished_at = ?
                WHERE measurement_id = ?
                """,
                (
                    final_status,
                    reason,
                    to_json_text(control_plane_result),
                    timestamp,
                    timestamp,
                    normalized_measurement_id,
                ),
            )
            if cursor.rowcount == 0:
                raise ProbeMeasurementNotFoundError(
                    f"Probe measurement not found: measurement_id={normalized_measurement_id}"
                )
            updated_row = connection.execute(
                "SELECT * FROM fleet_probe_measurements WHERE id = ?",
                (int(row["id"]),),
            ).fetchone()
        if updated_row is None:
            raise ProbeRepoError("Failed to load finalized measurement")
        set_event_type("sqlite_probe_measurement_finalized")
        self._logger.info(
            "Finalized probe measurement measurement_id=%s status=%s",
            normalized_measurement_id,
            final_status,
        )
        return map_probe_measurement_record(updated_row)

    def create_measurement_result(
        self,
        request: ProbeMeasurementResultCreateRequest,
    ) -> ProbeMeasurementResultRecord:
        timestamp = utcnow_iso()
        with self._sqlite_manager.connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO fleet_probe_measurement_results (
                    measurement_id,
                    probe_id,
                    probe_status,
                    failure_stage,
                    resolved_ip,
                    latency_ms,
                    result_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request.measurement_id.strip(),
                    request.probe_id.strip(),
                    request.probe_status.strip(),
                    request.failure_stage,
                    request.resolved_ip,
                    request.latency_ms,
                    to_json_text(request.result),
                    timestamp,
                ),
            )
            row_id = int(cursor.lastrowid)
            row = connection.execute(
                "SELECT * FROM fleet_probe_measurement_results WHERE id = ?",
                (row_id,),
            ).fetchone()
        if row is None:
            raise ProbeRepoError("Failed to load created measurement result")
        set_event_type("sqlite_probe_measurement_result_created")
        self._logger.info(
            "Created probe measurement result id=%s measurement_id=%s probe_id=%s",
            row_id,
            request.measurement_id,
            request.probe_id,
        )
        return map_probe_measurement_result_record(row)

    def list_measurement_results(self, measurement_id: str) -> list[ProbeMeasurementResultRecord]:
        with self._sqlite_manager.connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM fleet_probe_measurement_results
                WHERE measurement_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (measurement_id.strip(),),
            ).fetchall()
        return [map_probe_measurement_result_record(row) for row in rows]

    def list_recent_measurements(self, limit: int = 20) -> list[ProbeMeasurementRecord]:
        with self._sqlite_manager.connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM fleet_probe_measurements
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [map_probe_measurement_record(row) for row in rows]

    def list_recent_measurements_for_node(
        self,
        xboard_node_id: int,
        limit: int = 10,
    ) -> list[ProbeMeasurementRecord]:
        with self._sqlite_manager.connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM fleet_probe_measurements
                WHERE xboard_node_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (xboard_node_id, limit),
            ).fetchall()
        return [map_probe_measurement_record(row) for row in rows]
