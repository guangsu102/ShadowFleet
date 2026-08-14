"""Service layer tests for HealerService with mocked dependencies."""

from __future__ import annotations

import logging
import time
from unittest.mock import ANY, MagicMock, patch

import pytest

from database.state_models import FleetNodeRecord, FleetNodeStatus
from services.healing_models import (
    AwsAccountBannedError,
    HealRequest,
    HealResult,
    HealerServiceError,
)
from services.healing_support import determine_heal_strategy, get_duration_ms


def create_mock_runtime_context() -> MagicMock:
    """Create a mock RuntimeContext for healer tests."""
    mock_context = MagicMock()
    mock_context.logger = MagicMock(spec=logging.Logger)
    mock_context.logger.getChild.return_value = mock_context.logger
    mock_context.correlation_id = "healer-test-correlation-id"
    return mock_context


def create_mock_node_record(
    asset_type: str = "aws",
    node_type: str = "AnyTLS",
    status: FleetNodeStatus = "online",
) -> FleetNodeRecord:
    """Create a mock FleetNodeRecord."""
    is_aws = asset_type == "aws"
    is_digitalocean = asset_type == "digitalocean"
    is_vultr = asset_type == "vultr"
    is_azure = asset_type == "azure"
    return FleetNodeRecord(
        id=1,
        xboard_node_id=12345,
        node_name="test-node",
        node_type=node_type,
        status=status,
        status_reason=None,
        aws_account_id=(
            "test-aws-account"
            if is_aws
            else "test-do-account"
            if is_digitalocean
            else "vultr:test"
            if is_vultr
            else "azure:subscription"
            if is_azure
            else None
        ),
        aws_region=(
            "ap-northeast-1"
            if is_aws
            else "sgp1"
            if is_digitalocean or is_vultr
            else "japaneast"
            if is_azure
            else None
        ),
        aws_instance_id=(
            "i-1234567890abcdef0"
            if is_aws
            else "do-droplet-123"
            if is_digitalocean
            else "vultr-instance-123"
            if is_vultr
            else "/subscriptions/subscription/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/test-node"
            if is_azure
            else None
        ),
        aws_subnet_id="subnet-1234567890abcdef0" if is_aws else None,
        aws_security_group_id="sg-1234567890abcdef0" if is_aws else None,
        cloudflare_record_id="cf-record-123",
        domain_name="sf-12345.example.com",
        ipv4_address=None,
        ipv6_address="2600:1f14:804:as03:1234::",
        last_known_host=None,
        last_error=None,
        is_deleted=False,
        created_at="2026-03-23T10:00:00Z",
        updated_at="2026-03-23T10:00:00Z",
        online_at="2026-03-23T10:00:00Z",
        offline_at=None,
        deleted_at=None,
        last_healed_at=None,
        xboard_status=None,
        xboard_show=None,
        xboard_updated_at=None,
        asset_type=asset_type,
    )


class TestHealerServiceHealRequest:
    """Tests for HealRequest validation."""

    def test_heal_request_valid(self) -> None:
        """Valid heal request should be created."""
        request = HealRequest(
            xboard_node_id=12345,
            reason="confirmed_blocked_by_gfw",
            source="sentinel",
        )
        assert request.xboard_node_id == 12345
        assert request.reason == "confirmed_blocked_by_gfw"
        assert request.source == "sentinel"

    def test_heal_request_with_measurement_payload(self) -> None:
        """HealRequest should accept measurement payload."""
        payload = {"probe_results": [{"probe": "cn-1", "status": "failed"}]}
        request = HealRequest(
            xboard_node_id=12345,
            reason="suspected_blocked",
            measurement_payload=payload,
        )
        assert request.measurement_payload is not None
        assert "probe_results" in request.measurement_payload


class TestHealerServiceHealResult:
    """Tests for HealResult structure."""

    def test_heal_result_success(self) -> None:
        """HealResult should capture success details."""
        result = HealResult(
            xboard_node_id=12345,
            node_name="test-node",
            node_type="AnyTLS",
            asset_type="aws",
            strategy="aws_ipv6_rotate",
            success=True,
            old_ipv6_address="2600:1f14:804:as03:1234::",
            new_ipv6_address="2600:1f14:804:as03:5678::",
            domain_name="sf-12345.example.com",
            cloudflare_record_id="cf-record-123",
            proxied_enabled=False,
            duration_ms=500,
            message="AWS IPv6 热切换自愈成功",
            correlation_id="corr-123",
        )
        assert result.success is True
        assert result.strategy == "aws_ipv6_rotate"
        assert result.old_ipv6_address != result.new_ipv6_address

    def test_heal_result_failure(self) -> None:
        """HealResult should capture failure details."""
        result = HealResult(
            xboard_node_id=12345,
            node_name="test-node",
            node_type="Trojan",
            asset_type="aws",
            strategy="manual_review_required",
            success=False,
            old_ipv6_address="2600:1f14:804:as03:1234::",
            new_ipv6_address="2600:1f14:804:as03:1234::",
            domain_name="sf-12345.example.com",
            cloudflare_record_id=None,
            proxied_enabled=None,
            duration_ms=100,
            message="需要人工介入",
            correlation_id="corr-456",
        )
        assert result.success is False
        assert result.strategy == "manual_review_required"


class TestDetermineHealStrategy:
    """Tests for heal strategy determination logic."""

    def test_aws_node_uses_ipv6_rotate(self) -> None:
        """AWS node should use aws_ipv6_rotate strategy."""
        node = create_mock_node_record(asset_type="aws")
        request = HealRequest(
            xboard_node_id=12345,
            reason="confirmed_blocked_by_gfw",
        )
        strategy = determine_heal_strategy(node, request)
        assert strategy == "aws_ipv6_rotate"

    def test_self_hosted_node_uses_cdn_proxy(self) -> None:
        """Self-hosted node with supported protocol should use cloudflare_enable_proxy strategy."""
        # Self-hosted Trojan/vless/vmess nodes can use cloudflare proxy
        node = create_mock_node_record(asset_type="self_hosted", node_type="Trojan")
        request = HealRequest(
            xboard_node_id=12345,
            reason="confirmed_blocked_by_gfw",
        )
        strategy = determine_heal_strategy(node, request)
        assert strategy == "cloudflare_enable_proxy"

    def test_self_hosted_anytls_returns_manual_review(self) -> None:
        """Self-hosted AnyTLS node should require manual review (not in SELF_HOSTED_PROXY_PROTOCOLS)."""
        # AnyTLS is not in SELF_HOSTED_PROXY_PROTOCOLS, so it returns manual_review_required
        node = create_mock_node_record(asset_type="self_hosted", node_type="AnyTLS")
        request = HealRequest(
            xboard_node_id=12345,
            reason="confirmed_blocked_by_gfw",
        )
        strategy = determine_heal_strategy(node, request)
        assert strategy == "manual_review_required"

    def test_digitalocean_node_returns_manual_review(self) -> None:
        """DigitalOcean nodes should not use AWS IPv6 rotation."""
        node = create_mock_node_record(asset_type="digitalocean", node_type="AnyTLS")
        request = HealRequest(
            xboard_node_id=12345,
            reason="confirmed_blocked_by_gfw",
        )
        strategy = determine_heal_strategy(node, request)
        assert strategy == "manual_review_required"

    def test_vultr_proxy_protocol_uses_instance_replacement(self) -> None:
        node = create_mock_node_record(asset_type="vultr", node_type="Trojan")
        request = HealRequest(xboard_node_id=12345, reason="confirmed_blocked_by_gfw")

        assert determine_heal_strategy(node, request) == "vultr_instance_replace"

    def test_vultr_anytls_uses_instance_replacement(self) -> None:
        node = create_mock_node_record(asset_type="vultr", node_type="AnyTLS")
        request = HealRequest(xboard_node_id=12345, reason="confirmed_blocked_by_gfw")

        assert determine_heal_strategy(node, request) == "vultr_instance_replace"

    def test_azure_proxy_protocol_uses_ipv6_rotate(self) -> None:
        node = create_mock_node_record(asset_type="azure", node_type="Trojan")
        request = HealRequest(xboard_node_id=12345, reason="confirmed_blocked_by_gfw")

        assert determine_heal_strategy(node, request) == "azure_ipv6_rotate"

    def test_azure_anytls_uses_ipv6_rotate(self) -> None:
        node = create_mock_node_record(asset_type="azure", node_type="AnyTLS")
        request = HealRequest(xboard_node_id=12345, reason="confirmed_blocked_by_gfw")

        assert determine_heal_strategy(node, request) == "azure_ipv6_rotate"

    def test_suspected_blocked_returns_manual_review(self) -> None:
        """Nodes with unsupported protocols should require manual review."""
        # This tests a node with unsupported protocol that would return manual_review_required
        node = create_mock_node_record(asset_type="aws", node_type="Hysteria2")
        request = HealRequest(
            xboard_node_id=12345,
            reason="suspected_blocked",
        )
        strategy = determine_heal_strategy(node, request)
        assert strategy == "manual_review_required"

    def test_force_strategy_overrides(self) -> None:
        """Force strategy should override auto-determination."""
        node = create_mock_node_record(asset_type="self_hosted")
        request = HealRequest(
            xboard_node_id=12345,
            reason="confirmed_blocked_by_gfw",
            force_strategy="aws_ipv6_rotate",
        )
        strategy = determine_heal_strategy(node, request)
        assert strategy == "aws_ipv6_rotate"


class TestAwsAccountBannedError:
    """Tests for AwsAccountBannedError."""

    def test_error_attributes(self) -> None:
        """AwsAccountBannedError should have correct attributes."""
        error = AwsAccountBannedError(
            aws_account_id="test-account",
            error_code="AuthFailure",
            message="Account banned by AWS",
        )
        assert error.aws_account_id == "test-account"
        assert error.error_code == "AuthFailure"
        assert str(error) == "Account banned by AWS"

    def test_error_inheritance(self) -> None:
        """AwsAccountBannedError should inherit from HealerServiceError."""
        error = AwsAccountBannedError(
            aws_account_id="test-account",
            error_code="AuthFailure",
            message="Account banned",
        )
        assert isinstance(error, HealerServiceError)


class TestGetDurationMs:
    """Tests for duration calculation."""

    def test_duration_calculation(self) -> None:
        """get_duration_ms should calculate elapsed time correctly."""
        start = time.monotonic()
        time.sleep(0.1)  # 100ms
        duration = get_duration_ms(start)
        assert duration >= 80  # Allow some tolerance for system overhead
        assert duration < 2000  # Should be under 2 seconds for this test

    def test_duration_zero_for_future_start(self) -> None:
        """get_duration_ms should handle future start time."""
        future_start = time.monotonic() + 100
        duration = get_duration_ms(future_start)
        assert duration >= 0


class TestHealerServiceIntegration:
    """Integration tests for HealerService with mocked components."""

    def test_heal_request_for_nonexistent_node_raises(self) -> None:
        """Healing non-existent node should raise error."""
        from services.healer_service import HealerService

        mock_state_repo = MagicMock()
        mock_state_repo.get_node_by_xboard_node_id.return_value = None

        mock_context = create_mock_runtime_context()
        mock_context.sqlite_manager = MagicMock()

        healer = HealerService(mock_context)
        healer._state_repo = mock_state_repo

        request = HealRequest(xboard_node_id=99999, reason="confirmed_blocked_by_gfw")

        with pytest.raises(HealerServiceError, match="not found"):
            healer.heal_node(request)

    def test_heal_skipped_when_locked(self) -> None:
        """Healing should be skipped when node is already locked."""
        from services.healer_service import HealerService

        node_record = create_mock_node_record()

        mock_state_repo = MagicMock()
        mock_state_repo.get_node_by_xboard_node_id.return_value = node_record
        mock_state_repo.acquire_operation_lock.return_value = False

        mock_context = create_mock_runtime_context()
        mock_context.sqlite_manager = MagicMock()

        healer = HealerService(mock_context)
        healer._state_repo = mock_state_repo

        request = HealRequest(xboard_node_id=12345, reason="confirmed_blocked_by_gfw")
        result = healer.heal_node(request)

        assert result.success is False
        # Implementation returns Chinese message: "节点当前已有自愈任务执行中，已跳过本次请求"
        assert "跳过" in result.message or "已跳过" in result.message

    def test_azure_strategy_dispatches_to_azure_flow(self) -> None:
        from services.healer_service import HealerService

        node_record = create_mock_node_record(asset_type="azure")
        mock_state_repo = MagicMock()
        mock_state_repo.get_node_by_xboard_node_id.return_value = node_record
        mock_state_repo.acquire_operation_lock.return_value = True
        mock_context = create_mock_runtime_context()
        mock_context.sqlite_manager = MagicMock()
        healer = HealerService(mock_context)
        healer._state_repo = mock_state_repo
        healer._asset_repo = MagicMock()
        healer._xboard_repo = MagicMock()
        expected_result = MagicMock(spec=HealResult)

        with patch(
            "services.healer_service.heal_azure_node",
            return_value=expected_result,
        ) as heal_azure:
            result = healer.heal_node(
                HealRequest(
                    xboard_node_id=node_record.xboard_node_id,
                    reason="confirmed_blocked_by_gfw",
                )
            )

        assert result is expected_result
        lock_request = mock_state_repo.acquire_operation_lock.call_args.args[0]
        assert lock_request.expires_in_seconds == 2100
        heal_azure.assert_called_once_with(
            runtime_context=mock_context,
            asset_repo=healer._asset_repo,
            state_repo=mock_state_repo,
            xboard_repo=healer._xboard_repo,
            node_record=node_record,
            request=ANY,
            started_monotonic=ANY,
        )
        mock_state_repo.release_operation_lock.assert_called_once_with(
            f"healing:{node_record.xboard_node_id}"
        )
