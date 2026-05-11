"""
并发控制服务
解决并发场景下的数据一致性问题
"""
from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Callable, TypeVar

from database.state_repo import StateRepo
from utils.logger import set_event_type


if TYPE_CHECKING:
    from services.runtime_service import RuntimeContext


T = TypeVar('T')


class LockType(Enum):
    """锁类型"""
    SHARED = "shared"      # 共享锁，允许多个读操作
    EXCLUSIVE = "exclusive"  # 排他锁，阻止所有读写


@dataclass(frozen=True)
class LockRequest:
    """锁请求"""
    lock_key: str
    lock_type: LockType
    timeout_seconds: float
    correlation_id: str
    owner_id: str
    created_at: str


@dataclass(frozen=True)
class LockResult:
    """锁获取结果"""
    acquired: bool
    lock_key: str
    lock_type: LockType
    acquired_at: str | None = None
    wait_time_seconds: float | None = None
    error: str | None = None


@dataclass
class LockStatistics:
    """锁统计信息"""
    total_acquires: int = 0
    successful_acquires: int = 0
    failed_acquires: int = 0
    deadlocks_detected: int = 0
    lock_contention_count: int = 0
    average_wait_time: float = 0.0
    max_wait_time: float = 0.0


class InProcessLock:
    """
    进程内锁实现

    使用 threading.RLock 实现，用于保护同一进程内的并发访问
    """

    def __init__(self, lock_key: str) -> None:
        self._lock_key = lock_key
        self._lock = threading.RLock()
        self._holder: str | None = None
        self._acquire_time: float | None = None
        self._reference_count = 0

    def acquire(
        self,
        owner_id: str,
        timeout_seconds: float,
        correlation_id: str,
    ) -> LockResult:
        """尝试获取锁"""
        start_time = time.time()

        acquired = self._lock.acquire(timeout=timeout_seconds)
        wait_time = time.time() - start_time

        if acquired:
            self._holder = owner_id
            self._acquire_time = time.time()
            self._reference_count += 1
            return LockResult(
                acquired=True,
                lock_key=self._lock_key,
                lock_type=LockType.EXCLUSIVE,
                acquired_at=datetime.utcnow().isoformat(),
                wait_time_seconds=wait_time,
            )
        else:
            return LockResult(
                acquired=False,
                lock_key=self._lock_key,
                lock_type=LockType.EXCLUSIVE,
                wait_time_seconds=wait_time,
                error=f"Lock acquisition timeout after {timeout_seconds}s",
            )

    def release(self, owner_id: str) -> bool:
        """释放锁"""
        if self._holder != owner_id:
            return False

        self._reference_count -= 1
        if self._reference_count <= 0:
            self._holder = None
            self._acquire_time = None
            self._reference_count = 0
            self._lock.release()
        return True

    @property
    def is_held(self) -> bool:
        """检查锁是否被持有"""
        return self._holder is not None

    @property
    def holder(self) -> str | None:
        """获取当前持有者"""
        return self._holder


class ConcurrencyControlService:
    """
    并发控制服务

    提供多层次的并发控制机制：
    1. 进程内锁 - threading.RLock
    2. 数据库操作锁 - SQLite UNIQUE constraint + expires_at
    3. 分布式锁接口 - 可扩展到 Redis
    """

    LOCK_SCOPE_NODE = "node"           # 节点级别锁
    LOCK_SCOPE_ASSET = "asset"         # 资产级别锁
    LOCK_SCOPE_ACCOUNT = "account"      # 账户级别锁
    LOCK_SCOPE_REGION_PROTOCOL = "rp"   # 区域+协议级别锁

    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime_context = runtime_context
        self._logger = runtime_context.logger.getChild("services.concurrency_control")
        self._state_repo = StateRepo(runtime_context)

        # 进程内锁映射
        self._in_process_locks: dict[str, InProcessLock] = {}
        self._locks_lock = threading.Lock()

        # 统计信息
        self._stats = LockStatistics()

    def _utcnow_iso(self) -> str:
        """获取当前 UTC 时间 ISO 格式字符串"""
        return datetime.utcnow().isoformat()

    def _get_in_process_lock(self, lock_key: str) -> InProcessLock:
        """获取进程内锁"""
        with self._locks_lock:
            if lock_key not in self._in_process_locks:
                self._in_process_locks[lock_key] = InProcessLock(lock_key)
            return self._in_process_locks[lock_key]

    def acquire_operation_lock(
        self,
        scope: str,
        resource_id: str,
        operation_type: str,
        timeout_seconds: float = 30.0,
    ) -> LockResult:
        """
        获取操作锁

        Args:
            scope: 锁作用域
            resource_id: 资源 ID
            operation_type: 操作类型
            timeout_seconds: 超时时间

        Returns:
            LockResult 锁获取结果
        """
        lock_key = f"{scope}:{resource_id}"
        owner_id = f"{self._runtime_context.correlation_id or 'unknown'}-{threading.get_ident()}"
        correlation_id = self._runtime_context.correlation_id or "no-correlation"

        self._stats.total_acquires += 1
        start_time = time.time()

        # 1. 先尝试获取数据库操作锁
        try:
            db_lock_result = self._try_acquire_db_lock(
                lock_key=lock_key,
                operation_type=operation_type,
                owner_id=owner_id,
                correlation_id=correlation_id,
                timeout_seconds=timeout_seconds,
            )

            if not db_lock_result.acquired:
                self._stats.failed_acquires += 1
                self._stats.lock_contention_count += 1
                return db_lock_result

            # 2. 获取进程内锁
            in_process_lock = self._get_in_process_lock(lock_key)
            ip_result = in_process_lock.acquire(
                owner_id=owner_id,
                timeout_seconds=timeout_seconds,
                correlation_id=correlation_id,
            )

            if not ip_result.acquired:
                # 释放数据库锁
                self._release_db_lock(lock_key)
                self._stats.failed_acquires += 1
                self._stats.lock_contention_count += 1
                return ip_result

            # 成功获取所有锁
            self._stats.successful_acquires += 1
            wait_time = time.time() - start_time
            self._update_wait_stats(wait_time)

            set_event_type("lock_acquired")
            self._logger.debug(
                "Acquired lock: key=%s owner=%s wait_time=%.3fs",
                lock_key,
                owner_id,
                wait_time,
            )

            return LockResult(
                acquired=True,
                lock_key=lock_key,
                lock_type=LockType.EXCLUSIVE,
                acquired_at=self._utcnow_iso(),
                wait_time_seconds=wait_time,
            )

        except Exception as exc:
            self._stats.failed_acquires += 1
            self._logger.exception("Failed to acquire lock: %s", lock_key)
            return LockResult(
                acquired=False,
                lock_key=lock_key,
                lock_type=LockType.EXCLUSIVE,
                error=str(exc),
            )

    def release_operation_lock(self, scope: str, resource_id: str) -> bool:
        """
        释放操作锁

        Args:
            scope: 锁作用域
            resource_id: 资源 ID

        Returns:
            是否成功释放
        """
        lock_key = f"{scope}:{resource_id}"
        owner_id = f"{self._runtime_context.correlation_id or 'unknown'}-{threading.get_ident()}"

        # 1. 释放进程内锁
        in_process_lock = self._get_in_process_lock(lock_key)
        in_process_lock.release(owner_id)

        # 2. 释放数据库锁
        self._release_db_lock(lock_key)

        set_event_type("lock_released")
        self._logger.debug("Released lock: key=%s owner=%s", lock_key, owner_id)
        return True

    def _try_acquire_db_lock(
        self,
        lock_key: str,
        operation_type: str,
        owner_id: str,
        correlation_id: str,
        timeout_seconds: float,
    ) -> LockResult:
        """尝试获取数据库操作锁"""
        # 清理过期锁
        self._state_repo.purge_expired_locks()

        try:
            # 创建锁请求
            lock_request = self._create_lock_request(
                lock_key=lock_key,
                operation_type=operation_type,
                correlation_id=correlation_id,
                expires_in_seconds=timeout_seconds,
            )

            acquired = self._state_repo.acquire_operation_lock(lock_request)

        except Exception as exc:
            self._logger.warning("Failed to acquire db lock via StateRepo: %s", exc)
            # 尝试直接插入
            acquired = self._db_lock_insert(lock_key, operation_type, owner_id, correlation_id)

        if acquired:
            return LockResult(
                acquired=True,
                lock_key=lock_key,
                lock_type=LockType.EXCLUSIVE,
                acquired_at=self._utcnow_iso(),
            )
        else:
            return LockResult(
                acquired=False,
                lock_key=lock_key,
                lock_type=LockType.EXCLUSIVE,
                error=f"Lock already held: {lock_key}",
            )

    def _db_lock_insert(
        self,
        lock_key: str,
        operation_type: str,
        owner_id: str,
        correlation_id: str,
        expires_at: datetime,
    ) -> bool:
        """直接插入数据库锁记录"""
        try:
            with self._runtime_context.sqlite_manager.connection() as conn:
                try:
                    now = datetime.utcnow()
                    expires_at = now + timedelta(seconds=30)
                    conn.execute(
                        """
                        INSERT INTO fleet_operation_locks (
                            lock_key, operation_type, correlation_id, expires_at,
                            created_at, node_id
                        )
                        VALUES (?, ?, ?, ?, ?, NULL)
                        """,
                        (
                            lock_key,
                            operation_type,
                            correlation_id,
                            expires_at.isoformat(),
                            now.isoformat(),
                        ),
                    )
                    return True
                except sqlite3.IntegrityError:
                    # 锁已存在
                    return False
        except Exception as exc:
            self._logger.warning("Failed to insert db lock: %s", exc)
            return False

    def _release_db_lock(self, lock_key: str) -> None:
        """释放数据库锁"""
        try:
            self._state_repo.release_operation_lock(lock_key)
        except Exception as exc:
            self._logger.warning("Failed to release db lock %s: %s", lock_key, exc)

    def _create_lock_request(
        self,
        lock_key: str,
        operation_type: str,
        correlation_id: str,
        expires_in_seconds: float,
    ):
        """创建锁请求对象"""
        from database.state_models import FleetOperationLockRequest
        return FleetOperationLockRequest(
            lock_key=lock_key,
            operation_type=operation_type,
            correlation_id=correlation_id,
            expires_in_seconds=expires_in_seconds,
        )

    def _update_wait_stats(self, wait_time: float) -> None:
        """更新等待时间统计"""
        total = self._stats.successful_acquires
        if total <= 1:
            self._stats.average_wait_time = wait_time
        else:
            self._stats.average_wait_time = (
                (self._stats.average_wait_time * (total - 1) + wait_time) / total
            )
        if wait_time > self._stats.max_wait_time:
            self._stats.max_wait_time = wait_time

    def is_locked(self, scope: str, resource_id: str) -> bool:
        """检查资源是否被锁定"""
        lock_key = f"{scope}:{resource_id}"
        in_process_lock = self._get_in_process_lock(lock_key)
        return in_process_lock.is_held

    def get_lock_holder(self, scope: str, resource_id: str) -> str | None:
        """获取当前锁持有者"""
        lock_key = f"{scope}:{resource_id}"
        in_process_lock = self._get_in_process_lock(lock_key)
        return in_process_lock.holder

    def get_statistics(self) -> LockStatistics:
        """获取锁统计信息"""
        return self._stats

    @contextmanager
    def node_operation_lock(
        self,
        xboard_node_id: int,
        operation_type: str,
        timeout_seconds: float = 30.0,
    ):
        """
        节点操作锁上下文管理器

        使用方式：
        with concurrency_control.node_operation_lock(node_id, "provisioning"):
            # 执行节点操作
        """
        result = self.acquire_operation_lock(
            scope=self.LOCK_SCOPE_NODE,
            resource_id=str(xboard_node_id),
            operation_type=operation_type,
            timeout_seconds=timeout_seconds,
        )

        if not result.acquired:
            raise ConcurrencyError(
                f"Failed to acquire lock for node {xboard_node_id}: {result.error}"
            )

        try:
            yield
        finally:
            self.release_operation_lock(
                scope=self.LOCK_SCOPE_NODE,
                resource_id=str(xboard_node_id),
            )

    @contextmanager
    def asset_operation_lock(
        self,
        asset_id: int,
        operation_type: str,
        timeout_seconds: float = 30.0,
    ):
        """
        资产操作锁上下文管理器
        """
        result = self.acquire_operation_lock(
            scope=self.LOCK_SCOPE_ASSET,
            resource_id=str(asset_id),
            operation_type=operation_type,
            timeout_seconds=timeout_seconds,
        )

        if not result.acquired:
            raise ConcurrencyError(
                f"Failed to acquire lock for asset {asset_id}: {result.error}"
            )

        try:
            yield
        finally:
            self.release_operation_lock(
                scope=self.LOCK_SCOPE_ASSET,
                resource_id=str(asset_id),
            )

    @contextmanager
    def account_operation_lock(
        self,
        aws_account_id: str,
        operation_type: str,
        timeout_seconds: float = 60.0,
    ):
        """
        账户操作锁上下文管理器

        用于确保同一账户的操作串行执行
        """
        result = self.acquire_operation_lock(
            scope=self.LOCK_SCOPE_ACCOUNT,
            resource_id=aws_account_id,
            operation_type=operation_type,
            timeout_seconds=timeout_seconds,
        )

        if not result.acquired:
            raise ConcurrencyError(
                f"Failed to acquire lock for account {aws_account_id}: {result.error}"
            )

        try:
            yield
        finally:
            self.release_operation_lock(
                scope=self.LOCK_SCOPE_ACCOUNT,
                resource_id=aws_account_id,
            )

    @contextmanager
    def region_protocol_lock(
        self,
        region: str,
        protocol_type: str,
        operation_type: str,
        timeout_seconds: float = 30.0,
    ):
        """
        区域+协议操作锁上下文管理器

        用于确保同一区域+协议的调度操作串行执行
        """
        resource_id = f"{region}:{protocol_type}"
        result = self.acquire_operation_lock(
            scope=self.LOCK_SCOPE_REGION_PROTOCOL,
            resource_id=resource_id,
            operation_type=operation_type,
            timeout_seconds=timeout_seconds,
        )

        if not result.acquired:
            raise ConcurrencyError(
                f"Failed to acquire lock for region/protocol {resource_id}: {result.error}"
            )

        try:
            yield
        finally:
            self.release_operation_lock(
                scope=self.LOCK_SCOPE_REGION_PROTOCOL,
                resource_id=resource_id,
            )

    def with_lock_retry(
        self,
        lock_scope: str,
        resource_id: str,
        operation_type: str,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
        """
        带锁重试的上下文管理器装饰器

        当锁获取失败时自动重试
        """
        def decorator(func: Callable[[], T]) -> Callable[[], T]:
            def wrapper() -> T:
                last_error: Exception | None = None
                for attempt in range(max_retries):
                    try:
                        with self.acquire_operation_lock(lock_scope, resource_id, operation_type):
                            return func()
                    except ConcurrencyError as exc:
                        last_error = exc
                        self._logger.warning(
                            "Lock acquisition failed (attempt %d/%d), retrying: %s",
                            attempt + 1,
                            max_retries,
                            exc,
                        )
                        if attempt < max_retries - 1:
                            time.sleep(retry_delay * (attempt + 1))
                        else:
                            raise

                if last_error:
                    raise last_error

            return wrapper
        return decorator


class ConcurrencyError(Exception):
    """并发错误"""
    pass


class DeadlockDetector:
    """
    死锁检测器

    检测可能的死锁情况并提供警告
    """

    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime_context = runtime_context
        self._logger = runtime_context.logger.getChild("services.deadlock_detector")
        self._lock_wait_graph: dict[str, set[str]] = {}  # owner -> waiting_for locks
        self._lock_hold_graph: dict[str, set[str]] = {}  # lock -> holders

    def record_lock_wait(self, owner_id: str, lock_key: str) -> None:
        """记录锁等待"""
        if owner_id not in self._lock_wait_graph:
            self._lock_wait_graph[owner_id] = set()
        self._lock_wait_graph[owner_id].add(lock_key)

    def record_lock_acquire(self, owner_id: str, lock_key: str) -> None:
        """记录锁获取"""
        if lock_key not in self._lock_hold_graph:
            self._lock_hold_graph[lock_key] = set()
        self._lock_hold_graph[lock_key].add(owner_id)

        # 清除等待记录
        if owner_id in self._lock_wait_graph:
            self._lock_wait_graph[owner_id].discard(lock_key)

    def record_lock_release(self, owner_id: str, lock_key: str) -> None:
        """记录锁释放"""
        if lock_key in self._lock_hold_graph:
            self._lock_hold_graph[lock_key].discard(owner_id)

    def detect_potential_deadlock(self) -> list[str]:
        """检测可能的死锁"""
        potential_deadlocks: list[str] = []

        # 检查循环等待
        for owner, waiting_locks in self._lock_wait_graph.items():
            for lock_key in waiting_locks:
                if lock_key in self._lock_hold_graph:
                    holders = self._lock_hold_graph[lock_key]
                    for holder in holders:
                        if holder in self._lock_wait_graph:
                            # 发现循环等待
                            deadlock_chain = self._build_deadlock_chain(owner, holder)
                            potential_deadlocks.append(deadlock_chain)

                            self._logger.warning(
                                "Potential deadlock detected: %s",
                                deadlock_chain,
                            )

        return potential_deadlocks

    def _build_deadlock_chain(self, owner1: str, owner2: str) -> str:
        """构建死锁链"""
        chain = [owner1]
        current = owner2

        visited = {owner1, owner2}
        while current not in visited:
            chain.append(current)
            visited.add(current)
            if current in self._lock_wait_graph:
                waiting = list(self._lock_wait_graph[current])
                if waiting:
                    lock_key = waiting[0]
                    if lock_key in self._lock_hold_graph:
                        holders = list(self._lock_hold_graph[lock_key])
                        if holders and holders[0] != current:
                            current = holders[0]
                            continue
            break

        chain.append(owner1)
        return " -> ".join(chain[:10])  # 限制长度


# 全局并发控制服务实例
_global_concurrency_control: ConcurrencyControlService | None = None


def get_concurrency_control(runtime_context: RuntimeContext) -> ConcurrencyControlService:
    """获取全局并发控制服务"""
    global _global_concurrency_control
    if _global_concurrency_control is None:
        _global_concurrency_control = ConcurrencyControlService(runtime_context)
    return _global_concurrency_control
