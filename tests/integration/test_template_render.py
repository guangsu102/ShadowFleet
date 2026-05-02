"""Integration tests for template rendering output validation."""

from __future__ import annotations

import json


from utils.template_engine import render_user_data
from utils.template_models import (
    UserDataRenderRequest,
    V2bxCertConfig,
    UNRESOLVED_PLACEHOLDER_PATTERN,
)


def create_render_request(**overrides) -> UserDataRenderRequest:
    """Create a valid render request for testing."""
    defaults = {
        "asset_provider": "aws",
        "protocol_type": "AnyTLS",
        "node_name": "test-node",
        "xboard_api_host": "https://panel.example.com",
        "xboard_api_key": "test_api_key",
        "xboard_node_id": 12345,
        "server_host": "sf-12345.example.com",
        "correlation_id": "test-correlation-id",
        "domain_name": "sf-12345.example.com",
        "cert_config": V2bxCertConfig(cert_mode="none"),
    }
    defaults.update(overrides)
    return UserDataRenderRequest(**defaults)


class TestUserDataScriptSyntax:
    """Tests for User-Data script syntax correctness."""

    def test_script_starts_with_shebang(self) -> None:
        """Generated script should start with bash shebang."""
        request = create_render_request()
        result = render_user_data(request)
        assert result.user_data.startswith("#!/bin/bash")

    def test_script_has_set_euo_pipefail(self) -> None:
        """Script should have set -euo pipefail for safety."""
        request = create_render_request()
        result = render_user_data(request)
        assert "set -euo pipefail" in result.user_data

    def test_script_has_log_function(self) -> None:
        """Script should define log function."""
        request = create_render_request()
        result = render_user_data(request)
        assert "log()" in result.user_data
        assert 'printf' in result.user_data

    def test_script_has_cleanup_trap(self) -> None:
        """Script should have cleanup trap."""
        request = create_render_request()
        result = render_user_data(request)
        assert "trap cleanup EXIT" in result.user_data

    def test_script_has_v2bx_install_section(self) -> None:
        """Script should have V2bX installation section."""
        request = create_render_request()
        result = render_user_data(request)
        assert "V2bX" in result.user_data
        assert "install" in result.user_data.lower()

    def test_script_has_callback_section(self) -> None:
        """Script should have ready callback section."""
        request = create_render_request(
            ready_callback_url="https://callback.example.com/ready",
            ready_callback_token="test_token",
        )
        result = render_user_data(request)
        assert "send_ready_callback" in result.user_data
        assert "curl" in result.user_data

    def test_script_no_unresolved_placeholders(self) -> None:
        """Script should have no unresolved __PLACEHOLDER__ patterns."""
        request = create_render_request()
        result = render_user_data(request)

        unresolved = UNRESOLVED_PLACEHOLDER_PATTERN.findall(result.user_data)
        assert len(unresolved) == 0, f"Found unresolved placeholders: {unresolved}"


class TestV2bxConfigJson:
    """Tests for V2bX configuration JSON validity."""

    def test_config_json_is_valid(self) -> None:
        """V2bX config should be valid JSON."""
        request = create_render_request()
        result = render_user_data(request)

        config = json.loads(result.v2bx_config_json)
        assert isinstance(config, dict)

    def test_config_has_required_keys(self) -> None:
        """V2bX config should have required top-level keys."""
        request = create_render_request()
        result = render_user_data(request)

        config = json.loads(result.v2bx_config_json)
        assert "Log" in config
        assert "Cores" in config
        assert "Nodes" in config

    def test_config_log_level(self) -> None:
        """V2bX config Log level should match request."""
        request = create_render_request(log_level="warn")
        result = render_user_data(request)

        config = json.loads(result.v2bx_config_json)
        assert config["Log"]["Level"] == "warn"

    def test_config_node_name(self) -> None:
        """V2bX config should contain correct node name."""
        request = create_render_request(node_name="my-test-node")
        result = render_user_data(request)

        config = json.loads(result.v2bx_config_json)
        assert config["Nodes"][0]["Name"] == "my-test-node"

    def test_config_node_id(self) -> None:
        """V2bX config should contain correct node ID."""
        request = create_render_request(xboard_node_id=99999)
        result = render_user_data(request)

        config = json.loads(result.v2bx_config_json)
        assert config["Nodes"][0]["NodeID"] == 99999

    def test_config_api_host(self) -> None:
        """V2bX config should contain API host."""
        request = create_render_request(xboard_api_host="https://my.panel.com")
        result = render_user_data(request)

        config = json.loads(result.v2bx_config_json)
        assert config["Nodes"][0]["ApiHost"] == "https://my.panel.com"

    def test_config_cert_mode_none(self) -> None:
        """Cert mode 'none' should be properly configured."""
        request = create_render_request(
            cert_config=V2bxCertConfig(cert_mode="none")
        )
        result = render_user_data(request)

        config = json.loads(result.v2bx_config_json)
        assert config["Nodes"][0]["CertConfig"]["CertMode"] == "none"

    def test_config_cert_mode_dns(self) -> None:
        """Cert mode 'dns' should include provider settings."""
        request = create_render_request(
            cert_config=V2bxCertConfig(
                cert_mode="dns",
                provider="cloudflare",
                cert_domain="example.com",
                dns_env={"CLOUDFLARE_EMAIL": "test@example.com"},
            )
        )
        result = render_user_data(request)

        config = json.loads(result.v2bx_config_json)
        cert_config = config["Nodes"][0]["CertConfig"]
        assert cert_config["CertMode"] == "dns"
        assert cert_config["Provider"] == "cloudflare"
        assert cert_config["CertDomain"] == "example.com"


class TestProtocolSpecificRendering:
    """Tests for protocol-specific rendering behavior."""

    def test_anytls_uses_sing_core(self) -> None:
        """AnyTLS should use sing core."""
        request = create_render_request(protocol_type="AnyTLS")
        result = render_user_data(request)

        config = json.loads(result.v2bx_config_json)
        assert config["Cores"][0]["Type"] == "sing"
        assert "sing_origin" in result.user_data

    def test_trojan_uses_xray_core(self) -> None:
        """Trojan should use xray core."""
        request = create_render_request(protocol_type="Trojan")
        result = render_user_data(request)

        config = json.loads(result.v2bx_config_json)
        assert config["Cores"][0]["Type"] == "xray"

    def test_vless_uses_xray_core(self) -> None:
        """VLESS should use xray core."""
        request = create_render_request(protocol_type="vless")
        result = render_user_data(request)

        config = json.loads(result.v2bx_config_json)
        assert config["Cores"][0]["Type"] == "xray"

    def test_vmess_uses_xray_core(self) -> None:
        """VMess should use xray core."""
        request = create_render_request(protocol_type="vmess")
        result = render_user_data(request)

        config = json.loads(result.v2bx_config_json)
        assert config["Cores"][0]["Type"] == "xray"

    def test_hysteria2_uses_sing_core(self) -> None:
        """Hysteria2 should use sing core and no DNS."""
        request = create_render_request(
            asset_provider="self_hosted",
            protocol_type="Hysteria2",
            domain_name=None,
        )
        result = render_user_data(request)

        config = json.loads(result.v2bx_config_json)
        assert config["Cores"][0]["Type"] == "sing"
        assert "sing_origin" in result.user_data


class TestScriptContentVerification:
    """Tests for specific script content verification."""

    def test_install_script_url_present(self) -> None:
        """V2bX install script URL should be in output."""
        request = create_render_request()
        result = render_user_data(request)
        assert "https://raw.githubusercontent.com/wyx2685/V2bX-script/master/install.sh" in result.user_data

    def test_node_id_injected(self) -> None:
        """Node ID should be injected into callback payload."""
        request = create_render_request(
            xboard_node_id=54321,
            ready_callback_url="https://callback.example.com",
            ready_callback_token="token123",
        )
        result = render_user_data(request)
        assert "54321" in result.user_data

    def test_correlation_id_in_callback(self) -> None:
        """Correlation ID should appear in callback payload."""
        request = create_render_request(
            correlation_id="corr-abc-123",
            ready_callback_url="https://callback.example.com",
            ready_callback_token="token123",
        )
        result = render_user_data(request)
        assert "corr-abc-123" in result.user_data

    def test_sudo_used_for_v2bx(self) -> None:
        """Script should use sudo for V2bX operations."""
        request = create_render_request()
        result = render_user_data(request)
        assert "sudo" in result.user_data

    def test_systemctl_for_v2bx_service(self) -> None:
        """Script should use systemctl for V2bX service."""
        request = create_render_request()
        result = render_user_data(request)
        assert "systemctl" in result.user_data
        assert "V2bX" in result.user_data
