from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from database.state_repo import FleetNodeStatus


JsonPrimitive = str | int | float | bool | None
JsonValue = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]


class NodeRegistryServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class RegisterNodeRequest:
    node_type: str
    node_name: str
    host: str
    port: str
    server_port: int
    rate: Decimal
    code: str | None = None
    parent_id: int | None = None
    group_ids: list[int] | None = None
    route_ids: list[int] | None = None
    tags: list[JsonValue] | None = None
    protocol_settings: dict[str, JsonValue] | None = None
    show: bool = True
    sort: int | None = None
    rate_time_enable: bool = False
    rate_time_ranges: list[JsonValue] | dict[str, JsonValue] | None = None
    initial_status: FleetNodeStatus = "provisioning"
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
    last_error: str | None = None


@dataclass(frozen=True)
class RegisterNodeResult:
    local_node_id: int
    xboard_node_id: int
    status: FleetNodeStatus
    node_name: str
    node_type: str


@dataclass(frozen=True)
class NodeStateChangeResult:
    local_node_id: int
    xboard_node_id: int
    status: FleetNodeStatus
