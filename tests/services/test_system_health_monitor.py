"""
Tests for SystemHealthMonitor
"""
from unittest.mock import MagicMock, patch

import pytest

from services.system_health_monitor import SystemHealthMonitor, SystemHealthMonitorError, SystemHealthReport


@pytest.fixture
def mock_runtime_context():
    """Create a mock runtime context"""
    context = MagicMock()
    context.logger = MagicMock()
    context.logger.getChild.return_value = MagicMock()
    context.config = MagicMock()
    context.config.telegram = MagicMock()
    context.config.telegram.enabled = False
    return context


@pytest.fixture
def mock_orphan_report():
    """Create a mock orphan resource report"""
    report = MagicMock()
    report.total_count = 0
    report.ec2_instances = []
    report.dns_records = []
    report.asset_allocations = []
    report.xboard_nodes = []
    return report


@pytest.fixture
def mock_sync_report():
    """Create a mock sync health report"""
    report = MagicMock()
    report.health_status = "healthy"
    report.inconsistency_count = 0
    report.total_xboard_nodes = 10
    report.total_sqlite_nodes = 10
    return report


@pytest.fixture
def service(mock_runtime_context):
    """Create SystemHealthMonitor instance"""
    with patch('services.system_health_monitor.OrphanResourceDetector'), \
         patch('services.system_health_monitor.OrphanResourceCleaner'), \
         patch('services.system_health_monitor.DatabaseSyncMonitor'):
        return SystemHealthMonitor(mock_runtime_context)


class TestSystemHealthMonitor:
    """Tests for SystemHealthMonitor"""

    def test_init(self, mock_runtime_context):
        """Test service initialization"""
        with patch('services.system_health_monitor.OrphanResourceDetector') as mock_detector, \
             patch('services.system_health_monitor.OrphanResourceCleaner') as mock_cleaner, \
             patch('services.system_health_monitor.DatabaseSyncMonitor') as mock_monitor:

            service = SystemHealthMonitor(mock_runtime_context)

            assert service._runtime == mock_runtime_context
            mock_runtime_context.logger.getChild.assert_called_once_with("services.system_health_monitor")
            mock_detector.assert_called_once_with(mock_runtime_context)
            mock_cleaner.assert_called_once_with(mock_runtime_context)
            mock_monitor.assert_called_once_with(mock_runtime_context)

    def test_run_health_check_healthy(self, service, mock_orphan_report, mock_sync_report):
        """Test health check with healthy system"""
        service._orphan_detector.scan_all_orphan_resources.return_value = mock_orphan_report
        service._sync_monitor.check_sync_health.return_value = mock_sync_report

        report = service.run_health_check()

        assert isinstance(report, SystemHealthReport)
        assert report.overall_status == "healthy"
        assert len(report.alerts) == 0
        assert report.orphan_resource_report == mock_orphan_report
        assert report.sync_health_report == mock_sync_report

    def test_run_health_check_with_orphans(self, service, mock_orphan_report, mock_sync_report):
        """Test health check with orphan resources"""
        mock_orphan_report.total_count = 3
        mock_orphan_report.ec2_instances = ["i-1", "i-2"]
        mock_orphan_report.dns_records = ["dns-1"]

        service._orphan_detector.scan_all_orphan_resources.return_value = mock_orphan_report
        service._sync_monitor.check_sync_health.return_value = mock_sync_report

        report = service.run_health_check()

        assert report.overall_status == "healthy"  # < 5 orphans
        assert len(report.alerts) == 1
        assert "3 个孤儿资源" in report.alerts[0]

    def test_run_health_check_warning_orphans(self, service, mock_orphan_report, mock_sync_report):
        """Test health check with warning level orphans"""
        mock_orphan_report.total_count = 8
        mock_orphan_report.ec2_instances = ["i-1"] * 8

        service._orphan_detector.scan_all_orphan_resources.return_value = mock_orphan_report
        service._sync_monitor.check_sync_health.return_value = mock_sync_report

        report = service.run_health_check()

        assert report.overall_status == "warning"  # > 5 orphans
        assert len(report.alerts) == 1

    def test_run_health_check_critical_orphans(self, service, mock_orphan_report, mock_sync_report):
        """Test health check with critical level orphans"""
        mock_orphan_report.total_count = 25
        mock_orphan_report.ec2_instances = ["i-1"] * 25

        service._orphan_detector.scan_all_orphan_resources.return_value = mock_orphan_report
        service._sync_monitor.check_sync_health.return_value = mock_sync_report

        report = service.run_health_check()

        assert report.overall_status == "critical"  # > 20 orphans

    def test_run_health_check_sync_warning(self, service, mock_orphan_report, mock_sync_report):
        """Test health check with sync warning"""
        mock_sync_report.health_status = "warning"
        mock_sync_report.inconsistency_count = 3

        service._orphan_detector.scan_all_orphan_resources.return_value = mock_orphan_report
        service._sync_monitor.check_sync_health.return_value = mock_sync_report

        report = service.run_health_check()

        assert report.overall_status == "warning"
        assert len(report.alerts) == 1
        assert "数据库同步状态" in report.alerts[0]

    def test_run_health_check_sync_critical(self, service, mock_orphan_report, mock_sync_report):
        """Test health check with sync critical"""
        mock_sync_report.health_status = "critical"
        mock_sync_report.inconsistency_count = 10

        service._orphan_detector.scan_all_orphan_resources.return_value = mock_orphan_report
        service._sync_monitor.check_sync_health.return_value = mock_sync_report

        report = service.run_health_check()

        assert report.overall_status == "critical"

    def test_run_health_check_auto_cleanup_orphans(self, service, mock_orphan_report, mock_sync_report):
        """Test health check with auto cleanup enabled"""
        mock_orphan_report.total_count = 5
        mock_cleanup_report = MagicMock()
        mock_cleanup_report.total_succeeded = 4
        mock_cleanup_report.total_failed = 1

        service._orphan_detector.scan_all_orphan_resources.return_value = mock_orphan_report
        service._sync_monitor.check_sync_health.return_value = mock_sync_report
        service._orphan_cleaner.cleanup_orphan_resources.return_value = mock_cleanup_report

        report = service.run_health_check(auto_cleanup_orphans=True)

        service._orphan_cleaner.cleanup_orphan_resources.assert_called_once_with(
            mock_orphan_report,
            dry_run=False
        )
        assert any("自动清理完成" in alert for alert in report.alerts)

    def test_run_health_check_auto_repair_sync(self, service, mock_orphan_report, mock_sync_report):
        """Test health check with auto repair enabled"""
        mock_sync_report.inconsistency_count = 3
        mock_repair_stats = {
            "repaired": 2,
            "failed": 1,
            "skipped": 0
        }

        service._orphan_detector.scan_all_orphan_resources.return_value = mock_orphan_report
        service._sync_monitor.check_sync_health.return_value = mock_sync_report
        service._sync_monitor.auto_repair_inconsistencies.return_value = mock_repair_stats

        report = service.run_health_check(auto_repair_sync=True)

        service._sync_monitor.auto_repair_inconsistencies.assert_called_once_with(
            mock_sync_report,
            dry_run=False
        )
        assert any("自动修复完成" in alert for alert in report.alerts)

    def test_run_health_check_no_auto_cleanup_when_no_orphans(self, service, mock_orphan_report, mock_sync_report):
        """Test auto cleanup not triggered when no orphans"""
        mock_orphan_report.total_count = 0

        service._orphan_detector.scan_all_orphan_resources.return_value = mock_orphan_report
        service._sync_monitor.check_sync_health.return_value = mock_sync_report

        report = service.run_health_check(auto_cleanup_orphans=True)

        service._orphan_cleaner.cleanup_orphan_resources.assert_not_called()

    def test_run_health_check_no_auto_repair_when_no_inconsistencies(self, service, mock_orphan_report, mock_sync_report):
        """Test auto repair not triggered when no inconsistencies"""
        mock_sync_report.inconsistency_count = 0

        service._orphan_detector.scan_all_orphan_resources.return_value = mock_orphan_report
        service._sync_monitor.check_sync_health.return_value = mock_sync_report

        report = service.run_health_check(auto_repair_sync=True)

        service._sync_monitor.auto_repair_inconsistencies.assert_not_called()

    def test_run_health_check_failure(self, service):
        """Test health check handles failures"""
        service._orphan_detector.scan_all_orphan_resources.side_effect = RuntimeError("Scan failed")

        with pytest.raises(SystemHealthMonitorError, match="Failed to run system health check"):
            service.run_health_check()

    def test_run_health_check_multiple_alerts(self, service, mock_orphan_report, mock_sync_report):
        """Test health check with multiple alerts"""
        mock_orphan_report.total_count = 10
        mock_orphan_report.ec2_instances = ["i-1"] * 10
        mock_sync_report.health_status = "warning"
        mock_sync_report.inconsistency_count = 5

        service._orphan_detector.scan_all_orphan_resources.return_value = mock_orphan_report
        service._sync_monitor.check_sync_health.return_value = mock_sync_report

        report = service.run_health_check()

        assert len(report.alerts) == 2
        assert report.overall_status == "warning"

    @patch('services.system_health_monitor.TelegramNotifier')
    def test_send_alert_telegram_enabled(self, mock_telegram_class, service, mock_orphan_report, mock_sync_report):
        """Test sending alert when Telegram is enabled"""
        service._runtime.config.telegram.enabled = True
        mock_orphan_report.total_count = 10
        mock_orphan_report.ec2_instances = ["i-1"] * 10

        mock_notifier = MagicMock()
        mock_telegram_class.return_value = mock_notifier

        service._orphan_detector.scan_all_orphan_resources.return_value = mock_orphan_report
        service._sync_monitor.check_sync_health.return_value = mock_sync_report

        report = service.run_health_check()

        mock_telegram_class.assert_called_once_with(service._runtime)
        mock_notifier.send_message.assert_called_once()
        message = mock_notifier.send_message.call_args[0][0]
        assert "系统健康检查报告" in message
        assert "WARNING" in message

    def test_send_alert_telegram_disabled(self, service, mock_orphan_report, mock_sync_report):
        """Test no alert sent when Telegram is disabled"""
        service._runtime.config.telegram.enabled = False
        mock_orphan_report.total_count = 10
        mock_orphan_report.ec2_instances = ["i-1"] * 10

        service._orphan_detector.scan_all_orphan_resources.return_value = mock_orphan_report
        service._sync_monitor.check_sync_health.return_value = mock_sync_report

        with patch('services.system_health_monitor.TelegramNotifier') as mock_telegram:
            report = service.run_health_check()
            mock_telegram.assert_not_called()

    def test_send_alert_no_alert_when_healthy(self, service, mock_orphan_report, mock_sync_report):
        """Test no alert sent when system is healthy"""
        service._runtime.config.telegram.enabled = True

        service._orphan_detector.scan_all_orphan_resources.return_value = mock_orphan_report
        service._sync_monitor.check_sync_health.return_value = mock_sync_report

        with patch('services.system_health_monitor.TelegramNotifier') as mock_telegram:
            report = service.run_health_check()
            mock_telegram.assert_not_called()

    @patch('services.system_health_monitor.TelegramNotifier')
    def test_send_alert_handles_telegram_failure(self, mock_telegram_class, service, mock_orphan_report, mock_sync_report):
        """Test health check continues even if Telegram alert fails"""
        service._runtime.config.telegram.enabled = True
        mock_orphan_report.total_count = 10
        mock_orphan_report.ec2_instances = ["i-1"] * 10

        mock_notifier = MagicMock()
        mock_notifier.send_message.side_effect = RuntimeError("Telegram API error")
        mock_telegram_class.return_value = mock_notifier

        service._orphan_detector.scan_all_orphan_resources.return_value = mock_orphan_report
        service._sync_monitor.check_sync_health.return_value = mock_sync_report

        # Should not raise exception
        report = service.run_health_check()
        assert report.overall_status == "warning"

    @patch('services.system_health_monitor.TelegramNotifier')
    def test_send_alert_critical_status(self, mock_telegram_class, service, mock_orphan_report, mock_sync_report):
        """Test alert message for critical status"""
        service._runtime.config.telegram.enabled = True
        mock_sync_report.health_status = "critical"
        mock_sync_report.inconsistency_count = 15

        mock_notifier = MagicMock()
        mock_telegram_class.return_value = mock_notifier

        service._orphan_detector.scan_all_orphan_resources.return_value = mock_orphan_report
        service._sync_monitor.check_sync_health.return_value = mock_sync_report

        report = service.run_health_check()

        message = mock_notifier.send_message.call_args[0][0]
        assert "🚨" in message
        assert "CRITICAL" in message

    def test_health_check_report_structure(self, service, mock_orphan_report, mock_sync_report):
        """Test health check report has correct structure"""
        service._orphan_detector.scan_all_orphan_resources.return_value = mock_orphan_report
        service._sync_monitor.check_sync_health.return_value = mock_sync_report

        report = service.run_health_check()

        assert hasattr(report, 'check_time')
        assert hasattr(report, 'orphan_resource_report')
        assert hasattr(report, 'sync_health_report')
        assert hasattr(report, 'overall_status')
        assert hasattr(report, 'alerts')
        assert isinstance(report.alerts, list)
