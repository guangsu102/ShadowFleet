"""
双数据库同步监控服务

负责监控 Xboard (PostgreSQL) 和 SQLite 之间的数据一致性，包括：
1. 定期检查两个数据库的节点状态是否一致
2. 检测同步延迟和失败
3. 生成一致性报告
4. 触发告警
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from database.state_repo import StateRepo
from database.xboard_repo import XboardRepo
from utils.logger import set_event_type

if TYPE_CHECKING:
    from services.runtime_service import RuntimeContext


@dataclass(frozen=True)
class NodeInconsistency:
    """节点不一致记录"""
    xboard_node_id: int
    inconsistency_type: str  # missing_in_sqlite, missing_in_xboard, status_mismatch, host_mismatch
    xboard_state: dict[str, object] | None
    sqlite_state: dict[str, object] | None
    details: str


@dataclass(frozen=True)
class SyncHealthReport:
    """同步健康报告"""
    check_time: str
    total_xboard_nodes: int
    total_sqlite_nodes: int
    inconsistencies: list[NodeInconsistency]
    inconsistency_count: int
    health_status: str  # healthy, warning, critical


class DatabaseSyncMonitorError(RuntimeError):
    pass


class DatabaseSyncMonitor:
    """双数据库同步监控器"""

    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime = runtime_context
        self._logger = runtime_context.logger.getChild("services.database_sync_monitor")
        self._state_repo = StateRepo(runtime_context)
        self._xboard_repo = XboardRepo(runtime_context)

    def check_sync_health(self) -> SyncHealthReport:
        """
        检查双数据库同步健康状态

        Returns:
            同步健康报告
        """
        set_event_type("sync_health_check_started")
        self._logger.info("Starting database sync health check")

        try:
            # 获取 Xboard 中所有 ShadowFleet 节点
            xboard_nodes = self._xboard_repo.list_all_shadowfleet_nodes()
            xboard_node_map = {node.node_id: node for node in xboard_nodes}

            # 获取 SQLite 中所有活跃节点
            sqlite_nodes = self._state_repo.list_active_nodes()
            sqlite_node_map = {node.xboard_node_id: node for node in sqlite_nodes}

            inconsistencies: list[NodeInconsistency] = []

            # 检查 Xboard 中存在但 SQLite 中缺失的节点
            for xboard_id, xboard_node in xboard_node_map.items():
                if xboard_id not in sqlite_node_map:
                    inconsistencies.append(
                        NodeInconsistency(
                            xboard_node_id=xboard_id,
                            inconsistency_type="missing_in_sqlite",
                            xboard_state={
                                "node_name": xboard_node.node_name,
                                "node_type": xboard_node.node_type,
                                "host": xboard_node.host,
                                "show": xboard_node.show,
                            },
                            sqlite_state=None,
                            details=f"Node exists in Xboard but missing in SQLite: {xboard_node.node_name}",
                        )
                    )

            # 检查 SQLite 中存在但 Xboard 中缺失的节点
            for sqlite_id, sqlite_node in sqlite_node_map.items():
                if sqlite_id not in xboard_node_map:
                    inconsistencies.append(
                        NodeInconsistency(
                            xboard_node_id=sqlite_id,
                            inconsistency_type="missing_in_xboard",
                            xboard_state=None,
                            sqlite_state={
                                "node_name": sqlite_node.node_name,
                                "status": sqlite_node.status,
                                "last_known_host": sqlite_node.last_known_host,
                            },
                            details=f"Node exists in SQLite but missing in Xboard: {sqlite_node.node_name}",
                        )
                    )

            # 检查两边都存在的节点的状态一致性
            common_ids = set(xboard_node_map.keys()) & set(sqlite_node_map.keys())
            for node_id in common_ids:
                xboard_node = xboard_node_map[node_id]
                sqlite_node = sqlite_node_map[node_id]

                # 检查 show 状态与 SQLite status 的一致性
                expected_show = sqlite_node.status == "online"
                if xboard_node.show != expected_show:
                    inconsistencies.append(
                        NodeInconsistency(
                            xboard_node_id=node_id,
                            inconsistency_type="status_mismatch",
                            xboard_state={"show": xboard_node.show},
                            sqlite_state={"status": sqlite_node.status},
                            details=(
                                f"Status mismatch: Xboard.show={xboard_node.show}, "
                                f"SQLite.status={sqlite_node.status}"
                            ),
                        )
                    )

                # 检查 host 一致性
                sqlite_host = sqlite_node.last_known_host or sqlite_node.domain_name
                if sqlite_host and xboard_node.host != sqlite_host:
                    inconsistencies.append(
                        NodeInconsistency(
                            xboard_node_id=node_id,
                            inconsistency_type="host_mismatch",
                            xboard_state={"host": xboard_node.host},
                            sqlite_state={"host": sqlite_host},
                            details=(
                                f"Host mismatch: Xboard.host={xboard_node.host}, "
                                f"SQLite.host={sqlite_host}"
                            ),
                        )
                    )

            # 确定健康状态
            inconsistency_count = len(inconsistencies)
            if inconsistency_count == 0:
                health_status = "healthy"
            elif inconsistency_count <= 5:
                health_status = "warning"
            else:
                health_status = "critical"

            report = SyncHealthReport(
                check_time=datetime.utcnow().isoformat(),
                total_xboard_nodes=len(xboard_nodes),
                total_sqlite_nodes=len(sqlite_nodes),
                inconsistencies=inconsistencies,
                inconsistency_count=inconsistency_count,
                health_status=health_status,
            )

            # 记录日志
            if health_status == "healthy":
                set_event_type("sync_health_check_healthy")
                self._logger.info(
                    "Database sync health check: HEALTHY (xboard=%d, sqlite=%d)",
                    len(xboard_nodes),
                    len(sqlite_nodes),
                )
            elif health_status == "warning":
                set_event_type("sync_health_check_warning")
                self._logger.warning(
                    "Database sync health check: WARNING (inconsistencies=%d)",
                    inconsistency_count,
                )
            else:
                set_event_type("sync_health_check_critical")
                self._logger.error(
                    "Database sync health check: CRITICAL (inconsistencies=%d)",
                    inconsistency_count,
                )

            # 记录详细的不一致信息
            for inconsistency in inconsistencies:
                self._logger.warning(
                    "Inconsistency detected: type=%s, xboard_node_id=%d, details=%s",
                    inconsistency.inconsistency_type,
                    inconsistency.xboard_node_id,
                    inconsistency.details,
                )

            return report

        except Exception as exc:
            set_event_type("sync_health_check_failed")
            self._logger.exception("Database sync health check failed: %s", exc)
            raise DatabaseSyncMonitorError("Failed to check database sync health") from exc

    def auto_repair_inconsistencies(
        self,
        report: SyncHealthReport,
        repair_missing_in_sqlite: bool = True,
        repair_missing_in_xboard: bool = False,
        repair_status_mismatch: bool = True,
        repair_host_mismatch: bool = True,
        dry_run: bool = False,
    ) -> dict[str, int]:
        """
        自动修复不一致问题

        Args:
            report: 同步健康报告
            repair_missing_in_sqlite: 是否修复 SQLite 中缺失的节点
            repair_missing_in_xboard: 是否修复 Xboard 中缺失的节点
            repair_status_mismatch: 是否修复状态不匹配
            repair_host_mismatch: 是否修复 host 不匹配
            dry_run: 是否为演练模式

        Returns:
            修复统计 {repaired: int, failed: int, skipped: int}
        """
        set_event_type("sync_auto_repair_started")
        self._logger.info(
            "Starting auto-repair of database inconsistencies (dry_run=%s, total=%d)",
            dry_run,
            report.inconsistency_count,
        )

        stats = {"repaired": 0, "failed": 0, "skipped": 0}

        for inconsistency in report.inconsistencies:
            try:
                if inconsistency.inconsistency_type == "missing_in_sqlite":
                    if repair_missing_in_sqlite:
                        if dry_run:
                            self._logger.info(
                                "[DRY RUN] Would create SQLite record for xboard_node_id=%d",
                                inconsistency.xboard_node_id,
                            )
                            stats["repaired"] += 1
                        else:
                            # 这种情况比较复杂，需要从 Xboard 同步完整的节点信息
                            # 暂时只记录，不自动修复
                            self._logger.warning(
                                "Cannot auto-repair missing_in_sqlite: xboard_node_id=%d (requires manual intervention)",
                                inconsistency.xboard_node_id,
                            )
                            stats["skipped"] += 1
                    else:
                        stats["skipped"] += 1

                elif inconsistency.inconsistency_type == "missing_in_xboard":
                    if repair_missing_in_xboard:
                        if dry_run:
                            self._logger.info(
                                "[DRY RUN] Would delete SQLite record for xboard_node_id=%d",
                                inconsistency.xboard_node_id,
                            )
                            stats["repaired"] += 1
                        else:
                            # 删除 SQLite 中的孤儿记录
                            self._state_repo.mark_node_deleted(
                                inconsistency.xboard_node_id,
                                reason="Auto-repair: node missing in Xboard",
                            )
                            self._logger.info(
                                "Auto-repaired missing_in_xboard: marked node as deleted in SQLite (xboard_node_id=%d)",
                                inconsistency.xboard_node_id,
                            )
                            stats["repaired"] += 1
                    else:
                        stats["skipped"] += 1

                elif inconsistency.inconsistency_type == "status_mismatch":
                    if repair_status_mismatch:
                        if dry_run:
                            self._logger.info(
                                "[DRY RUN] Would sync status for xboard_node_id=%d",
                                inconsistency.xboard_node_id,
                            )
                            stats["repaired"] += 1
                        else:
                            # 以 SQLite 为准，更新 Xboard
                            sqlite_status = inconsistency.sqlite_state.get("status") if inconsistency.sqlite_state else None
                            if sqlite_status == "online":
                                self._xboard_repo.mark_node_online(inconsistency.xboard_node_id)
                            else:
                                self._xboard_repo.mark_node_offline(inconsistency.xboard_node_id)
                            self._logger.info(
                                "Auto-repaired status_mismatch: synced Xboard status (xboard_node_id=%d, status=%s)",
                                inconsistency.xboard_node_id,
                                sqlite_status,
                            )
                            stats["repaired"] += 1
                    else:
                        stats["skipped"] += 1

                elif inconsistency.inconsistency_type == "host_mismatch":
                    if repair_host_mismatch:
                        if dry_run:
                            self._logger.info(
                                "[DRY RUN] Would sync host for xboard_node_id=%d",
                                inconsistency.xboard_node_id,
                            )
                            stats["repaired"] += 1
                        else:
                            # 以 SQLite 为准，更新 Xboard
                            sqlite_host = inconsistency.sqlite_state.get("host") if inconsistency.sqlite_state else None
                            if sqlite_host:
                                self._xboard_repo.update_node_host(
                                    inconsistency.xboard_node_id,
                                    str(sqlite_host),
                                )
                                self._logger.info(
                                    "Auto-repaired host_mismatch: synced Xboard host (xboard_node_id=%d, host=%s)",
                                    inconsistency.xboard_node_id,
                                    sqlite_host,
                                )
                                stats["repaired"] += 1
                    else:
                        stats["skipped"] += 1

            except Exception as exc:
                self._logger.warning(
                    "Failed to repair inconsistency for xboard_node_id=%d: %s",
                    inconsistency.xboard_node_id,
                    exc,
                )
                stats["failed"] += 1

        set_event_type("sync_auto_repair_completed")
        self._logger.info(
            "Auto-repair completed: repaired=%d, failed=%d, skipped=%d",
            stats["repaired"],
            stats["failed"],
            stats["skipped"],
        )

        return stats
