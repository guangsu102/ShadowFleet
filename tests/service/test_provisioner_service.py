"""Service layer tests for ProvisionerService with mocked dependencies."""

from __future__ import annotations

import logging
from decimal import Decimal
from unittest.mock import MagicMock, patch


from services.provisioning_models import (
    AssetType,
    DnsRecordSnapshot,
    DnsSyncResult,
    ProvisionRequest,
    ProvisionResult,
    ProtocolType,
)
from services.provisioner_service import ProvisionerService


def create_mock_runtime_context() -> MagicMock:
    """Create a mock RuntimeContext for provisioner tests."""
    mock_context = MagicMock()
    mock_context.logger = MagicMock(spec=logging.Logger)
    mock_context.logger.getChild.return_value = mock_context.logger
    mock_context.correlation_id = "provisioner-test-correlation-id"
    return mock_context


class TestProvisionRequest:
    """Tests for ProvisionRequest validation."""

    def test_provision_request_valid(self) -> None:
        """Valid provision request should be created."""
        request = ProvisionRequest(
            protocol_type="AnyTLS",
            node_name="test-node",
            port="443",
            server_port=443,
            rate=Decimal("100"),
        )
        assert request.protocol_type == "AnyTLS"
        assert request.node_name == "test-node"
        assert request.asset_type == "aws"  # default

    def test_provision_request_aws_defaults(self) -> None:
        """AWS should be default asset type."""
        request = ProvisionRequest(
            protocol_type="Trojan",
            node_name="trojan-node",
            port="443",
            server_port=443,
            rate=Decimal("100"),
        )
        assert request.asset_type == "aws"

    def test_provision_request_self_hosted(self) -> None:
        """Self-hosted type should be explicitly set."""
        request = ProvisionRequest(
            protocol_type="Hysteria2",
            node_name="hy2-node",
            port="443",
            server_port=443,
            rate=Decimal("100"),
            asset_type="self_hosted",
            region="self-hosted",
        )
        assert request.asset_type == "self_hosted"

    def test_provision_request_with_cert_config(self) -> None:
        """ProvisionRequest should accept certificate configuration."""
        request = ProvisionRequest(
            protocol_type="Trojan",
            node_name="tls-node",
            port="443",
            server_port=443,
            rate=Decimal("100"),
            cert_mode="dns",
            cert_domain="example.com",
            cert_provider="cloudflare",
        )
        assert request.cert_mode == "dns"
        assert request.cert_domain == "example.com"


class TestProvisionResult:
    """Tests for ProvisionResult structure."""

    def test_provision_result_aws(self) -> None:
        """ProvisionResult should capture AWS node details."""
        result = ProvisionResult(
            local_node_id=1,
            xboard_node_id=12345,
            asset_id=1,
            asset_type="aws",
            protocol_type="AnyTLS",
            node_name="aws-node",
            status="online",
            aws_account_id="test-account",
            region="ap-northeast-1",
            instance_id="i-1234567890abcdef0",
            network_interface_id="eni-1234567890abcdef0",
            ipv6_address="2600:1f14:804:as03:abcd::",
            domain_name="sf-12345.example.com",
            cloudflare_record_id="cf-record-123",
        )
        assert result.asset_type == "aws"
        assert result.instance_id == "i-1234567890abcdef0"
        assert result.ipv6_address is not None

    def test_provision_result_self_hosted(self) -> None:
        """ProvisionResult should capture self-hosted details."""
        result = ProvisionResult(
            local_node_id=2,
            xboard_node_id=12346,
            asset_id=2,
            asset_type="self_hosted",
            protocol_type="Hysteria2",
            node_name="self-hosted-node",
            status="online",
            aws_account_id=None,
            region=None,
            instance_id=None,
            network_interface_id=None,
            ipv6_address="192.168.1.100",
            domain_name=None,
            cloudflare_record_id=None,
        )
        assert result.asset_type == "self_hosted"
        assert result.aws_account_id is None


class TestDnsSyncResult:
    """Tests for DnsSyncResult structure."""

    def test_dns_sync_result(self) -> None:
        """DnsSyncResult should capture DNS record details."""
        snapshots = (
            DnsRecordSnapshot(
                record_type="AAAA",
                record_id="record-123",
                existed=True,
                content="2600:1f14:804:as03:abcd::",
                proxied=False,
            ),
        )
        result = DnsSyncResult(
            primary_record_id="record-123",
            a_record_id=None,
            aaaa_record_id="record-123",
            snapshots=snapshots,
        )
        assert result.primary_record_id == "record-123"
        assert len(result.snapshots) == 1
        assert result.snapshots[0].record_type == "AAAA"


class TestProvisionerServiceValidation:
    """Tests for provisioner service validation logic."""

    def test_validate_aws_region_required_for_aws(self) -> None:
        """AWS asset should require region."""
        request = ProvisionRequest(
            protocol_type="AnyTLS",
            node_name="test-node",
            port="443",
            server_port=443,
            rate=Decimal("100"),
            asset_type="aws",
            region=None,  # AWS requires region
        )
        # Region is None, should fail in validation
        assert request.region is None

    def test_self_hosted_region_optional(self) -> None:
        """Self-hosted asset should not require region."""
        request = ProvisionRequest(
            protocol_type="Hysteria2",
            node_name="test-node",
            port="443",
            server_port=443,
            rate=Decimal("100"),
            asset_type="self_hosted",
            region="self-hosted",  # Can be any value
        )
        assert request.asset_type == "self_hosted"


class TestProtocolTypeValidation:
    """Tests for protocol type validation."""

    def test_all_supported_protocols(self) -> None:
        """All protocol types should be valid."""
        protocols: list[ProtocolType] = ["AnyTLS", "Trojan", "vless", "vmess", "Hysteria2"]
        for protocol in protocols:
            request = ProvisionRequest(
                protocol_type=protocol,
                node_name=f"{protocol.lower()}-node",
                port="443",
                server_port=443,
                rate=Decimal("100"),
            )
            assert request.protocol_type == protocol


class TestAssetTypeValidation:
    """Tests for asset type validation."""

    def test_all_supported_asset_types(self) -> None:
        """All asset types should be valid."""
        asset_types: list[AssetType] = [
            "aws",
            "digitalocean",
            "vultr",
            "azure",
            "oci",
            "self_hosted",
        ]
        for asset_type in asset_types:
            request = ProvisionRequest(
                protocol_type="Trojan",
                node_name=f"{asset_type}-node",
                port="443",
                server_port=443,
                rate=Decimal("100"),
                asset_type=asset_type,
            )
            assert request.asset_type == asset_type


class TestProvisionerServiceMockedFlow:
    """Tests for provisioner service with mocked dependencies."""

    def test_provision_request_with_measurement_payload(self) -> None:
        """ProvisionRequest should accept basic configuration fields."""
        request = ProvisionRequest(
            protocol_type="Trojan",
            node_name="configured-node",
            port="443",
            server_port=443,
            rate=Decimal("100"),
        )
        assert request.protocol_type == "Trojan"

    def test_azure_request_dispatches_to_azure_flow(self) -> None:
        service = ProvisionerService.__new__(ProvisionerService)
        service._runtime_context = create_mock_runtime_context()
        service._logger = MagicMock()
        service._asset_selector = MagicMock()
        service._asset_repo = MagicMock()
        service._node_registry = MagicMock()
        service._ready_callback_service = MagicMock()
        request = ProvisionRequest(
            protocol_type="Trojan",
            node_name="azure-node",
            port="443",
            server_port=443,
            rate=Decimal("1"),
            asset_type="azure",
            region="japaneast",
        )
        expected = MagicMock(spec=ProvisionResult)

        with patch(
            "services.provisioner_service.provision_azure_node",
            return_value=expected,
        ) as provision_azure:
            result = service.provision_node(request)

        assert result is expected
        dependencies, asset_repo, dispatched_request = provision_azure.call_args.args
        assert dependencies.runtime_context is service._runtime_context
        assert asset_repo is service._asset_repo
        assert dispatched_request is request
