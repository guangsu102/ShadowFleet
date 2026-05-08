from __future__ import annotations

from datetime import datetime, timezone
import json
import sqlite3

from database.state_models import FleetNodeCreateRequest, FleetNodeRecord, JsonValue


def validate_create_request(request: FleetNodeCreateRequest) -> None:
    if request.xboard_node_id <= 0:
        raise ValueError("xboard_node_id must be greater than 0")
    if not request.node_name or not request.node_name.strip():
        raise ValueError("node_name must not be empty")
    if not request.node_type or not request.node_type.strip():
        raise ValueError("node_type must not be empty")


def map_fleet_node_record(row: sqlite3.Row) -> FleetNodeRecord:
    return FleetNodeRecord(
        id=int(row["id"]),
        xboard_node_id=int(row["xboard_node_id"]),
        node_name=str(row["node_name"]),
        node_type=str(row["node_type"]),
        status=row["status"],
        status_reason=row["status_reason"],
        aws_account_id=row["aws_account_id"],
        aws_region=row["aws_region"],
        aws_instance_id=row["aws_instance_id"],
        aws_subnet_id=row["aws_subnet_id"],
        aws_security_group_id=row["aws_security_group_id"],
        cloudflare_record_id=row["cloudflare_record_id"],
        domain_name=row["domain_name"],
        ipv4_address=row["ipv4_address"],
        ipv6_address=row["ipv6_address"],
        last_known_host=row["last_known_host"],
        last_error=row["last_error"],
        is_deleted=bool(row["is_deleted"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        online_at=row["online_at"],
        offline_at=row["offline_at"],
        deleted_at=row["deleted_at"],
        last_healed_at=row["last_healed_at"],
        xboard_status=row["xboard_status"],
        xboard_show=row["xboard_show"],
        xboard_updated_at=row["xboard_updated_at"],
    )


def to_json_text(value: JsonValue | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utcnow_iso() -> str:
    return utcnow().isoformat()
