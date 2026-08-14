from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal


AssetType = Literal["aws", "azure", "digitalocean", "oci", "vultr", "self_hosted"]
ProtocolType = Literal["AnyTLS", "Trojan", "vless", "vmess", "Hysteria2"]
CertMode = Literal["none", "http", "dns", "self"]


@dataclass(frozen=True)
class DnsRecordSnapshot:
    record_type: Literal["A", "AAAA"]
    record_id: str | None
    existed: bool
    content: str | None
    proxied: bool


@dataclass(frozen=True)
class DnsSyncResult:
    primary_record_id: str
    a_record_id: str | None
    aaaa_record_id: str | None
    snapshots: tuple[DnsRecordSnapshot, ...]


@dataclass(frozen=True)
class ProvisionRequest:
    protocol_type: ProtocolType
    node_name: str
    port: str
    server_port: int
    rate: Decimal
    provisioning_task_id: int | None = None
    asset_type: AssetType | None = "aws"
    region: str | None = None
    domain_name: str | None = None
    require_cdn_proxy: bool = False
    cert_mode: CertMode = "dns"
    cert_domain: str | None = None
    cert_provider: str | None = None
    cert_dns_env: dict[str, str] | None = None
    cert_email: str | None = None
    code: str | None = None
    parent_id: int | None = None
    group_ids: list[int] | None = None
    route_ids: list[int] | None = None
    tags: list[str] | None = None
    protocol_settings: dict[str, str | int | float | bool | list[object] | dict[str, object] | None] | None = None
    show: bool = True
    sort: int | None = None
    rate_time_enable: bool = False
    rate_time_ranges: list[object] | dict[str, object] | None = None
    status_reason: str | None = None
    # Protocol-specific fields
    sni_domain: str | None = None
    reality_private_key: str | None = None
    reality_public_key: str | None = None
    reality_dest: str | None = None
    allow_insecure: bool = True
    network: str = "grpc"
    flow: str | None = None
    # Self-hosted SSH fields
    ssh_host: str | None = None
    ssh_port: int | None = None
    ssh_username: str | None = None
    ssh_password: str | None = None
    ssh_private_key: str | None = None


@dataclass(frozen=True)
class ProvisionResult:
    local_node_id: int
    xboard_node_id: int
    asset_id: int
    asset_type: AssetType
    protocol_type: ProtocolType
    node_name: str
    status: str
    aws_account_id: str | None
    region: str | None
    instance_id: str | None
    network_interface_id: str | None
    ipv4_address: str | None = None
    ipv6_address: str | None = None
    domain_name: str | None = None
    cloudflare_record_id: str | None = None
    cloudflare_a_record_id: str | None = None
    cloudflare_aaaa_record_id: str | None = None
