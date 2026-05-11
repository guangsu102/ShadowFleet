"""
并发控制服务单元测试
"""

import threading
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from services.concurrency_control_service import (
    ConcurrencyControlService,
    ConcurrencyError,
    DeadlockDetector,
    InProcessLock,
    LockResult,
    LockStatistics,
    LockType,
    get_concurrency_control,
)


@pytest.fixture
def mock_runtime():
    """创建模拟的运行时上下文"""
    runtime = MagicMock()
    runtime.logger = MagicMock()
    runtime.logger.getChild = MagicMock(return_value=MagicMock())
    runtime.sqlite_manager = MagicMock()
    runtime.correlation_id = "test-correlation-123"
    return runtime


@pytest.fixture
def mock_state_repo():
    """创建模拟的状态仓库"""
    repo = MagicMock()
    repo.purge_expired_locks = MagicMock()
    repo.acquire_operation_lock = MagicMock(return_value=True)
    repo.release_operation_lock = MagicMock()
    return repo


class TestInProcessLock:
    """进程内锁测试"""

    def test_acquire_lock_success(self):
        """测试成功获取锁"""
        lock = InProcessLock("test_key")
        result = lock.acquire("owner1", timeout_seconds=1.0, correlation_id="corr1")

        assert result.acquired is True
        assert result.lock_key == "test_key"
        assert result.lock_type == LockType.EXCLUSIVE
        assert lock.is_held is True
        assert lock.holder == "owner1"

    def test_acquire_lock_timeout(self):
        """测试获取锁超时"""
        lock = InProcessLock("test_key")

        # 第一个持有者获取锁
        lock.acquire("owner1", timeout_seconds=1.0, correlation_id="corr1")

        # 使用线程来测试锁超时（因为 RLock 是可重入的，同一线程可以多次获取）
        def try_acquire():
            result = lock.acquire("owner2", timeout_seconds=0.1, correlation_id="corr2")
            return result

        import threading
        result_holder = []
        thread = threading.Thread(target=lambda: result_holder.append(try_acquire()))
        thread.start()
        thread.join()

        result = result_holder[0]
        assert result.acquired is False
        assert "timeout" in result.error.lower()

    def test_release_lock_success(self):
        """测试成功释放锁"""
        lock = InProcessLock("test_key")
        lock.acquire("owner1", timeout_seconds=1.0, correlation_id="corr1")

        result = lock.release("owner1")

        assert result is True
        assert lock.is_held is False
        assert lock.holder is None

    def test_release_lock_wrong_owner(self):
        """测试错误的持有者释放锁"""
        lock = InProcessLock("test_key")
        lock.acquire("owner1", timeout_seconds=1.0, correlation_id="corr1")

        result = lock.release("owner2")

        assert result is False
        assert lock.is_held is True
        assert lock.holder == "owner1"

    def test_reentrant_lock(self):
        """测试可重入锁"""
        lock = InProcessLock("test_key")

        # 同一持有者多次获取锁
        lock.acquire("owner1", timeout_seconds=1.0, correlation_id="corr1")
        lock.acquire("owner1", timeout_seconds=1.0, correlation_id="corr1")

        assert lock.is_held is True
        assert lock._reference_count == 2

        # 释放一次，锁仍然被持有
        lock.release("owner1")
        assert lock.is_held is True

        # 再次释放，锁被完全释放
        lock.release("owner1")
        assert lock.is_held is False


class TestConcurrencyControlService:
    """并发控制服务测试"""

    def test_acquire_operation_lock_success(self, mock_runtime, mock_state_repo):
        """测试成功获取操作锁"""
        with patch("services.concurrency_control_service.StateRepo", return_value=mock_state_repo):
            service = ConcurrencyControlService(mock_runtime)

            result = service.acquire_operation_lock(
                scope=ConcurrencyControlService.LOCK_SCOPE_NODE,
                resource_id="123",
                operation_type="provisioning",
                timeout_seconds=30.0
            )

        assert result.acquired is True
        assert result.lock_key == "node:123"
        assert result.lock_type == LockType.EXCLUSIVE

    def test_acquire_operation_lock_db_lock_failed(self, mock_runtime, mock_state_repo):
        """测试数据库锁获取失败"""
        mock_state_repo.acquire_operation_lock.return_value = False

        with patch("services.concurrency_control_service.StateRepo", return_value=mock_state_repo):
            service = ConcurrencyControlService(mock_runtime)

            result = service.acquire_operation_lock(
                scope=ConcurrencyControlService.LOCK_SCOPE_NODE,
                resource_id="123",
                operation_type="provisioning",
                timeout_seconds=30.0
            )

        assert result.acquired is False
        assert "already held" in result.error.lower()

    def test_release_operation_lock(self, mock_runtime, mock_state_repo):
        """测试释放操作锁"""
        with patch("services.concurrency_control_service.StateRepo", return_value=mock_state_repo):
            service = ConcurrencyControlService(mock_runtime)

            # 先获取锁
            service.acquire_operation_lock(
                scope=ConcurrencyControlService.LOCK_SCOPE_NODE,
                resource_id="123",
                operation_type="provisioning"
            )

            # 释放锁
            result = service.release_operation_lock(
                scope=ConcurrencyControlService.LOCK_SCOPE_NODE,
                resource_id="123"
            )

        assert result is True

    def test_is_locked(self, mock_runtime, mock_state_repo):
        """测试检查资源是否被锁定"""
        with patch("services.concurrency_control_service.StateRepo", return_value=mock_state_repo):
            service = ConcurrencyControlService(mock_runtime)

            # 未锁定
            assert service.is_locked(ConcurrencyControlService.LOCK_SCOPE_NODE, "123") is False

            # 获取锁
            service.acquire_operation_lock(
                scope=ConcurrencyControlService.LOCK_SCOPE_NODE,
                resource_id="123",
                operation_type="provisioning"
            )

            # 已锁定
            assert service.is_locked(ConcurrencyControlService.LOCK_SCOPE_NODE, "123") is True

    def test_get_lock_holder(self, mock_runtime, mock_state_repo):
        """测试获取锁持有者"""
        with patch("services.concurrency_control_service.StateRepo", return_value=mock_state_repo):
            service = ConcurrencyControlService(mock_runtime)

            # 未锁定
            assert service.get_lock_holder(ConcurrencyControlService.LOCK_SCOPE_NODE, "123") is None

            # 获取锁
            service.acquire_operation_lock(
                scope=ConcurrencyControlService.LOCK_SCOPE_NODE,
                resource_id="123",
                operation_type="provisioning"
            )

            # 获取持有者
            holder = service.get_lock_holder(ConcurrencyControlService.LOCK_SCOPE_NODE, "123")
            assert holder is not None
            assert "test-correlation-123" in holder

    def test_get_statistics(self, mock_runtime, mock_state_repo):
        """测试获取统计信息"""
        with patch("services.concurrency_control_service.StateRepo", return_value=mock_state_repo):
            service = ConcurrencyControlService(mock_runtime)

            stats = service.get_statistics()
            assert isinstance(stats, LockStatistics)
            assert stats.total_acquires == 0

            # 获取锁
            service.acquire_operation_lock(
                scope=ConcurrencyControlService.LOCK_SCOPE_NODE,
                resource_id="123",
                operation_type="provisioning"
            )

            stats = service.get_statistics()
            assert stats.total_acquires == 1
            assert stats.successful_acquires == 1

    def test_node_operation_lock_context_manager(self, mock_runtime, mock_state_repo):
        """测试节点操作锁上下文管理器"""
        with patch("services.concurrency_control_service.StateRepo", return_value=mock_state_repo):
            service = ConcurrencyControlService(mock_runtime)

            with service.node_operation_lock(123, "provisioning"):
                assert service.is_locked(ConcurrencyControlService.LOCK_SCOPE_NODE, "123") is True

            # 锁应该被释放
            assert service.is_locked(ConcurrencyControlService.LOCK_SCOPE_NODE, "123") is False

    def test_node_operation_lock_context_manager_failed(self, mock_runtime, mock_state_repo):
        """测试节点操作锁上下文管理器失败"""
        mock_state_repo.acquire_operation_lock.return_value = False

        with patch("services.concurrency_control_service.StateRepo", return_value=mock_state_repo):
            service = ConcurrencyControlService(mock_runtime)

            with pytest.raises(ConcurrencyError):
                with service.node_operation_lock(123, "provisioning"):
                    pass

    def test_asset_operation_lock_context_manager(self, mock_runtime, mock_state_repo):
        """测试资产操作锁上下文管理器"""
        with patch("services.concurrency_control_service.StateRepo", return_value=mock_state_repo):
            service = ConcurrencyControlService(mock_runtime)

            with service.asset_operation_lock(456, "allocation"):
                assert service.is_locked(ConcurrencyControlService.LOCK_SCOPE_ASSET, "456") is True

            assert service.is_locked(ConcurrencyControlService.LOCK_SCOPE_ASSET, "456") is False

    def test_account_operation_lock_context_manager(self, mock_runtime, mock_state_repo):
        """测试账户操作锁上下文管理器"""
        with patch("services.concurrency_control_service.StateRepo", return_value=mock_state_repo):
            service = ConcurrencyControlService(mock_runtime)

            with service.account_operation_lock("aws-123", "provisioning"):
                assert service.is_locked(ConcurrencyControlService.LOCK_SCOPE_ACCOUNT, "aws-123") is True

            assert service.is_locked(ConcurrencyControlService.LOCK_SCOPE_ACCOUNT, "aws-123") is False

    def test_region_protocol_lock_context_manager(self, mock_runtime, mock_state_repo):
        """测试区域+协议操作锁上下文管理器"""
        with patch("services.concurrency_control_service.StateRepo", return_value=mock_state_repo):
            service = ConcurrencyControlService(mock_runtime)

            with service.region_protocol_lock("us-east-1", "vless", "scheduling"):
                assert service.is_locked(ConcurrencyControlService.LOCK_SCOPE_REGION_PROTOCOL, "us-east-1:vless") is True

            assert service.is_locked(ConcurrencyControlService.LOCK_SCOPE_REGION_PROTOCOL, "us-east-1:vless") is False

    def test_update_wait_stats(self, mock_runtime, mock_state_repo):
        """测试更新等待时间统计"""
        with patch("services.concurrency_control_service.StateRepo", return_value=mock_state_repo):
            service = ConcurrencyControlService(mock_runtime)

            # 第一次获取锁
            service.acquire_operation_lock(
                scope=ConcurrencyControlService.LOCK_SCOPE_NODE,
                resource_id="123",
                operation_type="provisioning"
            )

            stats = service.get_statistics()
            assert stats.average_wait_time >= 0
            assert stats.max_wait_time >= 0

    def test_acquire_lock_exception(self, mock_runtime, mock_state_repo):
        """测试获取锁时发生异常"""
        mock_state_repo.purge_expired_locks.side_effect = Exception("Database error")

        with patch("services.concurrency_control_service.StateRepo", return_value=mock_state_repo):
            service = ConcurrencyControlService(mock_runtime)

            result = service.acquire_operation_lock(
                scope=ConcurrencyControlService.LOCK_SCOPE_NODE,
                resource_id="123",
                operation_type="provisioning"
            )

        assert result.acquired is False
        assert result.error is not None


class TestDeadlockDetector:
    """死锁检测器测试"""

    def test_record_lock_wait(self, mock_runtime):
        """测试记录锁等待"""
        detector = DeadlockDetector(mock_runtime)

        detector.record_lock_wait("owner1", "lock1")

        assert "owner1" in detector._lock_wait_graph
        assert "lock1" in detector._lock_wait_graph["owner1"]

    def test_record_lock_acquire(self, mock_runtime):
        """测试记录锁获取"""
        detector = DeadlockDetector(mock_runtime)

        detector.record_lock_wait("owner1", "lock1")
        detector.record_lock_acquire("owner1", "lock1")

        assert "lock1" in detector._lock_hold_graph
        assert "owner1" in detector._lock_hold_graph["lock1"]
        # 等待记录应该被清除
        assert "lock1" not in detector._lock_wait_graph.get("owner1", set())

    def test_record_lock_release(self, mock_runtime):
        """测试记录锁释放"""
        detector = DeadlockDetector(mock_runtime)

        detector.record_lock_acquire("owner1", "lock1")
        detector.record_lock_release("owner1", "lock1")

        assert "owner1" not in detector._lock_hold_graph.get("lock1", set())

    def test_detect_potential_deadlock(self, mock_runtime):
        """测试检测潜在死锁"""
        detector = DeadlockDetector(mock_runtime)

        # 模拟死锁场景：owner1 持有 lock1，等待 lock2；owner2 持有 lock2，等待 lock1
        detector.record_lock_acquire("owner1", "lock1")
        detector.record_lock_wait("owner1", "lock2")
        detector.record_lock_acquire("owner2", "lock2")
        detector.record_lock_wait("owner2", "lock1")

        deadlocks = detector.detect_potential_deadlock()

        assert len(deadlocks) > 0

    def test_no_deadlock(self, mock_runtime):
        """测试无死锁情况"""
        detector = DeadlockDetector(mock_runtime)

        # 正常的锁获取和释放
        detector.record_lock_acquire("owner1", "lock1")
        detector.record_lock_release("owner1", "lock1")
        detector.record_lock_acquire("owner2", "lock2")
        detector.record_lock_release("owner2", "lock2")

        deadlocks = detector.detect_potential_deadlock()

        assert len(deadlocks) == 0

    def test_build_deadlock_chain(self, mock_runtime):
        """测试构建死锁链"""
        detector = DeadlockDetector(mock_runtime)

        # 创建一个简单的死锁场景
        detector.record_lock_acquire("owner1", "lock1")
        detector.record_lock_wait("owner1", "lock2")
        detector.record_lock_acquire("owner2", "lock2")

        chain = detector._build_deadlock_chain("owner1", "owner2")

        # 验证链中包含相关的持有者
        assert "owner1" in chain


class TestGetConcurrencyControl:
    """全局并发控制服务测试"""

    def test_get_concurrency_control_singleton(self, mock_runtime, mock_state_repo):
        """测试获取全局并发控制服务（单例）"""
        with patch("services.concurrency_control_service.StateRepo", return_value=mock_state_repo):
            # 重置全局实例
            import services.concurrency_control_service
            services.concurrency_control_service._global_concurrency_control = None

            service1 = get_concurrency_control(mock_runtime)
            service2 = get_concurrency_control(mock_runtime)

            assert service1 is service2


class TestLockResult:
    """锁获取结果测试"""

    def test_lock_result_success(self):
        """测试成功的锁获取结果"""
        result = LockResult(
            acquired=True,
            lock_key="test_key",
            lock_type=LockType.EXCLUSIVE,
            acquired_at="2026-05-10T12:00:00",
            wait_time_seconds=0.5
        )

        assert result.acquired is True
        assert result.lock_key == "test_key"
        assert result.lock_type == LockType.EXCLUSIVE
        assert result.acquired_at == "2026-05-10T12:00:00"
        assert result.wait_time_seconds == 0.5

    def test_lock_result_failed(self):
        """测试失败的锁获取结果"""
        result = LockResult(
            acquired=False,
            lock_key="test_key",
            lock_type=LockType.EXCLUSIVE,
            error="Lock timeout"
        )

        assert result.acquired is False
        assert result.error == "Lock timeout"


class TestLockStatistics:
    """锁统计信息测试"""

    def test_lock_statistics_default(self):
        """测试默认的锁统计信息"""
        stats = LockStatistics()

        assert stats.total_acquires == 0
        assert stats.successful_acquires == 0
        assert stats.failed_acquires == 0
        assert stats.deadlocks_detected == 0
        assert stats.lock_contention_count == 0
        assert stats.average_wait_time == 0.0
        assert stats.max_wait_time == 0.0

    def test_lock_statistics_update(self):
        """测试更新锁统计信息"""
        stats = LockStatistics()

        stats.total_acquires = 10
        stats.successful_acquires = 8
        stats.failed_acquires = 2
        stats.average_wait_time = 0.5
        stats.max_wait_time = 2.0

        assert stats.total_acquires == 10
        assert stats.successful_acquires == 8
        assert stats.failed_acquires == 2
