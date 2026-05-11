"""
Tests for healing_notifier module
"""
from unittest.mock import Mock

import pytest

from models.message_models import TelegramMessage, TelegramNotificationType
from services.healing_models import HealRequest, HealResult
from services.healing_notifier import notify_healing_success, notify_healing_failure


class TestHealingNotifier:
    """Test healing_notifier functions"""

    @pytest.fixture
    def mock_runtime_context(self):
        """Create a mock runtime context"""
        context = Mock()
        context.tg_reporter = Mock()
        context.logger = Mock()
        context.correlation_id = "test-correlation-123"
        return context

    @pytest.fixture
    def heal_result(self):
        """Create a mock HealResult"""
        return HealResult(
            node_name="test-node",
            node_type="trojan",
            strategy="replace_instance",
            xboard_node_id=100,
            asset_type="aws",
            old_ipv6_address="2001:db8::1",
            new_ipv6_address="2001:db8::2",
            domain_name="test.example.com",
            cloudflare_record_id="cf-record-123",
            proxied_enabled=True,
            duration_ms=5000,
            correlation_id="test-correlation-123"
        )

    @pytest.fixture
    def heal_request(self):
        """Create a mock HealRequest"""
        return HealRequest(
            xboard_node_id=100,
            reason="health_check_failed",
            source="monitor"
        )

    def test_notify_healing_success(self, mock_runtime_context, heal_result):
        """Test notify_healing_success sends notification successfully"""
        notify_healing_success(mock_runtime_context, heal_result)

        mock_runtime_context.tg_reporter.send.assert_called_once()

        call_args = mock_runtime_context.tg_reporter.send.call_args[0]
        message = call_args[0]

        assert isinstance(message, TelegramMessage)
        assert message.type == TelegramNotificationType.HEALING_SUCCESS
        assert message.level == "INFO"
        assert "战损自愈完成" in message.title
        assert "test-node" in message.body
        assert "trojan" in message.body
        assert "replace_instance" in message.body
        assert "100" in message.body
        assert "aws" in message.body
        assert "2001:db8::1" in message.body
        assert "2001:db8::2" in message.body
        assert "test.example.com" in message.body
        assert "cf-record-123" in message.body
        assert "开启" in message.body
        assert "5000ms" in message.body
        assert "test-correlation-123" in message.body

    def test_notify_healing_success_with_none_values(self, mock_runtime_context):
        """Test notify_healing_success with None values"""
        result = HealResult(
            node_name="test-node",
            node_type="trojan",
            strategy="replace_instance",
            xboard_node_id=100,
            asset_type="aws",
            old_ipv6_address=None,
            new_ipv6_address=None,
            domain_name=None,
            cloudflare_record_id=None,
            proxied_enabled=False,
            duration_ms=3000,
            correlation_id="test-correlation-123"
        )

        notify_healing_success(mock_runtime_context, result)

        call_args = mock_runtime_context.tg_reporter.send.call_args[0]
        message = call_args[0]

        # Verify None values are replaced with '-'
        assert "旧IPv6=-" in message.body
        assert "新IPv6=-" in message.body
        assert "域名=-" in message.body
        assert "Cloudflare记录ID=-" in message.body
        assert "关闭" in message.body

    def test_notify_healing_success_telegram_exception(self, mock_runtime_context, heal_result):
        """Test notify_healing_success handles Telegram exceptions"""
        mock_runtime_context.tg_reporter.send.side_effect = Exception("Telegram API error")

        # Should not raise exception
        notify_healing_success(mock_runtime_context, heal_result)

        mock_runtime_context.logger.exception.assert_called_once()

    def test_notify_healing_failure(self, mock_runtime_context, heal_request):
        """Test notify_healing_failure sends notification successfully"""
        notify_healing_failure(
            mock_runtime_context,
            heal_request,
            node_name="test-node",
            node_type="trojan",
            strategy="replace_instance",
            error_message="Failed to create new instance"
        )

        mock_runtime_context.tg_reporter.send.assert_called_once()

        call_args = mock_runtime_context.tg_reporter.send.call_args[0]
        message = call_args[0]

        assert isinstance(message, TelegramMessage)
        assert message.type == TelegramNotificationType.HEALING_FAILURE
        assert message.level == "ERROR"
        assert "战损自愈失败" in message.title
        assert "test-node" in message.body
        assert "trojan" in message.body
        assert "replace_instance" in message.body
        assert "health_check_failed" in message.body
        assert "Failed to create new instance" in message.body
        assert "monitor" in message.body
        assert "100" in message.body
        assert "test-correlation-123" in message.body

    def test_notify_healing_failure_telegram_exception(self, mock_runtime_context, heal_request):
        """Test notify_healing_failure handles Telegram exceptions"""
        mock_runtime_context.tg_reporter.send.side_effect = Exception("Telegram API error")

        # Should not raise exception
        notify_healing_failure(
            mock_runtime_context,
            heal_request,
            node_name="test-node",
            node_type="trojan",
            strategy="replace_instance",
            error_message="Test error"
        )

        mock_runtime_context.logger.exception.assert_called_once()

    def test_notify_healing_success_different_strategies(self, mock_runtime_context):
        """Test notify_healing_success with different strategies"""
        strategies = ["replace_instance", "restart_service", "update_config"]

        for strategy in strategies:
            result = HealResult(
                node_name="test-node",
                node_type="trojan",
                strategy=strategy,
                xboard_node_id=100,
                asset_type="aws",
                old_ipv6_address=None,
                new_ipv6_address=None,
                domain_name=None,
                cloudflare_record_id=None,
                proxied_enabled=False,
                duration_ms=1000,
                correlation_id="corr-123"
            )

            notify_healing_success(mock_runtime_context, result)

            call_args = mock_runtime_context.tg_reporter.send.call_args[0]
            message = call_args[0]

            assert strategy in message.body

    def test_notify_healing_failure_different_reasons(self, mock_runtime_context):
        """Test notify_healing_failure with different failure reasons"""
        reasons = ["health_check_failed", "instance_terminated", "network_error"]

        for reason in reasons:
            request = HealRequest(
                xboard_node_id=100,
                reason=reason,
                source="monitor"
            )

            notify_healing_failure(
                mock_runtime_context,
                request,
                node_name="test-node",
                node_type="trojan",
                strategy="replace_instance",
                error_message="Test error"
            )

            call_args = mock_runtime_context.tg_reporter.send.call_args[0]
            message = call_args[0]

            assert reason in message.body

    def test_notify_healing_success_different_asset_types(self, mock_runtime_context):
        """Test notify_healing_success with different asset types"""
        asset_types = ["aws", "self_hosted", "gcp"]

        for asset_type in asset_types:
            result = HealResult(
                node_name="test-node",
                node_type="trojan",
                strategy="replace_instance",
                xboard_node_id=100,
                asset_type=asset_type,
                old_ipv6_address=None,
                new_ipv6_address=None,
                domain_name=None,
                cloudflare_record_id=None,
                proxied_enabled=False,
                duration_ms=1000,
                correlation_id="corr-123"
            )

            notify_healing_success(mock_runtime_context, result)

            call_args = mock_runtime_context.tg_reporter.send.call_args[0]
            message = call_args[0]

            assert asset_type in message.body

    def test_notify_healing_success_proxied_enabled_true(self, mock_runtime_context):
        """Test notify_healing_success with proxied enabled"""
        result = HealResult(
            node_name="test-node",
            node_type="trojan",
            strategy="replace_instance",
            xboard_node_id=100,
            asset_type="aws",
            old_ipv6_address=None,
            new_ipv6_address=None,
            domain_name=None,
            cloudflare_record_id=None,
            proxied_enabled=True,
            duration_ms=1000,
            correlation_id="corr-123"
        )

        notify_healing_success(mock_runtime_context, result)

        call_args = mock_runtime_context.tg_reporter.send.call_args[0]
        message = call_args[0]

        assert "开启" in message.body

    def test_notify_healing_success_proxied_enabled_false(self, mock_runtime_context):
        """Test notify_healing_success with proxied disabled"""
        result = HealResult(
            node_name="test-node",
            node_type="trojan",
            strategy="replace_instance",
            xboard_node_id=100,
            asset_type="aws",
            old_ipv6_address=None,
            new_ipv6_address=None,
            domain_name=None,
            cloudflare_record_id=None,
            proxied_enabled=False,
            duration_ms=1000,
            correlation_id="corr-123"
        )

        notify_healing_success(mock_runtime_context, result)

        call_args = mock_runtime_context.tg_reporter.send.call_args[0]
        message = call_args[0]

        assert "关闭" in message.body

    def test_notify_healing_failure_different_sources(self, mock_runtime_context):
        """Test notify_healing_failure with different sources"""
        sources = ["monitor", "manual", "scheduler"]

        for source in sources:
            request = HealRequest(
                xboard_node_id=100,
                reason="health_check_failed",
                source=source
            )

            notify_healing_failure(
                mock_runtime_context,
                request,
                node_name="test-node",
                node_type="trojan",
                strategy="replace_instance",
                error_message="Test error"
            )

            call_args = mock_runtime_context.tg_reporter.send.call_args[0]
            message = call_args[0]

            assert source in message.body

    def test_notify_healing_success_long_duration(self, mock_runtime_context):
        """Test notify_healing_success with long duration"""
        result = HealResult(
            node_name="test-node",
            node_type="trojan",
            strategy="replace_instance",
            xboard_node_id=100,
            asset_type="aws",
            old_ipv6_address=None,
            new_ipv6_address=None,
            domain_name=None,
            cloudflare_record_id=None,
            proxied_enabled=False,
            duration_ms=300000,  # 5 minutes
            correlation_id="corr-123"
        )

        notify_healing_success(mock_runtime_context, result)

        call_args = mock_runtime_context.tg_reporter.send.call_args[0]
        message = call_args[0]

        assert "300000ms" in message.body
