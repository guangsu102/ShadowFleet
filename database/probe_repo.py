"""Probe repository — handles fleet_probes and fleet_probe_configs tables."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from database.probe_models import (
    JsonValue,
    ProbeConfigRecord,
    ProbeConfigUpsertRequest,
    ProbeCreateRequest,
    ProbeHeartbeatRecord,
    ProbeRecord,
)
from database.probe_row_mapper import (
    ProbeRepoError,
    map_probe_config_record,
    map_probe_record,
    to_json_text,
    utcnow_iso,
)
from utils.logger import set_event_type

if TYPE_CHECKING:
    from services.runtime_service import RuntimeContext


class ProbeNotFoundError(ProbeRepoError):
    pass


class ProbeRepo:
    def __init__(self, runtime_context: RuntimeContext) -> None:
        sqlite_manager = runtime_context.sqlite_manager
        if sqlite_manager is None:
            raise ValueError("RuntimeContext.sqlite_manager is required for ProbeRepo")
        self._sqlite_manager = sqlite_manager
        self._logger = runtime_context.logger.getChild("database.probe")

    def create_probe(self, request: ProbeCreateRequest) -> ProbeRecord:
        timestamp = utcnow_iso()
        with self._sqlite_manager.connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO fleet_probes (
                    probe_id,
                    probe_name,
                    status,
                    auth_token,
                    machine_fingerprint,
                    public_ip,
                    region,
                    isp,
                    tags_json,
                    capabilities_json,
                    config_version,
                    last_seen_at,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    request.probe_id.strip(),
                    request.probe_name.strip(),
                    request.status,
                    request.auth_token,
                    request.machine_fingerprint.strip(),
                    request.public_ip,
                    request.region,
                    request.isp,
                    to_json_text(request.tags or []),
                    to_json_text(request.capabilities or {}),
                    request.config_version,
                    timestamp,
                    timestamp,
                ),
            )
            row_id = int(cursor.lastrowid)
            row = connection.execute(
                "SELECT * FROM fleet_probes WHERE id = ?",
                (row_id,),
            ).fetchone()
        if row is None:
            raise ProbeRepoError("Failed to load created probe")
        probe_record = map_probe_record(row)
        set_event_type("sqlite_probe_created")
        self._logger.info("Created probe id=%s probe_id=%s", probe_record.id, probe_record.probe_id)
        return probe_record

    def get_probe_by_probe_id(self, probe_id: str) -> ProbeRecord:
        normalized_probe_id = probe_id.strip()
        if not normalized_probe_id:
            raise ValueError("probe_id must not be empty")
        with self._sqlite_manager.connection() as connection:
            row = connection.execute(
                "SELECT * FROM fleet_probes WHERE probe_id = ?",
                (normalized_probe_id,),
            ).fetchone()
        if row is None:
            raise ProbeNotFoundError(f"Probe not found: probe_id={normalized_probe_id}")
        return map_probe_record(row)

    def get_probe_by_auth_token(self, auth_token: str) -> ProbeRecord:
        normalized_token = auth_token.strip()
        if not normalized_token:
            raise ValueError("auth_token must not be empty")
        with self._sqlite_manager.connection() as connection:
            row = connection.execute(
                "SELECT * FROM fleet_probes WHERE auth_token = ?",
                (normalized_token,),
            ).fetchone()
        if row is None:
            raise ProbeNotFoundError("Probe auth token not found")
        return map_probe_record(row)

    def get_probe_by_machine_fingerprint(self, machine_fingerprint: str) -> ProbeRecord | None:
        normalized_fingerprint = machine_fingerprint.strip()
        if not normalized_fingerprint:
            raise ValueError("machine_fingerprint must not be empty")
        with self._sqlite_manager.connection() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM fleet_probes
                WHERE machine_fingerprint = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (normalized_fingerprint,),
            ).fetchone()
        if row is None:
            return None
        return map_probe_record(row)

    def list_probes(self, *, include_inactive: bool = True) -> list[ProbeRecord]:
        sql = "SELECT * FROM fleet_probes"
        parameters: tuple[object, ...] = ()
        if not include_inactive:
            sql += " WHERE status IN ('active', 'draining')"
        sql += " ORDER BY updated_at DESC, id DESC"
        with self._sqlite_manager.connection() as connection:
            rows = connection.execute(sql, parameters).fetchall()
        return [map_probe_record(row) for row in rows]

    def list_active_probes(self) -> list[ProbeRecord]:
        return self.list_probes(include_inactive=False)

    def update_probe_status(self, probe_id: str, status: str) -> ProbeRecord:
        timestamp = utcnow_iso()
        normalized_probe_id = probe_id.strip()
        with self._sqlite_manager.connection() as connection:
            row = connection.execute(
                "SELECT * FROM fleet_probes WHERE probe_id = ?",
                (normalized_probe_id,),
            ).fetchone()
            if row is None:
                raise ProbeNotFoundError(f"Probe not found: probe_id={normalized_probe_id}")
            cursor = connection.execute(
                """
                UPDATE fleet_probes
                SET status = ?, updated_at = ?
                WHERE probe_id = ?
                """,
                (status, timestamp, normalized_probe_id),
            )
            if cursor.rowcount == 0:
                raise ProbeNotFoundError(f"Probe not found: probe_id={normalized_probe_id}")
            updated_row = connection.execute(
                "SELECT * FROM fleet_probes WHERE id = ?",
                (int(row["id"]),),
            ).fetchone()
        if updated_row is None:
            raise ProbeRepoError("Failed to load updated probe status")
        return map_probe_record(updated_row)

    def record_heartbeat(
        self,
        *,
        probe_id: str,
        public_ip: str | None,
        agent_version: str | None,
        capabilities: dict[str, JsonValue] | None,
        runtime_metrics: dict[str, JsonValue] | None,
    ) -> ProbeHeartbeatRecord:
        timestamp = utcnow_iso()
        with self._sqlite_manager.connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO fleet_probe_heartbeats (
                    probe_id,
                    public_ip,
                    agent_version,
                    runtime_metrics_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    probe_id.strip(),
                    public_ip,
                    agent_version,
                    to_json_text(runtime_metrics),
                    timestamp,
                ),
            )
            heartbeat_id = int(cursor.lastrowid)
            updates: dict[str, object] = {
                "last_seen_at": timestamp,
                "updated_at": timestamp,
            }
            probe_row = connection.execute(
                "SELECT status FROM fleet_probes WHERE probe_id = ?",
                (probe_id.strip(),),
            ).fetchone()
            if probe_row is None:
                raise ProbeNotFoundError(f"Probe not found: probe_id={probe_id.strip()}")
            if str(probe_row["status"]) == "offline":
                updates["status"] = "active"
            if public_ip is not None:
                updates["public_ip"] = public_ip
            if capabilities is not None:
                updates["capabilities_json"] = to_json_text(capabilities)
            assignments = ", ".join(f"{column} = ?" for column in updates)
            parameters = tuple(updates.values()) + (probe_id.strip(),)
            updated = connection.execute(
                f"UPDATE fleet_probes SET {assignments} WHERE probe_id = ?",
                parameters,
            )
            if updated.rowcount == 0:
                raise ProbeNotFoundError(f"Probe not found: probe_id={probe_id.strip()}")
        set_event_type("sqlite_probe_heartbeat_recorded")
        self._logger.info("Recorded probe heartbeat probe_id=%s", probe_id.strip())
        return ProbeHeartbeatRecord(
            id=heartbeat_id,
            probe_id=probe_id.strip(),
            public_ip=public_ip,
            agent_version=agent_version,
            runtime_metrics=runtime_metrics,
            created_at=timestamp,
        )

    def mark_stale_probes_offline(self, timeout_seconds: float) -> int:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than 0")
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)).isoformat()
        timestamp = utcnow_iso()
        with self._sqlite_manager.connection() as connection:
            cursor = connection.execute(
                """
                UPDATE fleet_probes
                SET status = 'offline',
                    updated_at = ?
                WHERE status IN ('active', 'draining')
                  AND last_seen_at IS NOT NULL
                  AND last_seen_at < ?
                """,
                (timestamp, cutoff),
            )
            updated_count = int(cursor.rowcount if cursor.rowcount != -1 else 0)
        if updated_count > 0:
            set_event_type("sqlite_probe_marked_offline")
            self._logger.warning("Marked stale probes offline count=%s", updated_count)
        return updated_count

    def upsert_probe_config(self, request: ProbeConfigUpsertRequest) -> ProbeConfigRecord:
        timestamp = utcnow_iso()
        with self._sqlite_manager.connection() as connection:
            connection.execute(
                """
                INSERT INTO fleet_probe_configs (
                    probe_id,
                    config_version,
                    config_json,
                    created_at
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(probe_id, config_version) DO UPDATE SET
                    config_json = excluded.config_json
                """,
                (
                    request.probe_id.strip(),
                    request.config_version,
                    to_json_text(request.config),
                    timestamp,
                ),
            )
            connection.execute(
                """
                UPDATE fleet_probes
                SET config_version = ?, updated_at = ?
                WHERE probe_id = ?
                """,
                (request.config_version, timestamp, request.probe_id.strip()),
            )
            row = connection.execute(
                """
                SELECT *
                FROM fleet_probe_configs
                WHERE probe_id = ? AND config_version = ?
                """,
                (request.probe_id.strip(), request.config_version),
            ).fetchone()
        if row is None:
            raise ProbeRepoError("Failed to load upserted probe config")
        set_event_type("sqlite_probe_config_upserted")
        self._logger.info(
            "Upserted probe config probe_id=%s version=%s",
            request.probe_id.strip(),
            request.config_version,
        )
        return map_probe_config_record(row)

    def get_latest_probe_config(self, probe_id: str) -> ProbeConfigRecord | None:
        with self._sqlite_manager.connection() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM fleet_probe_configs
                WHERE probe_id = ?
                ORDER BY config_version DESC, id DESC
                LIMIT 1
                """,
                (probe_id.strip(),),
            ).fetchone()
        if row is None:
            return None
        return map_probe_config_record(row)

    def delete_probe(self, probe_id: str) -> None:
        normalized_probe_id = probe_id.strip()
        if not normalized_probe_id:
            raise ValueError("probe_id must not be empty")
        with self._sqlite_manager.connection() as connection:
            row = connection.execute(
                "SELECT id FROM fleet_probes WHERE probe_id = ?",
                (normalized_probe_id,),
            ).fetchone()
            if row is None:
                raise ProbeNotFoundError(f"Probe not found: probe_id={normalized_probe_id}")
            connection.execute(
                "DELETE FROM fleet_probes WHERE probe_id = ?",
                (normalized_probe_id,),
            )
        set_event_type("sqlite_probe_deleted")
        self._logger.info("Deleted probe probe_id=%s", normalized_probe_id)
