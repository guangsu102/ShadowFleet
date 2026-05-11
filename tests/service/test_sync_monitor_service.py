"""
同步监控服务单元测试
"""

import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from services.sync_monitor_service import (
    SyncAlert,
    SyncCoordinatorMonitor,
    SyncHealthMetrics,
    SyncMonitorService,
    SyncMonitorState,
    SyncOperationRecord,
)


@pytest.fixture
def mock_runtime():
    """创建模拟的运行时上下文"""
    runtime = MagicMock()
    runtime.logger = MagicMock()
    runtime.logger.getChild = MagicMock(return_value=MagicMock())
    runtime.correlation_id = "test-correlation-123"
    runtime.config = MagicMock()
    runtime.config.app = MagicMock()
    runtime.config.app.sync_lag_warning_threshold_seconds = 300
    return runtime


@pytest.fixture
def mock_xboard_node():
    """创建模拟的 Xboard 节点"""
    node = MagicMock()
    node.node_id = 1
    node.node_name = "test-node-1"
    node.show = True
    return node


@pytest.fixture
def mock_sqlite_node():
    """创建模拟的 SQLite 节点"""
    node = MagicMock()
    node.xboard_node_id = 1
    node.node_name = "test-node-1"
    node.status = "online"
    return node


class TestSyncMonitorService:
    """同步监控服务测试"""

    def test_record_sync_operation_start(self, mock_runtime):
        """测试记录同步操作开始"""
        with patch("services.sync_monitor_service.StateRepo"):
            with patch("services.sync_monitor_service.XboardRepo"):
                service = SyncMonitorService(mock_runtime)
                operation_id = service.record_sync_operation_start("register", 123)

        assert operation_id.startswith("sync-123-")
        assert len(service._state.operation_history) == 1
        assert service._state.operation_history[0].operation_type == "register"
        assert service._state.operation_history[0].xboard_node_id == 123

    def test_record_sync_operation_complete_success(self, mock_runtime):
        """测试记录同步操作成功完成"""
        with patch("services.sync_monitor_service.StateRepo"):
            with patch("services.sync_monitor_service.XboardRepo"):
                service = SyncMonitorService(mock_runtime)
                operation_id = service.record_sync_operation_start("register", 123)

                service.record_sync_operation_complete(
                    operation_id=operation_id,
                    success=True,
                    synced_to_sqlite=True,
                    synced_to_xboard=True
                )

        record = service._state.operation_history[0]
        assert record.success is True
        assert record.completed_at is not None
        assert record.duration_ms is not None
        assert service._state.last_successful_sync is not None

    def test_record_sync_operation_complete_failure(self, mock_runtime):
        """测试记录同步操作失败"""
        with patch("services.sync_monitor_service.StateRepo"):
            with patch("services.sync_monitor_service.XboardRepo"):
                service = SyncMonitorService(mock_runtime)
                operation_id = service.record_sync_operation_start("register", 123)

                service.record_sync_operation_complete(
                    operation_id=operation_id,
                    success=False,
                    error_message="Database error"
                )

        record = service._state.operation_history[0]
        assert record.success is False
        assert record.error_message == "Database error"
        assert service._state.failed_sync_attempts["register"] == 1

    def test_check_sync_health_healthy(self, mock_runtime, mock_xboard_node, mock_sqlite_node):
        """测试健康的同步状态"""
        mock_state_repo = MagicMock()
        mock_state_repo.list_active_nodes.return_value = [mock_sqlite_node]

        mock_xboard_repo = MagicMock()
        mock_xboard_repo.list_all_shadowfleet_nodes.return_value = [mock_xboard_node]

        with patch("services.sync_monitor_service.StateRepo", return_value=mock_state_repo):
            with patch("services.sync_monitor_service.XboardRepo", return_value=mock_xboard_repo):
                service = SyncMonitorService(mock_runtime)
                metrics = service.check_sync_health()

        assert metrics.total_nodes == 1
        assert metrics.synced_nodes == 1
        assert metrics.sqlite_only_nodes == 0
        assert metrics.xboard_only_nodes == 0
        assert metrics.health_score == 1.0

    def test_check_sync_health_with_discrepancies(self, mock_runtime, mock_xboard_node, mock_sqlite_node):
        """测试有差异的同步状态"""
        # 创建不同的节点
        xboard_node2 = MagicMock()
        xboard_node2.node_id = 2
        xboard_node2.node_name = "test-node-2"
        xboard_node2.show = True

        sqlite_node3 = MagicMock()
        sqlite_node3.xboard_node_id = 3
        sqlite_node3.node_name = "test-node-3"
        sqlite_node3.status = "online"

        mock_state_repo = MagicMock()
        mock_state_repo.list_active_nodes.return_value = [mock_sqlite_node, sqlite_node3]

        mock_xboard_repo = MagicMock()
        mock_xboard_repo.list_all_shadowfleet_nodes.return_value = [mock_xboard_node, xboard_node2]

        with patch("services.sync_monitor_service.StateRepo", return_value=mock_state_repo):
            with patch("services.sync_monitor_service.XboardRepo", return_value=mock_xboard_repo):
                service = SyncMonitorService(mock_runtime)
                metrics = service.check_sync_health()

        assert metrics.total_nodes == 3
        assert metrics.synced_nodes == 1
        assert metrics.sqlite_only_nodes == 1
        assert metrics.xboard_only_nodes == 1
        assert metrics.health_score < 1.0

    def test_check_sync_health_exception(self, mock_runtime):
        """测试检查同步健康时发生异常"""
        mock_state_repo = MagicMock()
        mock_state_repo.list_active_nodes.side_effect = Exception("Database error")

        with patch("services.sync_monitor_service.StateRepo", return_value=mock_state_repo):
            with patch("services.sync_monitor_service.XboardRepo"):
                service = SyncMonitorService(mock_runtime)
                metrics = service.check_sync_health()

        assert metrics.health_score == 0.0
        assert metrics.total_nodes == 0

    def test_calculate_sync_lag(self, mock_runtime):
        """测试计算同步延迟"""
        with patch("services.sync_monitor_service.StateRepo"):
            with patch("services.sync_monitor_service.XboardRepo"):
                service = SyncMonitorService(mock_runtime)

                # 没有同步记录
                lag = service._calculate_sync_lag()
                assert lag is None

                # 设置最后同步时间
                service._state.last_successful_sync = datetime.utcnow() - timedelta(seconds=100)
                lag = service._calculate_sync_lag()
                assert lag is not None
                assert lag >= 100

    def test_calculate_sync_lag_with_alert(self, mock_runtime):
        """测试同步延迟超过阈值触发告警"""
        with patch("services.sync_monitor_service.StateRepo"):
            with patch("services.sync_monitor_service.XboardRepo"):
                service = SyncMonitorService(mock_runtime)

                # 设置超过阈值的延迟
                service._state.last_successful_sync = datetime.utcnow() - timedelta(seconds=400)
                lag = service._calculate_sync_lag()

                assert lag >= 400
                # 应该创建告警
                assert len(service._state.alerts) > 0
                assert service._state.alerts[0].alert_type == "sync_lag"

    def test_check_and_create_alert(self, mock_runtime):
        """测试创建告警"""
        with patch("services.sync_monitor_service.StateRepo"):
            with patch("services.sync_monitor_service.XboardRepo"):
                service = SyncMonitorService(mock_runtime)

                # Mock the _send_alert_notification method
                service._send_alert_notification = MagicMock()

                service._check_and_create_alert(
                    alert_type="sync_failure",
                    severity="error",
                    message="Test alert",
                    xboard_node_id=123
                )

        assert len(service._state.alerts) == 1
        alert = service._state.alerts[0]
        assert alert.alert_type == "sync_failure"
        assert alert.severity == "error"
        assert alert.message == "Test alert"
        assert alert.xboard_node_id == 123

    def test_resolve_alert(self, mock_runtime):
        """测试解决告警"""
        with patch("services.sync_monitor_service.StateRepo"):
            with patch("services.sync_monitor_service.XboardRepo"):
                service = SyncMonitorService(mock_runtime)
                service._send_alert_notification = MagicMock()

                service._check_and_create_alert(
                    alert_type="sync_failure",
                    severity="error",
                    message="Test alert"
                )

                alert_id = service._state.alerts[0].alert_id
                result = service.resolve_alert(alert_id)

        assert result is True
        assert service._state.alerts[0].resolved_at is not None

    def test_get_unresolved_alerts(self, mock_runtime):
        """测试获取未解决的告警"""
        with patch("services.sync_monitor_service.StateRepo"):
            with patch("services.sync_monitor_service.XboardRepo"):
                service = SyncMonitorService(mock_runtime)
                service._send_alert_notification = MagicMock()

                service._check_and_create_alert(
                    alert_type="sync_failure",
                    severity="error",
                    message="Alert 1"
                )

                unresolved = service.get_unresolved_alerts()

        assert len(unresolved) == 1

    def test_get_sync_health_report(self, mock_runtime, mock_xboard_node, mock_sqlite_node):
        """测试获取同步健康报告"""
        mock_state_repo = MagicMock()
        mock_state_repo.list_active_nodes.return_value = [mock_sqlite_node]

        mock_xboard_repo = MagicMock()
        mock_xboard_repo.list_all_shadowfleet_nodes.return_value = [mock_xboard_node]

        with patch("services.sync_monitor_service.StateRepo", return_value=mock_state_repo):
            with patch("services.sync_monitor_service.XboardRepo", return_value=mock_xboard_repo):
                service = SyncMonitorService(mock_runtime)
                report = service.get_sync_health_report()

        assert "health_metrics" in report
        assert "alerts" in report
        assert "recent_operations" in report


class TestSyncCoordinatorMonitor:
    """同步协调器监控装饰器测试"""

    def test_wrap_sync_operation_success(self, mock_runtime):
        """测试包装同步操作成功"""
        with patch("services.sync_monitor_service.StateRepo"):
            with patch("services.sync_monitor_service.XboardRepo"):
                monitor = SyncCoordinatorMonitor(mock_runtime)

                def test_operation():
                    return "success"

                result = monitor.wrap_sync_operation("register", 123, test_operation)

        assert result == "success"
        assert len(monitor._monitor._state.operation_history) == 1
        assert monitor._monitor._state.operation_history[0].success is True

    def test_wrap_sync_operation_failure(self, mock_runtime):
        """测试包装同步操作失败"""
        with patch("services.sync_monitor_service.StateRepo"):
            with patch("services.sync_monitor_service.XboardRepo"):
                monitor = SyncCoordinatorMonitor(mock_runtime)

                def test_operation():
                    raise Exception("Operation failed")

                with pytest.raises(Exception):
                    monitor.wrap_sync_operation("register", 123, test_operation)

        assert len(monitor._monitor._state.operation_history) == 1
        assert monitor._monitor._state.operation_history[0].success is False
