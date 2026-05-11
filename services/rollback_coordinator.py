"""
增强的错误处理和回滚协调器

提供统一的错误处理和回滚机制，确保：
1. 所有回滚操作都尝试执行
2. 记录所有失败的回滚
3. 支持自定义回滚策略
4. 提供回滚结果报告
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, TYPE_CHECKING

from utils.logger import set_event_type

if TYPE_CHECKING:
    import logging


class RollbackPriority(Enum):
    """回滚优先级（数字越小优先级越高）"""
    CRITICAL = 1  # 必须立即回滚（如删除节点记录）
    HIGH = 2      # 高优先级（如释放资源）
    MEDIUM = 3    # 中优先级（如清理 DNS）
    LOW = 4       # 低优先级（如清理临时文件）


@dataclass(frozen=True)
class RollbackAction:
    """回滚动作"""
    name: str
    action: Callable[[], None]
    priority: RollbackPriority
    resource_type: str
    resource_id: str | None = None
    allow_failure: bool = False  # 是否允许失败（不影响整体回滚）


@dataclass(frozen=True)
class RollbackResult:
    """回滚结果"""
    action_name: str
    resource_type: str
    resource_id: str | None
    success: bool
    error_message: str | None = None


@dataclass(frozen=True)
class RollbackReport:
    """回滚报告"""
    total_actions: int
    succeeded: int
    failed: int
    skipped: int
    results: list[RollbackResult]
    critical_failures: list[RollbackResult]  # 关键失败（不允许失败的动作）


class RollbackCoordinatorError(RuntimeError):
    pass


class RollbackCoordinator:
    """回滚协调器"""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger
        self._actions: list[RollbackAction] = []

    def register_action(
        self,
        name: str,
        action: Callable[[], None],
        priority: RollbackPriority,
        resource_type: str,
        resource_id: str | None = None,
        allow_failure: bool = False,
    ) -> None:
        """
        注册回滚动作

        Args:
            name: 动作名称
            action: 回滚函数
            priority: 优先级
            resource_type: 资源类型
            resource_id: 资源 ID
            allow_failure: 是否允许失败
        """
        self._actions.append(
            RollbackAction(
                name=name,
                action=action,
                priority=priority,
                resource_type=resource_type,
                resource_id=resource_id,
                allow_failure=allow_failure,
            )
        )
        self._logger.debug(
            "Registered rollback action: %s (priority=%s, resource=%s:%s)",
            name,
            priority.name,
            resource_type,
            resource_id,
        )

    def execute_rollback(self, continue_on_failure: bool = True) -> RollbackReport:
        """
        执行所有回滚动作

        Args:
            continue_on_failure: 是否在失败后继续执行其他回滚

        Returns:
            回滚报告
        """
        if not self._actions:
            self._logger.info("No rollback actions registered")
            return RollbackReport(
                total_actions=0,
                succeeded=0,
                failed=0,
                skipped=0,
                results=[],
                critical_failures=[],
            )

        set_event_type("rollback_started")
        self._logger.info("Starting rollback execution: total_actions=%d", len(self._actions))

        # 按优先级排序（优先级高的先执行）
        sorted_actions = sorted(self._actions, key=lambda a: a.priority.value)

        results: list[RollbackResult] = []
        critical_failures: list[RollbackResult] = []
        succeeded = 0
        failed = 0
        skipped = 0

        for action in sorted_actions:
            try:
                self._logger.info(
                    "Executing rollback action: %s (priority=%s, resource=%s:%s)",
                    action.name,
                    action.priority.name,
                    action.resource_type,
                    action.resource_id,
                )

                # 执行回滚动作
                action.action()

                result = RollbackResult(
                    action_name=action.name,
                    resource_type=action.resource_type,
                    resource_id=action.resource_id,
                    success=True,
                )
                results.append(result)
                succeeded += 1

                self._logger.info("Rollback action succeeded: %s", action.name)

            except Exception as exc:
                error_message = str(exc)
                result = RollbackResult(
                    action_name=action.name,
                    resource_type=action.resource_type,
                    resource_id=action.resource_id,
                    success=False,
                    error_message=error_message,
                )
                results.append(result)
                failed += 1

                if not action.allow_failure:
                    critical_failures.append(result)
                    self._logger.error(
                        "CRITICAL: Rollback action failed: %s (error: %s)",
                        action.name,
                        error_message,
                    )
                else:
                    self._logger.warning(
                        "Rollback action failed (allowed): %s (error: %s)",
                        action.name,
                        error_message,
                    )

                # 如果不允许继续，且这是关键失败，则停止
                if not continue_on_failure and not action.allow_failure:
                    self._logger.error("Stopping rollback due to critical failure")
                    # 标记剩余动作为跳过
                    remaining_actions = sorted_actions[sorted_actions.index(action) + 1:]
                    skipped = len(remaining_actions)
                    for remaining in remaining_actions:
                        results.append(
                            RollbackResult(
                                action_name=remaining.name,
                                resource_type=remaining.resource_type,
                                resource_id=remaining.resource_id,
                                success=False,
                                error_message="Skipped due to previous critical failure",
                            )
                        )
                    break

        report = RollbackReport(
            total_actions=len(self._actions),
            succeeded=succeeded,
            failed=failed,
            skipped=skipped,
            results=results,
            critical_failures=critical_failures,
        )

        # 记录最终结果
        if critical_failures:
            set_event_type("rollback_completed_with_critical_failures")
            self._logger.error(
                "Rollback completed with CRITICAL failures: total=%d, succeeded=%d, failed=%d, critical=%d",
                len(self._actions),
                succeeded,
                failed,
                len(critical_failures),
            )
        elif failed > 0:
            set_event_type("rollback_completed_with_failures")
            self._logger.warning(
                "Rollback completed with failures: total=%d, succeeded=%d, failed=%d",
                len(self._actions),
                succeeded,
                failed,
            )
        else:
            set_event_type("rollback_completed_successfully")
            self._logger.info(
                "Rollback completed successfully: total=%d, succeeded=%d",
                len(self._actions),
                succeeded,
            )

        return report

    def clear(self) -> None:
        """清空所有注册的回滚动作"""
        self._actions.clear()
        self._logger.debug("Cleared all rollback actions")


def create_rollback_coordinator(logger: logging.Logger) -> RollbackCoordinator:
    """创建回滚协调器的工厂函数"""
    return RollbackCoordinator(logger)
