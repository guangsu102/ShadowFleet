from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SecurityGroupRule:
    """Single inbound rule for a security group."""
    port: int
    protocol: str = "tcp"
    description: str = "ShadowFleet"


@dataclass(frozen=True)
class AssetRegistrationRequest:
    asset_name: str
    region: str
    aws_access_key: str
    aws_secret_key: str
    aws_account_id: str | None = None
    default_instance_type: str | None = None
    default_vcpu: int | None = None
    account_total_vcpu: int | None = None
    default_architecture: str | None = None
    remarks: str | None = None
    protocol_type: str | None = None
    additional_protocol_types: tuple[str, ...] = ()
    target_count: int = 0
    max_count: int = 0
    priority: int = 100
    allow_cdn_proxy: bool = False
    protocol_instance_type: str | None = None
    protocol_vcpu: int | None = None
    protocol_architecture: str | None = None
    ami_id: str | None = None
    vpc_id: str | None = None
    subnet_id: str | None = None
    security_group_id: str | None = None
    auto_create_security_group: bool = False
    security_group_name: str | None = None
    security_group_ports: tuple[int, ...] = ()


@dataclass(frozen=True)
class AssetRegistrationResult:
    asset_id: int
    asset_name: str
    protocol_config_id: int | None


@dataclass(frozen=True)
class SelfHostedAssetRegistrationRequest:
    """Request model for registering self-hosted (自建) assets."""
    asset_name: str
    region: str
    host: str
    ssh_port: int = 22
    ssh_username: str = "root"
    ssh_password: str | None = None
    ssh_private_key: str | None = None
    remarks: str | None = None
    protocol_type: str | None = None
    additional_protocol_types: tuple[str, ...] = ()
    target_count: int = 0
    max_count: int = 0
    priority: int = 100
    cpu_cores: int | None = None
    memory_gb: float | None = None
