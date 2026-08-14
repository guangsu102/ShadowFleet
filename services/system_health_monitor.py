"""
系统健康监控和告警服务

负责：
1. 定期执行孤儿资源检测
2. 定期执行双数据库同步检查
3. 生成健康报告
4. 触发 Telegram 告警
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from services.database_sync_monitor import DatabaseSyncMonitor, SyncHealthReport
from services.orphan_resource_cleaner import OrphanResourceCleaner
from services.orphan_resource_detector import OrphanResourceDetector, OrphanResourceReport
from utils.logger import set_event_type

if TYPE_CHECKING:
    from services.runtime_service import RuntimeContext


@dataclass(frozen=True)
class SystemHealthReport:
    """系统健康报告"""
    check_time: str
    orphan_resource_report: OrphanResourceReport
    sync_health_report: SyncHealthReport
    overall_status: str  # healthy, warning, critical
    alerts: list[str]


class SystemHealthMonitorError(RuntimeError):
    pass


class SystemHealthMonitor:
    """系统健康监控器"""

    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime = runtime_context
        self._logger = runtime_context.logger.getChild("services.system_health_monitor")
        self._orphan_detector = OrphanResourceDetector(runtime_context)
        self._orphan_cleaner = OrphanResourceCleaner(runtime_context)
        self._sync_monitor = DatabaseSyncMonitor(runtime_context)

    def run_health_check(
        self,
        auto_cleanup_orphans: bool = False,
        auto_repair_sync: bool = False,
    ) -> SystemHealthReport:
        """
        执行系统健康检查

        Args:
            auto_cleanup_orphans: 是否自动清理孤儿资源
            auto_repair_sync: 是否自动修复同步问题

        Returns:
            系统健康报告
        """
        set_event_type("system_health_check_started")
        self._logger.info("Starting system health check")

        try:
            # 1. 检测孤儿资源
            orphan_report = self._orphan_detector.scan_all_orphan_resources()

            # 2. 检查数据库同步健康
            sync_report = self._sync_monitor.check_sync_health()

            # 3. 生成告警
            alerts: list[str] = []

            # 孤儿资源告警
            if orphan_report.total_count > 0:
                alerts.append(
                    f"发现 {orphan_report.total_count} 个孤儿资源: "
                    f"EC2={len(orphan_report.ec2_instances)}, "
                    f"Vultr={len(orphan_report.vultr_instances)}, "
                    f"OCI={len(orphan_report.oci_instances)}, "
                    f"Azure={len(orphan_report.azure_vms)}, "
                    f"AzureNetwork={len(orphan_report.azure_network_resources)}, "
                    f"DNS={len(orphan_report.dns_records)}, "
                    f"资产分配={len(orphan_report.asset_allocations)}, "
                    f"Xboard节点={len(orphan_report.xboard_nodes)}"
                )

            # 数据库同步告警
            if sync_report.health_status != "healthy":
                alerts.append(
                    f"数据库同步状态: {sync_report.health_status.upper()} "
                    f"(不一致数量: {sync_report.inconsistency_count})"
                )

            # 4. 确定整体健康状态
            if sync_report.health_status == "critical" or orphan_report.total_count > 20:
                overall_status = "critical"
            elif sync_report.health_status == "warning" or orphan_report.total_count > 5:
                overall_status = "warning"
            else:
                overall_status = "healthy"

            # 5. 自动清理和修复（如果启用）
            if auto_cleanup_orphans and orphan_report.total_count > 0:
                self._logger.info("Auto-cleanup enabled, cleaning up orphan resources")
                cleanup_report = self._orphan_cleaner.cleanup_orphan_resources(
                    orphan_report,
                    dry_run=False,
                )
                alerts.append(
                    f"自动清理完成: 成功={cleanup_report.total_succeeded}, "
                    f"失败={cleanup_report.total_failed}"
                )

            if auto_repair_sync and sync_report.inconsistency_count > 0:
                self._logger.info("Auto-repair enabled, repairing sync inconsistencies")
                repair_stats = self._sync_monitor.auto_repair_inconsistencies(
                    sync_report,
                    dry_run=False,
                )
                alerts.append(
                    f"自动修复完成: 成功={repair_stats['repaired']}, "
                    f"失败={repair_stats['failed']}, "
                    f"跳过={repair_stats['skipped']}"
                )

            # 6. 生成报告
            report = SystemHealthReport(
                check_time=datetime.utcnow().isoformat(),
                orphan_resource_report=orphan_report,
                sync_health_report=sync_report,
                overall_status=overall_status,
                alerts=alerts,
            )

            # 7. 发送告警
            if overall_status != "healthy":
                self._send_alert(report)

            set_event_type("system_health_check_completed")
            self._logger.info(
                "System health check completed: status=%s, alerts=%d",
                overall_status,
                len(alerts),
            )

            return report

        except Exception as exc:
            set_event_type("system_health_check_failed")
            self._logger.exception("System health check failed: %s", exc)
            raise SystemHealthMonitorError("Failed to run system health check") from exc

    def _send_alert(self, report: SystemHealthReport) -> None:
        """发送告警到 Telegram"""
        if not self._runtime.config.telegram.enabled:
            return

        try:
            from services.telegram_notifier import TelegramNotifier

            notifier = TelegramNotifier(self._runtime)

            # 构建告警消息
            status_emoji = {
                "healthy": "✅",
                "warning": "⚠️",
                "critical": "🚨",
            }

            message_lines = [
                f"{status_emoji.get(report.overall_status, '❓')} **系统健康检查报告**",
                f"",
                f"**整体状态**: {report.overall_status.upper()}",
                f"**检查时间**: {report.check_time}",
                f"",
                f"**孤儿资源**:",
                f"- EC2 实例: {len(report.orphan_resource_report.ec2_instances)}",
                f"- Vultr 实例: {len(report.orphan_resource_report.vultr_instances)}",
                f"- OCI 实例: {len(report.orphan_resource_report.oci_instances)}",
                f"- Azure VM: {len(report.orphan_resource_report.azure_vms)}",
                (
                    "- Azure network resources: "
                    f"{len(report.orphan_resource_report.azure_network_resources)}"
                ),
                f"- DNS 记录: {len(report.orphan_resource_report.dns_records)}",
                f"- 资产分配: {len(report.orphan_resource_report.asset_allocations)}",
                f"- Xboard 节点: {len(report.orphan_resource_report.xboard_nodes)}",
                f"",
                f"**数据库同步**:",
                f"- 状态: {report.sync_health_report.health_status.upper()}",
                f"- Xboard 节点数: {report.sync_health_report.total_xboard_nodes}",
                f"- SQLite 节点数: {report.sync_health_report.total_sqlite_nodes}",
                f"- 不一致数量: {report.sync_health_report.inconsistency_count}",
            ]

            if report.alerts:
                message_lines.append("")
                message_lines.append("**告警详情**:")
                for alert in report.alerts:
                    message_lines.append(f"- {alert}")

            message = "\n".join(message_lines)
            notifier.send_message(message)

            self._logger.info("Alert sent to Telegram")

        except Exception as exc:
            self._logger.warning("Failed to send alert to Telegram: %s", exc)
