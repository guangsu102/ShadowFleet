"""
增强的错误处理和回滚机制
提供更完善的错误处理、重试机制和回滚策略
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Callable, TypeVar

from utils.logger import set_event_type


if TYPE_CHECKING:
    from services.runtime_service import RuntimeContext


class ErrorSeverity(Enum):
    """错误严重程度"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class RetryStrategy(Enum):
    """重试策略"""
    NONE = "none"
    IMMEDIATE = "immediate"
    LINEAR_BACKOFF = "linear_backoff"
    EXPONENTIAL_BACKOFF = "exponential_backoff"


@dataclass(frozen=True)
class ErrorContext:
    """错误上下文"""
    operation_name: str
    error: BaseException
    severity: ErrorSeverity
    correlation_id: str | None = None
    xboard_node_id: int | None = None
    instance_id: str | None = None
    asset_id: int | None = None
    timestamp: str | None = None
    metadata: dict | None = None


@dataclass(frozen=True)
class RollbackTask:
    """回滚任务"""
    task_id: str
    resource_type: str  # ec2_instance, dns_record, node, etc.
    resource_id: str
    action: str  # terminate, delete, release, etc.
    status: str  # pending, executing, completed, failed
    created_at: str
    executed_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    retry_count: int = 0
    max_retries: int = 3


@dataclass(frozen=True)
class RollbackResult:
    """回滚结果"""
    success: bool
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    rollback_tasks: tuple[RollbackTask, ...]
    duration_seconds: float
    orphan_resources: tuple[str, ...]


@dataclass(frozen=True)
class RetryPolicy:
    """重试策略配置"""
    strategy: RetryStrategy
    max_attempts: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0
    jitter: bool = True


@dataclass
class ErrorRecoveryState:
    """错误恢复状态"""
    rollback_tasks: list[RollbackTask] = field(default_factory=list)
    orphan_resources: list[str] = field(default_factory=list)
    error_history: list[ErrorContext] = field(default_factory=list)


class EnhancedErrorHandler:
    """
    增强的错误处理器

    功能：
    1. 智能重试机制（指数退避、线性退避）
    2. 分层回滚管理
    3. 错误聚合和去重
    4. 恢复状态跟踪
    """

    def __init__(self, runtime_context: RuntimeContext, operation_name: str) -> None:
        self._runtime_context = runtime_context
        self._logger = runtime_context.logger.getChild(f"services.error_handler.{operation_name}")
        self._operation_name = operation_name
        self._state = ErrorRecoveryState()
        self._correlation_id = runtime_context.correlation_id

    def _utcnow_iso(self) -> str:
        """获取当前 UTC 时间 ISO 格式字符串"""
        return datetime.utcnow().isoformat()

    def execute_with_retry(
        self,
        operation: Callable[[], T],
        retry_policy: RetryPolicy,
        error_handler: Callable[[ErrorContext], None] | None = None,
    ) -> T:
        """
        执行带重试的操作

        Args:
            operation: 要执行的操作
            retry_policy: 重试策略
            error_handler: 错误处理器回调

        Returns:
            操作结果

        Raises:
            最后一次执行的异常
        """
        last_error: BaseException | None = None
        strategy = retry_policy.strategy

        for attempt in range(retry_policy.max_attempts):
            try:
                result = operation()
                if attempt > 0:
                    self._logger.info(
                        "Operation succeeded after %d retries: %s",
                        attempt,
                        self._operation_name,
                    )
                return result
            except Exception as exc:
                last_error = exc

                # 记录错误
                error_ctx = ErrorContext(
                    operation_name=self._operation_name,
                    error=exc,
                    severity=self._classify_error_severity(exc),
                    correlation_id=self._correlation_id,
                    timestamp=self._utcnow_iso(),
                )
                self._state.error_history.append(error_ctx)

                # 调用错误处理器
                if error_handler:
                    error_handler(error_ctx)

                # 如果不是最后一次尝试，则重试
                if attempt < retry_policy.max_attempts - 1:
                    delay = self._calculate_retry_delay(retry_policy, attempt)
                    self._logger.warning(
                        "Operation failed (attempt %d/%d), retrying in %.2fs: %s - %s",
                        attempt + 1,
                        retry_policy.max_attempts,
                        delay,
                        self._operation_name,
                        exc,
                    )
                    time.sleep(delay)
                else:
                    self._logger.error(
                        "Operation failed after %d attempts: %s - %s",
                        retry_policy.max_attempts,
                        self._operation_name,
                        exc,
                    )

        if last_error:
            raise last_error

        # 不应该到达这里
        raise RuntimeError(f"Operation failed: {self._operation_name}")

    def _calculate_retry_delay(self, policy: RetryPolicy, attempt: int) -> float:
        """计算重试延迟"""
        if policy.strategy == RetryStrategy.NONE:
            return 0

        if policy.strategy == RetryStrategy.IMMEDIATE:
            delay = 0
        elif policy.strategy == RetryStrategy.LINEAR_BACKOFF:
            delay = policy.base_delay_seconds * (attempt + 1)
        elif policy.strategy == RetryStrategy.EXPONENTIAL_BACKOFF:
            delay = policy.base_delay_seconds * (2 ** attempt)
        else:
            delay = policy.base_delay_seconds

        # 限制最大延迟
        delay = min(delay, policy.max_delay_seconds)

        # 添加抖动
        if policy.jitter:
            import random
            delay = delay * (0.5 + random.random())

        return delay

    def _classify_error_severity(self, error: BaseException) -> ErrorSeverity:
        """分类错误严重程度"""
        error_type = type(error).__name__.lower()

        if "timeout" in error_type or "connection" in error_type:
            return ErrorSeverity.WARNING
        if "notfound" in error_type or "not found" in str(error).lower():
            return ErrorSeverity.INFO
        if "permission" in error_type or "auth" in error_type:
            return ErrorSeverity.CRITICAL
        if "integrity" in error_type or "constraint" in error_type:
            return ErrorSeverity.ERROR

        return ErrorSeverity.ERROR


class RollbackCoordinator:
    """
    回滚协调器

    管理资源回滚任务，确保按正确顺序执行回滚
    """

    def __init__(self, runtime_context: RuntimeContext, operation_name: str) -> None:
        self._runtime_context = runtime_context
        self._logger = runtime_context.logger.getChild(f"services.rollback.{operation_name}")
        self._operation_name = operation_name
        self._rollback_tasks: list[RollbackTask] = []
        self._orphan_resources: list[str] = []
        self._start_time: float = 0

    def add_rollback_task(
        self,
        resource_type: str,
        resource_id: str,
        action: str,
        executor: Callable[[], None],
        max_retries: int = 3,
        depends_on: list[str] | None = None,
    ) -> str:
        """
        添加回滚任务

        Args:
            resource_type: 资源类型
            resource_id: 资源 ID
            action: 操作类型
            executor: 执行函数
            max_retries: 最大重试次数
            depends_on: 依赖的任务 ID 列表

        Returns:
            任务 ID
        """
        task_id = f"rollback-{resource_type}-{resource_id}-{len(self._rollback_tasks)}"

        task = RollbackTask(
            task_id=task_id,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            status="pending",
            created_at=datetime.utcnow().isoformat(),
            max_retries=max_retries,
        )

        # 存储执行器
        setattr(self, f"_executor_{task_id}", executor)

        self._rollback_tasks.append(task)
        self._logger.info(
            "Added rollback task: %s for %s %s",
            task_id,
            resource_type,
            resource_id,
        )

        return task_id

    def execute_rollback(self) -> RollbackResult:
        """
        执行所有回滚任务

        按依赖顺序和资源依赖关系执行回滚
        """
        self._start_time = time.time()
        start_time_iso = datetime.utcnow().isoformat()
        set_event_type("rollback_started")

        completed = 0
        failed = 0
        tasks_to_execute = self._rollback_tasks.copy()

        # 按依赖顺序执行回滚（先创建的后回滚，逆序）
        for task in reversed(tasks_to_execute):
            if task.status != "pending":
                continue

            success = self._execute_single_task(task)
            if success:
                completed += 1
            else:
                failed += 1

        duration = time.time() - self._start_time

        # 更新孤儿资源列表
        for task in self._rollback_tasks:
            if task.status == "failed":
                orphan = f"{task.resource_type}:{task.resource_id}"
                if orphan not in self._orphan_resources:
                    self._orphan_resources.append(orphan)

        result = RollbackResult(
            success=failed == 0,
            total_tasks=len(self._rollback_tasks),
            completed_tasks=completed,
            failed_tasks=failed,
            rollback_tasks=tuple(self._rollback_tasks),
            duration_seconds=duration,
            orphan_resources=tuple(self._orphan_resources),
        )

        if result.success:
            set_event_type("rollback_completed")
            self._logger.info(
                "Rollback completed successfully: tasks=%d duration=%.2fs",
                completed,
                duration,
            )
        else:
            set_event_type("rollback_incomplete")
            self._logger.error(
                "Rollback completed with failures: total=%d completed=%d failed=%d orphans=%d duration=%.2fs",
                result.total_tasks,
                completed,
                failed,
                len(self._orphan_resources),
                duration,
            )

        return result

    def _execute_single_task(self, task: RollbackTask) -> bool:
        """执行单个回滚任务"""
        executor_attr = f"_executor_{task.task_id}"
        if not hasattr(self, executor_attr):
            self._logger.error("No executor found for task: %s", task.task_id)
            return False

        executor: Callable[[], None] = getattr(self, executor_attr)

        for retry in range(task.max_retries + 1):
            task.status = "executing"
            task.executed_at = datetime.utcnow().isoformat()

            try:
                executor()
                task.status = "completed"
                task.completed_at = datetime.utcnow().isoformat()
                self._logger.info(
                    "Rollback task completed: %s for %s %s",
                    task.task_id,
                    task.resource_type,
                    task.resource_id,
                )
                return True
            except Exception as exc:
                task.retry_count = retry + 1
                task.error = str(exc)

                if retry < task.max_retries:
                    delay = min(2 ** retry * 1.0, 30.0)  # 指数退避，最大 30 秒
                    self._logger.warning(
                        "Rollback task failed (attempt %d/%d), retrying in %.2fs: %s - %s",
                        retry + 1,
                        task.max_retries + 1,
                        delay,
                        task.task_id,
                        exc,
                    )
                    time.sleep(delay)
                else:
                    task.status = "failed"
                    task.completed_at = datetime.utcnow().isoformat()
                    self._logger.error(
                        "Rollback task failed after %d attempts: %s - %s",
                        task.max_retries + 1,
                        task.task_id,
                        exc,
                    )
                    set_event_type("rollback_task_failed")
                    return False

        return False

    def get_pending_tasks(self) -> list[RollbackTask]:
        """获取待执行的回滚任务"""
        return [t for t in self._rollback_tasks if t.status == "pending"]

    def get_failed_tasks(self) -> list[RollbackTask]:
        """获取失败的回滚任务"""
        return [t for t in self._rollback_tasks if t.status == "failed"]

    def get_completed_tasks(self) -> list[RollbackTask]:
        """获取已完成的回滚任务"""
        return [t for t in self._rollback_tasks if t.status == "completed"]


# 预定义的重试策略
RETRY_POLICIES = {
    "default": RetryPolicy(
        strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
        max_attempts=3,
        base_delay_seconds=1.0,
        max_delay_seconds=30.0,
        jitter=True,
    ),
    "aws_api": RetryPolicy(
        strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
        max_attempts=5,
        base_delay_seconds=2.0,
        max_delay_seconds=60.0,
        jitter=True,
    ),
    "database": RetryPolicy(
        strategy=RetryStrategy.LINEAR_BACKOFF,
        max_attempts=3,
        base_delay_seconds=0.5,
        max_delay_seconds=10.0,
        jitter=False,
    ),
    "no_retry": RetryPolicy(
        strategy=RetryStrategy.NONE,
        max_attempts=1,
    ),
}


def create_error_handler(
    runtime_context: RuntimeContext,
    operation_name: str,
) -> EnhancedErrorHandler:
    """创建错误处理器"""
    return EnhancedErrorHandler(runtime_context, operation_name)


def create_rollback_coordinator(
    runtime_context: RuntimeContext,
    operation_name: str,
) -> RollbackCoordinator:
    """创建回滚协调器"""
    return RollbackCoordinator(runtime_context, operation_name)
