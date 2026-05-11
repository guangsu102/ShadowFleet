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
            xboard_node_ids = {n.xboard_node_id for n in xboard_nodes}

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

            # 检查 Xboard 中存在的节点状态
            for node in sqlite_nodes:
                if node.xboard_node_id in xboard_node_ids:
                    xboard_node = next((n for n in xboard_nodes if n.xboard_node_id == node.xboard_node_id), None)
                    if xboard_node:
                        # 检查 show 字段（online/offline）
                        # 这里可以扩展更多状态检查
                        pass

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

                try:
                    # 尝试获取实例状态
                    from services.provisioning_support import build_aws_credential
                    from database.asset_repo_helpers import utcnow_iso

                    # 获取资产凭证
                    assets = self._asset_repo.list_assets_by_aws_account_id(node.aws_account_id)
                    if not assets:
                        orphans.append(OrphanResourceInfo(
                            resource_type="xboard_node",
                            resource_id=str(node.xboard_node_id),
                            region=node.aws_region,
                            aws_account_id=node.aws_account_id,
                            xboard_node_id=node.xboard_node_id,
                            reason="Node's AWS account not found in assets",
                            discovered_at=utcnow_iso(),
                        ))
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

    def _scan_allocation_orphans(self) -> list[OrphanResourceInfo]:
        """
        扫描资产分配孤儿

        查找分配记录与实际资源不匹配的情况
        """
        orphans: list[OrphanResourceInfo] = []

        try:
            # 检查 orphaned allocation events
            # 这些是 provisioning_rollback_incomplete 事件
            # 这个功能可以在后续实现
            pass

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
            elif orphan.resource_type == "xboard_node":
                return self._cleanup_node_orphan(orphan)
            else:
                self._logger.warning("Unknown orphan resource type: %s", orphan.resource_type)
                return False
        except Exception as exc:
            self._logger.exception("Failed to cleanup orphan %s: %s", orphan.resource_id, exc)
            return False

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
                self._orphan_cleanup.cleanup_orphan_node(
                    node_record=node_record,
                    reason=orphan.reason or "ec2_instance_not_found",
                )
            else:
                # 没有本地记录，直接从 Xboard 删除
                self._node_registry.delete_node(
                    xboard_node_id=orphan.xboard_node_id,
                    status_reason="孤儿节点清理：EC2实例已不存在",
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
