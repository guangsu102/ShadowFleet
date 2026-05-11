"""
Tests for provisioning_notifier module
"""
from unittest.mock import Mock

import pytest

from models.message_models import TelegramMessage, TelegramNotificationType
from services.asset_selector_service import AssetSelectionResult
from services.node_registry_service import NodeStateChangeResult
from services.provisioning_models import ProvisionRequest
from services.provisioning_notifier import notify_success, notify_failure


class TestProvisioningNotifier:
    """Test provisioning_notifier functions"""

    @pytest.fixture
    def mock_runtime_context(self):
        """Create a mock runtime context"""
        context = Mock()
        context.tg_reporter = Mock()
        context.logger = Mock()
        context.correlation_id = "test-correlation-123"
        return context

    @pytest.fixture
    def provision_request(self):
        """Create a mock ProvisionRequest"""
        return ProvisionRequest(
            node_name="test-node",
            protocol_type="trojan",
            asset_id=1,
            protocol_config_id=10
        )

    @pytest.fixture
    def selection_result(self):
        """Create a mock AssetSelectionResult"""
        return AssetSelectionResult(
            asset_id=1,
            asset_name="test-asset",
            asset_type="aws",
            region="us-east-1",
            protocol_config_id=10
        )

    @pytest.fixture
    def online_result(self):
        """Create a mock NodeStateChangeResult"""
        return NodeStateChangeResult(
            xboard_node_id=100,
            node_name="test-node",
            success=True
        )

    def test_notify_success(
        self, mock_runtime_context, provision_request, selection_result, online_result
    ):
        """Test notify_success sends notification successfully"""
        notify_success(
            mock_runtime_context,
            provision_request,
            selection_result,
            online_result,
            instance_id="i-1234567890abcdef0",
            ipv6_address="2001:db8::1",
            domain_name="test.example.com",
            cloudflare_record_id="cf-record-123"
        )

        mock_runtime_context.tg_reporter.send.assert_called_once()

        call_args = mock_runtime_context.tg_reporter.send.call_args[0]
        message = call_args[0]

        assert isinstance(message, TelegramMessage)
        assert message.type == TelegramNotificationType.PROVISION_SUCCESS
        assert message.level == "INFO"
        assert "节点开通成功" in message.title
        assert "test-node" in message.body
        assert "trojan" in message.body
        assert "test-asset" in message.body
        assert "us-east-1" in message.body
        assert "100" in message.body
        assert "i-1234567890abcdef0" in message.body
        assert "2001:db8::1" in message.body
        assert "test.example.com" in message.body
        assert "cf-record-123" in message.body

    def test_notify_success_with_none_values(
        self, mock_runtime_context, provision_request, selection_result, online_result
    ):
        """Test notify_success with None values"""
        notify_success(
            mock_runtime_context,
            provision_request,
            selection_result,
            online_result,
            instance_id=None,
            ipv6_address=None,
            domain_name=None,
            cloudflare_record_id=None
        )

        call_args = mock_runtime_context.tg_reporter.send.call_args[0]
        message = call_args[0]

        # Verify None values are replaced with '-'
        assert "实例ID=-" in message.body
        assert "IPv6=-" in message.body
        assert "域名=-" in message.body
        assert "Cloudflare记录ID=-" in message.body

    def test_notify_success_telegram_exception(
        self, mock_runtime_context, provision_request, selection_result, online_result
    ):
        """Test notify_success handles Telegram exceptions"""
        mock_runtime_context.tg_reporter.send.side_effect = Exception("Telegram API error")

        # Should not raise exception
        notify_success(
            mock_runtime_context,
            provision_request,
            selection_result,
            online_result,
            instance_id="i-123",
            ipv6_address="2001:db8::1",
            domain_name="test.com",
            cloudflare_record_id="cf-123"
        )

        mock_runtime_context.logger.exception.assert_called_once()

    def test_notify_failure(
        self, mock_runtime_context, provision_request, selection_result
    ):
        """Test notify_failure sends notification successfully"""
        error = Exception("Test provisioning error")

        notify_failure(
            mock_runtime_context,
            provision_request,
            selection_result,
            error,
            instance_id="i-1234567890abcdef0",
            xboard_node_id=100
        )

        mock_runtime_context.tg_reporter.send.assert_called_once()

        call_args = mock_runtime_context.tg_reporter.send.call_args[0]
        message = call_args[0]

        assert isinstance(message, TelegramMessage)
        assert message.type == TelegramNotificationType.PROVISION_FAILURE
        assert message.level == "ERROR"
        assert "节点开通失败" in message.title
        assert "test-node" in message.body
        assert "trojan" in message.body
        assert "test-asset" in message.body
        assert "us-east-1" in message.body
        assert "100" in message.body
        assert "i-1234567890abcdef0" in message.body
        assert "Test provisioning error" in message.body

    def test_notify_failure_with_none_values(
        self, mock_runtime_context, provision_request, selection_result
    ):
        """Test notify_failure with None values"""
        error = Exception("Test error")

        notify_failure(
            mock_runtime_context,
            provision_request,
            selection_result,
            error,
            instance_id=None,
            xboard_node_id=None
        )

        call_args = mock_runtime_context.tg_reporter.send.call_args[0]
        message = call_args[0]

        # Verify None values are replaced with '-'
        assert "Xboard节点ID=-" in message.body
        assert "实例ID=-" in message.body

    def test_notify_failure_telegram_exception(
        self, mock_runtime_context, provision_request, selection_result
    ):
        """Test notify_failure handles Telegram exceptions"""
        mock_runtime_context.tg_reporter.send.side_effect = Exception("Telegram API error")
        error = Exception("Test error")

        # Should not raise exception
        notify_failure(
            mock_runtime_context,
            provision_request,
            selection_result,
            error,
            instance_id="i-123",
            xboard_node_id=100
        )

        mock_runtime_context.logger.exception.assert_called_once()

    def test_notify_success_with_no_region(
        self, mock_runtime_context, provision_request, online_result
    ):
        """Test notify_success when region is None"""
        selection_result = AssetSelectionResult(
            asset_id=1,
            asset_name="test-asset",
            asset_type="self_hosted",
            region=None,
            protocol_config_id=10
        )

        notify_success(
            mock_runtime_context,
            provision_request,
            selection_result,
            online_result,
            instance_id=None,
            ipv6_address=None,
            domain_name=None,
            cloudflare_record_id=None
        )

        call_args = mock_runtime_context.tg_reporter.send.call_args[0]
        message = call_args[0]

        assert "区域=-" in message.body

    def test_notify_failure_with_no_region(
        self, mock_runtime_context, provision_request
    ):
        """Test notify_failure when region is None"""
        selection_result = AssetSelectionResult(
            asset_id=1,
            asset_name="test-asset",
            asset_type="self_hosted",
            region=None,
            protocol_config_id=10
        )
        error = Exception("Test error")

        notify_failure(
            mock_runtime_context,
            provision_request,
            selection_result,
            error,
            instance_id=None,
            xboard_node_id=None
        )

        call_args = mock_runtime_context.tg_reporter.send.call_args[0]
        message = call_args[0]

        assert "区域=-" in message.body

    def test_notify_success_different_protocols(
        self, mock_runtime_context, selection_result, online_result
    ):
        """Test notify_success with different protocol types"""
        protocols = ["anytls", "trojan", "vless", "vmess", "hysteria2"]

        for protocol in protocols:
            request = ProvisionRequest(
                node_name=f"{protocol}-node",
                protocol_type=protocol,
                asset_id=1,
                protocol_config_id=10
            )

            notify_success(
                mock_runtime_context,
                request,
                selection_result,
                online_result,
                instance_id="i-123",
                ipv6_address="2001:db8::1",
                domain_name="test.com",
                cloudflare_record_id="cf-123"
            )

            call_args = mock_runtime_context.tg_reporter.send.call_args[0]
            message = call_args[0]

            assert protocol in message.body
