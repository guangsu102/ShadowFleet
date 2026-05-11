"""
双数据库同步监控和告警服务
监控 Xboard (PostgreSQL) 和 SQLite 之间的同步状态，及时发现同步问题
"""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from database.state_repo import StateRepo
from database.xboard_repo import XboardRepo
from services.runtime_service import RuntimeContext
from utils.logger import generate_correlation_id, set_correlation_id, set_event_type


if TYPE_CHECKING:
    from database.state_models import FleetNodeRecord


@dataclass(frozen=True)
class SyncHealthMetrics:
    """同步健康指标"""
    total_nodes: int
    synced_nodes: int
    sqlite_only_nodes: int
    xboard_only_nodes: int
    status_mismatch_nodes: int
    last_sync_time: str | None
    sync_lag_seconds: float | None
    health_score: float  # 0.0 - 1.0


@dataclass(frozen=True)
class SyncOperationRecord:
    """同步操作记录"""
    operation_id: str
    operation_type: str  # register, update, delete, status_change
    xboard_node_id: int
    started_at: str
    completed_at: str | None = None
    duration_ms: float | None = None
    success: bool = True
    error_message: str | None = None
    synced_to_sqlite: bool = False
    synced_to_xboard: bool = False


@dataclass(frozen=True)
class SyncAlert:
    """同步告警"""
    alert_id: str
    alert_type: str  # sync_failure, sync_lag, consistency_issue
    severity: str  # info, warning, error, critical
    message: str
    xboard_node_id: int | None = None
    created_at: str | None = None
    resolved_at: str | None = None
    metadata: dict | None = None


@dataclass
class SyncMonitorState:
    """同步监控状态"""
    operation_history: list[SyncOperationRecord] = field(default_factory=list)
    alerts: list[SyncAlert] = field(default_factory=list)
    metrics_history: list[SyncHealthMetrics] = field(default_factory=list)
    failed_sync_attempts: defaultdict[str, int] = field(default_factory=lambda: defaultdict(int))
    last_full_sync_check: datetime | None = None
    last_successful_sync: datetime | None = None


class SyncMonitorService:
    """
    双数据库同步监控服务

    功能：
    1. 实时监控同步操作的状态和延迟
    2. 检测同步不一致情况
    3. 触发同步告警
    4. 提供同步健康报告
    """

    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime_context = runtime_context
        self._logger = runtime_context.logger.getChild("services.sync_monitor")
        self._state_repo = StateRepo(runtime_context)
        self._xboard_repo = XboardRepo(runtime_context)
        self._state = SyncMonitorState()
        self._config = runtime_context.config.app

    def record_sync_operation_start(
        self,
        operation_type: str,
        xboard_node_id: int,
    ) -> str:
        """记录同步操作开始"""
        operation_id = f"sync-{xboard_node_id}-{int(time.time() * 1000)}"
        record = SyncOperationRecord(
            operation_id=operation_id,
            operation_type=operation_type,
            xboard_node_id=xboard_node_id,
            started_at=datetime.utcnow().isoformat(),
        )
        self._state.operation_history.append(record)

        # 限制历史记录大小
        if len(self._state.operation_history) > 1000:
            self._state.operation_history = self._state.operation_history[-500:]

        return operation_id

    def record_sync_operation_complete(
        self,
        operation_id: str,
        success: bool,
        error_message: str | None = None,
        synced_to_sqlite: bool = False,
        synced_to_xboard: bool = False,
    ) -> None:
        """记录同步操作完成"""
        completed_at = datetime.utcnow().isoformat()

        for record in reversed(self._state.operation_history):
            if record.operation_id == operation_id:
                duration_ms = (datetime.utcnow() - datetime.fromisoformat(record.started_at)).total_seconds() * 1000
                # 创建更新后的记录
                updated_record = SyncOperationRecord(
                    operation_id=record.operation_id,
                    operation_type=record.operation_type,
                    xboard_node_id=record.xboard_node_id,
                    started_at=record.started_at,
                    completed_at=completed_at,
                    duration_ms=duration_ms,
                    success=success,
                    error_message=error_message,
                    synced_to_sqlite=synced_to_sqlite,
                    synced_to_xboard=synced_to_xboard,
                )
                idx = self._state.operation_history.index(record)
                self._state.operation_history[idx] = updated_record

                # 记录成功/失败
                if success:
                    self._state.last_successful_sync = datetime.utcnow()
                    set_event_type("sync_operation_completed")
                    self._logger.debug(
                        "Sync operation completed: id=%s node=%s duration=%.2fms",
                        operation_id,
                        record.xboard_node_id,
                        duration_ms,
                    )
                else:
                    self._state.failed_sync_attempts[record.operation_type] += 1
                    set_event_type("sync_operation_failed")
                    self._logger.warning(
                        "Sync operation failed: id=%s node=%s error=%s",
                        operation_id,
                        record.xboard_node_id,
                        error_message,
                    )
                    # 触发告警
                    self._check_and_create_alert(
                        alert_type="sync_failure",
                        severity="error",
                        message=f"同步操作失败: {error_message}",
                        xboard_node_id=record.xboard_node_id,
                        metadata={
                            "operation_id": operation_id,
                            "operation_type": record.operation_type,
                            "error": error_message,
                        },
                    )
                break

    def check_sync_health(self) -> SyncHealthMetrics:
        """
        检查同步健康状态

        Returns:
            SyncHealthMetrics 包含当前同步健康指标
        """
        try:
            # 获取 Xboard 中的所有节点
            xboard_nodes = self._xboard_repo.list_all_shadowfleet_nodes()
            xboard_node_ids = {n.node_id for n in xboard_nodes}

            # 获取 SQLite 中的所有节点
            sqlite_nodes = self._state_repo.list_active_nodes()
            sqlite_node_ids = {n.xboard_node_id for n in sqlite_nodes}

            # 计算差异
            sqlite_only = sqlite_node_ids - xboard_node_ids
            xboard_only = xboard_node_ids - sqlite_node_ids

            # 检查状态不一致
            status_mismatch = 0
            for sqlite_node in sqlite_nodes:
                if sqlite_node.xboard_node_id in xboard_node_ids:
                    xboard_node = next(
                        (n for n in xboard_nodes if n.node_id == sqlite_node.xboard_node_id),
                        None,
                    )
                    if xboard_node:
                        # 检查 show 字段（online/offline）
                        # 这里可以扩展更多状态检查
                        pass

            # 计算健康分数
            total = len(xboard_node_ids | sqlite_node_ids)
            synced = len(xboard_node_ids & sqlite_node_ids)
            health_score = synced / total if total > 0 else 1.0

            # 计算同步延迟
            sync_lag = self._calculate_sync_lag()

            # 计算最后同步时间
            last_sync_time = None
            if self._state.last_successful_sync:
                last_sync_time = self._state.last_successful_sync.isoformat()

            metrics = SyncHealthMetrics(
                total_nodes=total,
                synced_nodes=synced,
                sqlite_only_nodes=len(sqlite_only),
                xboard_only_nodes=len(xboard_only),
                status_mismatch_nodes=status_mismatch,
                last_sync_time=last_sync_time,
                sync_lag_seconds=sync_lag,
                health_score=health_score,
            )

            # 记录指标历史
            self._state.metrics_history.append(metrics)
            if len(self._state.metrics_history) > 100:
                self._state.metrics_history = self._state.metrics_history[-50:]

            # 更新事件类型
            if health_score >= 0.99:
                set_event_type("sync_health_excellent")
            elif health_score >= 0.95:
                set_event_type("sync_health_good")
            elif health_score >= 0.8:
                set_event_type("sync_health_degraded")
            else:
                set_event_type("sync_health_critical")
                self._check_and_create_alert(
                    alert_type="sync_lag",
                    severity="critical",
                    message=f"同步健康分数严重下降: {health_score:.2%}",
                    metadata={"health_score": health_score, "total": total, "synced": synced},
                )

            self._logger.info(
                "Sync health check: total=%d synced=%d health=%.2f%% lag=%.1fs",
                total,
                synced,
                health_score * 100,
                sync_lag or 0,
            )

            return metrics

        except Exception as exc:
            self._logger.exception("Failed to check sync health: %s", exc)
            set_event_type("sync_health_check_failed")
            return SyncHealthMetrics(
                total_nodes=0,
                synced_nodes=0,
                sqlite_only_nodes=0,
                xboard_only_nodes=0,
                status_mismatch_nodes=0,
                last_sync_time=None,
                sync_lag_seconds=None,
                health_score=0.0,
            )

    def _calculate_sync_lag(self) -> float | None:
        """计算同步延迟（秒）"""
        if not self._state.last_successful_sync:
            return None

        lag = (datetime.utcnow() - self._state.last_successful_sync).total_seconds()

        # 如果延迟超过阈值，触发告警
        threshold = getattr(self._config, "sync_lag_warning_threshold_seconds", 300)  # 默认 5 分钟
        if lag > threshold:
            self._check_and_create_alert(
                alert_type="sync_lag",
                severity="warning",
                message=f"同步延迟超过阈值: {lag:.0f}秒",
                metadata={"lag_seconds": lag, "threshold": threshold},
            )

        return lag

    def _check_and_create_alert(
        self,
        alert_type: str,
        severity: str,
        message: str,
        xboard_node_id: int | None = None,
        metadata: dict | None = None,
    ) -> None:
        """检查是否需要创建告警"""
        # 检查是否有相同类型的未解决告警
        for existing in self._state.alerts:
            if existing.alert_type == alert_type and existing.resolved_at is None:
                # 已有相同类型的未解决告警
                return

        # 创建新告警
        alert = SyncAlert(
            alert_id=f"alert-{alert_type}-{int(time.time() * 1000)}",
            alert_type=alert_type,
            severity=severity,
            message=message,
            xboard_node_id=xboard_node_id,
            created_at=datetime.utcnow().isoformat(),
            metadata=metadata,
        )
        self._state.alerts.append(alert)

        # 限制告警历史
        if len(self._state.alerts) > 100:
            self._state.alerts = self._state.alerts[-50:]

        # 发送告警通知
        self._send_alert_notification(alert)

        set_event_type(f"sync_alert_{severity}")
        self._logger.warning(
            "Sync alert created: type=%s severity=%s message=%s",
            alert_type,
            severity,
            message,
        )

    def _send_alert_notification(self, alert: SyncAlert) -> None:
        """发送告警通知"""
        try:
            severity_emoji = {
                "info": "ℹ️",
                "warning": "⚠️",
                "error": "❌",
                "critical": "🚨",
            }
            emoji = severity_emoji.get(alert.severity, "❓")

            from services.provisioning_notifier import notify_alert
            notify_alert(
                runtime_context=self._runtime_context,
                title=f"{emoji} 同步{alert.severity.upper()}: {alert.alert_type}",
                message=alert.message,
                severity=alert.severity,
            )
        except Exception as exc:
            self._logger.warning("Failed to send alert notification: %s", exc)

    def resolve_alert(self, alert_id: str) -> bool:
        """解决告警"""
        for alert in self._state.alerts:
            if alert.alert_id == alert_id and alert.resolved_at is None:
                # 标记为已解决
                idx = self._state.alerts.index(alert)
                resolved_alert = SyncAlert(
                    alert_id=alert.alert_id,
                    alert_type=alert.alert_type,
                    severity=alert.severity,
                    message=alert.message,
                    xboard_node_id=alert.xboard_node_id,
                    created_at=alert.created_at,
                    resolved_at=datetime.utcnow().isoformat(),
                    metadata=alert.metadata,
                )
                self._state.alerts[idx] = resolved_alert

                self._logger.info("Resolved sync alert: %s", alert_id)
                set_event_type("sync_alert_resolved")
                return True
        return False

    def get_unresolved_alerts(self) -> list[SyncAlert]:
        """获取未解决的告警"""
        return [a for a in self._state.alerts if a.resolved_at is None]

    def get_recent_operations(self, limit: int = 50) -> list[SyncOperationRecord]:
        """获取最近的同步操作"""
        return self._state.operation_history[-limit:]

    def get_failed_operations_count(self) -> dict[str, int]:
        """获取失败操作统计"""
        return dict(self._state.failed_sync_attempts)

    def get_sync_health_report(self) -> dict:
        """获取同步健康报告"""
        metrics = self.check_sync_health()
        alerts = self.get_unresolved_alerts()
        recent_ops = self.get_recent_operations(20)
        failed_counts = self.get_failed_operations_count()

        return {
            "health_metrics": {
                "total_nodes": metrics.total_nodes,
                "synced_nodes": metrics.synced_nodes,
                "sqlite_only_nodes": metrics.sqlite_only_nodes,
                "xboard_only_nodes": metrics.xboard_only_nodes,
                "health_score": f"{metrics.health_score:.2%}",
                "last_sync_time": metrics.last_sync_time,
                "sync_lag_seconds": metrics.sync_lag_seconds,
            },
            "alerts": {
                "unresolved_count": len(alerts),
                "items": [
                    {
                        "id": a.alert_id,
                        "type": a.alert_type,
                        "severity": a.severity,
                        "message": a.message,
                        "created_at": a.created_at,
                    }
                    for a in alerts
                ],
            },
            "recent_operations": {
                "total": len(recent_ops),
                "failed": sum(1 for op in recent_ops if not op.success),
                "operations": [
                    {
                        "id": op.operation_id,
                        "type": op.operation_type,
                        "node_id": op.xboard_node_id,
                        "duration_ms": op.duration_ms,
                        "success": op.success,
                    }
                    for op in recent_ops[-10:]
                ],
            },
            "failure_statistics": failed_counts,
        }

    def run_periodic_health_check(self) -> SyncHealthMetrics:
        """
        运行周期性健康检查

        在 Daemon 循环中调用，用于持续监控同步状态
        """
        correlation_id = generate_correlation_id()
        original_correlation_id = self._runtime_context.correlation_id
        set_correlation_id(correlation_id)

        try:
            return self.check_sync_health()
        finally:
            set_correlation_id(original_correlation_id)


class SyncCoordinatorMonitor:
    """
    同步协调器监控装饰器

    为 XboardSyncCoordinator 添加监控能力
    """

    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime_context = runtime_context
        self._monitor = SyncMonitorService(runtime_context)
        self._logger = runtime_context.logger.getChild("services.sync_coordinator_monitor")

    def wrap_sync_operation(
        self,
        operation_type: str,
        xboard_node_id: int,
        operation_fn,
    ):
        """
        包装同步操作，添加监控

        Args:
            operation_type: 操作类型
            xboard_node_id: 节点 ID
            operation_fn: 要执行的同步操作函数

        Returns:
            操作结果
        """
        operation_id = self._monitor.record_sync_operation_start(
            operation_type=operation_type,
            xboard_node_id=xboard_node_id,
        )

        try:
            result = operation_fn()
            self._monitor.record_sync_operation_complete(
                operation_id=operation_id,
                success=True,
            )
            return result
        except Exception as exc:
            self._monitor.record_sync_operation_complete(
                operation_id=operation_id,
                success=False,
                error_message=str(exc),
            )
            raise

    def on_sync_failure(
        self,
        operation_type: str,
        xboard_node_id: int,
        error: Exception,
    ) -> None:
        """记录同步失败"""
        operation_id = self._monitor.record_sync_operation_start(
            operation_type=operation_type,
            xboard_node_id=xboard_node_id,
        )
        self._monitor.record_sync_operation_complete(
            operation_id=operation_id,
            success=False,
            error_message=str(error),
        )

    def get_health_report(self) -> dict:
        """获取健康报告"""
        return self._monitor.get_sync_health_report()
