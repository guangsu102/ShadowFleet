from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


AssetType = Literal["aws", "digitalocean", "self_hosted"]
AssetStatus = Literal["active", "full", "banned", "offline", "deploying"]
ProtocolType = Literal["AnyTLS", "Trojan", "vless", "vmess", "Hysteria2"]
AllocationStatus = Literal["allocated", "released", "failed"]

DNS_REQUIRED_PROTOCOLS: set[ProtocolType] = {"AnyTLS", "Trojan", "vless", "vmess"}
CDN_PROXY_SUPPORTED_PROTOCOLS: set[ProtocolType] = {"Trojan", "vless", "vmess"}
AWS_SUPPORTED_PROTOCOLS: set[ProtocolType] = {"AnyTLS", "Trojan", "vless", "vmess"}
DIGITALOCEAN_SUPPORTED_PROTOCOLS: set[ProtocolType] = {
    "AnyTLS",
    "Trojan",
    "vless",
    "vmess",
}
SELF_HOSTED_SUPPORTED_PROTOCOLS: set[ProtocolType] = {
    "AnyTLS",
    "Trojan",
    "vless",
    "vmess",
    "Hysteria2",
}


class AssetRepoError(RuntimeError):
    pass


class AssetNotFoundError(AssetRepoError):
    pass


@dataclass(frozen=True)
class AssetCreateRequest:
    asset_type: AssetType
    asset_name: str
    status: AssetStatus = "active"
    region: str | None = None
    aws_account_id: str | None = None
    aws_access_key: str | None = None
    aws_secret_key: str | None = None
    ssh_host: str | None = None
    ssh_port: int | None = None
    ssh_username: str | None = None
    ssh_password: str | None = None
    ssh_private_key: str | None = None
    default_instance_type: str | None = None
    default_vcpu: int | None = None
    account_total_vcpu: int | None = None
    default_architecture: str | None = None
    cpu_cores: int | None = None
    memory_gb: float | None = None
    provider_config: dict[str, object] | None = None
    remarks: str | None = None


@dataclass(frozen=True)
class AssetProtocolConfigRequest:
    asset_id: int
    protocol_type: ProtocolType
    enabled: bool = True
    target_count: int = 0
    max_count: int = 0
    priority: int = 100
    allow_cdn_proxy: bool = False
    instance_type: str | None = None
    vcpu: int | None = None
    architecture: str | None = None
    ami_id: str | None = None
    subnet_id: str | None = None
    security_group_id: str | None = None
    requires_domain: bool | None = None
    requires_dns_record: bool | None = None
    supports_cdn_proxy: bool | None = None


@dataclass(frozen=True)
class AssetRecord:
    id: int
    asset_type: AssetType
    asset_name: str
    status: AssetStatus
    region: str | None
    aws_account_id: str | None
    aws_access_key: str | None
    aws_secret_key: str | None
    ssh_host: str | None
    ssh_port: int | None
    ssh_username: str | None
    ssh_password: str | None
    ssh_private_key: str | None
    default_instance_type: str | None
    default_vcpu: int | None
    account_total_vcpu: int | None
    default_architecture: str | None
    cpu_cores: int | None = None
    memory_gb: float | None = None
    provider_config: dict[str, object] | None = None
    remarks: str | None = None
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class PortAllocationRecord:
    id: int
    asset_id: int
    fleet_node_id: int | None
    xboard_node_id: int | None
    server_port: int
    protocol_type: str
    allocation_status: AllocationStatus
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class AssetProtocolConfigRecord:
    id: int
    asset_id: int
    protocol_type: ProtocolType
    enabled: bool
    target_count: int
    max_count: int
    priority: int
    allow_cdn_proxy: bool
    instance_type: str | None
    vcpu: int | None
    architecture: str | None
    ami_id: str | None
    subnet_id: str | None
    security_group_id: str | None
    requires_domain: bool
    requires_dns_record: bool
    supports_cdn_proxy: bool
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class AssetSelectionCandidate:
    asset: AssetRecord
    protocol_config: AssetProtocolConfigRecord
    current_allocated_count: int
    current_allocated_vcpu: int


@dataclass(frozen=True)
class AssetAllocationCreateRequest:
    asset_id: int
    protocol_type: ProtocolType
    fleet_node_id: int | None = None
    xboard_node_id: int | None = None
    allocation_status: AllocationStatus = "allocated"
    vcpu_count: int = 1


@dataclass(frozen=True)
class AssetEventCreateRequest:
    asset_id: int
    event_type: str
    correlation_id: str
    message: str | None = None
    payload: dict[str, object] | list[object] | str | int | float | bool | None = None


@dataclass(frozen=True)
class PortAllocationCreateRequest:
    asset_id: int
    server_port: int
    protocol_type: ProtocolType
    fleet_node_id: int | None = None
    xboard_node_id: int | None = None
    allocation_status: AllocationStatus = "allocated"
