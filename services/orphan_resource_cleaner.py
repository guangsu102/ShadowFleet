"""
孤儿资源清理服务

负责清理系统中检测到的孤儿资源，支持：
1. 自动清理（根据策略）
2. 手动清理（需要确认）
3. 清理结果报告
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from database.asset_repo import AssetRepo
from database.state_repo import StateRepo
from database.xboard_repo import XboardRepo
from infrastructure.aws.ec2_client import EC2Client
from infrastructure.azure import AzureClient, AzureCredentials
from infrastructure.cloudflare.cf_client import CFClient
from infrastructure.digitalocean import DigitalOceanClient
from infrastructure.kamatera import KamateraClient
from infrastructure.vultr import VultrClient
from infrastructure.oci import OCIClient, OCICredentials
from models.aws_credentials import AwsCredentials
from services.orphan_resource_detector import (
    OrphanAssetAllocation,
    OrphanAzureNetworkResource,
    OrphanAzureVm,
    OrphanDigitalOceanDroplet,
    OrphanDigitalOceanSnapshot,
    OrphanDnsRecord,
    OrphanEc2Instance,
    OrphanKamateraServer,
    OrphanResourceReport,
    OrphanOCIInstance,
    OrphanVultrInstance,
    OrphanXboardNode,
)
from services.orphan_azure_support import AZURE_NETWORK_RESOURCE_SPECS
from utils.logger import set_event_type

if TYPE_CHECKING:
    from services.runtime_service import RuntimeContext


@dataclass(frozen=True)
class CleanupResult:
    """清理结果"""
    resource_type: str
    resource_id: str
    success: bool
    error_message: str | None = None


@dataclass(frozen=True)
class CleanupReport:
    """清理报告"""
    cleanup_time: str
    total_attempted: int
    total_succeeded: int
    total_failed: int
    results: list[CleanupResult]


class OrphanResourceCleanerError(RuntimeError):
    pass


class OrphanResourceCleaner:
    """孤儿资源清理器"""

    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime = runtime_context
        self._logger = runtime_context.logger.getChild("services.orphan_resource_cleaner")
        self._state_repo = StateRepo(runtime_context)
        self._asset_repo = AssetRepo(runtime_context)
        self._xboard_repo = XboardRepo(runtime_context)

    def cleanup_orphan_resources(
        self,
        report: OrphanResourceReport,
        cleanup_ec2: bool = True,
        cleanup_dns: bool = True,
        cleanup_allocations: bool = True,
        cleanup_xboard: bool = True,
        dry_run: bool = False,
        cleanup_digitalocean: bool = True,
        cleanup_vultr: bool = True,
        cleanup_kamatera: bool = True,
        cleanup_azure: bool = True,
        cleanup_oci: bool = True,
    ) -> CleanupReport:
        """
        清理孤儿资源

        Args:
            report: 孤儿资源检测报告
            cleanup_ec2: 是否清理 EC2 实例
            cleanup_dns: 是否清理 DNS 记录
            cleanup_allocations: 是否清理资产分配
            cleanup_xboard: 是否清理 Xboard 节点
            dry_run: 是否为演练模式（不实际执行清理）

        Returns:
            清理报告
        """
        set_event_type("orphan_cleanup_started")
        self._logger.info(
            "Starting orphan resource cleanup (dry_run=%s, total=%d)",
            dry_run,
            report.total_count,
        )

        results: list[CleanupResult] = []

        try:
            if cleanup_ec2:
                results.extend(self._cleanup_ec2_instances(report.ec2_instances, dry_run))

            if cleanup_digitalocean:
                results.extend(
                    self._cleanup_digitalocean_droplets(
                        report.digitalocean_droplets,
                        dry_run,
                    )
                )
                results.extend(
                    self._cleanup_digitalocean_snapshots(
                        report.digitalocean_snapshots,
                        dry_run,
                    )
                )

            if cleanup_vultr:
                results.extend(self._cleanup_vultr_instances(report.vultr_instances, dry_run))

            if cleanup_kamatera:
                results.extend(
                    self._cleanup_kamatera_servers(report.kamatera_servers, dry_run)
                )

            if cleanup_azure:
                results.extend(self._cleanup_azure_vms(report.azure_vms, dry_run))
                results.extend(
                    self._cleanup_azure_network_resources(
                        report.azure_network_resources,
                        dry_run,
                    )
                )

            if cleanup_oci:
                results.extend(self._cleanup_oci_instances(report.oci_instances, dry_run))

            if cleanup_dns:
                results.extend(self._cleanup_dns_records(report.dns_records, dry_run))

            if cleanup_allocations:
                results.extend(self._cleanup_asset_allocations(report.asset_allocations, dry_run))

            if cleanup_xboard:
                results.extend(self._cleanup_xboard_nodes(report.xboard_nodes, dry_run))

            succeeded = sum(1 for r in results if r.success)
            failed = sum(1 for r in results if not r.success)

            cleanup_report = CleanupReport(
                cleanup_time=datetime.utcnow().isoformat(),
                total_attempted=len(results),
                total_succeeded=succeeded,
                total_failed=failed,
                results=results,
            )

            set_event_type("orphan_cleanup_completed")
            self._logger.info(
                "Orphan resource cleanup completed: attempted=%d, succeeded=%d, failed=%d",
                len(results),
                succeeded,
                failed,
            )
            return cleanup_report

        except Exception as exc:
            set_event_type("orphan_cleanup_failed")
            self._logger.exception("Orphan resource cleanup failed: %s", exc)
            raise OrphanResourceCleanerError("Failed to cleanup orphan resources") from exc

    def _cleanup_ec2_instances(
        self,
        instances: list[OrphanEc2Instance],
        dry_run: bool,
    ) -> list[CleanupResult]:
        """清理孤儿 EC2 实例"""
        results: list[CleanupResult] = []

        for instance in instances:
            try:
                if dry_run:
                    self._logger.info(
                        "[DRY RUN] Would terminate EC2 instance: %s (region=%s, account=%s)",
                        instance.instance_id,
                        instance.region,
                        instance.account_id,
                    )
                    results.append(
                        CleanupResult(
                            resource_type="ec2_instance",
                            resource_id=instance.instance_id,
                            success=True,
                        )
                    )
                else:
                    # 获取对应的资产
                    assets = self._asset_repo.list_assets_by_aws_account_id(instance.account_id)
                    if not assets:
                        raise OrphanResourceCleanerError(
                            f"No asset found for account_id={instance.account_id}"
                        )

                    asset = assets[0]
                    credential = AwsCredentials(
                        account_id=asset.aws_account_id or "",
                        access_key=asset.aws_access_key or "",
                        secret_key=asset.aws_secret_key or "",
                        region=instance.region,
                    )
                    ec2_client = EC2Client(
                        runtime_context=self._runtime,
                        aws_credential=credential,
                    )

                    ec2_client.terminate_instance(instance.instance_id)
                    self._logger.info(
                        "Terminated orphan EC2 instance: %s",
                        instance.instance_id,
                    )
                    results.append(
                        CleanupResult(
                            resource_type="ec2_instance",
                            resource_id=instance.instance_id,
                            success=True,
                        )
                    )

            except Exception as exc:
                self._logger.warning(
                    "Failed to cleanup EC2 instance %s: %s",
                    instance.instance_id,
                    exc,
                )
                results.append(
                    CleanupResult(
                        resource_type="ec2_instance",
                        resource_id=instance.instance_id,
                        success=False,
                        error_message=str(exc),
                    )
                )

        return results

    def _cleanup_digitalocean_droplets(
        self,
        droplets: list[OrphanDigitalOceanDroplet],
        dry_run: bool,
    ) -> list[CleanupResult]:
        results: list[CleanupResult] = []
        for droplet in droplets:
            try:
                if not dry_run:
                    asset = self._asset_repo.get_asset_by_id(droplet.asset_id)
                    if asset.asset_type != "digitalocean" or not asset.aws_access_key:
                        raise OrphanResourceCleanerError(
                            "DigitalOcean credentials missing for "
                            f"asset_id={droplet.asset_id}"
                        )
                    DigitalOceanClient(
                        self._runtime,
                        api_token=asset.aws_access_key,
                    ).delete_droplet(droplet.droplet_id)
                results.append(
                    CleanupResult(
                        resource_type="digitalocean_droplet",
                        resource_id=droplet.droplet_id,
                        success=True,
                    )
                )
            except Exception as exc:
                self._logger.warning(
                    "Failed to cleanup DigitalOcean Droplet %s: %s",
                    droplet.droplet_id,
                    exc,
                )
                results.append(
                    CleanupResult(
                        resource_type="digitalocean_droplet",
                        resource_id=droplet.droplet_id,
                        success=False,
                        error_message=str(exc),
                    )
                )
        return results
    def _cleanup_digitalocean_snapshots(
        self,
        snapshots: list[OrphanDigitalOceanSnapshot],
        dry_run: bool,
    ) -> list[CleanupResult]:
        results: list[CleanupResult] = []
        for snapshot in snapshots:
            try:
                if not dry_run:
                    asset = self._asset_repo.get_asset_by_id(snapshot.asset_id)
                    if asset.asset_type != "digitalocean" or not asset.aws_access_key:
                        raise OrphanResourceCleanerError(
                            "DigitalOcean credentials missing for "
                            f"asset_id={snapshot.asset_id}"
                        )
                    DigitalOceanClient(
                        self._runtime,
                        api_token=asset.aws_access_key,
                    ).delete_snapshot(snapshot.snapshot_id)
                results.append(
                    CleanupResult(
                        resource_type="digitalocean_snapshot",
                        resource_id=snapshot.snapshot_id,
                        success=True,
                    )
                )
            except Exception as exc:
                self._logger.warning(
                    "Failed to cleanup DigitalOcean snapshot %s: %s",
                    snapshot.snapshot_id,
                    exc,
                )
                results.append(
                    CleanupResult(
                        resource_type="digitalocean_snapshot",
                        resource_id=snapshot.snapshot_id,
                        success=False,
                        error_message=str(exc),
                    )
                )
        return results
    def _cleanup_vultr_instances(
        self,
        instances: list[OrphanVultrInstance],
        dry_run: bool,
    ) -> list[CleanupResult]:
        results: list[CleanupResult] = []
        for instance in instances:
            try:
                if not dry_run:
                    asset = self._asset_repo.get_asset_by_id(instance.asset_id)
                    if asset.asset_type != "vultr" or not asset.aws_access_key:
                        raise OrphanResourceCleanerError(
                            f"Vultr credentials missing for asset_id={instance.asset_id}"
                        )
                    client = VultrClient(
                        self._runtime,
                        api_token=asset.aws_access_key,
                    )
                    client.delete_instance(instance.instance_id)
                    if instance.firewall_group_id:
                        client.delete_managed_firewall_group(instance.firewall_group_id)
                results.append(
                    CleanupResult(
                        resource_type="vultr_instance",
                        resource_id=instance.instance_id,
                        success=True,
                    )
                )
            except Exception as exc:
                self._logger.warning(
                    "Failed to cleanup Vultr instance %s: %s",
                    instance.instance_id,
                    exc,
                )
                results.append(
                    CleanupResult(
                        resource_type="vultr_instance",
                        resource_id=instance.instance_id,
                        success=False,
                        error_message=str(exc),
                    )
                )
        return results

    def _cleanup_kamatera_servers(
        self,
        servers: list[OrphanKamateraServer],
        dry_run: bool,
    ) -> list[CleanupResult]:
        results: list[CleanupResult] = []
        for server in servers:
            try:
                if not dry_run:
                    asset = self._asset_repo.get_asset_by_id(server.asset_id)
                    if (
                        asset.asset_type != "kamatera"
                        or not asset.aws_access_key
                        or not asset.aws_secret_key
                    ):
                        raise ValueError("Kamatera credentials are unavailable")
                    KamateraClient(
                        self._runtime,
                        client_id=asset.aws_access_key,
                        secret=asset.aws_secret_key,
                    ).delete_server(server.server_id)
                else:
                    self._logger.info(
                        "[DRY RUN] Would delete Kamatera server: %s",
                        server.server_id,
                    )
                results.append(
                    CleanupResult(
                        resource_type="kamatera_server",
                        resource_id=server.server_id,
                        success=True,
                    )
                )
            except Exception as exc:
                self._logger.warning(
                    "Failed to cleanup Kamatera server %s: %s",
                    server.server_id,
                    exc,
                )
                results.append(
                    CleanupResult(
                        resource_type="kamatera_server",
                        resource_id=server.server_id,
                        success=False,
                        error_message=str(exc),
                    )
                )
        return results

    def _cleanup_oci_instances(
        self,
        instances: list[OrphanOCIInstance],
        dry_run: bool,
    ) -> list[CleanupResult]:
        results: list[CleanupResult] = []
        for instance in instances:
            try:
                if not dry_run:
                    self._build_oci_client(instance.asset_id).delete_instance(
                        instance.instance_id
                    )
                results.append(
                    CleanupResult(
                        resource_type="oci_instance",
                        resource_id=instance.instance_id,
                        success=True,
                    )
                )
            except Exception as exc:
                self._logger.warning(
                    "Failed to cleanup OCI instance %s: %s",
                    instance.instance_id,
                    exc,
                )
                results.append(
                    CleanupResult(
                        resource_type="oci_instance",
                        resource_id=instance.instance_id,
                        success=False,
                        error_message=str(exc),
                    )
                )
        return results


    def _cleanup_azure_vms(
        self,
        vms: list[OrphanAzureVm],
        dry_run: bool,
    ) -> list[CleanupResult]:
        results: list[CleanupResult] = []
        for vm in vms:
            try:
                if not dry_run:
                    self._build_azure_client(vm.asset_id).delete_vm(vm.vm_id)
                results.append(
                    CleanupResult(
                        resource_type="azure_vm",
                        resource_id=vm.vm_id,
                        success=True,
                    )
                )
            except Exception as exc:
                self._logger.warning("Failed to cleanup Azure VM %s: %s", vm.vm_id, exc)
                results.append(
                    CleanupResult(
                        resource_type="azure_vm",
                        resource_id=vm.vm_id,
                        success=False,
                        error_message=str(exc),
                    )
                )
        return results

    def _cleanup_azure_network_resources(
        self,
        resources: list[OrphanAzureNetworkResource],
        dry_run: bool,
    ) -> list[CleanupResult]:
        order = {
            spec.resource_type: index
            for index, spec in enumerate(AZURE_NETWORK_RESOURCE_SPECS)
        }
        ordered_resources = sorted(
            resources,
            key=lambda resource: order[resource.resource_type],
        )
        results: list[CleanupResult] = []
        for resource in ordered_resources:
            try:
                if not dry_run:
                    client = self._build_azure_client(resource.asset_id)
                    if resource.resource_type == "azure_network_interface":
                        client.delete_network_interface(resource.resource_id)
                    elif resource.resource_type == "azure_public_ip_address":
                        client.delete_public_ip_address(resource.resource_id)
                    elif resource.resource_type == "azure_network_security_group":
                        client.delete_network_security_group(resource.resource_id)
                    else:
                        raise OrphanResourceCleanerError(
                            f"Unsupported Azure resource type: {resource.resource_type}"
                        )
                results.append(
                    CleanupResult(
                        resource_type=resource.resource_type,
                        resource_id=resource.resource_id,
                        success=True,
                    )
                )
            except Exception as exc:
                self._logger.warning(
                    "Failed to cleanup Azure network resource %s: %s",
                    resource.resource_id,
                    exc,
                )
                results.append(
                    CleanupResult(
                        resource_type=resource.resource_type,
                        resource_id=resource.resource_id,
                        success=False,
                        error_message=str(exc),
                    )
                )
        return results

    def _build_oci_client(self, asset_id: int) -> OCIClient:
        asset = self._asset_repo.get_asset_by_id(asset_id)
        config = asset.provider_config
        if (
            asset.asset_type != "oci"
            or not asset.aws_access_key
            or not asset.aws_secret_key
            or not asset.region
            or not isinstance(config, dict)
        ):
            raise OrphanResourceCleanerError(
                f"OCI credentials missing for asset_id={asset_id}"
            )
        tenancy_ocid = str(config.get("tenancy_ocid") or "").strip()
        fingerprint = str(config.get("fingerprint") or "").strip()
        if not tenancy_ocid or not fingerprint:
            raise OrphanResourceCleanerError(
                f"OCI tenancy or fingerprint missing for asset_id={asset_id}"
            )
        return OCIClient(
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

    def _build_azure_client(self, asset_id: int) -> AzureClient:
        asset = self._asset_repo.get_asset_by_id(asset_id)
        config = asset.provider_config
        if (
            asset.asset_type != "azure"
            or not asset.aws_access_key
            or not asset.aws_secret_key
            or not isinstance(config, dict)
        ):
            raise OrphanResourceCleanerError(
                f"Azure credentials missing for asset_id={asset_id}"
            )
        return AzureClient(
            self._runtime,
            AzureCredentials(
                tenant_id=str(config.get("tenant_id") or ""),
                client_id=asset.aws_access_key,
                client_secret=asset.aws_secret_key,
                subscription_id=str(config.get("subscription_id") or ""),
            ),
        )

    def _cleanup_dns_records(
        self,
        records: list[OrphanDnsRecord],
        dry_run: bool,
    ) -> list[CleanupResult]:
        """清理孤儿 DNS 记录"""
        results: list[CleanupResult] = []

        if not self._runtime.config.cloudflare.enabled:
            return results

        try:
            cf_client = CFClient(self._runtime)

            for record in records:
                try:
                    if dry_run:
                        self._logger.info(
                            "[DRY RUN] Would delete DNS record: %s (%s)",
                            record.domain_name,
                            record.record_id,
                        )
                        results.append(
                            CleanupResult(
                                resource_type="dns_record",
                                resource_id=record.record_id,
                                success=True,
                            )
                        )
                    else:
                        cf_client.delete_dns_record(record.record_id)
                        self._logger.info(
                            "Deleted orphan DNS record: %s (%s)",
                            record.domain_name,
                            record.record_id,
                        )
                        results.append(
                            CleanupResult(
                                resource_type="dns_record",
                                resource_id=record.record_id,
                                success=True,
                            )
                        )

                except Exception as exc:
                    self._logger.warning(
                        "Failed to cleanup DNS record %s: %s",
                        record.record_id,
                        exc,
                    )
                    results.append(
                        CleanupResult(
                            resource_type="dns_record",
                            resource_id=record.record_id,
                            success=False,
                            error_message=str(exc),
                        )
                    )

        except Exception as exc:
            self._logger.warning("Failed to initialize Cloudflare client: %s", exc)

        return results

    def _cleanup_asset_allocations(
        self,
        allocations: list[OrphanAssetAllocation],
        dry_run: bool,
    ) -> list[CleanupResult]:
        """清理孤儿资产分配"""
        results: list[CleanupResult] = []

        for allocation in allocations:
            try:
                if dry_run:
                    self._logger.info(
                        "[DRY RUN] Would release asset allocation: id=%d, xboard_node_id=%d",
                        allocation.allocation_id,
                        allocation.xboard_node_id,
                    )
                    results.append(
                        CleanupResult(
                            resource_type="asset_allocation",
                            resource_id=str(allocation.allocation_id),
                            success=True,
                        )
                    )
                else:
                    # 释放资产分配
                    self._asset_repo.release_allocation_by_xboard_node_id(
                        allocation.xboard_node_id,
                        allocation_status="released",
                    )
                    self._logger.info(
                        "Released orphan asset allocation: id=%d, xboard_node_id=%d",
                        allocation.allocation_id,
                        allocation.xboard_node_id,
                    )
                    results.append(
                        CleanupResult(
                            resource_type="asset_allocation",
                            resource_id=str(allocation.allocation_id),
                            success=True,
                        )
                    )

            except Exception as exc:
                self._logger.warning(
                    "Failed to cleanup asset allocation %d: %s",
                    allocation.allocation_id,
                    exc,
                )
                results.append(
                    CleanupResult(
                        resource_type="asset_allocation",
                        resource_id=str(allocation.allocation_id),
                        success=False,
                        error_message=str(exc),
                    )
                )

        return results

    def _cleanup_xboard_nodes(
        self,
        nodes: list[OrphanXboardNode],
        dry_run: bool,
    ) -> list[CleanupResult]:
        """清理孤儿 Xboard 节点"""
        results: list[CleanupResult] = []

        for node in nodes:
            try:
                if dry_run:
                    self._logger.info(
                        "[DRY RUN] Would delete Xboard node: id=%d, name=%s",
                        node.xboard_node_id,
                        node.node_name,
                    )
                    results.append(
                        CleanupResult(
                            resource_type="xboard_node",
                            resource_id=str(node.xboard_node_id),
                            success=True,
                        )
                    )
                else:
                    self._xboard_repo.delete_node(node.xboard_node_id)
                    self._logger.info(
                        "Deleted orphan Xboard node: id=%d, name=%s",
                        node.xboard_node_id,
                        node.node_name,
                    )
                    results.append(
                        CleanupResult(
                            resource_type="xboard_node",
                            resource_id=str(node.xboard_node_id),
                            success=True,
                        )
                    )

            except Exception as exc:
                self._logger.warning(
                    "Failed to cleanup Xboard node %d: %s",
                    node.xboard_node_id,
                    exc,
                )
                results.append(
                    CleanupResult(
                        resource_type="xboard_node",
                        resource_id=str(node.xboard_node_id),
                        success=False,
                        error_message=str(exc),
                    )
                )

        return results
