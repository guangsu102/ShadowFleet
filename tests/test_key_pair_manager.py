"""
Tests for KeyPairManager service
"""
import os
from pathlib import Path
from unittest.mock import Mock, patch, mock_open

import pytest
from botocore.exceptions import ClientError

from models.aws_credentials import AwsCredentials
from services.key_pair_manager import KeyPairManager, KeyPairManagerError


class TestKeyPairManager:
    """Test KeyPairManager"""

    @pytest.fixture
    def mock_runtime_context(self):
        """Create a mock runtime context"""
        context = Mock()
        context.config = Mock()
        context.config.app = Mock()
        context.config.app.key_pair_local_dir = "/tmp/keypairs"
        context.logger = Mock()
        context.logger.getChild.return_value = Mock()
        return context

    @pytest.fixture
    def manager(self, mock_runtime_context):
        """Create a KeyPairManager instance"""
        return KeyPairManager(mock_runtime_context)

    @pytest.fixture
    def mock_aws_credential(self):
        """Create a mock AWS credential"""
        return AwsCredentials(
            account_id="123456789012",
            access_key="AKIAIOSFODNN7EXAMPLE",
            secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            region="us-east-1"
        )

    @pytest.fixture
    def mock_ec2_client(self):
        """Create a mock EC2 client"""
        return Mock()

    def test_init(self, mock_runtime_context):
        """Test KeyPairManager initialization"""
        manager = KeyPairManager(mock_runtime_context)

        assert manager._runtime_context == mock_runtime_context
        assert manager._config == mock_runtime_context.config.app
        assert manager._key_pair_dir == Path("/tmp/keypairs")
        assert manager._rate_limiter is not None

    def test_key_pair_path(self, manager):
        """Test _key_pair_path method"""
        path = manager._key_pair_path("123456789012")

        assert path == Path("/tmp/keypairs/123456789012/123456789012.pem")

    def test_ensure_parent_dir(self, manager):
        """Test _ensure_parent_dir creates directories"""
        test_path = Path("/tmp/test/subdir/file.pem")

        with patch.object(Path, "mkdir") as mock_mkdir:
            manager._ensure_parent_dir(test_path)

            mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)

    def test_ensure_key_pair_for_account_already_exists(
        self, manager, mock_aws_credential, mock_ec2_client, mock_runtime_context
    ):
        """Test ensure_key_pair_for_account when key pair already exists"""
        mock_ec2_client.describe_key_pairs.return_value = {
            "KeyPairs": [{"KeyName": "123456789012"}]
        }

        key_name = manager.ensure_key_pair_for_account(mock_aws_credential, mock_ec2_client)

        assert key_name == "123456789012"
        mock_ec2_client.describe_key_pairs.assert_called_once_with(KeyNames=["123456789012"])
        mock_ec2_client.import_key_pair.assert_not_called()

    def test_ensure_key_pair_for_account_creates_new(
        self, manager, mock_aws_credential, mock_ec2_client, mock_runtime_context
    ):
        """Test ensure_key_pair_for_account creates new key pair"""
        # Key pair doesn't exist
        error_response = {"Error": {"Code": "InvalidKeyPair.NotFound"}}
        mock_ec2_client.describe_key_pairs.side_effect = ClientError(error_response, "describe_key_pairs")

        # Mock import_key_pair response
        mock_ec2_client.import_key_pair.return_value = {"KeyPairId": "key-12345"}

        with patch("services.key_pair_manager._generate_rsa_key_pair") as mock_generate:
            mock_generate.return_value = ("private_key_pem", b"public_key_openssh")

            with patch("builtins.open", mock_open()) as mock_file:
                with patch.object(Path, "mkdir"):
                    with patch.object(Path, "chmod"):
                        key_name = manager.ensure_key_pair_for_account(
                            mock_aws_credential, mock_ec2_client
                        )

        assert key_name == "123456789012"
        mock_ec2_client.import_key_pair.assert_called_once()

    def test_key_pair_exists_remotely_true(self, manager, mock_ec2_client):
        """Test _key_pair_exists_remotely returns True when key exists"""
        mock_ec2_client.describe_key_pairs.return_value = {
            "KeyPairs": [{"KeyName": "test-key"}]
        }

        result = manager._key_pair_exists_remotely(mock_ec2_client, "test-key")

        assert result is True

    def test_key_pair_exists_remotely_false(self, manager, mock_ec2_client):
        """Test _key_pair_exists_remotely returns False when key doesn't exist"""
        error_response = {"Error": {"Code": "InvalidKeyPair.NotFound"}}
        mock_ec2_client.describe_key_pairs.side_effect = ClientError(error_response, "describe_key_pairs")

        result = manager._key_pair_exists_remotely(mock_ec2_client, "test-key")

        assert result is False

    def test_key_pair_exists_remotely_other_error(self, manager, mock_ec2_client):
        """Test _key_pair_exists_remotely raises error for other AWS errors"""
        error_response = {"Error": {"Code": "UnauthorizedOperation"}}
        mock_ec2_client.describe_key_pairs.side_effect = ClientError(error_response, "describe_key_pairs")

        with pytest.raises(KeyPairManagerError, match="describe_key_pairs failed"):
            manager._key_pair_exists_remotely(mock_ec2_client, "test-key")

    def test_generate_and_import_key_pair_success(
        self, manager, mock_aws_credential, mock_ec2_client
    ):
        """Test _generate_and_import_key_pair successfully imports key"""
        mock_ec2_client.import_key_pair.return_value = {"KeyPairId": "key-12345"}

        with patch("services.key_pair_manager._generate_rsa_key_pair") as mock_generate:
            mock_generate.return_value = ("private_key_pem", b"public_key_openssh")

            with patch("builtins.open", mock_open()) as mock_file:
                with patch.object(Path, "mkdir"):
                    with patch.object(Path, "chmod") as mock_chmod:
                        key_name = manager._generate_and_import_key_pair(
                            mock_aws_credential, mock_ec2_client
                        )

        assert key_name == "123456789012"
        mock_ec2_client.import_key_pair.assert_called_once()
        # Verify chmod was called with 0o600
        mock_chmod.assert_called_once_with(0o600)

    def test_generate_and_import_key_pair_import_fails(
        self, manager, mock_aws_credential, mock_ec2_client
    ):
        """Test _generate_and_import_key_pair handles import failure"""
        error_response = {"Error": {"Code": "InvalidKeyPair.Duplicate"}}
        mock_ec2_client.import_key_pair.side_effect = ClientError(error_response, "import_key_pair")

        with patch("services.key_pair_manager._generate_rsa_key_pair") as mock_generate:
            mock_generate.return_value = ("private_key_pem", b"public_key_openssh")

            with patch("builtins.open", mock_open()):
                with patch.object(Path, "mkdir"):
                    with patch.object(Path, "chmod"):
                        with patch("os.remove") as mock_remove:
                            with pytest.raises(KeyPairManagerError, match="import_key_pair failed"):
                                manager._generate_and_import_key_pair(
                                    mock_aws_credential, mock_ec2_client
                                )

                            # Verify cleanup was attempted
                            mock_remove.assert_called_once()

    def test_generate_and_import_key_pair_write_fails(
        self, manager, mock_aws_credential, mock_ec2_client
    ):
        """Test _generate_and_import_key_pair handles write failure"""
        with patch("services.key_pair_manager._generate_rsa_key_pair") as mock_generate:
            mock_generate.return_value = ("private_key_pem", b"public_key_openssh")

            with patch("builtins.open", side_effect=OSError("Permission denied")):
                with patch.object(Path, "mkdir"):
                    with pytest.raises(KeyPairManagerError, match="Failed to write private key"):
                        manager._generate_and_import_key_pair(
                            mock_aws_credential, mock_ec2_client
                        )

    def test_write_private_key(self, manager):
        """Test _write_private_key writes content to file"""
        test_path = Path("/tmp/test.pem")
        test_content = "-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----"

        with patch("builtins.open", mock_open()) as mock_file:
            manager._write_private_key(test_path, test_content)

            mock_file.assert_called_once_with(test_path, "w", encoding="ascii")
            mock_file().write.assert_called_once_with(test_content)

    def test_build_rate_limiter(self, manager):
        """Test _build_rate_limiter creates rate limiter with correct settings"""
        rate_limiter = manager._build_rate_limiter()

        # Verify rate limiter was created (basic check)
        assert rate_limiter is not None

    def test_generate_rsa_key_pair(self):
        """Test _generate_rsa_key_pair generates valid key pair"""
        from services.key_pair_manager import _generate_rsa_key_pair

        private_key_pem, public_key_openssh = _generate_rsa_key_pair()

        # Verify private key format
        assert isinstance(private_key_pem, str)
        assert "BEGIN" in private_key_pem
        assert "PRIVATE KEY" in private_key_pem

        # Verify public key format
        assert isinstance(public_key_openssh, bytes)
        assert public_key_openssh.startswith(b"ssh-rsa ")

    def test_build_key_name(self):
        """Test _build_key_name function"""
        from services.key_pair_manager import _build_key_name

        key_name = _build_key_name("123456789012")
        assert key_name == "123456789012"

    def test_ensure_key_pair_tags(self, manager, mock_aws_credential, mock_ec2_client):
        """Test that ensure_key_pair_for_account adds correct tags"""
        error_response = {"Error": {"Code": "InvalidKeyPair.NotFound"}}
        mock_ec2_client.describe_key_pairs.side_effect = ClientError(error_response, "describe_key_pairs")
        mock_ec2_client.import_key_pair.return_value = {"KeyPairId": "key-12345"}

        with patch("services.key_pair_manager._generate_rsa_key_pair") as mock_generate:
            mock_generate.return_value = ("private_key_pem", b"public_key_openssh")

            with patch("builtins.open", mock_open()):
                with patch.object(Path, "mkdir"):
                    with patch.object(Path, "chmod"):
                        manager.ensure_key_pair_for_account(mock_aws_credential, mock_ec2_client)

        # Verify tags were included in import_key_pair call
        call_args = mock_ec2_client.import_key_pair.call_args
        tag_specs = call_args[1]["TagSpecifications"]
        assert len(tag_specs) == 1
        assert tag_specs[0]["ResourceType"] == "key-pair"

        tags = {tag["Key"]: tag["Value"] for tag in tag_specs[0]["Tags"]}
        assert tags["CreatedBy"] == "ShadowFleet"
        assert tags["AccountId"] == "123456789012"
        assert tags["Region"] == "us-east-1"

    def test_rate_limiter_acquire_called(self, manager, mock_aws_credential, mock_ec2_client):
        """Test that rate limiter is used when generating key pair"""
        error_response = {"Error": {"Code": "InvalidKeyPair.NotFound"}}
        mock_ec2_client.describe_key_pairs.side_effect = ClientError(error_response, "describe_key_pairs")
        mock_ec2_client.import_key_pair.return_value = {"KeyPairId": "key-12345"}

        with patch("services.key_pair_manager._generate_rsa_key_pair") as mock_generate:
            mock_generate.return_value = ("private_key_pem", b"public_key_openssh")

            with patch("builtins.open", mock_open()):
                with patch.object(Path, "mkdir"):
                    with patch.object(Path, "chmod"):
                        with patch.object(manager._rate_limiter, "acquire") as mock_acquire:
                            manager.ensure_key_pair_for_account(mock_aws_credential, mock_ec2_client)

                            mock_acquire.assert_called_once()

    def test_key_pair_manager_error_inheritance(self):
        """Test that KeyPairManagerError is an Exception"""
        error = KeyPairManagerError("test error")
        assert isinstance(error, Exception)
        assert str(error) == "test error"

    def test_ensure_key_pair_logs_found(self, manager, mock_aws_credential, mock_ec2_client, mock_runtime_context):
        """Test logging when key pair is found"""
        mock_ec2_client.describe_key_pairs.return_value = {"KeyPairs": [{"KeyName": "123456789012"}]}
        logger = mock_runtime_context.logger.getChild.return_value

        manager.ensure_key_pair_for_account(mock_aws_credential, mock_ec2_client)

        logger.info.assert_called()
        call_args = logger.info.call_args[0]
        assert "already exists" in call_args[0]

    def test_ensure_key_pair_logs_imported(self, manager, mock_aws_credential, mock_ec2_client, mock_runtime_context):
        """Test logging when key pair is imported"""
        error_response = {"Error": {"Code": "InvalidKeyPair.NotFound"}}
        mock_ec2_client.describe_key_pairs.side_effect = ClientError(error_response, "describe_key_pairs")
        mock_ec2_client.import_key_pair.return_value = {"KeyPairId": "key-12345"}
        logger = mock_runtime_context.logger.getChild.return_value

        with patch("services.key_pair_manager._generate_rsa_key_pair") as mock_generate:
            mock_generate.return_value = ("private_key_pem", b"public_key_openssh")

            with patch("builtins.open", mock_open()):
                with patch.object(Path, "mkdir"):
                    with patch.object(Path, "chmod"):
                        manager.ensure_key_pair_for_account(mock_aws_credential, mock_ec2_client)

        # Check that import success was logged
        info_calls = [call[0][0] for call in logger.info.call_args_list]
        assert any("Imported KeyPair" in msg for msg in info_calls)
