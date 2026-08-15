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
class DigitalOceanAssetRegistrationRequest:
    asset_name: str
    region: str
    digitalocean_token: str
    default_size: str = "s-2vcpu-2gb"
    default_image: str = "ubuntu-24-04-x64"
    ssh_keys: tuple[str, ...] = ()
    vpc_uuid: str | None = None
    tags: tuple[str, ...] = ()
    remarks: str | None = None
    protocol_type: str | None = None
    additional_protocol_types: tuple[str, ...] = ()
    target_count: int = 0
    max_count: int = 0
    priority: int = 100
    allow_cdn_proxy: bool = False
    default_vcpu: int | None = None


@dataclass(frozen=True)
class VultrAssetRegistrationRequest:
    asset_name: str
    region: str
    vultr_token: str
    default_plan: str = "vc2-1c-1gb"
    default_os_id: int = 2284
    ssh_key_ids: tuple[str, ...] = ()
    vpc_ids: tuple[str, ...] = ()
    # Kept for API/database compatibility with the initial Vultr implementation.
    vpc2: str | None = None
    firewall_group_id: str | None = None
    tags: tuple[str, ...] = ()
    remarks: str | None = None
    protocol_type: str | None = None
    additional_protocol_types: tuple[str, ...] = ()
    target_count: int = 0
    max_count: int = 0
    priority: int = 100
    allow_cdn_proxy: bool = False
    default_vcpu: int | None = None


@dataclass(frozen=True)
class AzureAssetRegistrationRequest:
    asset_name: str
    region: str
    tenant_id: str
    client_id: str
    client_secret: str
    subscription_id: str
    resource_group: str
    ssh_public_key: str
    default_vm_size: str = "Standard_B1s"
    admin_username: str = "azureuser"
    image_publisher: str = "Canonical"
    image_offer: str = "0001-com-ubuntu-server-jammy"
    image_sku: str = "22_04-lts-gen2"
    image_version: str = "latest"
    vnet_name: str = "shadowfleet-vnet"
    subnet_name: str = "default"
    tags: tuple[str, ...] = ()
    remarks: str | None = None
    protocol_type: str | None = None
    additional_protocol_types: tuple[str, ...] = ()
    target_count: int = 0
    max_count: int = 0
    priority: int = 100
    allow_cdn_proxy: bool = False
    default_vcpu: int | None = None


@dataclass(frozen=True)
class GCPAssetRegistrationRequest:
    asset_name: str
    project_id: str
    service_account_json: str
    zone: str
    machine_type: str = "e2-small"
    source_image: str = "projects/ubuntu-os-cloud/global/images/family/ubuntu-2404-lts-amd64"
    network: str = "default"
    subnetwork: str | None = None
    ssh_username: str = "ubuntu"
    ssh_public_key: str = ""
    labels: tuple[str, ...] = ()
    remarks: str | None = None
    protocol_type: str | None = None
    additional_protocol_types: tuple[str, ...] = ()
    target_count: int = 0
    max_count: int = 0
    priority: int = 100
    allow_cdn_proxy: bool = False
    default_vcpu: int | None = None


@dataclass(frozen=True)
class OCIAssetRegistrationRequest:
    asset_name: str
    region: str
    tenancy_ocid: str
    user_ocid: str
    fingerprint: str
    private_key: str
    compartment_ocid: str
    subnet_ocid: str
    network_security_group_ocid: str
    image_ocid: str
    ssh_public_key: str
    shape: str = "VM.Standard.E4.Flex"
    private_key_passphrase: str | None = None
    availability_domain: str | None = None
    ocpus: float | None = None
    memory_in_gbs: float | None = None
    tags: tuple[str, ...] = ()
    remarks: str | None = None
    protocol_type: str | None = None
    additional_protocol_types: tuple[str, ...] = ()
    target_count: int = 0
    max_count: int = 0
    priority: int = 100
    allow_cdn_proxy: bool = False
    default_vcpu: int | None = None


@dataclass(frozen=True)
class KamateraAssetRegistrationRequest:
    asset_name: str
    datacenter: str
    client_id: str
    secret: str
    image: str
    ssh_public_key: str
    cpu_type: str = "B"
    cpu_cores: int = 2
    ram_mb: int = 2048
    disk_sizes_gb: tuple[int, ...] = (20,)
    billing_cycle: str = "hourly"
    monthly_package: str | None = None
    daily_backup: bool = False
    managed: bool = False
    tags: tuple[str, ...] = ()
    remarks: str | None = None
    protocol_type: str | None = None
    additional_protocol_types: tuple[str, ...] = ()
    target_count: int = 0
    max_count: int = 0
    priority: int = 100
    allow_cdn_proxy: bool = False


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
