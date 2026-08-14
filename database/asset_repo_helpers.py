from __future__ import annotations

from datetime import datetime, timezone
import json
import sqlite3

from database.asset_models import (
    AWS_SUPPORTED_PROTOCOLS,
    AZURE_SUPPORTED_PROTOCOLS,
    CDN_PROXY_SUPPORTED_PROTOCOLS,
    DIGITALOCEAN_SUPPORTED_PROTOCOLS,
    DNS_REQUIRED_PROTOCOLS,
    SELF_HOSTED_SUPPORTED_PROTOCOLS,
    VULTR_SUPPORTED_PROTOCOLS,
    AssetCreateRequest,
    AssetProtocolConfigRecord,
    AssetProtocolConfigRequest,
    AssetRecord,
    PortAllocationRecord,
)


def validate_asset_request(request: AssetCreateRequest) -> None:
    if not request.asset_name or not request.asset_name.strip():
        raise ValueError("asset_name must not be empty")
    if request.asset_type == "aws":
        if not request.region or not request.region.strip():
            raise ValueError("region is required for aws assets")
        if not request.aws_account_id or not request.aws_account_id.strip():
            raise ValueError("aws_account_id is required for aws assets")
        if not request.aws_access_key or not request.aws_access_key.strip():
            raise ValueError("aws_access_key is required for aws assets")
        if not request.aws_secret_key or not request.aws_secret_key.strip():
            raise ValueError("aws_secret_key is required for aws assets")
    if request.asset_type == "digitalocean":
        if not request.region or not request.region.strip():
            raise ValueError("region is required for digitalocean assets")
        if not request.aws_access_key or not request.aws_access_key.strip():
            raise ValueError("digitalocean_token is required for digitalocean assets")
    if request.asset_type == "vultr":
        if not request.region or not request.region.strip():
            raise ValueError("region is required for vultr assets")
        if not request.aws_access_key or not request.aws_access_key.strip():
            raise ValueError("vultr_token is required for vultr assets")
    if request.asset_type == "azure":
        if not request.region or not request.region.strip():
            raise ValueError("region is required for azure assets")
        if not request.aws_account_id or not request.aws_account_id.strip():
            raise ValueError("subscription_id is required for azure assets")
        if not request.aws_access_key or not request.aws_access_key.strip():
            raise ValueError("client_id is required for azure assets")
        if not request.aws_secret_key or not request.aws_secret_key.strip():
            raise ValueError("client_secret is required for azure assets")
    if request.asset_type == "self_hosted":
        if not request.ssh_host or not request.ssh_host.strip():
            raise ValueError("ssh_host is required for self_hosted assets")
        if request.ssh_port is None or request.ssh_port <= 0:
            raise ValueError("ssh_port must be greater than 0 for self_hosted assets")
        if not request.ssh_username or not request.ssh_username.strip():
            raise ValueError("ssh_username is required for self_hosted assets")
        if not request.ssh_password and not request.ssh_private_key:
            raise ValueError("ssh_password or ssh_private_key is required for self_hosted assets")


def _strip_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def validate_protocol_config_request(
    asset: AssetRecord,
    request: AssetProtocolConfigRequest,
) -> None:
    if request.target_count < 0:
        raise ValueError("target_count must be greater than or equal to 0")
    if request.max_count < 0:
        raise ValueError("max_count must be greater than or equal to 0")
    if request.max_count > 0 and request.target_count > request.max_count:
        raise ValueError("target_count must not exceed max_count")
    if request.vcpu is not None and request.vcpu <= 0:
        raise ValueError("vcpu must be greater than 0")

    if asset.asset_type == "aws":
        supported_protocols = AWS_SUPPORTED_PROTOCOLS
    elif asset.asset_type == "digitalocean":
        supported_protocols = DIGITALOCEAN_SUPPORTED_PROTOCOLS
    elif asset.asset_type == "vultr":
        supported_protocols = VULTR_SUPPORTED_PROTOCOLS
    elif asset.asset_type == "azure":
        supported_protocols = AZURE_SUPPORTED_PROTOCOLS
    else:
        supported_protocols = SELF_HOSTED_SUPPORTED_PROTOCOLS
    if request.protocol_type not in supported_protocols:
        raise ValueError(
            f"Protocol {request.protocol_type} is not supported by asset type {asset.asset_type}"
        )
    if request.protocol_type == "AnyTLS" and request.allow_cdn_proxy:
        raise ValueError("AnyTLS assets must not allow CDN proxy")


def build_protocol_defaults(protocol_type: str) -> dict[str, bool]:
    return {
        "requires_domain": protocol_type in DNS_REQUIRED_PROTOCOLS,
        "requires_dns_record": protocol_type in DNS_REQUIRED_PROTOCOLS,
        "supports_cdn_proxy": protocol_type in CDN_PROXY_SUPPORTED_PROTOCOLS,
    }


def map_asset_record(row: sqlite3.Row) -> AssetRecord:
    return AssetRecord(
        id=int(row["id"]),
        asset_type=row["asset_type"],
        asset_name=str(row["asset_name"]),
        status=row["status"],
        region=row["region"],
        aws_account_id=row["aws_account_id"],
        aws_access_key=row["aws_access_key"],
        aws_secret_key=row["aws_secret_key"],
        ssh_host=row["ssh_host"],
        ssh_port=row["ssh_port"],
        ssh_username=row["ssh_username"],
        ssh_password=row["ssh_password"],
        ssh_private_key=row["ssh_private_key"],
        default_instance_type=row["default_instance_type"],
        default_vcpu=row["default_vcpu"],
        account_total_vcpu=row["account_total_vcpu"],
        default_architecture=row["default_architecture"],
        cpu_cores=row["cpu_cores"],
        memory_gb=row["memory_gb"],
        provider_config=from_json_text(
            row["provider_config_json"] if "provider_config_json" in row.keys() else None
        ),
        remarks=row["remarks"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def map_asset_protocol_config_record(row: sqlite3.Row) -> AssetProtocolConfigRecord:
    return AssetProtocolConfigRecord(
        id=int(row["id"]),
        asset_id=int(row["asset_id"]),
        protocol_type=row["protocol_type"],
        enabled=bool(row["enabled"]),
        target_count=int(row["target_count"]),
        max_count=int(row["max_count"]),
        priority=int(row["priority"]),
        allow_cdn_proxy=bool(row["allow_cdn_proxy"]),
        instance_type=row["instance_type"],
        vcpu=row["vcpu"],
        architecture=row["architecture"],
        ami_id=row["ami_id"],
        subnet_id=row["subnet_id"],
        security_group_id=row["security_group_id"],
        requires_domain=bool(row["requires_domain"]),
        requires_dns_record=bool(row["requires_dns_record"]),
        supports_cdn_proxy=bool(row["supports_cdn_proxy"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def map_asset_protocol_config_record_from_join(row: sqlite3.Row) -> AssetProtocolConfigRecord:
    return AssetProtocolConfigRecord(
        id=int(row["protocol_config_id"]),
        asset_id=int(row["id"]),
        protocol_type=row["protocol_type"],
        enabled=bool(row["enabled"]),
        target_count=int(row["target_count"]),
        max_count=int(row["max_count"]),
        priority=int(row["priority"]),
        allow_cdn_proxy=bool(row["allow_cdn_proxy"]),
        instance_type=row["instance_type"],
        vcpu=row["vcpu"],
        architecture=row["architecture"],
        ami_id=row["ami_id"],
        subnet_id=row["subnet_id"],
        security_group_id=row["security_group_id"],
        requires_domain=bool(row["requires_domain"]),
        requires_dns_record=bool(row["requires_dns_record"]),
        supports_cdn_proxy=bool(row["supports_cdn_proxy"]),
        created_at=str(row["protocol_created_at"]),
        updated_at=str(row["protocol_updated_at"]),
    )


def to_json_text(value: dict[str, object] | list[object] | str | int | float | bool | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def from_json_text(value: str | None) -> dict[str, object] | None:
    if value is None or not value.strip():
        return None
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("provider_config_json must be a JSON object")
    return parsed


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def map_port_allocation_record(row: sqlite3.Row) -> PortAllocationRecord:
    return PortAllocationRecord(
        id=int(row["id"]),
        asset_id=int(row["asset_id"]),
        fleet_node_id=row["fleet_node_id"],
        xboard_node_id=row["xboard_node_id"],
        server_port=int(row["server_port"]),
        protocol_type=str(row["protocol_type"]),
        allocation_status=str(row["allocation_status"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )
