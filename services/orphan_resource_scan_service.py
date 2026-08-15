"""
孤儿资源自动检测和清理服务
定期扫描并清理孤儿资源，防止资源泄漏
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from database.asset_repo import AssetRepo
from database.state_models import FleetNodeRecord
from database.state_repo import StateRepo
from infrastructure.aws.ec2_client import EC2Client
from infrastructure.azure import AzureClient, AzureClientError, AzureCredentials
from infrastructure.digitalocean import DigitalOceanClient, DigitalOceanClientError
from infrastructure.gcp import GCPClient, GCPClientError, GCPCredentials
from infrastructure.kamatera import (
    KamateraClient,
    KamateraClientError,
    server_created_at,
    server_tags,
)
from infrastructure.vultr import VultrClient, VultrClientError
from infrastructure.oci import OCIClient, OCIClientError, OCICredentials
from services.monitor_support import infer_node_asset_type
from services.orphan_azure_support import (
    AZURE_NETWORK_RESOURCE_SPECS,
    AZURE_NETWORK_RESOURCE_TYPES,
    azure_parent_vm_is_live,
    azure_parent_vm_name_from_resource,
    azure_public_ip_is_attached,
    azure_resource_created_at,
    is_azure_healing_public_ip,
    azure_vm_name,
    is_shadowfleet_azure_resource,
)
from services.asset_selector_service import AssetSelectorService
from services.node_registry_service import NodeRegistryService
from services.orphan_node_cleanup_service import OrphanNodeCleanupService
from services.runtime_service import RuntimeContext
from utils.logger import generate_correlation_id, set_correlation_id, set_event_type


if TYPE_CHECKING:
    from services.fleet_scheduler_service import FleetSchedulerService


@dataclass(frozen=True)
class OrphanResourceInfo:
    """孤儿资源信息"""
    resource_type: str  # ec2_instance, xboard_node, cloudflare_record
    resource_id: str
    region: str | None = None
    aws_account_id: str | None = None
    xboard_node_id: int | None = None
    reason: str | None = None
    discovered_at: str | None = None
    asset_id: int | None = None
    firewall_group_id: str | None = None


@dataclass(frozen=True)
class OrphanCleanupResult:
    """孤儿资源清理结果"""
    scan_duration_seconds: float
    total_resources_scanned: int
    orphans_found: int
    orphans_cleaned: int
    orphans_failed: int
    orphans: tuple[OrphanResourceInfo, ...]
    errors: tuple[str, ...]


@dataclass(frozen=True)
class DatabaseConsistencyResult:
    """数据库一致性检查结果"""
    sqlite_only_nodes: tuple[int, ...]  # SQLite 有但 Xboard 没有
    xboard_only_nodes: tuple[int, ...]   # Xboard 有但 SQLite 没有
    status_mismatch: tuple[str, ...]     # 状态不一致的节点
    inconsistent_allocations: tuple[str, ...]  # 资产分配不一致


class OrphanResourceScanService:
    """
    孤儿资源自动检测和清理服务

    检测和清理以下类型的孤儿资源：
    1. EC2 实例孤儿 - AWS 上存在但 SQLite 中没有对应记录
    2. 节点孤儿 - SQLite 中存在但 AWS 上已终止
    3. 资产分配孤儿 - 分配记录与实际资源不匹配
    """

    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime_context = runtime_context
        self._logger = runtime_context.logger.getChild("services.orphan_resource_scan")
        self._state_repo = StateRepo(runtime_context)
        self._asset_repo = AssetRepo(runtime_context)
        self._node_registry = NodeRegistryService(runtime_context)
        self._orphan_cleanup = OrphanNodeCleanupService(runtime_context)
        self._asset_selector = AssetSelectorService(runtime_context)
        self._scheduler: FleetSchedulerService | None = None
        self._scan_history: list[OrphanCleanupResult] = []

    @property
    def _scheduler_service(self) -> FleetSchedulerService:
        if self._scheduler is None:
            from services.fleet_scheduler_service import FleetSchedulerService
            self._scheduler = FleetSchedulerService(self._runtime_context)
        return self._scheduler

    def run_orphan_scan_cycle(self) -> OrphanCleanupResult:
        """
        执行完整的孤儿资源扫描和清理周期

        Returns:
            OrphanCleanupResult 包含扫描和清理结果
        """
        correlation_id = generate_correlation_id()
        original_correlation_id = self._runtime_context.correlation_id
        set_correlation_id(correlation_id)
        start_time = time.time()

        orphans: list[OrphanResourceInfo] = []
        errors: list[str] = []
        orphans_cleaned = 0
        orphans_failed = 0

        try:
            set_event_type("orphan_scan_cycle_started")
            self._logger.info("Starting orphan resource scan cycle")

            # 1. 检查数据库一致性
            db_consistency = self.check_database_consistency()
            self._log_consistency_issues(db_consistency)

            # 2. 扫描 EC2 实例孤儿
            ec2_orphans = self._scan_ec2_orphans()
            orphans.extend(ec2_orphans)

            digitalocean_orphans = self._scan_digitalocean_orphans()
            orphans.extend(digitalocean_orphans)
            digitalocean_snapshot_orphans = (
                self._scan_digitalocean_snapshot_orphans()
            )
            orphans.extend(digitalocean_snapshot_orphans)

            vultr_orphans = self._scan_vultr_orphans()
            orphans.extend(vultr_orphans)

            kamatera_orphans = self._scan_kamatera_orphans()
            orphans.extend(kamatera_orphans)

            gcp_orphans = self._scan_gcp_orphans()
            orphans.extend(gcp_orphans)

            azure_orphans = self._scan_azure_orphans()
            orphans.extend(azure_orphans)
            oci_orphans = self._scan_oci_orphans()
            orphans.extend(oci_orphans)


            # 3. 扫描节点孤儿
            node_orphans = self._scan_node_orphans()
            orphans.extend(node_orphans)

            # 4. 扫描资产分配孤儿
            allocation_orphans = self._scan_allocation_orphans()
            orphans.extend(allocation_orphans)

            # 5. 清理孤儿资源
            for orphan in orphans:
                try:
                    if self._cleanup_orphan_resource(orphan):
                        orphans_cleaned += 1
                    else:
                        orphans_failed += 1
                except Exception as exc:
                    orphans_failed += 1
                    errors.append(f"Failed to cleanup {orphan.resource_type} {orphan.resource_id}: {exc}")
                    self._logger.exception("Failed to cleanup orphan resource: %s", orphan.resource_id)

            duration = time.time() - start_time
            result = OrphanCleanupResult(
                scan_duration_seconds=duration,
                total_resources_scanned=len(orphans) + len(db_consistency.sqlite_only_nodes) + len(db_consistency.xboard_only_nodes),
                orphans_found=len(orphans),
                orphans_cleaned=orphans_cleaned,
                orphans_failed=orphans_failed,
                orphans=tuple(orphans),
                errors=tuple(errors),
            )

            self._scan_history.append(result)
            if len(self._scan_history) > 100:
                self._scan_history = self._scan_history[-100:]

            set_event_type("orphan_scan_cycle_completed")
            self._logger.info(
                "Orphan scan cycle completed: found=%d cleaned=%d failed=%d duration=%.2fs",
                len(orphans),
                orphans_cleaned,
                orphans_failed,
                duration,
            )

            # 6. 发送告警如果有孤儿资源
            if len(orphans) > 0:
                self._send_orphan_alert(len(orphans), orphans_cleaned, orphans_failed)

            return result

        except Exception as exc:
            duration = time.time() - start_time
            errors.append(f"Scan cycle failed: {exc}")
            self._logger.exception("Orphan scan cycle failed")
            set_event_type("orphan_scan_cycle_failed")
            return OrphanCleanupResult(
                scan_duration_seconds=duration,
                total_resources_scanned=0,
                orphans_found=0,
                orphans_cleaned=0,
                orphans_failed=0,
                orphans=(),
                errors=tuple(errors),
            )
        finally:
            set_correlation_id(original_correlation_id)
            set_event_type("general")

    def check_database_consistency(self) -> DatabaseConsistencyResult:
        """
        检查 Xboard 和 SQLite 之间的一致性

        Returns:
            DatabaseConsistencyResult 包含各种不一致情况
        """
        try:
            # 获取 Xboard 中的所有节点
            xboard_nodes = self._node_registry.list_all_nodes()
            xboard_nodes_by_id = {
                node_id: node
                for node in xboard_nodes
                if (node_id := _xboard_node_id(node)) is not None
            }
            xboard_node_ids = set(xboard_nodes_by_id)

            # 获取 SQLite 中的所有节点
            sqlite_nodes = self._state_repo.list_active_nodes()
            sqlite_node_ids = {n.xboard_node_id for n in sqlite_nodes}

            # 找出只在 SQLite 中存在的节点（可能是孤儿）
            sqlite_only = sqlite_node_ids - xboard_node_ids

            # 找出只在 Xboard 中存在的节点（可能是未同步）
            xboard_only = xboard_node_ids - sqlite_node_ids

            # 检查状态不一致
            status_mismatch: list[str] = []
            inconsistent_allocations: list[str] = []

            # Xboard only exposes visibility, so compare stable online/offline states.
            for node in sqlite_nodes:
                xboard_node = xboard_nodes_by_id.get(node.xboard_node_id)
                if xboard_node is None or node.status not in {"online", "offline"}:
                    continue
                expected_visible = node.status == "online"
                actual_visible = bool(getattr(xboard_node, "show", False))
                if actual_visible != expected_visible:
                    status_mismatch.append(
                        f"xboard_node_id={node.xboard_node_id}: "
                        f"sqlite_status={node.status}, xboard_show={actual_visible}"
                    )

            return DatabaseConsistencyResult(
                sqlite_only_nodes=tuple(sorted(sqlite_only)),
                xboard_only_nodes=tuple(sorted(xboard_only)),
                status_mismatch=tuple(status_mismatch),
                inconsistent_allocations=tuple(inconsistent_allocations),
            )
        except Exception as exc:
            self._logger.exception("Failed to check database consistency: %s", exc)
            return DatabaseConsistencyResult(
                sqlite_only_nodes=(),
                xboard_only_nodes=(),
                status_mismatch=(),
                inconsistent_allocations=(),
            )

    def _scan_ec2_orphans(self) -> list[OrphanResourceInfo]:
        """
        扫描 EC2 实例孤儿

        查找 AWS 上存在但 SQLite 中没有对应记录的实例
        """
        orphans: list[OrphanResourceInfo] = []

        try:
            # 获取所有活跃的 AWS 账户
            assets = self._asset_repo.list_assets_by_status("active")
            aws_assets = [a for a in assets if a.asset_type == "aws" and a.aws_access_key]

            for asset in aws_assets:
                try:
                    # 创建 EC2 客户端
                    from services.provisioning_support import build_aws_credential
                    aws_cred = build_aws_credential(asset)
                    ec2_client = EC2Client(
                        runtime_context=self._runtime_context,
                        aws_credential=aws_cred,
                    )

                    # 获取所有 ShadowFleet 创建的实例（通过名称前缀）
                    # 注意：这需要实例有 Name tag 以 sf- 开头
                    instances = ec2_client._execute_ec2_call(
                        operation_name="describe_orphan_instances",
                        func=lambda: ec2_client._ec2_client.describe_instances(
                            Filters=[
                                {"Name": "tag:Name", "Values": ["sf-*"]},
                            ]
                        ),
                    )

                    # 获取 SQLite 中的实例 ID
                    sqlite_instances = self._state_repo.list_active_nodes()
                    sqlite_instance_ids = {
                        n.aws_instance_id for n in sqlite_instances
                        if n.aws_instance_id
                    }

                    # 找出孤儿实例
                    for reservation in instances.get("Reservations", []):
                        for instance in reservation.get("Instances", []):
                            instance_id = instance.get("InstanceId")
                            state = instance.get("State", {}).get("Name")

                            # 跳过已终止的实例
                            if state == "terminated":
                                continue

                            if instance_id and instance_id not in sqlite_instance_ids:
                                orphans.append(OrphanResourceInfo(
                                    resource_type="ec2_instance",
                                    resource_id=instance_id,
                                    region=asset.region,
                                    aws_account_id=asset.aws_account_id,
                                    reason=f"Instance exists in AWS but not in SQLite (state={state})",
                                    discovered_at=datetime.utcnow().isoformat(),
                                ))
                                self._logger.warning(
                                    "Found orphan EC2 instance: %s in %s/%s (state=%s)",
                                    instance_id,
                                    asset.aws_account_id,
                                    asset.region,
                                    state,
                                )

                except Exception as exc:
                    self._logger.warning(
                        "Failed to scan EC2 orphans for asset %s: %s",
                        asset.asset_name,
                        exc,
                    )

        except Exception as exc:
            self._logger.exception("Failed to scan EC2 orphans: %s", exc)

        return orphans

    def _scan_digitalocean_orphans(self) -> list[OrphanResourceInfo]:
        orphans: list[OrphanResourceInfo] = []
        try:
            assets = self._asset_repo.list_assets_by_status("active")
            digitalocean_assets = [
                asset
                for asset in assets
                if asset.asset_type == "digitalocean" and asset.aws_access_key
            ]
            known_ids = {
                node.aws_instance_id
                for node in self._state_repo.list_active_nodes()
                if node.aws_instance_id
            }
            scanned_accounts: set[str] = set()
            for asset in digitalocean_assets:
                scope = (asset.aws_account_id or f"asset:{asset.id}").casefold()
                if scope in scanned_accounts:
                    continue
                try:
                    client = DigitalOceanClient(
                        self._runtime_context,
                        api_token=asset.aws_access_key,
                    )
                    droplets = client.list_droplets(tag_name="shadowfleet")
                    scanned_accounts.add(scope)
                    for droplet in droplets:
                        droplet_id = str(droplet.get("id") or "").strip()
                        raw_tags = droplet.get("tags")
                        tags = {
                            str(tag).strip().casefold()
                            for tag in raw_tags
                            if str(tag).strip()
                        } if isinstance(raw_tags, list) else set()
                        if (
                            not droplet_id
                            or "shadowfleet" not in tags
                            or droplet_id in known_ids
                        ):
                            continue
                        created_at = str(droplet.get("created_at") or "").strip()
                        if not self._resource_age_exceeded(created_at):
                            continue
                        region = droplet.get("region")
                        region_slug = (
                            str(region.get("slug") or "").strip()
                            if isinstance(region, dict)
                            else str(region or asset.region or "").strip()
                        )
                        orphans.append(
                            OrphanResourceInfo(
                                resource_type="digitalocean_droplet",
                                resource_id=droplet_id,
                                region=region_slug,
                                aws_account_id=asset.aws_account_id,
                                asset_id=asset.id,
                                reason=(
                                    "Droplet exists in DigitalOcean but not in SQLite"
                                ),
                                discovered_at=datetime.utcnow().isoformat(),
                            )
                        )
                except Exception as exc:
                    self._logger.warning(
                        "Failed to scan DigitalOcean orphans for asset %s: %s",
                        asset.asset_name,
                        exc,
                    )
        except Exception as exc:
            self._logger.exception("Failed to scan DigitalOcean orphans: %s", exc)
        return orphans

    def _scan_digitalocean_snapshot_orphans(self) -> list[OrphanResourceInfo]:
        orphans: list[OrphanResourceInfo] = []
        try:
            assets = self._asset_repo.list_assets_by_status("active")
            digitalocean_assets = [
                asset
                for asset in assets
                if asset.asset_type == "digitalocean" and asset.aws_access_key
            ]
            scanned_accounts: set[str] = set()
            for asset in digitalocean_assets:
                scope = (asset.aws_account_id or f"asset:{asset.id}").casefold()
                if scope in scanned_accounts:
                    continue
                try:
                    client = DigitalOceanClient(
                        self._runtime_context,
                        api_token=asset.aws_access_key,
                    )
                    snapshots = client.list_snapshots(resource_type="droplet")
                    scanned_accounts.add(scope)
                    for snapshot in snapshots:
                        snapshot_id = str(snapshot.get("id") or "").strip()
                        name = str(snapshot.get("name") or "").strip()
                        if not snapshot_id or not name.startswith("shadowfleet-heal-"):
                            continue
                        created_at = str(snapshot.get("created_at") or "").strip()
                        if not self._resource_age_exceeded(created_at):
                            continue
                        orphans.append(
                            OrphanResourceInfo(
                                resource_type="digitalocean_snapshot",
                                resource_id=snapshot_id,
                                aws_account_id=asset.aws_account_id,
                                asset_id=asset.id,
                                reason=(
                                    "Temporary DigitalOcean healing snapshot was not deleted"
                                ),
                                discovered_at=datetime.utcnow().isoformat(),
                            )
                        )
                except Exception as exc:
                    self._logger.warning(
                        "Failed to scan DigitalOcean snapshot orphans for asset %s: %s",
                        asset.asset_name,
                        exc,
                    )
        except Exception as exc:
            self._logger.exception(
                "Failed to scan DigitalOcean snapshot orphans: %s",
                exc,
            )
        return orphans
    def _scan_vultr_orphans(self) -> list[OrphanResourceInfo]:
        orphans: list[OrphanResourceInfo] = []
        try:
            assets = self._asset_repo.list_assets_by_status("active")
            vultr_assets = [
                asset
                for asset in assets
                if asset.asset_type == "vultr" and asset.aws_access_key
            ]
            known_ids = {
                node.aws_instance_id
                for node in self._state_repo.list_active_nodes()
                if node.aws_instance_id
            }
            for asset in vultr_assets:
                try:
                    client = VultrClient(
                        self._runtime_context,
                        api_token=asset.aws_access_key,
                    )
                    for instance in client.list_instances():
                        instance_id = str(instance.get("id") or "").strip()
                        raw_tags = instance.get("tags")
                        tags = {
                            str(tag).strip().lower()
                            for tag in raw_tags
                            if str(tag).strip()
                        } if isinstance(raw_tags, list) else set()
                        if not instance_id or "shadowfleet" not in tags or instance_id in known_ids:
                            continue
                        created_at = str(instance.get("date_created") or "").strip()
                        if not self._resource_age_exceeded(created_at):
                            continue
                        orphans.append(
                            OrphanResourceInfo(
                                resource_type="vultr_instance",
                                resource_id=instance_id,
                                region=str(instance.get("region") or asset.region or ""),
                                aws_account_id=asset.aws_account_id,
                                asset_id=asset.id,
                                firewall_group_id=(
                                    str(instance.get("firewall_group_id") or "").strip() or None
                                ),
                                reason="Instance exists in Vultr but not in SQLite",
                                discovered_at=datetime.utcnow().isoformat(),
                            )
                        )
                except Exception as exc:
                    self._logger.warning(
                        "Failed to scan Vultr orphans for asset %s: %s",
                        asset.asset_name,
                        exc,
                    )
        except Exception as exc:
            self._logger.exception("Failed to scan Vultr orphans: %s", exc)
        return orphans

    def _scan_kamatera_orphans(self) -> list[OrphanResourceInfo]:
        orphans: list[OrphanResourceInfo] = []
        try:
            assets = self._asset_repo.list_assets_by_status("active")
            known_ids = {
                node.aws_instance_id
                for node in self._state_repo.list_active_nodes()
                if node.aws_instance_id
            }
            scanned_accounts: set[str] = set()
            for asset in assets:
                if (
                    asset.asset_type != "kamatera"
                    or not asset.aws_access_key
                    or not asset.aws_secret_key
                ):
                    continue
                scope = (asset.aws_account_id or f"asset:{asset.id}").casefold()
                if scope in scanned_accounts:
                    continue
                try:
                    client = KamateraClient(
                        self._runtime_context,
                        client_id=asset.aws_access_key,
                        secret=asset.aws_secret_key,
                    )
                    servers = client.list_servers()
                    scanned_accounts.add(scope)
                    for summary in servers:
                        server_id = str(summary.get("id") or "").strip()
                        if not server_id or server_id in known_ids:
                            continue
                        server = client.get_server(server_id)
                        tags = server_tags(server) or client.list_server_tags(server_id)
                        if "shadowfleet" not in {tag.casefold() for tag in tags}:
                            continue
                        created_at = server_created_at(server)
                        if not self._resource_age_exceeded(created_at):
                            continue
                        orphans.append(
                            OrphanResourceInfo(
                                resource_type="kamatera_server",
                                resource_id=server_id,
                                region=str(server.get("datacenter") or asset.region or ""),
                                aws_account_id=asset.aws_account_id,
                                asset_id=asset.id,
                                reason="Server exists in Kamatera but not in SQLite",
                                discovered_at=datetime.utcnow().isoformat(),
                            )
                        )
                except Exception as exc:
                    self._logger.warning(
                        "Failed to scan Kamatera orphans for asset %s: %s",
                        asset.asset_name,
                        exc,
                    )
        except Exception as exc:
            self._logger.exception("Failed to scan Kamatera orphans: %s", exc)
        return orphans

    def _scan_gcp_orphans(self) -> list[OrphanResourceInfo]:
        orphans: list[OrphanResourceInfo] = []
        try:
            assets = self._asset_repo.list_assets_by_status("active")
            known_ids = {
                str(node.aws_instance_id).casefold()
                for node in self._state_repo.list_active_nodes()
                if node.aws_instance_id
            }
            scanned_scopes: set[tuple[str, str]] = set()
            for asset in assets:
                config = asset.provider_config
                if (
                    asset.asset_type != "gcp"
                    or not asset.aws_access_key
                    or not asset.aws_secret_key
                    or not asset.region
                    or not isinstance(config, dict)
                ):
                    continue
                project_id = str(config.get("project_id") or "").strip()
                if not project_id:
                    continue
                scope = (project_id.casefold(), asset.region.casefold())
                if scope in scanned_scopes:
                    continue
                try:
                    client = self._build_gcp_client(asset)
                    instances = client.list_instances(asset.region)
                    scanned_scopes.add(scope)
                    for instance in instances:
                        name = str(instance.get("name") or "").strip()
                        labels = instance.get("labels")
                        managed = (
                            isinstance(labels, dict)
                            and str(labels.get("managed-by") or "").casefold()
                            == "shadowfleet"
                        )
                        status = str(instance.get("status") or "unknown")
                        if (
                            not name
                            or not managed
                            or name.casefold() in known_ids
                            or status.upper() in {"TERMINATED", "SUSPENDING"}
                        ):
                            continue
                        created_at = str(
                            instance.get("creationTimestamp") or ""
                        ).strip()
                        if not self._resource_age_exceeded(created_at):
                            continue
                        orphans.append(
                            OrphanResourceInfo(
                                resource_type="gcp_instance",
                                resource_id=name,
                                region=asset.region,
                                aws_account_id=asset.aws_account_id,
                                asset_id=asset.id,
                                reason="Instance exists in GCP but not in SQLite",
                                discovered_at=datetime.utcnow().isoformat(),
                            )
                        )
                except Exception as exc:
                    self._logger.warning(
                        "Failed to scan GCP orphans for asset %s: %s",
                        asset.asset_name,
                        exc,
                    )
        except Exception as exc:
            self._logger.exception("Failed to scan GCP orphans: %s", exc)
        return orphans

    def _scan_oci_orphans(self) -> list[OrphanResourceInfo]:
        orphans: list[OrphanResourceInfo] = []
        try:
            assets = self._asset_repo.list_assets_by_status("active")
            known_ids = {
                node.aws_instance_id
                for node in self._state_repo.list_active_nodes()
                if node.aws_instance_id
            }
            scanned_scopes: set[tuple[str, str, str]] = set()
            for asset in assets:
                if asset.asset_type != "oci":
                    continue
                config = asset.provider_config
                if not isinstance(config, dict) or not asset.region:
                    continue
                tenancy_ocid = str(config.get("tenancy_ocid") or "").strip()
                compartment_ocid = str(config.get("compartment_ocid") or "").strip()
                if not tenancy_ocid or not compartment_ocid:
                    continue
                scope = (
                    tenancy_ocid.casefold(),
                    compartment_ocid.casefold(),
                    asset.region.casefold(),
                )
                if scope in scanned_scopes:
                    continue
                try:
                    client = self._build_oci_client(asset)
                    instances = client.list_instances(compartment_ocid)
                    scanned_scopes.add(scope)
                    for instance in instances:
                        instance_id = str(instance.get("id") or "").strip()
                        tags = instance.get("freeformTags")
                        managed = (
                            isinstance(tags, dict)
                            and str(tags.get("ManagedBy") or "") == "ShadowFleet"
                        )
                        state = str(instance.get("lifecycleState") or "unknown")
                        if (
                            not instance_id
                            or not managed
                            or instance_id in known_ids
                            or state.upper() in {"TERMINATED", "TERMINATING"}
                        ):
                            continue
                        created_at = str(instance.get("timeCreated") or "").strip()
                        if not self._resource_age_exceeded(created_at):
                            continue
                        orphans.append(
                            OrphanResourceInfo(
                                resource_type="oci_instance",
                                resource_id=instance_id,
                                region=asset.region,
                                aws_account_id=asset.aws_account_id,
                                asset_id=asset.id,
                                reason="Instance exists in OCI but not in SQLite",
                                discovered_at=datetime.utcnow().isoformat(),
                            )
                        )
                except Exception as exc:
                    self._logger.warning(
                        "Failed to scan OCI orphans for asset %s: %s",
                        asset.asset_name,
                        exc,
                    )
        except Exception as exc:
            self._logger.exception("Failed to scan OCI orphans: %s", exc)
        return orphans

    def _scan_azure_orphans(self) -> list[OrphanResourceInfo]:
        orphans: list[OrphanResourceInfo] = []
        try:
            assets = self._asset_repo.list_assets_by_status("active")
            scanned_scopes: set[tuple[str, str]] = set()
            known_ids = {
                str(node.aws_instance_id).lower()
                for node in self._state_repo.list_active_nodes()
                if node.aws_instance_id
            }
            for asset in assets:
                if asset.asset_type != "azure":
                    continue
                config = asset.provider_config
                if not isinstance(config, dict):
                    continue
                resource_group = str(config.get("resource_group") or "").strip()
                subscription_id = str(config.get("subscription_id") or "").strip()
                if not resource_group or not subscription_id:
                    continue
                scope = (subscription_id.casefold(), resource_group.casefold())
                if scope in scanned_scopes:
                    continue
                try:
                    client = self._build_azure_client(asset)
                    virtual_machines = client.list_virtual_machines(resource_group)
                    resource_collections = (
                        client.list_network_interfaces(resource_group),
                        client.list_public_ip_addresses(resource_group),
                        client.list_network_security_groups(resource_group),
                    )
                    scanned_scopes.add(scope)
                    live_vm_names = {
                        azure_vm_name(vm).casefold()
                        for vm in virtual_machines
                        if azure_vm_name(vm)
                    }
                    for vm in virtual_machines:
                        vm_id = str(vm.get("id") or "").strip()
                        tags = vm.get("tags")
                        managed = (
                            isinstance(tags, dict)
                            and str(tags.get("shadowfleet") or "").lower() == "true"
                        )
                        if not vm_id or not managed or vm_id.lower() in known_ids:
                            continue
                        properties = vm.get("properties")
                        created_at = str(
                            properties.get("timeCreated") if isinstance(properties, dict) else ""
                        ).strip()
                        if not self._resource_age_exceeded(created_at):
                            continue
                        orphans.append(
                            OrphanResourceInfo(
                                resource_type="azure_vm",
                                resource_id=vm_id,
                                region=str(vm.get("location") or asset.region or ""),
                                aws_account_id=asset.aws_account_id,
                                asset_id=asset.id,
                                reason="VM exists in Azure but not in SQLite",
                                discovered_at=datetime.utcnow().isoformat(),
                            )
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
                            resource_name = str(resource.get("name") or "").strip()
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
                            if not self._resource_age_exceeded(created_at):
                                continue
                            orphans.append(
                                OrphanResourceInfo(
                                    resource_type=spec.resource_type,
                                    resource_id=resource_id,
                                    region=str(
                                        resource.get("location")
                                        or asset.region
                                        or ""
                                    ),
                                    aws_account_id=asset.aws_account_id,
                                    asset_id=asset.id,
                                    reason=(
                                        f"Azure {spec.resource_type} exists without "
                                        f"parent VM {parent_vm_name}"
                                    ),
                                    discovered_at=datetime.utcnow().isoformat(),
                                )
                            )
                except Exception as exc:
                    self._logger.warning(
                        "Failed to scan Azure orphans for asset %s: %s",
                        asset.asset_name,
                        exc,
                    )
        except Exception as exc:
            self._logger.exception("Failed to scan Azure orphans: %s", exc)
        return orphans

    @staticmethod
    def _resource_age_exceeded(created_at: str) -> bool:
        if not created_at:
            return False
        try:
            timestamp = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError:
            return False
        return datetime.utcnow() - timestamp.replace(tzinfo=None) > timedelta(hours=1)

    def _resolve_node_asset_type(self, node: FleetNodeRecord) -> str:
        asset = self._asset_repo.get_asset_by_xboard_node_id(node.xboard_node_id)
        if asset is not None and isinstance(asset.asset_type, str):
            return asset.asset_type
        if isinstance(node.aws_account_id, str):
            candidates = self._asset_repo.list_assets_by_aws_account_id(
                node.aws_account_id
            )
            candidate_types = {
                candidate.asset_type
                for candidate in candidates
                if isinstance(candidate.asset_type, str)
            }
            if len(candidate_types) == 1:
                return candidate_types.pop()
        return infer_node_asset_type(node)

    def _scan_node_orphans(self) -> list[OrphanResourceInfo]:
        """
        扫描节点孤儿

        查找 SQLite 中存在但 AWS 上已不存在的节点
        """
        orphans: list[OrphanResourceInfo] = []

        try:
            active_nodes = self._state_repo.list_active_nodes()

            for node in active_nodes:
                if not node.aws_instance_id or not node.aws_account_id:
                    continue
                asset_type = self._resolve_node_asset_type(node)
                if asset_type == "digitalocean":
                    try:
                        orphan = self._scan_digitalocean_node_orphan(node)
                        if orphan is not None:
                            orphans.append(orphan)
                    except Exception as exc:
                        self._logger.warning(
                            "DigitalOcean node scan is indeterminate for node %s Droplet %s: %s",
                            node.xboard_node_id,
                            node.aws_instance_id,
                            exc,
                        )
                    continue
                if asset_type == "vultr":
                    try:
                        orphan = self._scan_vultr_node_orphan(node)
                        if orphan is not None:
                            orphans.append(orphan)
                    except Exception as exc:
                        self._logger.warning(
                            "Vultr node scan is indeterminate for node %s instance %s: %s",
                            node.xboard_node_id,
                            node.aws_instance_id,
                            exc,
                        )
                    continue
                if asset_type == "gcp":
                    try:
                        orphan = self._scan_gcp_node_orphan(node)
                        if orphan is not None:
                            orphans.append(orphan)
                    except Exception as exc:
                        self._logger.warning(
                            "GCP node scan is indeterminate for node %s instance %s: %s",
                            node.xboard_node_id,
                            node.aws_instance_id,
                            exc,
                        )
                    continue
                if asset_type == "kamatera":
                    try:
                        orphan = self._scan_kamatera_node_orphan(node)
                        if orphan is not None:
                            orphans.append(orphan)
                    except Exception as exc:
                        self._logger.warning(
                            "Kamatera node scan is indeterminate for node %s server %s: %s",
                            node.xboard_node_id,
                            node.aws_instance_id,
                            exc,
                        )
                    continue
                if asset_type == "azure":
                    try:
                        orphan = self._scan_azure_node_orphan(node)
                        if orphan is not None:
                            orphans.append(orphan)
                    except Exception as exc:
                        self._logger.warning(
                            "Azure node scan is indeterminate for node %s VM %s: %s",
                            node.xboard_node_id,
                            node.aws_instance_id,
                            exc,
                        )
                    continue
                if asset_type == "oci":
                    try:
                        orphan = self._scan_oci_node_orphan(node)
                        if orphan is not None:
                            orphans.append(orphan)
                    except Exception as exc:
                        self._logger.warning(
                            "OCI node scan is indeterminate for node %s instance %s: %s",
                            node.xboard_node_id,
                            node.aws_instance_id,
                            exc,
                        )
                    continue
                if asset_type != "aws":
                    continue

                try:
                    # 尝试获取实例状态
                    from services.provisioning_support import build_aws_credential
                    from database.asset_repo_helpers import utcnow_iso

                    # 获取资产凭证
                    assets = self._asset_repo.list_assets_by_aws_account_id(node.aws_account_id)
                    if not assets:
                        self._logger.warning(
                            "AWS node scan is indeterminate because asset credentials were not "
                            "found: node=%s account=%s",
                            node.xboard_node_id,
                            node.aws_account_id,
                        )
                        continue

                    asset = assets[0]
                    aws_cred = build_aws_credential(asset)
                    ec2_client = EC2Client(
                        runtime_context=self._runtime_context,
                        aws_credential=aws_cred,
                    )

                    # 检查实例状态
                    try:
                        state = ec2_client.get_instance_state(node.aws_instance_id)
                        if state in ("terminated", "shutting-down"):
                            orphans.append(OrphanResourceInfo(
                                resource_type="xboard_node",
                                resource_id=str(node.xboard_node_id),
                                region=node.aws_region,
                                aws_account_id=node.aws_account_id,
                                xboard_node_id=node.xboard_node_id,
                                reason=f"EC2 instance state is {state}",
                                discovered_at=utcnow_iso(),
                            ))
                            self._logger.warning(
                                "Found orphan node: xboard_node_id=%s instance=%s state=%s",
                                node.xboard_node_id,
                                node.aws_instance_id,
                                state,
                            )
                    except ValueError:
                        # 实例不存在
                        orphans.append(OrphanResourceInfo(
                            resource_type="xboard_node",
                            resource_id=str(node.xboard_node_id),
                            region=node.aws_region,
                            aws_account_id=node.aws_account_id,
                            xboard_node_id=node.xboard_node_id,
                            reason="EC2 instance not found in AWS",
                            discovered_at=utcnow_iso(),
                        ))
                        self._logger.warning(
                            "Found orphan node: xboard_node_id=%s instance=%s (instance not found)",
                            node.xboard_node_id,
                            node.aws_instance_id,
                        )

                except Exception as exc:
                    self._logger.warning(
                        "Failed to check node %s instance %s: %s",
                        node.xboard_node_id,
                        node.aws_instance_id,
                        exc,
                    )

        except Exception as exc:
            self._logger.exception("Failed to scan node orphans: %s", exc)

        return orphans

    def _scan_digitalocean_node_orphan(
        self,
        node: FleetNodeRecord,
    ) -> OrphanResourceInfo | None:
        asset = self._asset_repo.get_asset_by_xboard_node_id(node.xboard_node_id)
        if asset is None and node.aws_account_id:
            asset = next(
                (
                    candidate
                    for candidate in self._asset_repo.list_assets_by_aws_account_id(
                        node.aws_account_id
                    )
                    if candidate.asset_type == "digitalocean"
                ),
                None,
            )
        if (
            asset is None
            or asset.asset_type != "digitalocean"
            or not asset.aws_access_key
        ):
            self._logger.warning(
                "DigitalOcean node scan is indeterminate because asset credentials "
                "were not found: node=%s account=%s",
                node.xboard_node_id,
                node.aws_account_id,
            )
            return None
        try:
            DigitalOceanClient(
                self._runtime_context,
                api_token=asset.aws_access_key,
            ).get_droplet(node.aws_instance_id or "")
        except DigitalOceanClientError as exc:
            if exc.status_code != 404:
                raise
            return OrphanResourceInfo(
                resource_type="xboard_node",
                resource_id=str(node.xboard_node_id),
                region=node.aws_region,
                aws_account_id=node.aws_account_id,
                xboard_node_id=node.xboard_node_id,
                reason="DigitalOcean Droplet not found",
                discovered_at=datetime.utcnow().isoformat(),
            )
        return None

    def _scan_vultr_node_orphan(self, node: FleetNodeRecord) -> OrphanResourceInfo | None:
        asset = self._asset_repo.get_asset_by_xboard_node_id(node.xboard_node_id)
        if asset is None and node.aws_account_id:
            asset = next(
                (
                    candidate
                    for candidate in self._asset_repo.list_assets_by_aws_account_id(
                        node.aws_account_id
                    )
                    if candidate.asset_type == "vultr"
                ),
                None,
            )
        if asset is None or asset.asset_type != "vultr" or not asset.aws_access_key:
            self._logger.warning(
                "Vultr node scan is indeterminate because asset credentials were not found: "
                "node=%s account=%s",
                node.xboard_node_id,
                node.aws_account_id,
            )
            return None
        try:
            VultrClient(
                self._runtime_context,
                api_token=asset.aws_access_key,
            ).get_instance(node.aws_instance_id or "")
        except VultrClientError as exc:
            if exc.status_code != 404:
                raise
            return OrphanResourceInfo(
                resource_type="xboard_node",
                resource_id=str(node.xboard_node_id),
                region=node.aws_region,
                aws_account_id=node.aws_account_id,
                xboard_node_id=node.xboard_node_id,
                reason="Vultr instance not found",
                discovered_at=datetime.utcnow().isoformat(),
            )
        return None

    def _scan_azure_node_orphan(self, node: FleetNodeRecord) -> OrphanResourceInfo | None:
        asset = self._asset_repo.get_asset_by_xboard_node_id(node.xboard_node_id)
        if asset is None and node.aws_account_id:
            asset = next(
                (
                    candidate
                    for candidate in self._asset_repo.list_assets_by_aws_account_id(
                        node.aws_account_id
                    )
                    if candidate.asset_type == "azure"
                ),
                None,
            )
        if asset is None or asset.asset_type != "azure":
            self._logger.warning(
                "Azure node scan is indeterminate because asset credentials were not found: "
                "node=%s account=%s",
                node.xboard_node_id,
                node.aws_account_id,
            )
            return None
        try:
            self._build_azure_client(asset).get_vm(node.aws_instance_id or "")
        except AzureClientError as exc:
            if exc.status_code != 404:
                raise
            return OrphanResourceInfo(
                resource_type="xboard_node",
                resource_id=str(node.xboard_node_id),
                region=node.aws_region,
                aws_account_id=node.aws_account_id,
                xboard_node_id=node.xboard_node_id,
                reason="Azure VM not found",
                discovered_at=datetime.utcnow().isoformat(),
            )
        return None

    def _scan_kamatera_node_orphan(
        self,
        node: FleetNodeRecord,
    ) -> OrphanResourceInfo | None:
        asset = self._asset_repo.get_asset_by_xboard_node_id(node.xboard_node_id)
        if asset is None and node.aws_account_id:
            asset = next(
                (
                    candidate
                    for candidate in self._asset_repo.list_assets_by_aws_account_id(
                        node.aws_account_id
                    )
                    if candidate.asset_type == "kamatera"
                ),
                None,
            )
        if (
            asset is None
            or asset.asset_type != "kamatera"
            or not asset.aws_access_key
            or not asset.aws_secret_key
        ):
            self._logger.warning(
                "Kamatera node scan is indeterminate because asset credentials were not found: "
                "node=%s account=%s",
                node.xboard_node_id,
                node.aws_account_id,
            )
            return None
        try:
            KamateraClient(
                self._runtime_context,
                client_id=asset.aws_access_key,
                secret=asset.aws_secret_key,
            ).get_server(node.aws_instance_id or "")
        except KamateraClientError as exc:
            if exc.status_code != 404:
                raise
            return OrphanResourceInfo(
                resource_type="xboard_node",
                resource_id=str(node.xboard_node_id),
                region=node.aws_region,
                aws_account_id=node.aws_account_id,
                xboard_node_id=node.xboard_node_id,
                reason="Kamatera server not found",
                discovered_at=datetime.utcnow().isoformat(),
            )
        return None

    def _scan_gcp_node_orphan(
        self,
        node: FleetNodeRecord,
    ) -> OrphanResourceInfo | None:
        asset = self._asset_repo.get_asset_by_xboard_node_id(
            node.xboard_node_id
        )
        if asset is None and node.aws_account_id:
            asset = next(
                (
                    candidate
                    for candidate in self._asset_repo.list_assets_by_aws_account_id(
                        node.aws_account_id
                    )
                    if candidate.asset_type == "gcp"
                ),
                None,
            )
        if asset is None or asset.asset_type != "gcp":
            raise ValueError("GCP asset credentials are unavailable")
        zone = node.aws_region or asset.region
        if not zone or not node.aws_instance_id:
            raise ValueError("GCP node zone or instance name is missing")
        try:
            instance = self._build_gcp_client(asset).get_instance(
                zone,
                node.aws_instance_id,
            )
        except GCPClientError as exc:
            if exc.status_code != 404:
                raise
            instance = None
        state = (
            str(instance.get("status") or "").upper()
            if isinstance(instance, dict)
            else "NOT_FOUND"
        )
        if state not in {"NOT_FOUND", "TERMINATED", "SUSPENDED"}:
            return None
        return OrphanResourceInfo(
            resource_type="xboard_node",
            resource_id=str(node.xboard_node_id),
            region=zone,
            aws_account_id=node.aws_account_id,
            xboard_node_id=node.xboard_node_id,
            reason=f"GCP instance state is {state}",
            discovered_at=datetime.utcnow().isoformat(),
        )

    def _scan_oci_node_orphan(
        self,
        node: FleetNodeRecord,
    ) -> OrphanResourceInfo | None:
        asset = self._asset_repo.get_asset_by_xboard_node_id(node.xboard_node_id)
        if asset is None and node.aws_account_id:
            asset = next(
                (
                    candidate
                    for candidate in self._asset_repo.list_assets_by_aws_account_id(
                        node.aws_account_id
                    )
                    if candidate.asset_type == "oci"
                ),
                None,
            )
        if asset is None or asset.asset_type != "oci":
            self._logger.warning(
                "OCI node scan is indeterminate because asset credentials were not found: "
                "node=%s account=%s",
                node.xboard_node_id,
                node.aws_account_id,
            )
            return None
        try:
            instance = self._build_oci_client(asset).get_instance(
                node.aws_instance_id or ""
            )
            state = str(instance.get("lifecycleState") or "").upper()
            if state not in {"TERMINATED", "TERMINATING"}:
                return None
            reason = f"OCI instance state is {state}"
        except OCIClientError as exc:
            if exc.status_code != 404:
                raise
            reason = "OCI instance not found"
        return OrphanResourceInfo(
            resource_type="xboard_node",
            resource_id=str(node.xboard_node_id),
            region=node.aws_region,
            aws_account_id=node.aws_account_id,
            xboard_node_id=node.xboard_node_id,
            reason=reason,
            discovered_at=datetime.utcnow().isoformat(),
        )

    def _scan_allocation_orphans(self) -> list[OrphanResourceInfo]:
        """
        扫描资产分配孤儿

        查找分配记录与实际资源不匹配的情况
        """
        orphans: list[OrphanResourceInfo] = []

        try:

            sql = """
                SELECT
                    allocation.id,
                    allocation.asset_id,
                    allocation.fleet_node_id,
                    allocation.xboard_node_id,
                    node.id AS actual_fleet_node_id,
                    node.is_deleted
                FROM fleet_asset_allocations AS allocation
                LEFT JOIN fleet_nodes AS node
                    ON node.xboard_node_id = allocation.xboard_node_id
                WHERE allocation.allocation_status = 'allocated'
                  AND (
                        allocation.xboard_node_id IS NULL
                        OR node.id IS NULL
                        OR node.is_deleted = 1
                        OR (
                            allocation.fleet_node_id IS NOT NULL
                            AND allocation.fleet_node_id != node.id
                        )
                  )
                ORDER BY allocation.id ASC
            """
            with self._runtime_context.sqlite_manager.connection() as connection:
                rows = connection.execute(sql).fetchall()
            for row in rows:
                xboard_node_id = (
                    int(row["xboard_node_id"])
                    if row["xboard_node_id"] is not None
                    else None
                )
                if xboard_node_id is None:
                    reason = "Active allocation has no Xboard node binding"
                elif row["actual_fleet_node_id"] is None:
                    reason = "Active allocation references a missing fleet node"
                elif bool(row["is_deleted"]):
                    reason = "Active allocation references a deleted fleet node"
                else:
                    reason = "Active allocation fleet node binding is inconsistent"
                orphans.append(
                    OrphanResourceInfo(
                        resource_type="asset_allocation",
                        resource_id=str(row["id"]),
                        xboard_node_id=xboard_node_id,
                        asset_id=int(row["asset_id"]),
                        reason=reason,
                        discovered_at=datetime.utcnow().isoformat(),
                    )
                )

        except Exception as exc:
            self._logger.exception("Failed to scan allocation orphans: %s", exc)

        return orphans

    def _cleanup_orphan_resource(self, orphan: OrphanResourceInfo) -> bool:
        """
        清理单个孤儿资源

        Returns:
            True 如果清理成功，False 否则
        """
        try:
            if orphan.resource_type == "ec2_instance":
                return self._cleanup_ec2_orphan(orphan)
            elif orphan.resource_type == "digitalocean_droplet":
                return self._cleanup_digitalocean_orphan(orphan)
            elif orphan.resource_type == "digitalocean_snapshot":
                return self._cleanup_digitalocean_snapshot_orphan(orphan)
            elif orphan.resource_type == "vultr_instance":
                return self._cleanup_vultr_orphan(orphan)
            elif orphan.resource_type == "kamatera_server":
                return self._cleanup_kamatera_orphan(orphan)
            elif orphan.resource_type == "gcp_instance":
                return self._cleanup_gcp_orphan(orphan)
            elif orphan.resource_type == "oci_instance":
                return self._cleanup_oci_orphan(orphan)
            elif orphan.resource_type == "azure_vm":
                return self._cleanup_azure_orphan(orphan)
            elif orphan.resource_type in AZURE_NETWORK_RESOURCE_TYPES:
                return self._cleanup_azure_network_orphan(orphan)
            elif orphan.resource_type == "xboard_node":
                return self._cleanup_node_orphan(orphan)
            elif orphan.resource_type == "asset_allocation":
                return self._cleanup_allocation_orphan(orphan)
            else:
                self._logger.warning("Unknown orphan resource type: %s", orphan.resource_type)
                return False
        except Exception as exc:
            self._logger.exception("Failed to cleanup orphan %s: %s", orphan.resource_id, exc)
            return False

    def _cleanup_allocation_orphan(
        self,
        orphan: OrphanResourceInfo,
    ) -> bool:
        allocation_id = int(orphan.resource_id)
        released = self._asset_repo.release_allocation_by_id(allocation_id)
        if released:
            set_event_type("orphan_asset_allocation_released")
        return released

    def _cleanup_digitalocean_orphan(self, orphan: OrphanResourceInfo) -> bool:
        if orphan.asset_id is None:
            self._logger.warning("Cannot cleanup DigitalOcean orphan: no asset_id")
            return False
        try:
            asset = self._asset_repo.get_asset_by_id(orphan.asset_id)
            if asset.asset_type != "digitalocean" or not asset.aws_access_key:
                return False
            DigitalOceanClient(
                self._runtime_context,
                api_token=asset.aws_access_key,
            ).delete_droplet(orphan.resource_id)
            set_event_type("orphan_digitalocean_droplet_deleted")
            return True
        except Exception as exc:
            self._logger.warning(
                "Failed to delete orphan DigitalOcean Droplet %s: %s",
                orphan.resource_id,
                exc,
            )
            return False

    def _cleanup_digitalocean_snapshot_orphan(
        self,
        orphan: OrphanResourceInfo,
    ) -> bool:
        if orphan.asset_id is None:
            self._logger.warning(
                "Cannot cleanup DigitalOcean snapshot orphan: no asset_id"
            )
            return False
        try:
            asset = self._asset_repo.get_asset_by_id(orphan.asset_id)
            if asset.asset_type != "digitalocean" or not asset.aws_access_key:
                return False
            DigitalOceanClient(
                self._runtime_context,
                api_token=asset.aws_access_key,
            ).delete_snapshot(orphan.resource_id)
            set_event_type("orphan_digitalocean_snapshot_deleted")
            return True
        except Exception as exc:
            self._logger.warning(
                "Failed to delete orphan DigitalOcean snapshot %s: %s",
                orphan.resource_id,
                exc,
            )
            return False
    def _cleanup_vultr_orphan(self, orphan: OrphanResourceInfo) -> bool:
        if orphan.asset_id is None:
            self._logger.warning("Cannot cleanup Vultr orphan: no asset_id")
            return False
        try:
            asset = self._asset_repo.get_asset_by_id(orphan.asset_id)
            if asset.asset_type != "vultr" or not asset.aws_access_key:
                return False
            client = VultrClient(
                self._runtime_context,
                api_token=asset.aws_access_key,
            )
            client.delete_instance(orphan.resource_id)
            if orphan.firewall_group_id:
                client.delete_managed_firewall_group(orphan.firewall_group_id)
            set_event_type("orphan_vultr_instance_deleted")
            return True
        except Exception as exc:
            self._logger.warning(
                "Failed to delete orphan Vultr instance %s: %s",
                orphan.resource_id,
                exc,
            )
            return False

    def _cleanup_kamatera_orphan(self, orphan: OrphanResourceInfo) -> bool:
        if orphan.asset_id is None:
            self._logger.warning("Cannot cleanup Kamatera orphan: no asset_id")
            return False
        try:
            asset = self._asset_repo.get_asset_by_id(orphan.asset_id)
            if (
                asset.asset_type != "kamatera"
                or not asset.aws_access_key
                or not asset.aws_secret_key
            ):
                return False
            KamateraClient(
                self._runtime_context,
                client_id=asset.aws_access_key,
                secret=asset.aws_secret_key,
            ).delete_server(orphan.resource_id)
            set_event_type("orphan_kamatera_server_deleted")
            return True
        except Exception as exc:
            self._logger.warning(
                "Failed to delete orphan Kamatera server %s: %s",
                orphan.resource_id,
                exc,
            )
            return False

    def _cleanup_gcp_orphan(self, orphan: OrphanResourceInfo) -> bool:
        if orphan.asset_id is None or not orphan.region:
            self._logger.warning(
                "Cannot cleanup GCP orphan: asset_id or zone missing"
            )
            return False
        try:
            asset = self._asset_repo.get_asset_by_id(orphan.asset_id)
            if asset.asset_type != "gcp":
                return False
            self._build_gcp_client(asset).delete_instance(
                orphan.region,
                orphan.resource_id,
            )
            set_event_type("orphan_gcp_instance_deleted")
            return True
        except Exception as exc:
            self._logger.warning(
                "Failed to delete orphan GCP instance %s: %s",
                orphan.resource_id,
                exc,
            )
            return False

    def _cleanup_oci_orphan(self, orphan: OrphanResourceInfo) -> bool:
        if orphan.asset_id is None:
            self._logger.warning("Cannot cleanup OCI orphan: no asset_id")
            return False
        try:
            asset = self._asset_repo.get_asset_by_id(orphan.asset_id)
            if asset.asset_type != "oci":
                return False
            self._build_oci_client(asset).delete_instance(orphan.resource_id)
            set_event_type("orphan_oci_instance_deleted")
            return True
        except Exception as exc:
            self._logger.warning(
                "Failed to delete orphan OCI instance %s: %s",
                orphan.resource_id,
                exc,
            )
            return False

    def _cleanup_azure_orphan(self, orphan: OrphanResourceInfo) -> bool:
        if orphan.asset_id is None:
            self._logger.warning("Cannot cleanup Azure orphan: no asset_id")
            return False
        try:
            asset = self._asset_repo.get_asset_by_id(orphan.asset_id)
            if asset.asset_type != "azure":
                return False
            self._build_azure_client(asset).delete_vm(orphan.resource_id)
            set_event_type("orphan_azure_vm_deleted")
            return True
        except Exception as exc:
            self._logger.warning(
                "Failed to delete orphan Azure VM %s: %s", orphan.resource_id, exc
            )
            return False

    def _cleanup_azure_network_orphan(self, orphan: OrphanResourceInfo) -> bool:
        if orphan.asset_id is None:
            self._logger.warning("Cannot cleanup Azure network orphan: no asset_id")
            return False
        try:
            asset = self._asset_repo.get_asset_by_id(orphan.asset_id)
            if asset.asset_type != "azure":
                return False
            client = self._build_azure_client(asset)
            if orphan.resource_type == "azure_network_interface":
                client.delete_network_interface(orphan.resource_id)
            elif orphan.resource_type == "azure_public_ip_address":
                client.delete_public_ip_address(orphan.resource_id)
            elif orphan.resource_type == "azure_network_security_group":
                client.delete_network_security_group(orphan.resource_id)
            else:
                return False
            set_event_type(f"orphan_{orphan.resource_type}_deleted")
            return True
        except Exception as exc:
            self._logger.warning(
                "Failed to delete orphan Azure network resource %s: %s",
                orphan.resource_id,
                exc,
            )
            return False

    def _build_gcp_client(self, asset) -> GCPClient:
        config = asset.provider_config
        if (
            asset.asset_type != "gcp"
            or not asset.aws_access_key
            or not asset.aws_secret_key
            or not isinstance(config, dict)
        ):
            raise ValueError("GCP credentials are incomplete")
        project_id = str(config.get("project_id") or "").strip()
        if not project_id:
            raise ValueError("GCP project_id is missing")
        return GCPClient(
            self._runtime_context,
            credentials=GCPCredentials(
                project_id=project_id,
                client_email=asset.aws_access_key,
                private_key=asset.aws_secret_key,
                private_key_id=str(config.get("private_key_id") or "").strip() or None,
                client_id=str(config.get("client_id") or "").strip() or None,
                token_uri=str(config.get("token_uri") or "").strip()
                or "https://oauth2.googleapis.com/token",
            ),
        )

    def _build_oci_client(self, asset) -> OCIClient:
        config = asset.provider_config
        if (
            asset.asset_type != "oci"
            or not asset.aws_access_key
            or not asset.aws_secret_key
            or not asset.region
            or not isinstance(config, dict)
        ):
            raise ValueError("OCI credentials are incomplete")
        tenancy_ocid = str(config.get("tenancy_ocid") or "").strip()
        fingerprint = str(config.get("fingerprint") or "").strip()
        if not tenancy_ocid or not fingerprint:
            raise ValueError("OCI tenancy_ocid or fingerprint is missing")
        return OCIClient(
            self._runtime_context,
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

    def _build_azure_client(self, asset) -> AzureClient:
        config = asset.provider_config
        if (
            not asset.aws_access_key
            or not asset.aws_secret_key
            or not isinstance(config, dict)
        ):
            raise ValueError("Azure credentials are incomplete")
        return AzureClient(
            self._runtime_context,
            AzureCredentials(
                tenant_id=str(config.get("tenant_id") or ""),
                client_id=asset.aws_access_key,
                client_secret=asset.aws_secret_key,
                subscription_id=str(config.get("subscription_id") or ""),
            ),
        )

    def _cleanup_ec2_orphan(self, orphan: OrphanResourceInfo) -> bool:
        """清理 EC2 孤儿实例"""
        try:
            from services.provisioning_support import build_aws_credential
            from database.asset_repo import AssetRepo

            # 获取账户凭证
            if not orphan.aws_account_id:
                self._logger.warning("Cannot cleanup EC2 orphan: no aws_account_id")
                return False

            assets = self._asset_repo.list_assets_by_aws_account_id(orphan.aws_account_id)
            if not assets:
                self._logger.warning(
                    "Cannot cleanup EC2 orphan %s: account %s not found",
                    orphan.resource_id,
                    orphan.aws_account_id,
                )
                return False

            asset = assets[0]
            aws_cred = build_aws_credential(asset)
            ec2_client = EC2Client(
                runtime_context=self._runtime_context,
                aws_credential=aws_cred,
            )

            # 终止实例
            ec2_client.terminate_instance(orphan.resource_id)
            set_event_type("orphan_ec2_instance_terminated")
            self._logger.info(
                "Terminated orphan EC2 instance: %s in %s",
                orphan.resource_id,
                orphan.aws_account_id,
            )
            return True

        except Exception as exc:
            self._logger.warning(
                "Failed to terminate orphan EC2 %s: %s",
                orphan.resource_id,
                exc,
            )
            return False

    def _cleanup_node_orphan(self, orphan: OrphanResourceInfo) -> bool:
        """清理节点孤儿"""
        try:
            if orphan.xboard_node_id is None:
                self._logger.warning("Cannot cleanup node orphan: no xboard_node_id")
                return False

            # 查找本地记录
            node_record = self._state_repo.get_node_by_xboard_node_id(orphan.xboard_node_id)
            if node_record:
                # 使用现有的孤儿节点清理服务
                cleanup_result = self._orphan_cleanup.cleanup_orphan_node(
                    node_record=node_record,
                    reason=orphan.reason or "provider_resource_not_found",
                )
                if not cleanup_result.deleted:
                    return False
            else:
                # 没有本地记录，直接从 Xboard 删除
                self._node_registry.delete_node(
                    xboard_node_id=orphan.xboard_node_id,
                    status_reason="孤儿节点清理：底层云资源已不存在",
                )

            set_event_type("orphan_node_cleaned")
            self._logger.info("Cleaned up orphan node: xboard_node_id=%s", orphan.xboard_node_id)
            return True

        except Exception as exc:
            self._logger.warning(
                "Failed to cleanup orphan node %s: %s",
                orphan.xboard_node_id,
                exc,
            )
            return False

    def _log_consistency_issues(self, result: DatabaseConsistencyResult) -> None:
        """记录数据库一致性问题"""
        if result.sqlite_only_nodes:
            self._logger.warning(
                "Database consistency issue: %d nodes only in SQLite: %s",
                len(result.sqlite_only_nodes),
                result.sqlite_only_nodes,
            )
            set_event_type("db_consistency_sqlite_only")

        if result.xboard_only_nodes:
            self._logger.warning(
                "Database consistency issue: %d nodes only in Xboard: %s",
                len(result.xboard_only_nodes),
                result.xboard_only_nodes,
            )
            set_event_type("db_consistency_xboard_only")

        if result.status_mismatch:
            self._logger.warning(
                "Database consistency issue: %d nodes with status mismatch: %s",
                len(result.status_mismatch),
                result.status_mismatch,
            )

        if not any([result.sqlite_only_nodes, result.xboard_only_nodes, result.status_mismatch]):
            set_event_type("db_consistency_ok")
            self._logger.info("Database consistency check passed")

    def _send_orphan_alert(self, orphans_found: int, cleaned: int, failed: int) -> None:
        """发送孤儿资源告警"""
        try:
            from services.provisioning_notifier import notify_alert
            notify_alert(
                runtime_context=self._runtime_context,
                title="孤儿资源检测告警",
                message=f"检测到 {orphans_found} 个孤儿资源，已清理 {cleaned} 个，失败 {failed} 个",
                severity="warning" if failed == 0 else "error",
            )
        except Exception as exc:
            self._logger.warning("Failed to send orphan alert: %s", exc)

    def get_scan_history(self, limit: int = 10) -> list[OrphanCleanupResult]:
        """获取扫描历史"""
        return self._scan_history[-limit:]


def _xboard_node_id(node: object) -> int | None:
    xboard_node_id = getattr(node, "xboard_node_id", None)
    if isinstance(xboard_node_id, int):
        return xboard_node_id
    node_id = getattr(node, "node_id", None)
    if isinstance(node_id, int):
        return node_id
    return None


class OrphanCleanupScheduler:
    """
    孤儿资源清理调度器

    定期触发孤儿资源扫描任务
    """

    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime_context = runtime_context
        self._logger = runtime_context.logger.getChild("services.orphan_cleanup_scheduler")
        self._scan_service = OrphanResourceScanService(runtime_context)
        self._last_run: datetime | None = None
        self._last_result: OrphanCleanupResult | None = None

    def should_run(self) -> bool:
        """检查是否应该运行扫描"""
        if self._last_run is None:
            return True

        config = self._runtime_context.config.app
        interval_seconds = getattr(config, "orphan_scan_interval_seconds", 3600)  # 默认 1 小时
        elapsed = (datetime.utcnow() - self._last_run).total_seconds()

        return elapsed >= interval_seconds

    def run_if_due(self) -> OrphanCleanupResult | None:
        """如果应该运行则执行扫描"""
        if not self.should_run():
            return None

        self._last_run = datetime.utcnow()
        self._last_result = self._scan_service.run_orphan_scan_cycle()
        return self._last_result

    def get_last_result(self) -> OrphanCleanupResult | None:
        """获取上次运行结果"""
        return self._last_result
