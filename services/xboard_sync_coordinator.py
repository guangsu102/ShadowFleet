"""
Xboard 与 SQLite 状态同步协调器
解决竞态条件问题，确保两个数据库的状态一致性
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import TYPE_CHECKING, Callable, TypeVar

from database.state_repo import StateRepo
from database.xboard_repo import XboardRepo, XboardRepoError
from services.runtime_service import RuntimeContext
from services.sync_monitor_service import SyncCoordinatorMonitor, SyncMonitorService
from utils.logger import generate_correlation_id, set_correlation_id, set_event_type

if TYPE_CHECKING:
    from services.runtime_service import RuntimeContext

T = TypeVar('T')


class XboardSyncCoordinator:
    """
    协调 Xboard (PostgreSQL) 和 SQLite 之间的状态同步

    核心改进：
    1. 使用两阶段提交模式确保原子性
    2. 先写 Xboard，再写 SQLite，失败时回滚 Xboard
    3. 使用 SQLite 事务锁防止并发冲突
    4. 集成 SyncMonitorService 监控同步状态和告警
    """

    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime_context = runtime_context
        self._logger = runtime_context.logger.getChild("services.xboard_sync_coordinator")
        self._xboard_repo = XboardRepo(runtime_context)
        self._state_repo = StateRepo(runtime_context)
        self._sync_monitor = SyncMonitorService(runtime_context)
        self._coordinator_monitor = SyncCoordinatorMonitor(runtime_context)

    @contextmanager
    def atomic_sync_context(self):
        """
        原子同步上下文管理器

        使用方式：
        with coordinator.atomic_sync_context():
            # 1. 执行 Xboard 操作
            xboard_node_id = xboard_repo.register_node(...)

            # 2. 执行 SQLite 操作
            local_node_id = state_repo.create_node(...)

            # 如果任何操作失败，自动回滚
        """
        xboard_operations = []

        class XboardRollback:
            def __init__(self, operation: str, rollback_fn: Callable[[], None]):
                self.operation = operation
                self.rollback_fn = rollback_fn

        try:
            # 提供回滚注册接口
            def register_xboard_rollback(operation: str, rollback_fn: Callable[[], None]):
                xboard_operations.append(XboardRollback(operation, rollback_fn))

            # 将注册函数注入到上下文
            yield register_xboard_rollback

        except Exception as exc:
            # 发生异常，回滚所有 Xboard 操作
            self._logger.error("Sync operation failed, rolling back Xboard operations: %s", exc)
            for rollback in reversed(xboard_operations):
                try:
                    self._logger.info("Rolling back Xboard operation: %s", rollback.operation)
                    rollback.rollback_fn()
                except Exception as rollback_exc:
                    self._logger.exception(
                        "Failed to rollback Xboard operation %s: %s",
                        rollback.operation,
                        rollback_exc,
                    )
            raise

    def sync_node_registration(
        self,
        xboard_node_id: int,
        local_node_create_fn: Callable[[], int],
    ) -> int:
        """
        同步节点注册（Xboard 已创建，需要同步到 SQLite）

        Args:
            xboard_node_id: 已创建的 Xboard 节点 ID
            local_node_create_fn: 创建本地节点的函数

        Returns:
            本地节点 ID

        改进：
        1. 使用 SQLite BEGIN IMMEDIATE 获取写锁
        2. 防止并发创建相同的 xboard_node_id
        """
        try:
            # 使用 BEGIN IMMEDIATE 获取写锁，防止并发冲突
            with self._get_sqlite_write_lock():
                local_node_id = local_node_create_fn()
                self._logger.info(
                    "Synced node registration: xboard_node_id=%s local_node_id=%s",
                    xboard_node_id,
                    local_node_id,
                )
                return local_node_id
        except sqlite3.IntegrityError as exc:
            # 唯一约束冲突，说明已经存在
            self._logger.warning(
                "Node already exists in SQLite for xboard_node_id=%s: %s",
                xboard_node_id,
                exc,
            )
            raise
        except Exception as exc:
            self._logger.exception(
                "Failed to sync node registration for xboard_node_id=%s",
                xboard_node_id,
            )
            raise

    def sync_node_status_change(
        self,
        xboard_node_id: int,
        xboard_operation: Callable[[], None],
        sqlite_operation: Callable[[], None],
        rollback_xboard_operation: Callable[[], None],
        operation_name: str,
    ) -> None:
        """
        同步节点状态变更（online/offline/delete）

        Args:
            xboard_node_id: 节点 ID
            xboard_operation: Xboard 操作函数
            sqlite_operation: SQLite 操作函数
            rollback_xboard_operation: Xboard 回滚函数
            operation_name: 操作名称（用于日志）

        改进：
        1. 先执行 Xboard 操作
        2. 再执行 SQLite 操作
        3. SQLite 失败时回滚 Xboard
        4. 使用 SyncMonitorService 记录同步操作和告警
        """
        correlation_id = generate_correlation_id()
        original_correlation_id = self._runtime_context.correlation_id
        set_correlation_id(correlation_id)

        # 记录同步操作开始
        operation_id = self._sync_monitor.record_sync_operation_start(
            operation_type=f"status_change_{operation_name}",
            xboard_node_id=xboard_node_id,
        )

        set_event_type(f"sync_{operation_name}_started")
        self._logger.info(
            "Starting sync %s for xboard_node_id=%s",
            operation_name,
            xboard_node_id,
        )

        try:
            # 第一阶段：执行 Xboard 操作
            try:
                xboard_operation()
                self._sync_monitor.record_sync_operation_complete(
                    operation_id=operation_id,
                    success=True,
                    synced_to_xboard=True,
                )
            except XboardRepoError as exc:
                self._logger.exception(
                    "Xboard operation failed for %s xboard_node_id=%s",
                    operation_name,
                    xboard_node_id,
                )
                self._sync_monitor.record_sync_operation_complete(
                    operation_id=operation_id,
                    success=False,
                    error_message=str(exc),
                    synced_to_xboard=False,
                )
                set_event_type(f"sync_{operation_name}_xboard_failed")
                raise

            # 第二阶段：执行 SQLite 操作
            try:
                with self._get_sqlite_write_lock():
                    sqlite_operation()
                    self._sync_monitor.record_sync_operation_complete(
                        operation_id=operation_id,
                        success=True,
                        synced_to_xboard=True,
                        synced_to_sqlite=True,
                    )
            except Exception as exc:
                # SQLite 操作失败，回滚 Xboard
                self._logger.error(
                    "SQLite operation failed for %s xboard_node_id=%s, rolling back Xboard",
                    operation_name,
                    xboard_node_id,
                )
                self._sync_monitor.record_sync_operation_complete(
                    operation_id=operation_id,
                    success=False,
                    error_message=str(exc),
                    synced_to_xboard=True,
                    synced_to_sqlite=False,
                )
                try:
                    rollback_xboard_operation()
                    self._logger.info(
                        "Successfully rolled back Xboard for %s xboard_node_id=%s",
                        operation_name,
                        xboard_node_id,
                    )
                except Exception as rollback_exc:
                    self._logger.exception(
                        "Failed to rollback Xboard for %s xboard_node_id=%s: %s",
                        operation_name,
                        xboard_node_id,
                        rollback_exc,
                    )
                set_event_type(f"sync_{operation_name}_sqlite_failed")
                raise

            set_event_type(f"sync_{operation_name}_completed")
            self._logger.info(
                "Completed sync %s for xboard_node_id=%s",
                operation_name,
                xboard_node_id,
            )

        finally:
            set_correlation_id(original_correlation_id)

    @contextmanager
    def _get_sqlite_write_lock(self):
        """
        获取 SQLite 写锁

        使用 BEGIN IMMEDIATE 立即获取写锁，防止并发写入冲突
        """
        connection = None
        try:
            # 直接使用 sqlite_manager 的连接
            connection = sqlite3.connect(
                self._state_repo._sqlite_manager.database_path,
                timeout=30.0,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 30000")

            # BEGIN IMMEDIATE 立即获取写锁
            connection.execute("BEGIN IMMEDIATE")

            yield connection

            connection.commit()
        except Exception:
            if connection:
                connection.rollback()
            raise
        finally:
            if connection:
                connection.close()
