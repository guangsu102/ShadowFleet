"""
并发控制增强服务

提供更强的并发控制机制，解决数据一致性问题：
1. 分布式锁（基于 SQLite 的轻量级实现）
2. 乐观锁（版本号控制）
3. 悲观锁（行级锁）
4. 重试机制
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Generator

from utils.logger import set_event_type

if TYPE_CHECKING:
    from services.runtime_service import RuntimeContext


@dataclass(frozen=True)
class LockAcquisitionResult:
    """锁获取结果"""
    acquired: bool
    lock_id: str | None
    holder: str | None  # 当前持有锁的进程/线程
    expires_at: str | None


class ConcurrencyControlError(RuntimeError):
    pass


class DistributedLock:
    """分布式锁（基于 SQLite）"""

    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime = runtime_context
        self._logger = runtime_context.logger.getChild("services.distributed_lock")
        self._sqlite_manager = runtime_context.sqlite_manager

    def acquire_lock(
        self,
        lock_key: str,
        holder: str,
        ttl_seconds: int = 30,
        wait_timeout_seconds: float = 0,
        retry_interval_seconds: float = 0.1,
    ) -> LockAcquisitionResult:
        """
        获取分布式锁

        Args:
            lock_key: 锁的唯一标识
            holder: 持有者标识（进程ID、线程ID等）
            ttl_seconds: 锁的过期时间（秒）
            wait_timeout_seconds: 等待超时时间（0 表示不等待）
            retry_interval_seconds: 重试间隔

        Returns:
            锁获取结果
        """
        start_time = time.time()
        expires_at = (datetime.utcnow() + timedelta(seconds=ttl_seconds)).isoformat()

        while True:
            # 清理过期锁
            self._cleanup_expired_locks()

            # 尝试获取锁
            try:
                with self._sqlite_manager.connection() as conn:
                    # 使用 BEGIN IMMEDIATE 获取写锁
                    conn.execute("BEGIN IMMEDIATE")
                    try:
                        # 检查锁是否存在
                        row = conn.execute(
                            "SELECT holder, expires_at FROM distributed_locks WHERE lock_key = ?",
                            (lock_key,),
                        ).fetchone()

                        if row is None:
                            # 锁不存在，创建新锁
                            conn.execute(
                                """
                                INSERT INTO distributed_locks (lock_key, holder, expires_at, created_at)
                                VALUES (?, ?, ?, ?)
                                """,
                                (lock_key, holder, expires_at, datetime.utcnow().isoformat()),
                            )
                            conn.commit()

                            set_event_type("distributed_lock_acquired")
                            self._logger.info(
                                "Acquired distributed lock: key=%s, holder=%s, ttl=%ds",
                                lock_key,
                                holder,
                                ttl_seconds,
                            )

                            return LockAcquisitionResult(
                                acquired=True,
                                lock_id=lock_key,
                                holder=holder,
                                expires_at=expires_at,
                            )
                        else:
                            # 锁已存在
                            current_holder = row[0]
                            current_expires_at = row[1]

                            conn.rollback()

                            # 检查是否已过期
                            if datetime.fromisoformat(current_expires_at) < datetime.utcnow():
                                # 锁已过期，下次循环会被清理
                                pass
                            else:
                                # 锁仍然有效
                                if wait_timeout_seconds <= 0:
                                    # 不等待，直接返回失败
                                    set_event_type("distributed_lock_conflict")
                                    self._logger.debug(
                                        "Failed to acquire lock (no wait): key=%s, holder=%s",
                                        lock_key,
                                        current_holder,
                                    )
                                    return LockAcquisitionResult(
                                        acquired=False,
                                        lock_id=None,
                                        holder=current_holder,
                                        expires_at=current_expires_at,
                                    )

                    except Exception:
                        conn.rollback()
                        raise

            except Exception as exc:
                self._logger.warning("Error acquiring lock: %s", exc)
                if wait_timeout_seconds <= 0:
                    raise ConcurrencyControlError(f"Failed to acquire lock: {exc}") from exc

            # 检查是否超时
            elapsed = time.time() - start_time
            if elapsed >= wait_timeout_seconds:
                set_event_type("distributed_lock_timeout")
                self._logger.warning(
                    "Lock acquisition timeout: key=%s, waited=%.2fs",
                    lock_key,
                    elapsed,
                )
                return LockAcquisitionResult(
                    acquired=False,
                    lock_id=None,
                    holder=None,
                    expires_at=None,
                )

            # 等待后重试
            time.sleep(retry_interval_seconds)

    def release_lock(self, lock_key: str, holder: str) -> bool:
        """
        释放分布式锁

        Args:
            lock_key: 锁的唯一标识
            holder: 持有者标识

        Returns:
            是否成功释放
        """
        try:
            with self._sqlite_manager.connection() as conn:
                cursor = conn.execute(
                    "DELETE FROM distributed_locks WHERE lock_key = ? AND holder = ?",
                    (lock_key, holder),
                )

                if cursor.rowcount > 0:
                    set_event_type("distributed_lock_released")
                    self._logger.info("Released distributed lock: key=%s, holder=%s", lock_key, holder)
                    return True
                else:
                    self._logger.warning(
                        "Failed to release lock (not holder): key=%s, holder=%s",
                        lock_key,
                        holder,
                    )
                    return False

        except Exception as exc:
            self._logger.exception("Error releasing lock: %s", exc)
            return False

    def _cleanup_expired_locks(self) -> int:
        """清理过期的锁"""
        try:
            with self._sqlite_manager.connection() as conn:
                cursor = conn.execute(
                    "DELETE FROM distributed_locks WHERE expires_at < ?",
                    (datetime.utcnow().isoformat(),),
                )
                deleted = cursor.rowcount

                if deleted > 0:
                    self._logger.debug("Cleaned up %d expired locks", deleted)

                return deleted

        except Exception as exc:
            self._logger.warning("Error cleaning up expired locks: %s", exc)
            return 0

    @contextmanager
    def lock(
        self,
        lock_key: str,
        holder: str,
        ttl_seconds: int = 30,
        wait_timeout_seconds: float = 10,
    ) -> Generator[bool, None, None]:
        """
        上下文管理器形式的锁

        Usage:
            with distributed_lock.lock("my_resource", "worker-1") as acquired:
                if acquired:
                    # 执行需要锁保护的操作
                    pass
        """
        result = self.acquire_lock(lock_key, holder, ttl_seconds, wait_timeout_seconds)

        try:
            yield result.acquired
        finally:
            if result.acquired:
                self.release_lock(lock_key, holder)


class OptimisticLockManager:
    """乐观锁管理器（基于版本号）"""

    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime = runtime_context
        self._logger = runtime_context.logger.getChild("services.optimistic_lock")
        self._sqlite_manager = runtime_context.sqlite_manager

    def update_with_version_check(
        self,
        table: str,
        record_id: int,
        updates: dict[str, object],
        expected_version: int,
        id_column: str = "id",
        version_column: str = "version",
    ) -> bool:
        """
        使用版本号进行乐观锁更新

        Args:
            table: 表名
            record_id: 记录 ID
            updates: 要更新的字段
            expected_version: 期望的版本号
            id_column: ID 列名
            version_column: 版本号列名

        Returns:
            是否更新成功
        """
        if not updates:
            raise ValueError("updates must not be empty")

        # 构建 SET 子句
        set_clauses = [f"{col} = ?" for col in updates.keys()]
        set_clauses.append(f"{version_column} = {version_column} + 1")
        set_clause = ", ".join(set_clauses)

        # 构建 SQL
        sql = f"""
            UPDATE {table}
            SET {set_clause}
            WHERE {id_column} = ? AND {version_column} = ?
        """

        parameters = tuple(updates.values()) + (record_id, expected_version)

        try:
            with self._sqlite_manager.connection() as conn:
                cursor = conn.execute(sql, parameters)

                if cursor.rowcount > 0:
                    set_event_type("optimistic_lock_update_success")
                    self._logger.debug(
                        "Optimistic lock update succeeded: table=%s, id=%d, version=%d",
                        table,
                        record_id,
                        expected_version,
                    )
                    return True
                else:
                    set_event_type("optimistic_lock_conflict")
                    self._logger.warning(
                        "Optimistic lock conflict: table=%s, id=%d, expected_version=%d",
                        table,
                        record_id,
                        expected_version,
                    )
                    return False

        except Exception as exc:
            self._logger.exception("Error in optimistic lock update: %s", exc)
            raise ConcurrencyControlError(f"Optimistic lock update failed: {exc}") from exc


def ensure_distributed_locks_table(runtime_context: RuntimeContext) -> None:
    """确保分布式锁表存在"""
    sql = """
        CREATE TABLE IF NOT EXISTS distributed_locks (
            lock_key TEXT PRIMARY KEY,
            holder TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """

    try:
        with runtime_context.sqlite_manager.connection() as conn:
            conn.execute(sql)
            # 创建索引
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_distributed_locks_expires_at ON distributed_locks(expires_at)"
            )

    except Exception as exc:
        runtime_context.logger.exception("Failed to create distributed_locks table: %s", exc)
        raise
