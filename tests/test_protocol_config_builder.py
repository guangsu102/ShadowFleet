"""
Tests for ProtocolConfigBuilder service
"""
import pytest

from services.protocol_config_builder import ProtocolConfigBuilder


class TestProtocolConfigBuilder:
    """Test ProtocolConfigBuilder"""

    def test_build_anytls_config_default(self):
        """Test building AnyTLS config with default values"""
        config = ProtocolConfigBuilder.build_anytls_config()

        assert "padding_scheme" in config
        assert isinstance(config["padding_scheme"], list)
        assert len(config["padding_scheme"]) == 9
        assert config["padding_scheme"][0] == "stop=8"

        assert "tls" in config
        assert config["tls"]["server_name"] == "www.bilibili.com"
        assert config["tls"]["allow_insecure"] is True

    def test_build_anytls_config_custom_sni(self):
        """Test building AnyTLS config with custom SNI domain"""
        config = ProtocolConfigBuilder.build_anytls_config(
            sni_domain="custom.example.com"
        )

        assert config["tls"]["server_name"] == "custom.example.com"
        assert config["tls"]["allow_insecure"] is True

    def test_build_anytls_config_custom_allow_insecure(self):
        """Test building AnyTLS config with custom allow_insecure"""
        config = ProtocolConfigBuilder.build_anytls_config(
            allow_insecure=False
        )

        assert config["tls"]["server_name"] == "www.bilibili.com"
        assert config["tls"]["allow_insecure"] is False

    def test_build_trojan_config_default(self):
        """Test building Trojan config with default values"""
        config = ProtocolConfigBuilder.build_trojan_config()

        assert "tls" in config
        assert config["tls"]["server_name"] == "www.bilibili.com"
        assert config["tls"]["allow_insecure"] is True
        assert config["network"] == "grpc"
        assert "grpc" in config
        assert config["grpc"]["serviceName"] == ""

    def test_build_trojan_config_custom_network_ws(self):
        """Test building Trojan config with websocket network"""
        config = ProtocolConfigBuilder.build_trojan_config(network="ws")

        assert config["network"] == "ws"
        assert "grpc" not in config

    def test_build_trojan_config_custom_network_tcp(self):
        """Test building Trojan config with TCP network"""
        config = ProtocolConfigBuilder.build_trojan_config(network="tcp")

        assert config["network"] == "tcp"
        assert "grpc" not in config

    def test_build_trojan_config_custom_sni(self):
        """Test building Trojan config with custom SNI"""
        config = ProtocolConfigBuilder.build_trojan_config(
            sni_domain="trojan.example.com",
            allow_insecure=False
        )

        assert config["tls"]["server_name"] == "trojan.example.com"
        assert config["tls"]["allow_insecure"] is False

    def test_build_vmess_config_default(self):
        """Test building VMess config with default values"""
        config = ProtocolConfigBuilder.build_vmess_config()

        assert config["tls"] is True
        assert config["network"] == "grpc"
        assert "grpc" in config
        assert config["grpc"]["serviceName"] == ""

    def test_build_vmess_config_no_tls(self):
        """Test building VMess config without TLS"""
        config = ProtocolConfigBuilder.build_vmess_config(tls_enabled=False)

        assert config["tls"] is False
        assert config["network"] == "grpc"

    def test_build_vmess_config_custom_network(self):
        """Test building VMess config with custom network"""
        config = ProtocolConfigBuilder.build_vmess_config(
            tls_enabled=True,
            network="ws"
        )

        assert config["tls"] is True
        assert config["network"] == "ws"
        assert "grpc" not in config

    def test_build_vless_config_default(self):
        """Test building VLESS config with default values"""
        config = ProtocolConfigBuilder.build_vless_config()

        assert "tls" in config
        assert config["tls"]["server_name"] == "www.bilibili.com"
        assert config["tls"]["allow_insecure"] is True
        assert config["network"] == "grpc"
        assert config["flow"] == "xtls-rprx-vision"
        assert "reality" in config
        assert config["reality"]["enabled"] is True
        assert config["reality"]["dest"] == "www.bilibili.com"
        assert config["reality"]["private_key"] == ""
        assert config["reality"]["public_key"] == ""
        assert "grpc" in config

    def test_build_vless_config_custom_reality_keys(self):
        """Test building VLESS config with custom Reality keys"""
        config = ProtocolConfigBuilder.build_vless_config(
            reality_private_key="test_private_key",
            reality_public_key="test_public_key"
        )

        assert config["reality"]["private_key"] == "test_private_key"
        assert config["reality"]["public_key"] == "test_public_key"

    def test_build_vless_config_custom_reality_dest(self):
        """Test building VLESS config with custom Reality dest"""
        config = ProtocolConfigBuilder.build_vless_config(
            sni_domain="vless.example.com",
            reality_dest="reality.example.com"
        )

        assert config["tls"]["server_name"] == "vless.example.com"
        assert config["reality"]["dest"] == "reality.example.com"

    def test_build_vless_config_reality_dest_defaults_to_sni(self):
        """Test that reality_dest defaults to sni_domain"""
        config = ProtocolConfigBuilder.build_vless_config(
            sni_domain="vless.example.com"
        )

        assert config["reality"]["dest"] == "vless.example.com"

    def test_build_vless_config_no_reality(self):
        """Test building VLESS config without Reality"""
        config = ProtocolConfigBuilder.build_vless_config(reality_enabled=False)

        assert "reality" not in config

    def test_build_vless_config_custom_network(self):
        """Test building VLESS config with custom network"""
        config = ProtocolConfigBuilder.build_vless_config(network="tcp")

        assert config["network"] == "tcp"
        assert "grpc" not in config

    def test_build_protocol_config_anytls(self):
        """Test building protocol config for AnyTLS"""
        config = ProtocolConfigBuilder.build_protocol_config(
            "AnyTLS",
            sni_domain="test.example.com"
        )

        assert config["tls"]["server_name"] == "test.example.com"
        assert "padding_scheme" in config

    def test_build_protocol_config_trojan(self):
        """Test building protocol config for Trojan"""
        config = ProtocolConfigBuilder.build_protocol_config(
            "Trojan",
            network="ws"
        )

        assert config["network"] == "ws"
        assert "tls" in config

    def test_build_protocol_config_vmess(self):
        """Test building protocol config for VMess"""
        config = ProtocolConfigBuilder.build_protocol_config(
            "vmess",
            tls_enabled=False
        )

        assert config["tls"] is False

    def test_build_protocol_config_vless(self):
        """Test building protocol config for VLESS"""
        config = ProtocolConfigBuilder.build_protocol_config(
            "vless",
            reality_enabled=False
        )

        assert "reality" not in config

    def test_build_protocol_config_case_insensitive(self):
        """Test that protocol type is case-insensitive"""
        config1 = ProtocolConfigBuilder.build_protocol_config("ANYTLS")
        config2 = ProtocolConfigBuilder.build_protocol_config("anytls")
        config3 = ProtocolConfigBuilder.build_protocol_config("AnyTLS")

        assert config1 == config2 == config3

    def test_build_protocol_config_unknown_protocol(self):
        """Test building protocol config for unknown protocol"""
        config = ProtocolConfigBuilder.build_protocol_config("unknown")

        assert config == {}

    def test_merge_protocol_config_simple(self):
        """Test merging protocol configs with simple values"""
        base = {"key1": "value1", "key2": "value2"}
        override = {"key2": "override2", "key3": "value3"}

        merged = ProtocolConfigBuilder.merge_protocol_config(base, override)

        assert merged["key1"] == "value1"
        assert merged["key2"] == "override2"
        assert merged["key3"] == "value3"

    def test_merge_protocol_config_nested(self):
        """Test merging protocol configs with nested dicts"""
        base = {
            "tls": {
                "server_name": "base.example.com",
                "allow_insecure": True
            },
            "network": "grpc"
        }
        override = {
            "tls": {
                "server_name": "override.example.com"
            }
        }

        merged = ProtocolConfigBuilder.merge_protocol_config(base, override)

        assert merged["tls"]["server_name"] == "override.example.com"
        assert merged["tls"]["allow_insecure"] is True
        assert merged["network"] == "grpc"

    def test_merge_protocol_config_none_override(self):
        """Test merging with None override returns base"""
        base = {"key1": "value1"}

        merged = ProtocolConfigBuilder.merge_protocol_config(base, None)

        assert merged == base

    def test_merge_protocol_config_deep_nested(self):
        """Test merging deeply nested configs"""
        base = {
            "level1": {
                "level2": {
                    "key1": "value1",
                    "key2": "value2"
                }
            }
        }
        override = {
            "level1": {
                "level2": {
                    "key2": "override2"
                }
            }
        }

        merged = ProtocolConfigBuilder.merge_protocol_config(base, override)

        assert merged["level1"]["level2"]["key1"] == "value1"
        assert merged["level1"]["level2"]["key2"] == "override2"

    def test_merge_protocol_config_override_with_non_dict(self):
        """Test merging when override value is not a dict"""
        base = {
            "tls": {
                "server_name": "base.example.com"
            }
        }
        override = {
            "tls": "simple_string"
        }

        merged = ProtocolConfigBuilder.merge_protocol_config(base, override)

        assert merged["tls"] == "simple_string"

    def test_default_sni_domains_list(self):
        """Test that DEFAULT_SNI_DOMAINS is properly defined"""
        assert len(ProtocolConfigBuilder.DEFAULT_SNI_DOMAINS) >= 4
        assert "www.bilibili.com" in ProtocolConfigBuilder.DEFAULT_SNI_DOMAINS
        assert "api.bilibili.com" in ProtocolConfigBuilder.DEFAULT_SNI_DOMAINS
        assert "www.microsoft.com" in ProtocolConfigBuilder.DEFAULT_SNI_DOMAINS
        assert "www.cloudflare.com" in ProtocolConfigBuilder.DEFAULT_SNI_DOMAINS
