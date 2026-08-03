from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


FleetNodeStatus = Literal[
    "provisioning",
    "online",
    "offline",
    "healing",
    "deleting",
    "deleted",
    "failed",
]

JsonPrimitive = str | int | float | bool | None
JsonValue = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]


class StateRepoError(RuntimeError):
    pass


class FleetNodeNotFoundError(StateRepoError):
    pass


class FleetOperationLockError(StateRepoError):
    pass


@dataclass(frozen=True)
class FleetNodeCreateRequest:
    xboard_node_id: int
    node_name: str
    node_type: str
    status: FleetNodeStatus = "provisioning"
    status_reason: str | None = None
    aws_account_id: str | None = None
    aws_region: str | None = None
    aws_instance_id: str | None = None
    aws_subnet_id: str | None = None
    aws_security_group_id: str | None = None
    cloudflare_record_id: str | None = None
    domain_name: str | None = None
    ipv4_address: str | None = None
    ipv6_address: str | None = None
    last_known_host: str | None = None
    last_error: str | None = None


@dataclass(frozen=True)
class FleetNodeRecord:
    id: int
    xboard_node_id: int
    node_name: str
    node_type: str
    status: FleetNodeStatus
    status_reason: str | None
    aws_account_id: str | None
    aws_region: str | None
    aws_instance_id: str | None
    aws_subnet_id: str | None
    aws_security_group_id: str | None
    cloudflare_record_id: str | None
    domain_name: str | None
    ipv4_address: str | None
    ipv6_address: str | None
    last_known_host: str | None
    last_error: str | None
    is_deleted: bool
    created_at: str
    updated_at: str
    online_at: str | None
    offline_at: str | None
    deleted_at: str | None
    last_healed_at: str | None
    xboard_status: str | None
    xboard_show: bool | None
    xboard_updated_at: str | None
    asset_type: str | None = None


@dataclass(frozen=True)
class FleetNodeEventCreateRequest:
    node_id: int
    xboard_node_id: int | None
    event_type: str
    correlation_id: str
    from_status: FleetNodeStatus | None = None
    to_status: FleetNodeStatus | None = None
    message: str | None = None
    payload: JsonValue | None = None


@dataclass(frozen=True)
class FleetOperationLockRequest:
    lock_key: str
    operation_type: str
    correlation_id: str
    expires_in_seconds: int
    node_id: int | None = None
