"""Shared row-mapping helpers for fleet_probes SQLite tables."""
from __future__ import annotations

import json
from datetime import datetime, timezone
import sqlite3

from database.probe_models import (
    JsonValue,
    ProbeCommandRecord,
    ProbeConfigRecord,
    ProbeMeasurementRecord,
    ProbeMeasurementResultRecord,
    ProbeRecord,
)


class ProbeRepoError(RuntimeError):
    pass


# ----------------------------------------------------------------------------------------------------------------------
# JSON utilities
# ----------------------------------------------------------------------------------------------------------------------

def to_json_text(value: JsonValue | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def from_json_text(value: str | None) -> JsonValue | None:
    if value is None:
        return None
    return json.loads(value)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ----------------------------------------------------------------------------------------------------------------------
# ProbeRecord mapper
# ----------------------------------------------------------------------------------------------------------------------

def map_probe_record(row: sqlite3.Row) -> ProbeRecord:
    tags = from_json_text(row["tags_json"])
    capabilities = from_json_text(row["capabilities_json"])
    if not isinstance(tags, list):
        raise ProbeRepoError("Probe tags_json must be a JSON array")
    if not isinstance(capabilities, dict):
        raise ProbeRepoError("Probe capabilities_json must be a JSON object")
    return ProbeRecord(
        id=int(row["id"]),
        probe_id=str(row["probe_id"]),
        probe_name=str(row["probe_name"]),
        status=row["status"],
        auth_token=str(row["auth_token"]),
        machine_fingerprint=str(row["machine_fingerprint"]),
        public_ip=row["public_ip"],
        region=row["region"],
        isp=row["isp"],
        tags=[str(item) for item in tags],
        capabilities=capabilities,
        config_version=int(row["config_version"]),
        last_seen_at=row["last_seen_at"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


# ----------------------------------------------------------------------------------------------------------------------
# ProbeConfigRecord mapper
# ----------------------------------------------------------------------------------------------------------------------

def map_probe_config_record(row: sqlite3.Row) -> ProbeConfigRecord:
    config = from_json_text(row["config_json"])
    if not isinstance(config, dict):
        raise ProbeRepoError("Probe config_json must be a JSON object")
    return ProbeConfigRecord(
        id=int(row["id"]),
        probe_id=str(row["probe_id"]),
        config_version=int(row["config_version"]),
        config=config,
        created_at=str(row["created_at"]),
    )


# ----------------------------------------------------------------------------------------------------------------------
# ProbeCommandRecord mapper
# ----------------------------------------------------------------------------------------------------------------------

def map_probe_command_record(row: sqlite3.Row) -> ProbeCommandRecord:
    payload = from_json_text(row["payload_json"])
    result = from_json_text(row["result_json"])
    if not isinstance(payload, dict):
        raise ProbeRepoError("Probe command payload_json must be a JSON object")
    if result is not None and not isinstance(result, dict):
        raise ProbeRepoError("Probe command result_json must be a JSON object")
    return ProbeCommandRecord(
        id=int(row["id"]),
        command_id=str(row["command_id"]),
        probe_id=str(row["probe_id"]),
        command_type=row["command_type"],
        status=row["status"],
        correlation_id=str(row["correlation_id"]),
        payload=payload,
        result=result,
        last_error=row["last_error"],
        attempt_count=int(row["attempt_count"]),
        max_attempts=int(row["max_attempts"]),
        leased_by=row["leased_by"],
        leased_at=row["leased_at"],
        next_run_at=str(row["next_run_at"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        finished_at=row["finished_at"],
    )


# ----------------------------------------------------------------------------------------------------------------------
# ProbeMeasurementRecord mapper
# ----------------------------------------------------------------------------------------------------------------------

def map_probe_measurement_record(row: sqlite3.Row) -> ProbeMeasurementRecord:
    control_plane_result = from_json_text(row["control_plane_result_json"])
    if control_plane_result is not None and not isinstance(control_plane_result, dict):
        raise ProbeRepoError("Probe measurement control_plane_result_json must be a JSON object")
    return ProbeMeasurementRecord(
        id=int(row["id"]),
        measurement_id=str(row["measurement_id"]),
        xboard_node_id=int(row["xboard_node_id"]),
        correlation_id=str(row["correlation_id"]),
        final_status=row["final_status"],
        reason=row["reason"],
        control_plane_result=control_plane_result,
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        finished_at=row["finished_at"],
    )


# ----------------------------------------------------------------------------------------------------------------------
# ProbeMeasurementResultRecord mapper
# ----------------------------------------------------------------------------------------------------------------------

def map_probe_measurement_result_record(row: sqlite3.Row) -> ProbeMeasurementResultRecord:
    result = from_json_text(row["result_json"])
    if not isinstance(result, dict):
        raise ProbeRepoError("Probe measurement result_json must be a JSON object")
    return ProbeMeasurementResultRecord(
        id=int(row["id"]),
        measurement_id=str(row["measurement_id"]),
        probe_id=str(row["probe_id"]),
        probe_status=str(row["probe_status"]),
        failure_stage=row["failure_stage"],
        resolved_ip=row["resolved_ip"],
        latency_ms=int(row["latency_ms"]) if row["latency_ms"] is not None else None,
        result=result,
        created_at=str(row["created_at"]),
    )
