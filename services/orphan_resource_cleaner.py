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
from infrastructure.cloudflare.cf_client import CFClient
from models.aws_credentials import AwsCredentials
from services.orphan_resource_detector import (
    OrphanAssetAllocation,
    OrphanDnsRecord,
    OrphanEc2Instance,
    OrphanResourceReport,
    OrphanXboardNode,
)
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
