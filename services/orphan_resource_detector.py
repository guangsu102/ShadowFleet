"""
孤儿资源检测服务

负责检测和报告系统中的孤儿资源，包括：
1. EC2 实例：在 AWS 中存在但 SQLite 中无记录
2. DNS 记录：在 Cloudflare 中存在但 SQLite 中无记录
3. 资产分配：SQLite 中标记为 allocated 但对应节点已删除
4. Xboard 节点：在 Xboard 中存在但 SQLite 中无记录
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from database.asset_repo import AssetRepo
from database.state_repo import StateRepo
from database.xboard_repo import XboardRepo
from infrastructure.aws.ec2_client import EC2Client
from infrastructure.azure import AzureClient, AzureCredentials
from infrastructure.cloudflare.cf_client import CFClient
from infrastructure.vultr import VultrClient
from infrastructure.oci import OCIClient, OCICredentials
from models.aws_credentials import AwsCredentials
from services.orphan_azure_support import (
    AZURE_NETWORK_RESOURCE_SPECS,
    AzureNetworkResourceType,
    azure_parent_vm_is_live,
    azure_parent_vm_name_from_resource,
    azure_public_ip_is_attached,
    azure_resource_created_at,
    is_azure_healing_public_ip,
    azure_resource_tags,
    azure_vm_name,
    is_shadowfleet_azure_resource,
)
from utils.logger import set_event_type

if TYPE_CHECKING:
    from services.runtime_service import RuntimeContext


@dataclass(frozen=True)
class OrphanEc2Instance:
    """孤儿 EC2 实例"""
    instance_id: str
    region: str
    account_id: str
    launch_time: str
    state: str
    tags: dict[str, str]


@dataclass(frozen=True)
class OrphanVultrInstance:
    """Vultr instance managed by ShadowFleet but missing locally."""
    instance_id: str
    asset_id: int
    region: str
    label: str
    created_at: str
    status: str
    tags: tuple[str, ...]
    firewall_group_id: str | None = None


@dataclass(frozen=True)
class OrphanAzureVm:
    vm_id: str
    asset_id: int
    location: str
    name: str
    created_at: str
    state: str
    tags: dict[str, str]


@dataclass(frozen=True)
class OrphanOCIInstance:
    instance_id: str
    asset_id: int
    region: str
    display_name: str
    created_at: str
    state: str
    tags: dict[str, str]


@dataclass(frozen=True)
class OrphanAzureNetworkResource:
    resource_id: str
    asset_id: int
    resource_type: AzureNetworkResourceType
    location: str
    name: str
    parent_vm_name: str
    created_at: str
    tags: dict[str, str]


@dataclass(frozen=True)
class OrphanDnsRecord:
    """孤儿 DNS 记录"""
    record_id: str
    domain_name: str
    record_type: str
    content: str
    proxied: bool
    created_on: str


@dataclass(frozen=True)
class OrphanAssetAllocation:
    """孤儿资产分配"""
    allocation_id: int
    asset_id: int
    xboard_node_id: int
    protocol_type: str
    allocated_at: str


@dataclass(frozen=True)
class OrphanXboardNode:
    """孤儿 Xboard 节点"""
    xboard_node_id: int
    node_name: str
    node_type: str
    host: str
    show: bool


@dataclass(frozen=True)
class OrphanResourceReport:
    """孤儿资源检测报告"""
    scan_time: str
    ec2_instances: list[OrphanEc2Instance]
    dns_records: list[OrphanDnsRecord]
    asset_allocations: list[OrphanAssetAllocation]
    xboard_nodes: list[OrphanXboardNode]
    total_count: int
    vultr_instances: list[OrphanVultrInstance] = field(default_factory=list)
    azure_vms: list[OrphanAzureVm] = field(default_factory=list)
    oci_instances: list[OrphanOCIInstance] = field(default_factory=list)
    azure_network_resources: list[OrphanAzureNetworkResource] = field(
        default_factory=list
    )


class OrphanResourceDetectorError(RuntimeError):
    pass


class OrphanResourceDetector:
    """孤儿资源检测器"""

    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime = runtime_context
        self._logger = runtime_context.logger.getChild("services.orphan_resource_detector")
        self._state_repo = StateRepo(runtime_context)
        self._asset_repo = AssetRepo(runtime_context)
        self._xboard_repo = XboardRepo(runtime_context)

    def scan_all_orphan_resources(
        self,
        scan_ec2: bool = True,
        scan_dns: bool = True,
        scan_allocations: bool = True,
        scan_xboard: bool = True,
        scan_vultr: bool = True,
        scan_azure: bool = True,
        scan_oci: bool = True,
    ) -> OrphanResourceReport:
        """
        扫描所有孤儿资源

        Args:
            scan_ec2: 是否扫描 EC2 实例
            scan_dns: 是否扫描 DNS 记录
            scan_allocations: 是否扫描资产分配
            scan_xboard: 是否扫描 Xboard 节点

        Returns:
            孤儿资源报告
        """
        set_event_type("orphan_scan_started")
        self._logger.info("Starting orphan resource scan")

        orphan_ec2_instances: list[OrphanEc2Instance] = []
        orphan_vultr_instances: list[OrphanVultrInstance] = []
        orphan_azure_vms: list[OrphanAzureVm] = []
        orphan_azure_network_resources: list[OrphanAzureNetworkResource] = []
        orphan_oci_instances: list[OrphanOCIInstance] = []
        orphan_dns_records: list[OrphanDnsRecord] = []
        orphan_allocations: list[OrphanAssetAllocation] = []
        orphan_xboard_nodes: list[OrphanXboardNode] = []

        try:
            if scan_ec2:
                orphan_ec2_instances = self._scan_orphan_ec2_instances()
                self._logger.info("Found %d orphan EC2 instances", len(orphan_ec2_instances))

            if scan_vultr:
                orphan_vultr_instances = self._scan_orphan_vultr_instances()
                self._logger.info("Found %d orphan Vultr instances", len(orphan_vultr_instances))
            if scan_oci:
                orphan_oci_instances = self._scan_orphan_oci_instances()
                self._logger.info("Found %d orphan OCI instances", len(orphan_oci_instances))


            if scan_azure:
                orphan_azure_vms = self._scan_orphan_azure_vms()
                self._logger.info("Found %d orphan Azure VMs", len(orphan_azure_vms))
                orphan_azure_network_resources = (
                    self._scan_orphan_azure_network_resources()
                )
                self._logger.info(
                    "Found %d orphan Azure network resources",
                    len(orphan_azure_network_resources),
                )

            if scan_dns:
                orphan_dns_records = self._scan_orphan_dns_records()
                self._logger.info("Found %d orphan DNS records", len(orphan_dns_records))

            if scan_allocations:
                orphan_allocations = self._scan_orphan_asset_allocations()
                self._logger.info("Found %d orphan asset allocations", len(orphan_allocations))

            if scan_xboard:
                orphan_xboard_nodes = self._scan_orphan_xboard_nodes()
                self._logger.info("Found %d orphan Xboard nodes", len(orphan_xboard_nodes))

            total_count = (
                len(orphan_ec2_instances)
                + len(orphan_vultr_instances)
                + len(orphan_azure_vms)
                + len(orphan_azure_network_resources)
                + len(orphan_oci_instances)
                + len(orphan_dns_records)
                + len(orphan_allocations)
                + len(orphan_xboard_nodes)
            )

            report = OrphanResourceReport(
                scan_time=datetime.utcnow().isoformat(),
                ec2_instances=orphan_ec2_instances,
                vultr_instances=orphan_vultr_instances,
                azure_vms=orphan_azure_vms,
                azure_network_resources=orphan_azure_network_resources,
                oci_instances=orphan_oci_instances,
                dns_records=orphan_dns_records,
                asset_allocations=orphan_allocations,
                xboard_nodes=orphan_xboard_nodes,
                total_count=total_count,
            )

            set_event_type("orphan_scan_completed")
            self._logger.info("Orphan resource scan completed: total=%d", total_count)
            return report

        except Exception as exc:
            set_event_type("orphan_scan_failed")
            self._logger.exception("Orphan resource scan failed: %s", exc)
            raise OrphanResourceDetectorError("Failed to scan orphan resources") from exc

    def _scan_orphan_ec2_instances(self) -> list[OrphanEc2Instance]:
        """扫描孤儿 EC2 实例"""
        orphan_instances: list[OrphanEc2Instance] = []

        # 获取所有活跃的 AWS 资产
        active_assets = self._asset_repo.list_assets_by_status("active")
        aws_assets = [a for a in active_assets if a.asset_type == "aws"]

        # 获取 SQLite 中所有节点的 instance_id
        all_nodes = self._state_repo.list_active_nodes()
        known_instance_ids = {
            node.aws_instance_id
            for node in all_nodes
            if node.aws_instance_id is not None
        }

        # 扫描每个 AWS 账号
        for asset in aws_assets:
            try:
                credential = AwsCredentials(
                    account_id=asset.aws_account_id or "",
                    access_key=asset.aws_access_key or "",
                    secret_key=asset.aws_secret_key or "",
                    region=asset.region or "",
                )
                ec2_client = EC2Client(
                    runtime_context=self._runtime,
                    aws_credential=credential,
                )

                # 列出所有 ShadowFleet 管理的实例（通过 tag 识别）
                instances = ec2_client.list_instances_by_tag("ManagedBy", "ShadowFleet")

                for instance in instances:
                    instance_id = instance.get("InstanceId")
                    if instance_id not in known_instance_ids:
                        # 检查实例是否是最近创建的（可能正在 provisioning）
                        launch_time_str = instance.get("LaunchTime", "")
                        if launch_time_str:
                            launch_time = datetime.fromisoformat(launch_time_str.replace("Z", "+00:00"))
                            # 如果实例创建时间超过 1 小时，认为是孤儿
                            if datetime.utcnow() - launch_time.replace(tzinfo=None) > timedelta(hours=1):
                                tags = {
                                    tag["Key"]: tag["Value"]
                                    for tag in instance.get("Tags", [])
                                }
                                orphan_instances.append(
                                    OrphanEc2Instance(
                                        instance_id=instance_id,
                                        region=asset.region or "",
                                        account_id=asset.aws_account_id or "",
                                        launch_time=launch_time_str,
                                        state=instance.get("State", {}).get("Name", "unknown"),
                                        tags=tags,
                                    )
                                )

            except Exception as exc:
                self._logger.warning(
                    "Failed to scan EC2 instances for asset_id=%s: %s",
                    asset.id,
                    exc,
                )

        return orphan_instances

    def _scan_orphan_vultr_instances(self) -> list[OrphanVultrInstance]:
        orphan_instances: list[OrphanVultrInstance] = []
        active_assets = self._asset_repo.list_assets_by_status("active")
        vultr_assets = [
            asset
            for asset in active_assets
            if asset.asset_type == "vultr" and asset.aws_access_key
        ]
        known_instance_ids = {
            node.aws_instance_id
            for node in self._state_repo.list_active_nodes()
            if node.aws_instance_id
        }

        for asset in vultr_assets:
            try:
                client = VultrClient(self._runtime, api_token=asset.aws_access_key or "")
                for instance in client.list_instances():
                    instance_id = str(instance.get("id") or "").strip()
                    raw_tags = instance.get("tags")
                    tags = tuple(
                        str(tag).strip()
                        for tag in raw_tags
                        if str(tag).strip()
                    ) if isinstance(raw_tags, list) else ()
                    if not instance_id or "shadowfleet" not in {tag.lower() for tag in tags}:
                        continue
                    if instance_id in known_instance_ids:
                        continue
                    created_at = str(instance.get("date_created") or "").strip()
                    if not _is_older_than(created_at, timedelta(hours=1)):
                        continue
                    orphan_instances.append(
                        OrphanVultrInstance(
                            instance_id=instance_id,
                            asset_id=asset.id,
                            region=str(instance.get("region") or asset.region or ""),
                            label=str(instance.get("label") or ""),
                            created_at=created_at,
                            status=str(instance.get("status") or "unknown"),
                            tags=tags,
                            firewall_group_id=(
                                str(instance.get("firewall_group_id") or "").strip() or None
                            ),
                        )
                    )
            except Exception as exc:
                self._logger.warning(
                    "Failed to scan Vultr instances for asset_id=%s: %s",
                    asset.id,
                    exc,
                )
        return orphan_instances

    def _scan_orphan_oci_instances(self) -> list[OrphanOCIInstance]:
        orphan_instances: list[OrphanOCIInstance] = []
        active_assets = self._asset_repo.list_assets_by_status("active")
        known_ids = {
            node.aws_instance_id
            for node in self._state_repo.list_active_nodes()
            if node.aws_instance_id
        }
        scanned_scopes: set[tuple[str, str, str]] = set()
        for asset in active_assets:
            if asset.asset_type != "oci":
                continue
            config = asset.provider_config
            if (
                not asset.aws_access_key
                or not asset.aws_secret_key
                or not asset.region
                or not isinstance(config, dict)
            ):
                continue
            tenancy_ocid = str(config.get("tenancy_ocid") or "").strip()
            fingerprint = str(config.get("fingerprint") or "").strip()
            compartment_ocid = str(config.get("compartment_ocid") or "").strip()
            if not tenancy_ocid or not fingerprint or not compartment_ocid:
                continue
            scope = (
                tenancy_ocid.casefold(),
                compartment_ocid.casefold(),
                asset.region.casefold(),
            )
            if scope in scanned_scopes:
                continue
            try:
                client = OCIClient(
                    self._runtime,
                    credentials=OCICredentials(
                        tenancy_ocid=tenancy_ocid,
                        user_ocid=asset.aws_access_key,
                        fingerprint=fingerprint,
                        private_key=asset.aws_secret_key,
                        private_key_passphrase=(
                            str(config["private_key_passphrase"])
                            if config.get("private_key_passphrase") is not None
                            else None
                        ),
                    ),
                    region=asset.region,
                )
                instances = client.list_instances(compartment_ocid)
                scanned_scopes.add(scope)
                for instance in instances:
                    instance_id = str(instance.get("id") or "").strip()
                    tags = (
                        {
                            str(key): str(value)
                            for key, value in instance["freeformTags"].items()
                        }
                        if isinstance(instance.get("freeformTags"), dict)
                        else {}
                    )
                    state = str(instance.get("lifecycleState") or "unknown")
                    if (
                        not instance_id
                        or tags.get("ManagedBy") != "ShadowFleet"
                        or instance_id in known_ids
                        or state.upper() in {"TERMINATED", "TERMINATING"}
                    ):
                        continue
                    created_at = str(instance.get("timeCreated") or "").strip()
                    if not _is_older_than(created_at, timedelta(hours=1)):
                        continue
                    orphan_instances.append(
                        OrphanOCIInstance(
                            instance_id=instance_id,
                            asset_id=asset.id,
                            region=str(instance.get("region") or asset.region),
                            display_name=str(instance.get("displayName") or ""),
                            created_at=created_at,
                            state=state,
                            tags=tags,
                        )
                    )
            except Exception as exc:
                self._logger.warning(
                    "Failed to scan OCI instances for asset_id=%s: %s",
                    asset.id,
                    exc,
                )
        return orphan_instances


    def _scan_orphan_azure_vms(self) -> list[OrphanAzureVm]:
        orphan_vms: list[OrphanAzureVm] = []
        active_assets = self._asset_repo.list_assets_by_status("active")
        scanned_scopes: set[tuple[str, str]] = set()
        known_ids = {
            str(node.aws_instance_id).lower()
            for node in self._state_repo.list_active_nodes()
            if node.aws_instance_id
        }
        for asset in active_assets:
            if asset.asset_type != "azure":
                continue
            provider_config = asset.provider_config
            if (
                not asset.aws_access_key
                or not asset.aws_secret_key
                or not isinstance(provider_config, dict)
            ):
                continue
            tenant_id = str(provider_config.get("tenant_id") or "").strip()
            subscription_id = str(provider_config.get("subscription_id") or "").strip()
            resource_group = str(provider_config.get("resource_group") or "").strip()
            if not tenant_id or not subscription_id or not resource_group:
                continue
            scope = (subscription_id.casefold(), resource_group.casefold())
            if scope in scanned_scopes:
                continue
            try:
                client = AzureClient(
                    self._runtime,
                    AzureCredentials(
                        tenant_id=tenant_id,
                        client_id=asset.aws_access_key,
                        client_secret=asset.aws_secret_key,
                        subscription_id=subscription_id,
                    ),
                )
                virtual_machines = client.list_virtual_machines(resource_group)
                scanned_scopes.add(scope)
                for vm in virtual_machines:
                    vm_id = str(vm.get("id") or "").strip()
                    raw_tags = vm.get("tags")
                    tags = {
                        str(key): str(value)
                        for key, value in raw_tags.items()
                    } if isinstance(raw_tags, dict) else {}
                    managed = str(tags.get("shadowfleet") or "").lower() == "true"
                    if not vm_id or not managed or vm_id.lower() in known_ids:
                        continue
                    properties = vm.get("properties")
                    created_at = str(
                        properties.get("timeCreated") if isinstance(properties, dict) else ""
                    ).strip()
                    if not _is_older_than(created_at, timedelta(hours=1)):
                        continue
                    orphan_vms.append(
                        OrphanAzureVm(
                            vm_id=vm_id,
                            asset_id=asset.id,
                            location=str(vm.get("location") or asset.region or ""),
                            name=str(vm.get("name") or ""),
                            created_at=created_at,
                            state=client.get_vm_power_state(vm_id) or "unknown",
                            tags=tags,
                        )
                    )
            except Exception as exc:
                self._logger.warning(
                    "Failed to scan Azure VMs for asset_id=%s: %s", asset.id, exc
                )
        return orphan_vms

    def _scan_orphan_azure_network_resources(
        self,
    ) -> list[OrphanAzureNetworkResource]:
        orphan_resources: list[OrphanAzureNetworkResource] = []
        active_assets = self._asset_repo.list_assets_by_status("active")
        scanned_scopes: set[tuple[str, str]] = set()
        for asset in active_assets:
            if asset.asset_type != "azure":
                continue
            provider_config = asset.provider_config
            if (
                not asset.aws_access_key
                or not asset.aws_secret_key
                or not isinstance(provider_config, dict)
            ):
                continue
            tenant_id = str(provider_config.get("tenant_id") or "").strip()
            subscription_id = str(
                provider_config.get("subscription_id") or ""
            ).strip()
            resource_group = str(provider_config.get("resource_group") or "").strip()
            if not tenant_id or not subscription_id or not resource_group:
                continue
            scope = (subscription_id.casefold(), resource_group.casefold())
            if scope in scanned_scopes:
                continue
            try:
                client = AzureClient(
                    self._runtime,
                    AzureCredentials(
                        tenant_id=tenant_id,
                        client_id=asset.aws_access_key,
                        client_secret=asset.aws_secret_key,
                        subscription_id=subscription_id,
                    ),
                )
                virtual_machines = client.list_virtual_machines(resource_group)
                scanned_scopes.add(scope)
                live_vm_names = {
                    azure_vm_name(vm).casefold()
                    for vm in virtual_machines
                    if azure_vm_name(vm)
                }
                resource_collections = (
                    client.list_network_interfaces(resource_group),
                    client.list_public_ip_addresses(resource_group),
                    client.list_network_security_groups(resource_group),
                )
                for spec, resources in zip(
                    AZURE_NETWORK_RESOURCE_SPECS,
                    resource_collections,
                    strict=True,
                ):
                    for resource in resources:
                        if not is_shadowfleet_azure_resource(resource):
                            continue
                        resource_id = str(resource.get("id") or "").strip()
                        name = str(resource.get("name") or "").strip()
                        parent_vm_name = azure_parent_vm_name_from_resource(
                            spec.resource_type,
                            resource,
                        )
                        healing_public_ip = (
                            spec.resource_type == "azure_public_ip_address"
                            and is_azure_healing_public_ip(resource)
                        )
                        parent_is_live = (
                            parent_vm_name is not None
                            and azure_parent_vm_is_live(
                                parent_vm_name,
                                live_vm_names,
                                healing_public_ip=healing_public_ip,
                            )
                        )
                        if not resource_id or parent_vm_name is None:
                            continue
                        if parent_is_live and (
                            not healing_public_ip
                            or azure_public_ip_is_attached(resource)
                        ):
                            continue
                        created_at = azure_resource_created_at(resource)
                        if not _is_older_than(created_at, timedelta(hours=1)):
                            continue
                        orphan_resources.append(
                            OrphanAzureNetworkResource(
                                resource_id=resource_id,
                                asset_id=asset.id,
                                resource_type=spec.resource_type,
                                location=str(
                                    resource.get("location") or asset.region or ""
                                ),
                                name=name,
                                parent_vm_name=parent_vm_name,
                                created_at=created_at,
                                tags=azure_resource_tags(resource),
                            )
                        )
            except Exception as exc:
                self._logger.warning(
                    "Failed to scan Azure network resources for asset_id=%s: %s",
                    asset.id,
                    exc,
                )
        return orphan_resources

    def _scan_orphan_dns_records(self) -> list[OrphanDnsRecord]:
        """扫描孤儿 DNS 记录"""
        orphan_records: list[OrphanDnsRecord] = []

        if not self._runtime.config.cloudflare.enabled:
            return orphan_records

        try:
            cf_client = CFClient(self._runtime)

            # 获取所有 ShadowFleet 管理的域名（从 SQLite）
            all_nodes = self._state_repo.list_all_nodes_with_domains()
            known_domains = {node.domain_name for node in all_nodes if node.domain_name}

            # 列出 Cloudflare 中所有以 sf- 开头的记录
            root_domain = self._runtime.config.cloudflare.root_domain
            if not root_domain:
                return orphan_records

            all_records = cf_client.list_dns_records()

            for record in all_records:
                record_name = record.get("name", "")
                # 只检查 sf- 开头的子域名
                if record_name.startswith(f"sf-") and record_name.endswith(root_domain):
                    if record_name not in known_domains:
                        orphan_records.append(
                            OrphanDnsRecord(
                                record_id=record.get("id", ""),
                                domain_name=record_name,
                                record_type=record.get("type", ""),
                                content=record.get("content", ""),
                                proxied=record.get("proxied", False),
                                created_on=record.get("created_on", ""),
                            )
                        )

        except Exception as exc:
            self._logger.warning("Failed to scan DNS records: %s", exc)

        return orphan_records

    def _scan_orphan_asset_allocations(self) -> list[OrphanAssetAllocation]:
        """扫描孤儿资产分配"""
        orphan_allocations: list[OrphanAssetAllocation] = []

        # 这个查询需要在 SQLite 中执行
        sql = """
            SELECT
                faa.id,
                faa.asset_id,
                faa.xboard_node_id,
                faa.protocol_type,
                faa.created_at
            FROM fleet_asset_allocations faa
            LEFT JOIN fleet_nodes fn ON fn.xboard_node_id = faa.xboard_node_id
            WHERE faa.allocation_status = 'allocated'
              AND (fn.id IS NULL OR fn.is_deleted = 1)
        """

        try:
            with self._runtime.sqlite_manager.connection() as connection:
                rows = connection.execute(sql).fetchall()

            for row in rows:
                orphan_allocations.append(
                    OrphanAssetAllocation(
                        allocation_id=int(row[0]),
                        asset_id=int(row[1]),
                        xboard_node_id=int(row[2]),
                        protocol_type=str(row[3]),
                        allocated_at=str(row[4]),
                    )
                )

        except Exception as exc:
            self._logger.warning("Failed to scan asset allocations: %s", exc)

        return orphan_allocations

    def _scan_orphan_xboard_nodes(self) -> list[OrphanXboardNode]:
        """扫描孤儿 Xboard 节点"""
        orphan_nodes: list[OrphanXboardNode] = []

        try:
            # 获取 Xboard 中所有 ShadowFleet 节点
            xboard_nodes = self._xboard_repo.list_all_shadowfleet_nodes()

            # 获取 SQLite 中所有节点的 xboard_node_id
            sqlite_nodes = self._state_repo.list_active_nodes()
            known_xboard_ids = {node.xboard_node_id for node in sqlite_nodes}

            for xboard_node in xboard_nodes:
                if xboard_node.node_id not in known_xboard_ids:
                    orphan_nodes.append(
                        OrphanXboardNode(
                            xboard_node_id=xboard_node.node_id,
                            node_name=xboard_node.node_name,
                            node_type=xboard_node.node_type,
                            host=xboard_node.host,
                            show=xboard_node.show,
                        )
                    )

        except Exception as exc:
            self._logger.warning("Failed to scan Xboard nodes: %s", exc)

        return orphan_nodes


def _is_older_than(value: str, minimum_age: timedelta) -> bool:
    if not value:
        return False
    try:
        created_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return datetime.utcnow() - created_at.replace(tzinfo=None) > minimum_age
