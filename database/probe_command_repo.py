"""Probe command repository — handles fleet_probe_commands table."""
from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

from database.probe_models import (
    JsonValue,
    ProbeCommandCreateRequest,
    ProbeCommandRecord,
    ProbeCommandStatus,
)
from database.probe_row_mapper import (
    ProbeRepoError,
    map_probe_command_record,
    to_json_text,
    utcnow_iso,
)
from utils.logger import set_event_type

if TYPE_CHECKING:
    from services.runtime_service import RuntimeContext

COMMAND_ID_TOKEN_BYTES = 12


class ProbeCommandNotFoundError(ProbeRepoError):
    pass


class ProbeCommandRepo:
    def __init__(self, runtime_context: RuntimeContext) -> None:
        sqlite_manager = runtime_context.sqlite_manager
        if sqlite_manager is None:
            raise ValueError("RuntimeContext.sqlite_manager is required for ProbeCommandRepo")
        self._sqlite_manager = sqlite_manager
        self._logger = runtime_context.logger.getChild("database.probe_command")

    def create_command(self, request: ProbeCommandCreateRequest) -> ProbeCommandRecord:
        timestamp = utcnow_iso()
        command_id = secrets.token_urlsafe(COMMAND_ID_TOKEN_BYTES)
        with self._sqlite_manager.connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO fleet_probe_commands (
                    command_id,
                    probe_id,
                    command_type,
                    status,
                    correlation_id,
                    payload_json,
                    result_json,
                    last_error,
                    attempt_count,
                    max_attempts,
                    leased_by,
                    leased_at,
                    next_run_at,
                    created_at,
                    updated_at,
                    finished_at
                )
                VALUES (?, ?, ?, 'queued', ?, ?, NULL, NULL, 0, ?, NULL, NULL, ?, ?, ?, NULL)
                """,
                (
                    command_id,
                    request.probe_id.strip(),
                    request.command_type,
                    request.correlation_id.strip(),
                    to_json_text(request.payload),
                    request.max_attempts,
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
            row_id = int(cursor.lastrowid)
            row = connection.execute(
                "SELECT * FROM fleet_probe_commands WHERE id = ?",
                (row_id,),
            ).fetchone()
        if row is None:
            raise ProbeRepoError("Failed to load created probe command")
        set_event_type("sqlite_probe_command_created")
        self._logger.info(
            "Created probe command id=%s type=%s probe_id=%s",
            row_id,
            request.command_type,
            request.probe_id,
        )
        return map_probe_command_record(row)

    def claim_commands(
        self,
        *,
        probe_id: str,
        lease_owner: str,
        limit: int,
    ) -> list[ProbeCommandRecord]:
        if limit <= 0:
            raise ValueError("limit must be greater than 0")
        timestamp = utcnow_iso()
        claimed_records: list[ProbeCommandRecord] = []
        with self._sqlite_manager.connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM fleet_probe_commands
                WHERE probe_id = ?
                  AND status = 'queued'
                  AND next_run_at <= ?
                ORDER BY next_run_at ASC, created_at ASC, id ASC
                LIMIT ?
                """,
                (probe_id.strip(), timestamp, limit),
            ).fetchall()
            for row in rows:
                cursor = connection.execute(
                    """
                    UPDATE fleet_probe_commands
                    SET status = 'leased',
                        attempt_count = attempt_count + 1,
                        leased_by = ?,
                        leased_at = ?,
                        updated_at = ?,
                        finished_at = NULL
                    WHERE id = ? AND status = 'queued'
                    """,
                    (lease_owner.strip(), timestamp, timestamp, int(row["id"])),
                )
                if cursor.rowcount == 0:
                    continue
                claimed_row = connection.execute(
                    "SELECT * FROM fleet_probe_commands WHERE id = ?",
                    (int(row["id"]),),
                ).fetchone()
                if claimed_row is not None:
                    claimed_records.append(map_probe_command_record(claimed_row))
        return claimed_records

    def get_command_by_command_id(self, command_id: str) -> ProbeCommandRecord:
        with self._sqlite_manager.connection() as connection:
            row = connection.execute(
                "SELECT * FROM fleet_probe_commands WHERE command_id = ?",
                (command_id.strip(),),
            ).fetchone()
        if row is None:
            raise ProbeCommandNotFoundError(
                f"Probe command not found: command_id={command_id.strip()}"
            )
        return map_probe_command_record(row)

    def update_command_terminal_state(
        self,
        *,
        command_id: str,
        status: ProbeCommandStatus,
        result: dict[str, JsonValue] | None,
        last_error: str | None,
    ) -> ProbeCommandRecord:
        timestamp = utcnow_iso()
        normalized_command_id = command_id.strip()
        with self._sqlite_manager.connection() as connection:
            row = connection.execute(
                "SELECT id FROM fleet_probe_commands WHERE command_id = ?",
                (normalized_command_id,),
            ).fetchone()
            if row is None:
                raise ProbeCommandNotFoundError(
                    f"Probe command not found: command_id={normalized_command_id}"
                )
            cursor = connection.execute(
                """
                UPDATE fleet_probe_commands
                SET status = ?,
                    result_json = ?,
                    last_error = ?,
                    leased_by = NULL,
                    leased_at = NULL,
                    updated_at = ?,
                    finished_at = ?
                WHERE command_id = ?
                """,
                (
                    status,
                    to_json_text(result),
                    last_error,
                    timestamp,
                    timestamp,
                    normalized_command_id,
                ),
            )
            if cursor.rowcount == 0:
                raise ProbeCommandNotFoundError(
                    f"Probe command not found: command_id={normalized_command_id}"
                )
            updated_row = connection.execute(
                "SELECT * FROM fleet_probe_commands WHERE id = ?",
                (int(row["id"]),),
            ).fetchone()
        if updated_row is None:
            raise ProbeRepoError("Failed to load updated probe command")
        set_event_type("sqlite_probe_command_terminal")
        self._logger.info(
            "Updated probe command command_id=%s status=%s",
            normalized_command_id,
            status,
        )
        return map_probe_command_record(updated_row)

    def mark_command_succeeded(
        self,
        *,
        command_id: str,
        result: dict[str, JsonValue] | None,
    ) -> ProbeCommandRecord:
        return self.update_command_terminal_state(
            command_id=command_id,
            status="succeeded",
            result=result,
            last_error=None,
        )

    def mark_command_failed(
        self,
        *,
        command_id: str,
        last_error: str,
    ) -> ProbeCommandRecord:
        return self.update_command_terminal_state(
            command_id=command_id,
            status="failed",
            result=None,
            last_error=last_error.strip(),
        )

    def list_recent_commands(self, limit: int = 20) -> list[ProbeCommandRecord]:
        with self._sqlite_manager.connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM fleet_probe_commands
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [map_probe_command_record(row) for row in rows]
