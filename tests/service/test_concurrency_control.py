"""
并发控制服务单元测试
"""

import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from services.concurrency_control import (
    ConcurrencyControlError,
    DistributedLock,
    LockAcquisitionResult,
    OptimisticLockManager,
    ensure_distributed_locks_table,
)


@pytest.fixture
def mock_runtime():
    """创建模拟的运行时上下文"""
    runtime = MagicMock()
    runtime.logger = MagicMock()
    runtime.logger.getChild = MagicMock(return_value=MagicMock())
    runtime.sqlite_manager = MagicMock()
    return runtime


@pytest.fixture
def mock_connection():
    """创建模拟的数据库连接"""
    conn = MagicMock()
    conn.execute = MagicMock()
    conn.commit = MagicMock()
    conn.rollback = MagicMock()
    return conn


class TestDistributedLock:
    """分布式锁测试"""

    def test_acquire_lock_success(self, mock_runtime, mock_connection):
        """测试成功获取锁"""
        mock_connection.execute.return_value.fetchone.return_value = None
        mock_runtime.sqlite_manager.connection.return_value.__enter__.return_value = mock_connection

        lock = DistributedLock(mock_runtime)
        result = lock.acquire_lock("test_key", "holder1", ttl_seconds=30)

        assert result.acquired is True
        assert result.lock_id == "test_key"
        assert result.holder == "holder1"
        assert result.expires_at is not None

    def test_acquire_lock_already_held(self, mock_runtime, mock_connection):
        """测试锁已被持有"""
        expires_at = (datetime.utcnow() + timedelta(seconds=30)).isoformat()
        mock_connection.execute.return_value.fetchone.return_value = ("holder2", expires_at)
        mock_runtime.sqlite_manager.connection.return_value.__enter__.return_value = mock_connection

        lock = DistributedLock(mock_runtime)
        result = lock.acquire_lock("test_key", "holder1", ttl_seconds=30, wait_timeout_seconds=0)

        assert result.acquired is False
        assert result.lock_id is None
        assert result.holder == "holder2"

    def test_acquire_lock_expired(self, mock_runtime, mock_connection):
        """测试锁已过期"""
        expired_time = (datetime.utcnow() - timedelta(seconds=10)).isoformat()

        # 模拟多次调用：清理过期锁的 DELETE，检查锁的 SELECT（返回过期），再次 SELECT（返回 None）
        execute_mock = MagicMock()
        execute_mock.fetchone.side_effect = [
            ("holder2", expired_time),  # 第一次 SELECT 返回过期锁
            None  # 第二次 SELECT 返回 None（已清理）
        ]
        execute_mock.rowcount = 1  # DELETE 操作影响 1 行
        mock_connection.execute.return_value = execute_mock
        mock_runtime.sqlite_manager.connection.return_value.__enter__.return_value = mock_connection

        lock = DistributedLock(mock_runtime)
        result = lock.acquire_lock("test_key", "holder1", ttl_seconds=30, wait_timeout_seconds=1, retry_interval_seconds=0.1)

        assert result.acquired is True

    def test_acquire_lock_with_wait(self, mock_runtime, mock_connection):
        """测试等待获取锁"""
        expires_at = (datetime.utcnow() + timedelta(seconds=30)).isoformat()

        # 第一次返回锁被持有，第二次返回 None（锁已释放）
        mock_connection.execute.return_value.fetchone.side_effect = [
            ("holder2", expires_at),
            None
        ]
        mock_runtime.sqlite_manager.connection.return_value.__enter__.return_value = mock_connection

        lock = DistributedLock(mock_runtime)

        with patch("time.sleep"):
            result = lock.acquire_lock("test_key", "holder1", ttl_seconds=30, wait_timeout_seconds=1)

        assert result.acquired is True

    def test_acquire_lock_timeout(self, mock_runtime, mock_connection):
        """测试获取锁超时"""
        expires_at = (datetime.utcnow() + timedelta(seconds=30)).isoformat()
        mock_connection.execute.return_value.fetchone.return_value = ("holder2", expires_at)
        mock_runtime.sqlite_manager.connection.return_value.__enter__.return_value = mock_connection

        lock = DistributedLock(mock_runtime)

        with patch("time.sleep"):
            with patch("time.time", side_effect=[0, 0.5, 1.5]):
                result = lock.acquire_lock(
                    "test_key", "holder1", ttl_seconds=30,
                    wait_timeout_seconds=1, retry_interval_seconds=0.5
                )

        assert result.acquired is False
        assert result.lock_id is None

    def test_release_lock_success(self, mock_runtime, mock_connection):
        """测试成功释放锁"""
        mock_connection.execute.return_value.rowcount = 1
        mock_runtime.sqlite_manager.connection.return_value.__enter__.return_value = mock_connection

        lock = DistributedLock(mock_runtime)
        result = lock.release_lock("test_key", "holder1")

        assert result is True

    def test_release_lock_not_holder(self, mock_runtime, mock_connection):
        """测试释放不属于自己的锁"""
        mock_connection.execute.return_value.rowcount = 0
        mock_runtime.sqlite_manager.connection.return_value.__enter__.return_value = mock_connection

        lock = DistributedLock(mock_runtime)
        result = lock.release_lock("test_key", "holder1")

        assert result is False

    def test_release_lock_error(self, mock_runtime, mock_connection):
        """测试释放锁时发生错误"""
        mock_connection.execute.side_effect = Exception("Database error")
        mock_runtime.sqlite_manager.connection.return_value.__enter__.return_value = mock_connection

        lock = DistributedLock(mock_runtime)
        result = lock.release_lock("test_key", "holder1")

        assert result is False

    def test_cleanup_expired_locks(self, mock_runtime, mock_connection):
        """测试清理过期锁"""
        mock_connection.execute.return_value.rowcount = 3
        mock_runtime.sqlite_manager.connection.return_value.__enter__.return_value = mock_connection

        lock = DistributedLock(mock_runtime)
        deleted = lock._cleanup_expired_locks()

        assert deleted == 3

    def test_cleanup_expired_locks_error(self, mock_runtime, mock_connection):
        """测试清理过期锁时发生错误"""
        mock_connection.execute.side_effect = Exception("Database error")
        mock_runtime.sqlite_manager.connection.return_value.__enter__.return_value = mock_connection

        lock = DistributedLock(mock_runtime)
        deleted = lock._cleanup_expired_locks()

        assert deleted == 0

    def test_lock_context_manager_success(self, mock_runtime, mock_connection):
        """测试上下文管理器形式的锁（成功）"""
        mock_connection.execute.return_value.fetchone.return_value = None
        mock_connection.execute.return_value.rowcount = 1
        mock_runtime.sqlite_manager.connection.return_value.__enter__.return_value = mock_connection

        lock = DistributedLock(mock_runtime)

        with lock.lock("test_key", "holder1") as acquired:
            assert acquired is True

    def test_lock_context_manager_failed(self, mock_runtime, mock_connection):
        """测试上下文管理器形式的锁（失败）"""
        expires_at = (datetime.utcnow() + timedelta(seconds=30)).isoformat()
        mock_connection.execute.return_value.fetchone.return_value = ("holder2", expires_at)
        mock_runtime.sqlite_manager.connection.return_value.__enter__.return_value = mock_connection

        lock = DistributedLock(mock_runtime)

        with lock.lock("test_key", "holder1", wait_timeout_seconds=0) as acquired:
            assert acquired is False

    def test_lock_context_manager_auto_release(self, mock_runtime, mock_connection):
        """测试上下文管理器自动释放锁"""
        mock_connection.execute.return_value.fetchone.return_value = None
        mock_connection.execute.return_value.rowcount = 1
        mock_runtime.sqlite_manager.connection.return_value.__enter__.return_value = mock_connection

        lock = DistributedLock(mock_runtime)

        with lock.lock("test_key", "holder1") as acquired:
            pass

        # 验证释放锁被调用
        calls = [str(call) for call in mock_connection.execute.call_args_list]
        assert any("DELETE FROM distributed_locks" in call for call in calls)

    def test_acquire_lock_exception_no_wait(self, mock_runtime, mock_connection):
        """测试获取锁时发生异常（不等待）"""
        mock_connection.execute.side_effect = Exception("Database error")
        mock_runtime.sqlite_manager.connection.return_value.__enter__.return_value = mock_connection

        lock = DistributedLock(mock_runtime)

        with pytest.raises(ConcurrencyControlError):
            lock.acquire_lock("test_key", "holder1", wait_timeout_seconds=0)


class TestOptimisticLockManager:
    """乐观锁管理器测试"""

    def test_update_with_version_check_success(self, mock_runtime, mock_connection):
        """测试版本检查更新成功"""
        mock_connection.execute.return_value.rowcount = 1
        mock_runtime.sqlite_manager.connection.return_value.__enter__.return_value = mock_connection

        manager = OptimisticLockManager(mock_runtime)
        result = manager.update_with_version_check(
            table="nodes",
            record_id=1,
            updates={"status": "active"},
            expected_version=5
        )

        assert result is True

    def test_update_with_version_check_conflict(self, mock_runtime, mock_connection):
        """测试版本冲突"""
        mock_connection.execute.return_value.rowcount = 0
        mock_runtime.sqlite_manager.connection.return_value.__enter__.return_value = mock_connection

        manager = OptimisticLockManager(mock_runtime)
        result = manager.update_with_version_check(
            table="nodes",
            record_id=1,
            updates={"status": "active"},
            expected_version=5
        )

        assert result is False

    def test_update_with_version_check_multiple_fields(self, mock_runtime, mock_connection):
        """测试更新多个字段"""
        mock_connection.execute.return_value.rowcount = 1
        mock_runtime.sqlite_manager.connection.return_value.__enter__.return_value = mock_connection

        manager = OptimisticLockManager(mock_runtime)
        result = manager.update_with_version_check(
            table="nodes",
            record_id=1,
            updates={"status": "active", "name": "node1", "region": "us-east-1"},
            expected_version=5
        )

        assert result is True

    def test_update_with_version_check_custom_columns(self, mock_runtime, mock_connection):
        """测试使用自定义列名"""
        mock_connection.execute.return_value.rowcount = 1
        mock_runtime.sqlite_manager.connection.return_value.__enter__.return_value = mock_connection

        manager = OptimisticLockManager(mock_runtime)
        result = manager.update_with_version_check(
            table="custom_table",
            record_id=1,
            updates={"status": "active"},
            expected_version=5,
            id_column="custom_id",
            version_column="custom_version"
        )

        assert result is True

    def test_update_with_version_check_empty_updates(self, mock_runtime):
        """测试空更新"""
        manager = OptimisticLockManager(mock_runtime)

        with pytest.raises(ValueError, match="updates must not be empty"):
            manager.update_with_version_check(
                table="nodes",
                record_id=1,
                updates={},
                expected_version=5
            )

    def test_update_with_version_check_exception(self, mock_runtime, mock_connection):
        """测试更新时发生异常"""
        mock_connection.execute.side_effect = Exception("Database error")
        mock_runtime.sqlite_manager.connection.return_value.__enter__.return_value = mock_connection

        manager = OptimisticLockManager(mock_runtime)

        with pytest.raises(ConcurrencyControlError):
            manager.update_with_version_check(
                table="nodes",
                record_id=1,
                updates={"status": "active"},
                expected_version=5
            )


class TestEnsureDistributedLocksTable:
    """确保分布式锁表存在测试"""

    def test_ensure_table_success(self, mock_runtime, mock_connection):
        """测试成功创建表"""
        mock_runtime.sqlite_manager.connection.return_value.__enter__.return_value = mock_connection

        ensure_distributed_locks_table(mock_runtime)

        # 验证创建表和索引的 SQL 被执行
        assert mock_connection.execute.call_count >= 2

    def test_ensure_table_exception(self, mock_runtime, mock_connection):
        """测试创建表时发生异常"""
        mock_connection.execute.side_effect = Exception("Database error")
        mock_runtime.sqlite_manager.connection.return_value.__enter__.return_value = mock_connection

        with pytest.raises(Exception):
            ensure_distributed_locks_table(mock_runtime)


class TestLockAcquisitionResult:
    """锁获取结果测试"""

    def test_lock_acquisition_result_success(self):
        """测试成功的锁获取结果"""
        result = LockAcquisitionResult(
            acquired=True,
            lock_id="test_key",
            holder="holder1",
            expires_at="2026-05-10T12:00:00"
        )

        assert result.acquired is True
        assert result.lock_id == "test_key"
        assert result.holder == "holder1"
        assert result.expires_at == "2026-05-10T12:00:00"

    def test_lock_acquisition_result_failed(self):
        """测试失败的锁获取结果"""
        result = LockAcquisitionResult(
            acquired=False,
            lock_id=None,
            holder="holder2",
            expires_at="2026-05-10T12:00:00"
        )

        assert result.acquired is False
        assert result.lock_id is None
        assert result.holder == "holder2"

    def test_lock_acquisition_result_immutable(self):
        """测试锁获取结果不可变"""
        result = LockAcquisitionResult(
            acquired=True,
            lock_id="test_key",
            holder="holder1",
            expires_at="2026-05-10T12:00:00"
        )

        with pytest.raises(Exception):
            result.acquired = False
