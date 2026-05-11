"""
Tests for provisioning_support module
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from services.provisioning_support import (
    ProvisionerServiceError,
    ProvisioningDependencies,
    build_aws_credential,
    build_register_node_request,
    build_remote_execution_payload,
    build_self_hosted_ssh_config,
    require_non_empty,
    require_task_id,
    resolve_default_instance_spec,
    resolve_effective_domain_name,
    resolve_self_hosted_ip_addresses,
    select_asset,
    truncate_text,
    validate_request,
)
from services.provisioning_models import ProvisionRequest
from services.asset_selector_service import AssetSelectionResult, AssetSelectionError


@pytest.fixture
def mock_runtime_context():
    """Create a mock runtime context"""
    context = MagicMock()
    context.logger = MagicMock()
    context.correlation_id = "test-correlation-id"
    context.config = MagicMock()
    context.config.cloudflare = MagicMock()
    context.config.cloudflare.enabled = True
    context.config.cloudflare.root_domain = "example.com"
    return context


@pytest.fixture
def valid_provision_request():
    """Create a valid provision request"""
    return ProvisionRequest(
        node_name="test-node",
        port="443",
        server_port=8080,
        rate=Decimal("1.0"),
        protocol_type="trojan",
        asset_type="aws",
        region="us-east-1",
        require_cdn_proxy=False,
    )


class TestValidateRequest:
    """Tests for validate_request function"""

    def test_validate_request_success(self, valid_provision_request):
        """Test validating a valid request"""
        validate_request(valid_provision_request)  # Should not raise

    def test_validate_request_empty_node_name(self, valid_provision_request):
        """Test validation fails with empty node_name"""
        valid_provision_request.node_name = ""
        with pytest.raises(ValueError, match="node_name must not be empty"):
            validate_request(valid_provision_request)

    def test_validate_request_empty_port(self, valid_provision_request):
        """Test validation fails with empty port"""
        valid_provision_request.port = ""
        with pytest.raises(ValueError, match="port must not be empty"):
            validate_request(valid_provision_request)

    def test_validate_request_invalid_server_port(self, valid_provision_request):
        """Test validation fails with invalid server_port"""
        valid_provision_request.server_port = 0
        with pytest.raises(ValueError, match="server_port must be greater than 0"):
            validate_request(valid_provision_request)

    def test_validate_request_self_hosted_allows_zero_port(self, valid_provision_request):
        """Test self-hosted assets allow server_port <= 0 for auto-allocation"""
        valid_provision_request.asset_type = "self_hosted"
        valid_provision_request.server_port = 0
        validate_request(valid_provision_request)  # Should not raise

    def test_validate_request_zero_rate(self, valid_provision_request):
        """Test validation fails with zero rate"""
        valid_provision_request.rate = Decimal("0")
        with pytest.raises(ValueError, match="rate must be greater than 0"):
            validate_request(valid_provision_request)

    def test_validate_request_hysteria2_on_aws(self, valid_provision_request):
        """Test validation fails for Hysteria2 on AWS"""
        valid_provision_request.protocol_type = "Hysteria2"
        with pytest.raises(ProvisionerServiceError, match="Hysteria2 is not allowed on AWS assets"):
            validate_request(valid_provision_request)

    def test_validate_request_anytls_with_cdn_proxy(self, valid_provision_request):
        """Test validation fails for AnyTLS with CDN proxy"""
        valid_provision_request.protocol_type = "AnyTLS"
        valid_provision_request.require_cdn_proxy = True
        with pytest.raises(ProvisionerServiceError, match="AnyTLS supports DNS linkage but must not use CDN proxy"):
            validate_request(valid_provision_request)


class TestSelectAsset:
    """Tests for select_asset function"""

    def test_select_asset_success(self, valid_provision_request):
        """Test successful asset selection"""
        mock_selector = MagicMock()
        mock_result = AssetSelectionResult(
            asset_id=1,
            asset_type="aws",
            region="us-east-1",
            requires_dns_record=True,
            aws_account_id="123456789",
            aws_access_key="access",
            aws_secret_key="secret",
            ami_id="ami-123",
            subnet_id="subnet-123",
            security_group_id="sg-123",
            instance_type="t4g.micro",
        )
        mock_selector.select_asset.return_value = mock_result

        result = select_asset(mock_selector, valid_provision_request)

        assert result == mock_result
        mock_selector.select_asset.assert_called_once()

    def test_select_asset_failure(self, valid_provision_request):
        """Test asset selection failure"""
        mock_selector = MagicMock()
        mock_selector.select_asset.side_effect = AssetSelectionError("No assets available")

        with pytest.raises(ProvisionerServiceError, match="Failed to select a provisioning asset"):
            select_asset(mock_selector, valid_provision_request)


class TestBuildRegisterNodeRequest:
    """Tests for build_register_node_request function"""

    @patch('services.provisioning_support.NodeAutoConfigService')
    def test_build_register_node_request_with_group_ids(self, mock_auto_config_class, mock_runtime_context, valid_provision_request):
        """Test building register node request with provided group_ids"""
        valid_provision_request.group_ids = [1, 2, 3]

        result = build_register_node_request(mock_runtime_context, valid_provision_request)

        assert result.node_name == "test-node"
        assert result.host == "test-node"
        assert result.port == "443"
        assert result.server_port == 8080
        assert result.group_ids == [1, 2, 3]
        mock_auto_config_class.assert_not_called()

    @patch('services.provisioning_support.NodeAutoConfigService')
    def test_build_register_node_request_auto_group_ids(self, mock_auto_config_class, mock_runtime_context, valid_provision_request):
        """Test building register node request with auto-fetched group_ids"""
        valid_provision_request.group_ids = None
        mock_auto_config = MagicMock()
        mock_auto_config.get_default_group_ids.return_value = [10, 20, 30]
        mock_auto_config_class.return_value = mock_auto_config

        result = build_register_node_request(mock_runtime_context, valid_provision_request)

        assert result.group_ids == [10, 20, 30]
        mock_auto_config.get_default_group_ids.assert_called_once()

    @patch('services.provisioning_support.NodeAutoConfigService')
    def test_build_register_node_request_with_domain_name(self, mock_auto_config_class, mock_runtime_context, valid_provision_request):
        """Test building register node request with domain_name"""
        valid_provision_request.domain_name = "custom.example.com"
        valid_provision_request.group_ids = [1]

        result = build_register_node_request(mock_runtime_context, valid_provision_request)

        assert result.host == "custom.example.com"


class TestBuildAwsCredential:
    """Tests for build_aws_credential function"""

    def test_build_aws_credential_success(self):
        """Test building AWS credentials from selection result"""
        selection_result = AssetSelectionResult(
            asset_id=1,
            asset_type="aws",
            region="us-west-2",
            requires_dns_record=False,
            aws_account_id="987654321",
            aws_access_key="AKIATEST",
            aws_secret_key="secret123",
        )

        credential = build_aws_credential(selection_result)

        assert credential.account_id == "987654321"
        assert credential.access_key == "AKIATEST"
        assert credential.secret_key == "secret123"
        assert credential.region == "us-west-2"

    def test_build_aws_credential_missing_account_id(self):
        """Test building AWS credentials fails with missing account_id"""
        selection_result = AssetSelectionResult(
            asset_id=1,
            asset_type="aws",
            region="us-west-2",
            requires_dns_record=False,
            aws_account_id=None,
            aws_access_key="AKIATEST",
            aws_secret_key="secret123",
        )

        with pytest.raises(ProvisionerServiceError, match="aws_account_id is required"):
            build_aws_credential(selection_result)


class TestResolveEffectiveDomainName:
    """Tests for resolve_effective_domain_name function"""

    def test_resolve_with_provided_domain_name(self, mock_runtime_context, valid_provision_request):
        """Test resolving domain name when provided in request"""
        valid_provision_request.domain_name = "custom.example.com"
        selection_result = MagicMock()
        selection_result.requires_dns_record = True

        result = resolve_effective_domain_name(
            mock_runtime_context,
            valid_provision_request,
            selection_result,
            xboard_node_id=123
        )

        assert result == "custom.example.com"

    def test_resolve_without_dns_record_requirement(self, mock_runtime_context, valid_provision_request):
        """Test resolving domain name when DNS record not required"""
        valid_provision_request.domain_name = None
        selection_result = MagicMock()
        selection_result.requires_dns_record = False

        result = resolve_effective_domain_name(
            mock_runtime_context,
            valid_provision_request,
            selection_result,
            xboard_node_id=123
        )

        assert result is None

    @patch('services.provisioning_support.DomainPoolManager')
    def test_resolve_with_domain_pool(self, mock_domain_pool_class, mock_runtime_context, valid_provision_request):
        """Test resolving domain name using domain pool manager"""
        valid_provision_request.domain_name = None
        selection_result = MagicMock()
        selection_result.requires_dns_record = True

        mock_domain_manager = MagicMock()
        mock_domain_manager.allocate_domain.return_value = "auto-allocated.example.com"
        mock_domain_pool_class.return_value = mock_domain_manager

        result = resolve_effective_domain_name(
            mock_runtime_context,
            valid_provision_request,
            selection_result,
            xboard_node_id=456
        )

        assert result == "auto-allocated.example.com"
        mock_domain_manager.allocate_domain.assert_called_once_with(
            protocol_type="trojan",
            xboard_node_id=456
        )

    def test_resolve_cloudflare_disabled(self, mock_runtime_context, valid_provision_request):
        """Test resolving domain name fails when Cloudflare disabled"""
        valid_provision_request.domain_name = None
        selection_result = MagicMock()
        selection_result.requires_dns_record = True
        mock_runtime_context.config.cloudflare.enabled = False

        with pytest.raises(ProvisionerServiceError, match="Cloudflare must be enabled"):
            resolve_effective_domain_name(
                mock_runtime_context,
                valid_provision_request,
                selection_result,
                xboard_node_id=123
            )

    def test_resolve_missing_root_domain(self, mock_runtime_context, valid_provision_request):
        """Test resolving domain name fails when root_domain missing"""
        valid_provision_request.domain_name = None
        selection_result = MagicMock()
        selection_result.requires_dns_record = True
        mock_runtime_context.config.cloudflare.root_domain = None

        with pytest.raises(ProvisionerServiceError, match="cloudflare.root_domain is required"):
            resolve_effective_domain_name(
                mock_runtime_context,
                valid_provision_request,
                selection_result,
                xboard_node_id=123
            )


class TestBuildSelfHostedSshConfig:
    """Tests for build_self_hosted_ssh_config function"""

    def test_build_ssh_config_with_password(self):
        """Test building SSH config with password"""
        selection_result = AssetSelectionResult(
            asset_id=1,
            asset_type="self_hosted",
            region="",
            requires_dns_record=False,
            ssh_host="192.168.1.100",
            ssh_port=22,
            ssh_username="ubuntu",
            ssh_password="password123",
        )

        config = build_self_hosted_ssh_config(selection_result)

        assert config.host == "192.168.1.100"
        assert config.port == 22
        assert config.username == "ubuntu"
        assert config.password == "password123"

    def test_build_ssh_config_with_private_key(self):
        """Test building SSH config with private key"""
        selection_result = AssetSelectionResult(
            asset_id=1,
            asset_type="self_hosted",
            region="",
            requires_dns_record=False,
            ssh_host="example.com",
            ssh_port=2222,
            ssh_username="root",
            ssh_private_key="-----BEGIN RSA PRIVATE KEY-----",
        )

        config = build_self_hosted_ssh_config(selection_result)

        assert config.host == "example.com"
        assert config.port == 2222
        assert config.username == "root"
        assert config.private_key == "-----BEGIN RSA PRIVATE KEY-----"

    def test_build_ssh_config_missing_host(self):
        """Test building SSH config fails with missing host"""
        selection_result = AssetSelectionResult(
            asset_id=1,
            asset_type="self_hosted",
            region="",
            requires_dns_record=False,
            ssh_host=None,
            ssh_username="ubuntu",
        )

        with pytest.raises(ProvisionerServiceError, match="ssh_host is required"):
            build_self_hosted_ssh_config(selection_result)


class TestResolveSelfHostedIpAddresses:
    """Tests for resolve_self_hosted_ip_addresses function"""

    def test_resolve_ipv4_address(self):
        """Test resolving IPv4 address"""
        ipv4, ipv6 = resolve_self_hosted_ip_addresses("192.168.1.100")
        assert ipv4 == "192.168.1.100"
        assert ipv6 is None

    def test_resolve_ipv6_address(self):
        """Test resolving IPv6 address"""
        ipv4, ipv6 = resolve_self_hosted_ip_addresses("2001:db8::1")
        assert ipv4 is None
        assert ipv6 == "2001:db8::1"

    @patch('services.provisioning_support.socket.getaddrinfo')
    def test_resolve_hostname_to_ipv4(self, mock_getaddrinfo):
        """Test resolving hostname to IPv4"""
        import socket
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('203.0.113.1', 0))
        ]

        ipv4, ipv6 = resolve_self_hosted_ip_addresses("example.com")
        assert ipv4 == "203.0.113.1"
        assert ipv6 is None

    @patch('services.provisioning_support.socket.getaddrinfo')
    def test_resolve_hostname_to_both(self, mock_getaddrinfo):
        """Test resolving hostname to both IPv4 and IPv6"""
        import socket
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('203.0.113.1', 0)),
            (socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('2001:db8::1', 0, 0, 0))
        ]

        ipv4, ipv6 = resolve_self_hosted_ip_addresses("example.com")
        assert ipv4 == "203.0.113.1"
        assert ipv6 == "2001:db8::1"

    @patch('services.provisioning_support.socket.getaddrinfo')
    def test_resolve_hostname_failure(self, mock_getaddrinfo):
        """Test resolving hostname fails"""
        import socket
        mock_getaddrinfo.side_effect = socket.gaierror("Name or service not known")

        with pytest.raises(ProvisionerServiceError, match="Failed to resolve self-hosted asset address"):
            resolve_self_hosted_ip_addresses("invalid.example.com")

    def test_resolve_empty_host(self):
        """Test resolving empty host fails"""
        with pytest.raises(ProvisionerServiceError, match="ssh_host must not be empty"):
            resolve_self_hosted_ip_addresses("")


class TestBuildRemoteExecutionPayload:
    """Tests for build_remote_execution_payload function"""

    def test_build_payload_basic(self):
        """Test building basic payload"""
        payload = build_remote_execution_payload("install")
        assert payload == {"stage": "install"}

    def test_build_payload_with_command_result(self):
        """Test building payload with command result"""
        from infrastructure.self_hosted.ssh_client import RemoteCommandResult

        result = RemoteCommandResult(
            exit_status=0,
            stdout="Success",
            stderr=""
        )

        payload = build_remote_execution_payload("deploy", command_result=result)
        assert payload["stage"] == "deploy"
        assert payload["exit_status"] == 0
        assert payload["stdout"] == "Success"
        assert payload["stderr"] == ""

    def test_build_payload_with_error(self):
        """Test building payload with error"""
        from infrastructure.self_hosted.ssh_client import SelfHostedSshClientError

        error = SelfHostedSshClientError(
            message="Connection failed",
            stage="connect",
            exit_status=1,
            stdout="",
            stderr="Connection refused"
        )

        payload = build_remote_execution_payload("connect", error=error)
        assert payload["stage"] == "connect"
        assert payload["error_message"] == "Connection failed"
        assert payload["error_stage"] == "connect"
        assert payload["error_exit_status"] == 1
        assert payload["error_stderr"] == "Connection refused"


class TestTruncateText:
    """Tests for truncate_text function"""

    def test_truncate_none(self):
        """Test truncating None returns None"""
        assert truncate_text(None) is None

    def test_truncate_short_text(self):
        """Test truncating short text returns original"""
        text = "Short text"
        assert truncate_text(text) == text

    def test_truncate_long_text(self):
        """Test truncating long text"""
        text = "x" * 10000
        result = truncate_text(text, limit=100)
        assert len(result) < len(text)
        assert result.startswith("x" * 100)
        assert result.endswith("...[truncated]...")

    def test_truncate_exact_limit(self):
        """Test truncating text at exact limit"""
        text = "x" * 8000
        result = truncate_text(text, limit=8000)
        assert result == text


class TestRequireNonEmpty:
    """Tests for require_non_empty function"""

    def test_require_non_empty_valid(self):
        """Test requiring non-empty with valid value"""
        assert require_non_empty("value", "field") == "value"

    def test_require_non_empty_with_whitespace(self):
        """Test requiring non-empty strips whitespace"""
        assert require_non_empty("  value  ", "field") == "value"

    def test_require_non_empty_none(self):
        """Test requiring non-empty fails with None"""
        with pytest.raises(ProvisionerServiceError, match="field is required"):
            require_non_empty(None, "field")

    def test_require_non_empty_empty_string(self):
        """Test requiring non-empty fails with empty string"""
        with pytest.raises(ProvisionerServiceError, match="field is required"):
            require_non_empty("", "field")

    def test_require_non_empty_whitespace_only(self):
        """Test requiring non-empty fails with whitespace only"""
        with pytest.raises(ProvisionerServiceError, match="field is required"):
            require_non_empty("   ", "field")


class TestRequireTaskId:
    """Tests for require_task_id function"""

    def test_require_task_id_valid(self, valid_provision_request):
        """Test requiring task ID with valid value"""
        valid_provision_request.provisioning_task_id = 123
        assert require_task_id(valid_provision_request) == 123

    def test_require_task_id_none(self, valid_provision_request):
        """Test requiring task ID fails with None"""
        valid_provision_request.provisioning_task_id = None
        with pytest.raises(ProvisionerServiceError, match="provisioning_task_id is required"):
            require_task_id(valid_provision_request)

    def test_require_task_id_zero(self, valid_provision_request):
        """Test requiring task ID fails with zero"""
        valid_provision_request.provisioning_task_id = 0
        with pytest.raises(ProvisionerServiceError, match="provisioning_task_id is required"):
            require_task_id(valid_provision_request)

    def test_require_task_id_negative(self, valid_provision_request):
        """Test requiring task ID fails with negative value"""
        valid_provision_request.provisioning_task_id = -1
        with pytest.raises(ProvisionerServiceError, match="provisioning_task_id is required"):
            require_task_id(valid_provision_request)
