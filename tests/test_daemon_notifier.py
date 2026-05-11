"""
Tests for daemon_notifier module
"""
from unittest.mock import Mock

import pytest

from models.message_models import TelegramMessage, TelegramNotificationType
from services.daemon_notifier import DaemonWorkerAlertContext, notify_daemon_worker_cycle_failed


class TestDaemonNotifier:
    """Test daemon_notifier functions"""

    @pytest.fixture
    def mock_runtime_context(self):
        """Create a mock runtime context"""
        context = Mock()
        context.tg_reporter = Mock()
        context.logger = Mock()
        context.correlation_id = "test-correlation-123"
        return context

    @pytest.fixture
    def alert_context(self):
        """Create a DaemonWorkerAlertContext"""
        return DaemonWorkerAlertContext(
            worker_name="test_worker",
            error_message="Test error occurred",
            correlation_id="test-correlation-123"
        )

    def test_daemon_worker_alert_context_frozen(self, alert_context):
        """Test that DaemonWorkerAlertContext is frozen"""
        with pytest.raises(Exception):
            alert_context.worker_name = "new_name"

    def test_daemon_worker_alert_context_fields(self, alert_context):
        """Test DaemonWorkerAlertContext field values"""
        assert alert_context.worker_name == "test_worker"
        assert alert_context.error_message == "Test error occurred"
        assert alert_context.correlation_id == "test-correlation-123"

    def test_notify_daemon_worker_cycle_failed_success(self, mock_runtime_context, alert_context):
        """Test notify_daemon_worker_cycle_failed sends notification successfully"""
        notify_daemon_worker_cycle_failed(mock_runtime_context, alert_context)

        mock_runtime_context.tg_reporter.send.assert_called_once()

        # Verify the message sent
        call_args = mock_runtime_context.tg_reporter.send.call_args[0]
        message = call_args[0]

        assert isinstance(message, TelegramMessage)
        assert message.type == TelegramNotificationType.DAEMON_WORKER_FAILED
        assert message.level == "ERROR"
        assert "test_worker" in message.title
        assert "test_worker" in message.body
        assert "Test error occurred" in message.body
        assert "test-correlation-123" in message.body

    def test_notify_daemon_worker_cycle_failed_telegram_exception(self, mock_runtime_context, alert_context):
        """Test notify_daemon_worker_cycle_failed handles Telegram exceptions"""
        mock_runtime_context.tg_reporter.send.side_effect = Exception("Telegram API error")

        # Should not raise exception
        notify_daemon_worker_cycle_failed(mock_runtime_context, alert_context)

        # Verify exception was logged
        mock_runtime_context.logger.exception.assert_called_once()

    def test_notify_daemon_worker_cycle_failed_with_different_workers(self, mock_runtime_context):
        """Test notification with different worker names"""
        workers = ["scheduler_worker", "monitor_worker", "healer_worker"]

        for worker_name in workers:
            ctx = DaemonWorkerAlertContext(
                worker_name=worker_name,
                error_message="Error in worker",
                correlation_id="corr-123"
            )

            notify_daemon_worker_cycle_failed(mock_runtime_context, ctx)

            call_args = mock_runtime_context.tg_reporter.send.call_args[0]
            message = call_args[0]

            assert worker_name in message.title
            assert worker_name in message.body
