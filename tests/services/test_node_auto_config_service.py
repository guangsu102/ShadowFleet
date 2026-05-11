"""
Tests for NodeAutoConfigService
"""
from unittest.mock import MagicMock, patch

import pytest

from services.node_auto_config_service import NodeAutoConfigService


@pytest.fixture
def mock_runtime_context():
    """Create a mock runtime context"""
    context = MagicMock()
    context.logger = MagicMock()
    context.logger.getChild.return_value = MagicMock()
    return context


@pytest.fixture
def service(mock_runtime_context):
    """Create NodeAutoConfigService instance"""
    return NodeAutoConfigService(mock_runtime_context)


class TestNodeAutoConfigService:
    """Tests for NodeAutoConfigService"""

    def test_init(self, mock_runtime_context):
        """Test service initialization"""
        service = NodeAutoConfigService(mock_runtime_context)
        assert service._runtime_context == mock_runtime_context
        mock_runtime_context.logger.getChild.assert_called_once_with("services.node_auto_config")

    def test_auto_configure_node_anytls(self, service):
        """Test auto-configuring an AnyTLS node"""
        with patch('database.xboard_repo.XboardRepo') as mock_xboard_repo_class, \
             patch('services.node_id_generator.NodeIdGenerator') as mock_node_id_gen_class:

            # Setup mocks
            mock_xboard_repo = MagicMock()
            mock_xboard_repo_class.return_value = mock_xboard_repo

            mock_node_id_gen = MagicMock()
            mock_node_id_gen.generate_node_id.return_value = "test-node-id"
            mock_node_id_gen_class.return_value = mock_node_id_gen

            # Execute
            service.auto_configure_node(
                xboard_node_id=123,
                protocol_type="anytls",
                sni_domain="example.com"
            )

            # Verify node ID generation
            mock_node_id_gen.generate_node_id.assert_called_once_with("anytls", 123)
            mock_xboard_repo.update_node_code.assert_called_once_with(123, "test-node-id")

            # Verify protocol settings update
            mock_xboard_repo.update_node_protocol_settings.assert_called_once()
            settings = mock_xboard_repo.update_node_protocol_settings.call_args[0][1]
            assert settings["tls"]["server_name"] == "example.com"
            assert settings["tls"]["allow_insecure"] is True

    def test_auto_configure_node_vless_generates_keys(self, service):
        """Test auto-configuring a VLESS node generates Reality keys if not provided"""
        with patch('database.xboard_repo.XboardRepo') as mock_xboard_repo_class, \
             patch('services.node_id_generator.NodeIdGenerator') as mock_node_id_gen_class, \
             patch('services.reality_key_generator.RealityKeyGenerator') as mock_reality_gen_class:

            # Setup mocks
            mock_xboard_repo = MagicMock()
            mock_xboard_repo_class.return_value = mock_xboard_repo

            mock_node_id_gen = MagicMock()
            mock_node_id_gen.generate_node_id.return_value = "vless-node-id"
            mock_node_id_gen_class.return_value = mock_node_id_gen

            mock_reality_gen_class.generate_key_pair.return_value = ("private-key", "public-key")

            # Execute
            service.auto_configure_node(
                xboard_node_id=456,
                protocol_type="vless"
            )

            # Verify Reality key generation
            mock_reality_gen_class.generate_key_pair.assert_called_once()

            # Verify protocol settings include generated keys
            mock_xboard_repo.update_node_protocol_settings.assert_called_once()
            settings = mock_xboard_repo.update_node_protocol_settings.call_args[0][1]
            assert settings["reality"]["private_key"] == "private-key"
            assert settings["reality"]["public_key"] == "public-key"

    def test_auto_configure_node_vless_uses_provided_keys(self, service):
        """Test auto-configuring a VLESS node uses provided Reality keys"""
        with patch('database.xboard_repo.XboardRepo') as mock_xboard_repo_class, \
             patch('services.node_id_generator.NodeIdGenerator') as mock_node_id_gen_class, \
             patch('services.reality_key_generator.RealityKeyGenerator') as mock_reality_gen_class:

            # Setup mocks
            mock_xboard_repo = MagicMock()
            mock_xboard_repo_class.return_value = mock_xboard_repo

            mock_node_id_gen = MagicMock()
            mock_node_id_gen.generate_node_id.return_value = "vless-node-id"
            mock_node_id_gen_class.return_value = mock_node_id_gen

            # Execute with provided keys
            service.auto_configure_node(
                xboard_node_id=789,
                protocol_type="vless",
                reality_private_key="provided-private",
                reality_public_key="provided-public"
            )

            # Verify Reality key generation was NOT called
            mock_reality_gen_class.generate_key_pair.assert_not_called()

            # Verify protocol settings use provided keys
            mock_xboard_repo.update_node_protocol_settings.assert_called_once()
            settings = mock_xboard_repo.update_node_protocol_settings.call_args[0][1]
            assert settings["reality"]["private_key"] == "provided-private"
            assert settings["reality"]["public_key"] == "provided-public"

    def test_auto_configure_node_with_protocol_settings(self, service):
        """Test auto-configuring a node with user-provided protocol settings"""
        with patch('database.xboard_repo.XboardRepo') as mock_xboard_repo_class, \
             patch('services.node_id_generator.NodeIdGenerator') as mock_node_id_gen_class:

            # Setup mocks
            mock_xboard_repo = MagicMock()
            mock_xboard_repo_class.return_value = mock_xboard_repo

            mock_node_id_gen = MagicMock()
            mock_node_id_gen.generate_node_id.return_value = "custom-node-id"
            mock_node_id_gen_class.return_value = mock_node_id_gen

            custom_settings = {"custom": "settings"}

            # Execute
            service.auto_configure_node(
                xboard_node_id=999,
                protocol_type="trojan",
                protocol_settings=custom_settings
            )

            # Verify node ID generation
            mock_node_id_gen.generate_node_id.assert_called_once_with("trojan", 999)
            mock_xboard_repo.update_node_code.assert_called_once_with(999, "custom-node-id")

            # Verify protocol settings were NOT auto-generated
            mock_xboard_repo.update_node_protocol_settings.assert_not_called()

    def test_auto_configure_node_trojan(self, service):
        """Test auto-configuring a Trojan node"""
        with patch('database.xboard_repo.XboardRepo') as mock_xboard_repo_class, \
             patch('services.node_id_generator.NodeIdGenerator') as mock_node_id_gen_class:

            # Setup mocks
            mock_xboard_repo = MagicMock()
            mock_xboard_repo_class.return_value = mock_xboard_repo

            mock_node_id_gen = MagicMock()
            mock_node_id_gen.generate_node_id.return_value = "trojan-id"
            mock_node_id_gen_class.return_value = mock_node_id_gen

            # Execute
            service.auto_configure_node(
                xboard_node_id=111,
                protocol_type="trojan",
                sni_domain="trojan.example.com",
                network="ws"
            )

            # Verify protocol settings
            mock_xboard_repo.update_node_protocol_settings.assert_called_once()
            settings = mock_xboard_repo.update_node_protocol_settings.call_args[0][1]
            assert settings["tls"]["server_name"] == "trojan.example.com"
            assert settings["network"] == "ws"

    def test_auto_configure_node_vmess(self, service):
        """Test auto-configuring a VMess node"""
        with patch('database.xboard_repo.XboardRepo') as mock_xboard_repo_class, \
             patch('services.node_id_generator.NodeIdGenerator') as mock_node_id_gen_class:

            # Setup mocks
            mock_xboard_repo = MagicMock()
            mock_xboard_repo_class.return_value = mock_xboard_repo

            mock_node_id_gen = MagicMock()
            mock_node_id_gen.generate_node_id.return_value = "vmess-id"
            mock_node_id_gen_class.return_value = mock_node_id_gen

            # Execute
            service.auto_configure_node(
                xboard_node_id=222,
                protocol_type="vmess",
                network="grpc"
            )

            # Verify protocol settings
            mock_xboard_repo.update_node_protocol_settings.assert_called_once()
            settings = mock_xboard_repo.update_node_protocol_settings.call_args[0][1]
            assert settings["tls"] is True
            assert settings["network"] == "grpc"

    def test_build_protocol_settings_anytls(self, service):
        """Test building AnyTLS protocol settings"""
        settings = service._build_protocol_settings(
            protocol_type="anytls",
            sni_domain="test.com",
            reality_private_key=None,
            reality_public_key=None,
            reality_dest=None,
            allow_insecure=False,
            network="tcp",
            flow=None
        )

        assert settings is not None
        assert settings["tls"]["server_name"] == "test.com"
        assert settings["tls"]["allow_insecure"] is False

    def test_build_protocol_settings_trojan(self, service):
        """Test building Trojan protocol settings"""
        settings = service._build_protocol_settings(
            protocol_type="trojan",
            sni_domain="trojan.test.com",
            reality_private_key=None,
            reality_public_key=None,
            reality_dest=None,
            allow_insecure=True,
            network="ws",
            flow=None
        )

        assert settings is not None
        assert settings["tls"]["server_name"] == "trojan.test.com"
        assert settings["tls"]["allow_insecure"] is True
        assert settings["network"] == "ws"

    def test_build_protocol_settings_vmess(self, service):
        """Test building VMess protocol settings"""
        settings = service._build_protocol_settings(
            protocol_type="vmess",
            sni_domain=None,
            reality_private_key=None,
            reality_public_key=None,
            reality_dest=None,
            allow_insecure=True,
            network="grpc",
            flow=None
        )

        assert settings is not None
        assert settings["tls"] is True
        assert settings["network"] == "grpc"

    def test_build_protocol_settings_vless(self, service):
        """Test building VLESS protocol settings"""
        settings = service._build_protocol_settings(
            protocol_type="vless",
            sni_domain="vless.test.com",
            reality_private_key="priv-key",
            reality_public_key="pub-key",
            reality_dest="dest.com",
            allow_insecure=False,
            network="grpc",
            flow="xtls-rprx-vision"
        )

        assert settings is not None
        assert settings["tls"]["server_name"] == "vless.test.com"
        assert settings["network"] == "grpc"
        assert settings["flow"] == "xtls-rprx-vision"
        assert settings["reality"]["enabled"] is True
        assert settings["reality"]["dest"] == "dest.com"
        assert settings["reality"]["private_key"] == "priv-key"
        assert settings["reality"]["public_key"] == "pub-key"

    def test_build_protocol_settings_vless_defaults(self, service):
        """Test building VLESS protocol settings with defaults"""
        settings = service._build_protocol_settings(
            protocol_type="vless",
            sni_domain=None,
            reality_private_key="priv",
            reality_public_key="pub",
            reality_dest=None,
            allow_insecure=True,
            network="tcp",
            flow=None
        )

        assert settings is not None
        assert settings["tls"]["server_name"] == "www.bilibili.com"  # default
        assert settings["flow"] == "xtls-rprx-vision"  # default
        assert settings["reality"]["dest"] == "www.bilibili.com"  # default

    def test_build_protocol_settings_unknown_protocol(self, service):
        """Test building settings for unknown protocol returns None"""
        settings = service._build_protocol_settings(
            protocol_type="unknown",
            sni_domain=None,
            reality_private_key=None,
            reality_public_key=None,
            reality_dest=None,
            allow_insecure=True,
            network="tcp",
            flow=None
        )

        assert settings is None

    def test_get_default_group_ids(self, service):
        """Test getting default group IDs"""
        with patch('database.xboard_repo.XboardRepo') as mock_xboard_repo_class:
            # Setup mock
            mock_xboard_repo = MagicMock()
            mock_xboard_repo.get_all_group_ids.return_value = [1, 2, 3]
            mock_xboard_repo_class.return_value = mock_xboard_repo

            # Execute
            group_ids = service.get_default_group_ids()

            # Verify
            assert group_ids == [1, 2, 3]
            mock_xboard_repo.get_all_group_ids.assert_called_once()

    def test_build_protocol_settings_case_insensitive(self, service):
        """Test protocol type is case-insensitive"""
        settings_lower = service._build_protocol_settings(
            protocol_type="anytls",
            sni_domain="test.com",
            reality_private_key=None,
            reality_public_key=None,
            reality_dest=None,
            allow_insecure=True,
            network="tcp",
            flow=None
        )

        settings_upper = service._build_protocol_settings(
            protocol_type="ANYTLS",
            sni_domain="test.com",
            reality_private_key=None,
            reality_public_key=None,
            reality_dest=None,
            allow_insecure=True,
            network="tcp",
            flow=None
        )

        settings_mixed = service._build_protocol_settings(
            protocol_type="AnyTLS",
            sni_domain="test.com",
            reality_private_key=None,
            reality_public_key=None,
            reality_dest=None,
            allow_insecure=True,
            network="tcp",
            flow=None
        )

        assert settings_lower == settings_upper == settings_mixed
