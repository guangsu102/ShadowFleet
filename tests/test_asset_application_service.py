"""
Tests for AssetApplicationService
"""
from unittest.mock import Mock, patch

import pytest

from services.asset_application_service import AssetApplicationService
from services.asset_application_models import (
    AssetRegistrationRequest,
    DigitalOceanAssetRegistrationRequest,
    SelfHostedAssetRegistrationRequest,
)


class TestAssetApplicationService:
    """Test AssetApplicationService"""

    @pytest.fixture
    def mock_runtime_context(self):
        """Create a mock runtime context"""
        context = Mock()
        context.logger = Mock()
        context.logger.getChild.return_value = Mock()
        context.correlation_id = "test-correlation-123"
        context.config = Mock()
        context.config.app = Mock()
        context.config.app.request_timeout_seconds = 30
        context.config.app.max_retries = 3
        return context

    @pytest.fixture
    def service(self, mock_runtime_context):
        """Create an AssetApplicationService instance"""
        with patch("services.asset_application_service.AssetRepo"):
            return AssetApplicationService(mock_runtime_context)

    @pytest.fixture
    def aws_registration_request(self):
        """Create a mock AWS AssetRegistrationRequest"""
        return AssetRegistrationRequest(
            asset_name="test-asset",
            region="us-east-1",
            aws_access_key="AKIAIOSFOD" "NN7EXAMPLE",
            aws_secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            aws_account_id="123456789012",
            protocol_type="trojan",
            target_count=5,
            max_count=10,
            priority=100
        )

    @pytest.fixture
    def self_hosted_registration_request(self):
        """Create a mock SelfHostedAssetRegistrationRequest"""
        return SelfHostedAssetRegistrationRequest(
            asset_name="self-hosted-asset",
            region="local",
            host="192.168.1.100",
            ssh_port=22,
            ssh_username="root",
            ssh_password="password123",
            protocol_type="trojan",
            target_count=3,
            max_count=5
        )

    def test_init(self, mock_runtime_context):
        """Test AssetApplicationService initialization"""
        with patch("services.asset_application_service.AssetRepo") as mock_repo:
            service = AssetApplicationService(mock_runtime_context)

            assert service._runtime_context == mock_runtime_context
            mock_repo.assert_called_once_with(mock_runtime_context)

    def test_validate_registration_request_valid(self, aws_registration_request):
        """Test _validate_registration_request with valid request"""
        # Should not raise exception
        AssetApplicationService._validate_registration_request(aws_registration_request)

    def test_validate_registration_request_empty_asset_name(self):
        """Test _validate_registration_request with empty asset name"""
        request = AssetRegistrationRequest(
            asset_name="",
            region="us-east-1",
            aws_access_key="key",
            aws_secret_key="secret"
        )

        with pytest.raises(ValueError, match="资产名称不能为空"):
            AssetApplicationService._validate_registration_request(request)

    def test_validate_registration_request_empty_region(self):
        """Test _validate_registration_request with empty region"""
        request = AssetRegistrationRequest(
            asset_name="test",
            region="",
            aws_access_key="key",
            aws_secret_key="secret"
        )

        with pytest.raises(ValueError, match="区域不能为空"):
            AssetApplicationService._validate_registration_request(request)

    def test_validate_registration_request_empty_access_key(self):
        """Test _validate_registration_request with empty access key"""
        request = AssetRegistrationRequest(
            asset_name="test",
            region="us-east-1",
            aws_access_key="",
            aws_secret_key="secret"
        )

        with pytest.raises(ValueError, match="AWS Access Key 不能为空"):
            AssetApplicationService._validate_registration_request(request)

    def test_validate_registration_request_empty_secret_key(self):
        """Test _validate_registration_request with empty secret key"""
        request = AssetRegistrationRequest(
            asset_name="test",
            region="us-east-1",
            aws_access_key="key",
            aws_secret_key=""
        )

        with pytest.raises(ValueError, match="AWS Secret Key 不能为空"):
            AssetApplicationService._validate_registration_request(request)

    def test_validate_registration_request_invalid_vcpu(self):
        """Test _validate_registration_request with invalid vCPU"""
        request = AssetRegistrationRequest(
            asset_name="test",
            region="us-east-1",
            aws_access_key="key",
            aws_secret_key="secret",
            default_vcpu=0
        )

        with pytest.raises(ValueError, match="默认 vCPU 必须大于 0"):
            AssetApplicationService._validate_registration_request(request)

    def test_validate_registration_request_negative_target_count(self):
        """Test _validate_registration_request with negative target_count"""
        request = AssetRegistrationRequest(
            asset_name="test",
            region="us-east-1",
            aws_access_key="key",
            aws_secret_key="secret",
            protocol_type="trojan",
            target_count=-1
        )

        with pytest.raises(ValueError, match="target_count 不能小于 0"):
            AssetApplicationService._validate_registration_request(request)

    def test_validate_registration_request_target_exceeds_max(self):
        """Test _validate_registration_request when target_count > max_count"""
        request = AssetRegistrationRequest(
            asset_name="test",
            region="us-east-1",
            aws_access_key="key",
            aws_secret_key="secret",
            protocol_type="trojan",
            target_count=10,
            max_count=5
        )

        with pytest.raises(ValueError, match="target_count 不能大于 max_count"):
            AssetApplicationService._validate_registration_request(request)

    def test_normalize_optional_text_none(self):
        """Test _normalize_optional_text with None"""
        result = AssetApplicationService._normalize_optional_text(None)
        assert result is None

    def test_normalize_optional_text_empty_string(self):
        """Test _normalize_optional_text with empty string"""
        result = AssetApplicationService._normalize_optional_text("")
        assert result is None

    def test_normalize_optional_text_whitespace(self):
        """Test _normalize_optional_text with whitespace"""
        result = AssetApplicationService._normalize_optional_text("   ")
        assert result is None

    def test_normalize_optional_text_valid_string(self):
        """Test _normalize_optional_text with valid string"""
        result = AssetApplicationService._normalize_optional_text("  test  ")
        assert result == "test"

    def test_validate_self_hosted_request_valid(self, self_hosted_registration_request):
        """Test _validate_self_hosted_request with valid request"""
        # Should not raise exception
        AssetApplicationService._validate_self_hosted_request(self_hosted_registration_request)

    def test_register_digitalocean_asset_creates_asset_and_protocol(self, service):
        """DigitalOcean asset registration should persist token-backed provider config."""
        request = DigitalOceanAssetRegistrationRequest(
            asset_name="do-sgp1",
            region="sgp1",
            digitalocean_token="dop_v1_test",
            default_size="s-2vcpu-2gb",
            default_image="ubuntu-24-04-x64",
            ssh_keys=("fingerprint-1",),
            vpc_uuid="vpc-123",
            tags=("prod",),
            protocol_type="Trojan",
            target_count=1,
            max_count=2,
            default_vcpu=2,
        )
        service._asset_repo.create_asset.return_value = 42
        service._asset_repo.upsert_asset_protocol_config.return_value = 7

        with patch("services.asset_application_service.DigitalOceanClient") as mock_client_cls:
            mock_client_cls.return_value.validate_account.return_value = {"uuid": "acct-do-1"}
            result = service.register_digitalocean_asset(request)

        assert result.asset_id == 42
        created_asset = service._asset_repo.create_asset.call_args.args[0]
        assert created_asset.asset_type == "digitalocean"
        assert created_asset.aws_account_id == "acct-do-1"
        assert created_asset.aws_access_key == "dop_v1_test"
        assert created_asset.provider_config == {
            "ssh_keys": ["fingerprint-1"],
            "tags": ["shadowfleet", "prod"],
            "vpc_uuid": "vpc-123",
        }
        protocol_config = service._asset_repo.upsert_asset_protocol_config.call_args.args[0]
        assert protocol_config.asset_id == 42
        assert protocol_config.protocol_type == "Trojan"
        assert protocol_config.instance_type == "s-2vcpu-2gb"
        assert protocol_config.ami_id == "ubuntu-24-04-x64"
        assert protocol_config.subnet_id == "vpc-123"

    def test_validate_self_hosted_request_empty_asset_name(self):
        """Test _validate_self_hosted_request with empty asset name"""
        request = SelfHostedAssetRegistrationRequest(
            asset_name="",
            region="local",
            host="192.168.1.100"
        )

        with pytest.raises(ValueError, match="资产名称不能为空"):
            AssetApplicationService._validate_self_hosted_request(request)

    def test_validate_self_hosted_request_empty_host(self):
        """Test _validate_self_hosted_request with empty host"""
        request = SelfHostedAssetRegistrationRequest(
            asset_name="test",
            region="local",
            host=""
        )

        with pytest.raises(ValueError, match="主机地址不能为空"):
            AssetApplicationService._validate_self_hosted_request(request)

    def test_validate_self_hosted_request_invalid_ssh_port(self):
        """Test _validate_self_hosted_request with invalid SSH port"""
        request = SelfHostedAssetRegistrationRequest(
            asset_name="test",
            region="local",
            host="192.168.1.100",
            ssh_port=0
        )

        with pytest.raises(ValueError, match="SSH 端口必须在 1-65535 之间"):
            AssetApplicationService._validate_self_hosted_request(request)

    def test_validate_self_hosted_request_empty_username(self):
        """Test _validate_self_hosted_request with empty username"""
        request = SelfHostedAssetRegistrationRequest(
            asset_name="test",
            region="local",
            host="192.168.1.100",
            ssh_username=""
        )

        with pytest.raises(ValueError, match="SSH 用户名不能为空"):
            AssetApplicationService._validate_self_hosted_request(request)

    def test_validate_self_hosted_request_no_password_or_key(self):
        """Test _validate_self_hosted_request without password or key"""
        request = SelfHostedAssetRegistrationRequest(
            asset_name="test",
            region="local",
            host="192.168.1.100",
            ssh_password=None,
            ssh_private_key=None
        )

        with pytest.raises(ValueError, match="必须提供 SSH 密码或私钥之一"):
            AssetApplicationService._validate_self_hosted_request(request)

    def test_resolve_account_id_with_provided_id(self, service, aws_registration_request):
        """Test _resolve_account_id when account_id is provided"""
        result = service._resolve_account_id(aws_registration_request)
        assert result == "123456789012"

    def test_resolve_account_id_auto_fetch(self, service):
        """Test _resolve_account_id auto-fetches from STS"""
        request = AssetRegistrationRequest(
            asset_name="test",
            region="us-east-1",
            aws_access_key="key",
            aws_secret_key="secret",
            aws_account_id=None
        )

        mock_identity = Mock()
        mock_identity.account_id = "987654321098"

        with patch("services.asset_application_service.resolve_aws_account_id", return_value=mock_identity):
            result = service._resolve_account_id(request)

        assert result == "987654321098"

    def test_register_aws_asset_success(self, service, aws_registration_request):
        """Test register_aws_asset successfully registers asset"""
        service._asset_repo.create_asset.return_value = 1
        service._asset_repo.upsert_asset_protocol_config.return_value = 10

        result = service.register_aws_asset(aws_registration_request)

        assert result.asset_id == 1
        assert result.asset_name == "test-asset"
        assert result.protocol_config_id == 10
        service._asset_repo.create_asset.assert_called_once()
        service._asset_repo.create_asset_event.assert_called_once()

    def test_register_self_hosted_asset_success(self, service, self_hosted_registration_request):
        """Test register_self_hosted_asset successfully registers asset"""
        service._asset_repo.create_asset.return_value = 2
        service._asset_repo.upsert_asset_protocol_config.return_value = 20

        with patch.object(service, "probe_self_hosted_hardware", return_value=(4, 8.0)):
            result = service.register_self_hosted_asset(self_hosted_registration_request)

        assert result.asset_id == 2
        assert result.asset_name == "self-hosted-asset"
        assert result.protocol_config_id == 20
        service._asset_repo.create_asset.assert_called_once()

    def test_delete_asset_success(self, service):
        """Test delete_asset successfully deletes asset"""
        mock_asset = Mock()
        mock_asset.asset_name = "test-asset"
        mock_asset.asset_type = "aws"
        mock_asset.region = "us-east-1"

        service._asset_repo.get_active_allocations_count.return_value = 0
        service._asset_repo.get_asset_by_id.return_value = mock_asset

        service.delete_asset(1)

        service._asset_repo.delete_asset.assert_called_once_with(1)
        service._asset_repo.create_asset_event.assert_called_once()

    def test_delete_asset_with_active_allocations(self, service):
        """Test delete_asset fails when asset has active allocations"""
        service._asset_repo.get_active_allocations_count.return_value = 5

        with pytest.raises(ValueError, match="仍有 5 个活跃分配记录"):
            service.delete_asset(1)

        service._asset_repo.delete_asset.assert_not_called()

    def test_query_arm64_amis(self, service):
        """Test query_arm64_amis returns AMI list"""
        mock_ec2_client = Mock()
        mock_ec2_client.list_arm64_amis.return_value = [
            {"ImageId": "ami-123", "Name": "Ubuntu 22.04"},
            {"ImageId": "ami-456", "Name": "Ubuntu 20.04"}
        ]

        with patch.object(service, "_build_ec2_client", return_value=mock_ec2_client):
            result = service.query_arm64_amis(
                aws_access_key="key",
                aws_secret_key="secret",
                aws_region="us-east-1",
                name_filter="Ubuntu",
                limit=10
            )

        assert len(result) == 2
        assert result[0]["ImageId"] == "ami-123"

    def test_probe_self_hosted_hardware_success(self, service):
        """Test probe_self_hosted_hardware returns hardware specs"""
        mock_ssh_client = Mock()
        mock_spec = Mock()
        mock_spec.cpu_cores = 8
        mock_spec.memory_gb = 16.0
        mock_ssh_client.detect_hardware.return_value = mock_spec

        with patch("services.asset_application_service.SelfHostedSshClient", return_value=mock_ssh_client):
            cpu_cores, memory_gb = service.probe_self_hosted_hardware(
                host="192.168.1.100",
                ssh_port=22,
                ssh_username="root",
                ssh_password="password",
                ssh_private_key=None
            )

        assert cpu_cores == 8
        assert memory_gb == 16.0
