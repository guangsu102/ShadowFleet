"""
数据库同步监控服务单元测试
"""

from unittest.mock import MagicMock, patch

import pytest

from services.database_sync_monitor import (
    DatabaseSyncMonitor,
    DatabaseSyncMonitorError,
    NodeInconsistency,
    SyncHealthReport,
)


@pytest.fixture
def mock_runtime():
    """创建模拟的运行时上下文"""
    runtime = MagicMock()
    runtime.logger = MagicMock()
    runtime.logger.getChild = MagicMock(return_value=MagicMock())
    return runtime


@pytest.fixture
def mock_xboard_node():
    """创建模拟的 Xboard 节点"""
    node = MagicMock()
    node.node_id = 1
    node.node_name = "test-node-1"
    node.node_type = "shadowsocks"
    node.host = "example.com"
    node.show = True
    return node


@pytest.fixture
def mock_sqlite_node():
    """创建模拟的 SQLite 节点"""
    node = MagicMock()
    node.xboard_node_id = 1
    node.node_name = "test-node-1"
    node.status = "online"
    node.last_known_host = "example.com"
    node.domain_name = "example.com"
    return node


class TestDatabaseSyncMonitor:
    """数据库同步监控器测试"""

    def test_check_sync_health_healthy(self, mock_runtime, mock_xboard_node, mock_sqlite_node):
        """测试健康的同步状态"""
        mock_state_repo = MagicMock()
        mock_state_repo.list_active_nodes.return_value = [mock_sqlite_node]

        mock_xboard_repo = MagicMock()
        mock_xboard_repo.list_all_shadowfleet_nodes.return_value = [mock_xboard_node]

        with patch("services.database_sync_monitor.StateRepo", return_value=mock_state_repo):
            with patch("services.database_sync_monitor.XboardRepo", return_value=mock_xboard_repo):
                monitor = DatabaseSyncMonitor(mock_runtime)
                report = monitor.check_sync_health()

        assert report.health_status == "healthy"
        assert report.inconsistency_count == 0
        assert report.total_xboard_nodes == 1
        assert report.total_sqlite_nodes == 1

    def test_check_sync_health_missing_in_sqlite(self, mock_runtime, mock_xboard_node):
        """测试 SQLite 中缺失节点"""
        mock_state_repo = MagicMock()
        mock_state_repo.list_active_nodes.return_value = []

        mock_xboard_repo = MagicMock()
        mock_xboard_repo.list_all_shadowfleet_nodes.return_value = [mock_xboard_node]

        with patch("services.database_sync_monitor.StateRepo", return_value=mock_state_repo):
            with patch("services.database_sync_monitor.XboardRepo", return_value=mock_xboard_repo):
                monitor = DatabaseSyncMonitor(mock_runtime)
                report = monitor.check_sync_health()

        assert report.health_status == "warning"
        assert report.inconsistency_count == 1
        assert report.inconsistencies[0].inconsistency_type == "missing_in_sqlite"
        assert report.inconsistencies[0].xboard_node_id == 1

    def test_check_sync_health_missing_in_xboard(self, mock_runtime, mock_sqlite_node):
        """测试 Xboard 中缺失节点"""
        mock_state_repo = MagicMock()
        mock_state_repo.list_active_nodes.return_value = [mock_sqlite_node]

        mock_xboard_repo = MagicMock()
        mock_xboard_repo.list_all_shadowfleet_nodes.return_value = []

        with patch("services.database_sync_monitor.StateRepo", return_value=mock_state_repo):
            with patch("services.database_sync_monitor.XboardRepo", return_value=mock_xboard_repo):
                monitor = DatabaseSyncMonitor(mock_runtime)
                report = monitor.check_sync_health()

        assert report.health_status == "warning"
        assert report.inconsistency_count == 1
        assert report.inconsistencies[0].inconsistency_type == "missing_in_xboard"
        assert report.inconsistencies[0].xboard_node_id == 1

    def test_check_sync_health_status_mismatch(self, mock_runtime, mock_xboard_node, mock_sqlite_node):
        """测试状态不匹配"""
        # Xboard show=False, SQLite status=online
        mock_xboard_node.show = False
        mock_sqlite_node.status = "online"

        mock_state_repo = MagicMock()
        mock_state_repo.list_active_nodes.return_value = [mock_sqlite_node]

        mock_xboard_repo = MagicMock()
        mock_xboard_repo.list_all_shadowfleet_nodes.return_value = [mock_xboard_node]

        with patch("services.database_sync_monitor.StateRepo", return_value=mock_state_repo):
            with patch("services.database_sync_monitor.XboardRepo", return_value=mock_xboard_repo):
                monitor = DatabaseSyncMonitor(mock_runtime)
                report = monitor.check_sync_health()

        assert report.inconsistency_count == 1
        assert report.inconsistencies[0].inconsistency_type == "status_mismatch"

    def test_check_sync_health_host_mismatch(self, mock_runtime, mock_xboard_node, mock_sqlite_node):
        """测试 host 不匹配"""
        mock_xboard_node.host = "old-host.com"
        mock_sqlite_node.last_known_host = "new-host.com"

        mock_state_repo = MagicMock()
        mock_state_repo.list_active_nodes.return_value = [mock_sqlite_node]

        mock_xboard_repo = MagicMock()
        mock_xboard_repo.list_all_shadowfleet_nodes.return_value = [mock_xboard_node]

        with patch("services.database_sync_monitor.StateRepo", return_value=mock_state_repo):
            with patch("services.database_sync_monitor.XboardRepo", return_value=mock_xboard_repo):
                monitor = DatabaseSyncMonitor(mock_runtime)
                report = monitor.check_sync_health()

        assert report.inconsistency_count == 1
        assert report.inconsistencies[0].inconsistency_type == "host_mismatch"

    def test_check_sync_health_critical(self, mock_runtime):
        """测试严重的同步问题"""
        # 创建多个不一致的节点
        xboard_nodes = []
        sqlite_nodes = []

        for i in range(10):
            node = MagicMock()
            node.node_id = i
            node.node_name = f"node-{i}"
            node.node_type = "shadowsocks"
            node.host = "example.com"
            node.show = True
            xboard_nodes.append(node)

        mock_state_repo = MagicMock()
        mock_state_repo.list_active_nodes.return_value = sqlite_nodes

        mock_xboard_repo = MagicMock()
        mock_xboard_repo.list_all_shadowfleet_nodes.return_value = xboard_nodes

        with patch("services.database_sync_monitor.StateRepo", return_value=mock_state_repo):
            with patch("services.database_sync_monitor.XboardRepo", return_value=mock_xboard_repo):
                monitor = DatabaseSyncMonitor(mock_runtime)
                report = monitor.check_sync_health()

        assert report.health_status == "critical"
        assert report.inconsistency_count > 5

    def test_check_sync_health_exception(self, mock_runtime):
        """测试检查时发生异常"""
        mock_state_repo = MagicMock()
        mock_state_repo.list_active_nodes.side_effect = Exception("Database error")

        with patch("services.database_sync_monitor.StateRepo", return_value=mock_state_repo):
            with patch("services.database_sync_monitor.XboardRepo"):
                monitor = DatabaseSyncMonitor(mock_runtime)

                with pytest.raises(DatabaseSyncMonitorError):
                    monitor.check_sync_health()

    def test_auto_repair_missing_in_xboard(self, mock_runtime):
        """测试自动修复 Xboard 中缺失的节点"""
        inconsistency = NodeInconsistency(
            xboard_node_id=1,
            inconsistency_type="missing_in_xboard",
            xboard_state=None,
            sqlite_state={"node_name": "test-node", "status": "online"},
            details="Node missing in Xboard"
        )

        report = SyncHealthReport(
            check_time="2026-05-10T12:00:00",
            total_xboard_nodes=0,
            total_sqlite_nodes=1,
            inconsistencies=[inconsistency],
            inconsistency_count=1,
            health_status="warning"
        )

        mock_state_repo = MagicMock()
        mock_xboard_repo = MagicMock()

        with patch("services.database_sync_monitor.StateRepo", return_value=mock_state_repo):
            with patch("services.database_sync_monitor.XboardRepo", return_value=mock_xboard_repo):
                monitor = DatabaseSyncMonitor(mock_runtime)
                stats = monitor.auto_repair_inconsistencies(
                    report,
                    repair_missing_in_xboard=True,
                    dry_run=False
                )

        assert stats["repaired"] == 1
        mock_state_repo.mark_node_deleted.assert_called_once()

    def test_auto_repair_status_mismatch(self, mock_runtime):
        """测试自动修复状态不匹配"""
        inconsistency = NodeInconsistency(
            xboard_node_id=1,
            inconsistency_type="status_mismatch",
            xboard_state={"show": False},
            sqlite_state={"status": "online"},
            details="Status mismatch"
        )

        report = SyncHealthReport(
            check_time="2026-05-10T12:00:00",
            total_xboard_nodes=1,
            total_sqlite_nodes=1,
            inconsistencies=[inconsistency],
            inconsistency_count=1,
            health_status="warning"
        )

        mock_state_repo = MagicMock()
        mock_xboard_repo = MagicMock()

        with patch("services.database_sync_monitor.StateRepo", return_value=mock_state_repo):
            with patch("services.database_sync_monitor.XboardRepo", return_value=mock_xboard_repo):
                monitor = DatabaseSyncMonitor(mock_runtime)
                stats = monitor.auto_repair_inconsistencies(
                    report,
                    repair_status_mismatch=True,
                    dry_run=False
                )

        assert stats["repaired"] == 1
        mock_xboard_repo.mark_node_online.assert_called_once_with(1)

    def test_auto_repair_host_mismatch(self, mock_runtime):
        """测试自动修复 host 不匹配"""
        inconsistency = NodeInconsistency(
            xboard_node_id=1,
            inconsistency_type="host_mismatch",
            xboard_state={"host": "old-host.com"},
            sqlite_state={"host": "new-host.com"},
            details="Host mismatch"
        )

        report = SyncHealthReport(
            check_time="2026-05-10T12:00:00",
            total_xboard_nodes=1,
            total_sqlite_nodes=1,
            inconsistencies=[inconsistency],
            inconsistency_count=1,
            health_status="warning"
        )

        mock_state_repo = MagicMock()
        mock_xboard_repo = MagicMock()

        with patch("services.database_sync_monitor.StateRepo", return_value=mock_state_repo):
            with patch("services.database_sync_monitor.XboardRepo", return_value=mock_xboard_repo):
                monitor = DatabaseSyncMonitor(mock_runtime)
                stats = monitor.auto_repair_inconsistencies(
                    report,
                    repair_host_mismatch=True,
                    dry_run=False
                )

        assert stats["repaired"] == 1
        mock_xboard_repo.update_node_host.assert_called_once_with(1, "new-host.com")

    def test_auto_repair_dry_run(self, mock_runtime):
        """测试演练模式"""
        inconsistency = NodeInconsistency(
            xboard_node_id=1,
            inconsistency_type="status_mismatch",
            xboard_state={"show": False},
            sqlite_state={"status": "online"},
            details="Status mismatch"
        )

        report = SyncHealthReport(
            check_time="2026-05-10T12:00:00",
            total_xboard_nodes=1,
            total_sqlite_nodes=1,
            inconsistencies=[inconsistency],
            inconsistency_count=1,
            health_status="warning"
        )

        mock_state_repo = MagicMock()
        mock_xboard_repo = MagicMock()

        with patch("services.database_sync_monitor.StateRepo", return_value=mock_state_repo):
            with patch("services.database_sync_monitor.XboardRepo", return_value=mock_xboard_repo):
                monitor = DatabaseSyncMonitor(mock_runtime)
                stats = monitor.auto_repair_inconsistencies(
                    report,
                    repair_status_mismatch=True,
                    dry_run=True
                )

        assert stats["repaired"] == 1
        # 演练模式不应该调用实际的修复方法
        mock_xboard_repo.mark_node_online.assert_not_called()

    def test_auto_repair_skipped(self, mock_runtime):
        """测试跳过修复"""
        inconsistency = NodeInconsistency(
            xboard_node_id=1,
            inconsistency_type="status_mismatch",
            xboard_state={"show": False},
            sqlite_state={"status": "online"},
            details="Status mismatch"
        )

        report = SyncHealthReport(
            check_time="2026-05-10T12:00:00",
            total_xboard_nodes=1,
            total_sqlite_nodes=1,
            inconsistencies=[inconsistency],
            inconsistency_count=1,
            health_status="warning"
        )

        mock_state_repo = MagicMock()
        mock_xboard_repo = MagicMock()

        with patch("services.database_sync_monitor.StateRepo", return_value=mock_state_repo):
            with patch("services.database_sync_monitor.XboardRepo", return_value=mock_xboard_repo):
                monitor = DatabaseSyncMonitor(mock_runtime)
                stats = monitor.auto_repair_inconsistencies(
                    report,
                    repair_status_mismatch=False,
                    dry_run=False
                )

        assert stats["skipped"] == 1
        assert stats["repaired"] == 0

    def test_auto_repair_failed(self, mock_runtime):
        """测试修复失败"""
        inconsistency = NodeInconsistency(
            xboard_node_id=1,
            inconsistency_type="status_mismatch",
            xboard_state={"show": False},
            sqlite_state={"status": "online"},
            details="Status mismatch"
        )

        report = SyncHealthReport(
            check_time="2026-05-10T12:00:00",
            total_xboard_nodes=1,
            total_sqlite_nodes=1,
            inconsistencies=[inconsistency],
            inconsistency_count=1,
            health_status="warning"
        )

        mock_state_repo = MagicMock()
        mock_xboard_repo = MagicMock()
        mock_xboard_repo.mark_node_online.side_effect = Exception("Update failed")

        with patch("services.database_sync_monitor.StateRepo", return_value=mock_state_repo):
            with patch("services.database_sync_monitor.XboardRepo", return_value=mock_xboard_repo):
                monitor = DatabaseSyncMonitor(mock_runtime)
                stats = monitor.auto_repair_inconsistencies(
                    report,
                    repair_status_mismatch=True,
                    dry_run=False
                )

        assert stats["failed"] == 1
        assert stats["repaired"] == 0

    def test_auto_repair_missing_in_sqlite_skipped(self, mock_runtime):
        """测试 SQLite 中缺失节点的修复（应该被跳过）"""
        inconsistency = NodeInconsistency(
            xboard_node_id=1,
            inconsistency_type="missing_in_sqlite",
            xboard_state={"node_name": "test-node"},
            sqlite_state=None,
            details="Node missing in SQLite"
        )

        report = SyncHealthReport(
            check_time="2026-05-10T12:00:00",
            total_xboard_nodes=1,
            total_sqlite_nodes=0,
            inconsistencies=[inconsistency],
            inconsistency_count=1,
            health_status="warning"
        )

        mock_state_repo = MagicMock()
        mock_xboard_repo = MagicMock()

        with patch("services.database_sync_monitor.StateRepo", return_value=mock_state_repo):
            with patch("services.database_sync_monitor.XboardRepo", return_value=mock_xboard_repo):
                monitor = DatabaseSyncMonitor(mock_runtime)
                stats = monitor.auto_repair_inconsistencies(
                    report,
                    repair_missing_in_sqlite=True,
                    dry_run=False
                )

        # missing_in_sqlite 需要手动干预，应该被跳过
        assert stats["skipped"] == 1


class TestNodeInconsistency:
    """节点不一致记录测试"""

    def test_node_inconsistency_creation(self):
        """测试创建节点不一致记录"""
        inconsistency = NodeInconsistency(
            xboard_node_id=1,
            inconsistency_type="status_mismatch",
            xboard_state={"show": True},
            sqlite_state={"status": "offline"},
            details="Status mismatch"
        )

        assert inconsistency.xboard_node_id == 1
        assert inconsistency.inconsistency_type == "status_mismatch"
        assert inconsistency.xboard_state == {"show": True}
        assert inconsistency.sqlite_state == {"status": "offline"}


class TestSyncHealthReport:
    """同步健康报告测试"""

    def test_sync_health_report_creation(self):
        """测试创建同步健康报告"""
        report = SyncHealthReport(
            check_time="2026-05-10T12:00:00",
            total_xboard_nodes=10,
            total_sqlite_nodes=9,
            inconsistencies=[],
            inconsistency_count=0,
            health_status="healthy"
        )

        assert report.check_time == "2026-05-10T12:00:00"
        assert report.total_xboard_nodes == 10
        assert report.total_sqlite_nodes == 9
        assert report.inconsistency_count == 0
        assert report.health_status == "healthy"
