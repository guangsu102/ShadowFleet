"""Unit tests for utils.template_engine module."""

from __future__ import annotations

import pytest

from utils.template_engine import (
    RenderedUserData,
    UserDataRenderError,
    render_user_data,
)
from utils.template_models import (
    UserDataRenderRequest,
    get_protocol_capabilities,
)


def create_valid_request(**overrides) -> UserDataRenderRequest:
    """Create a valid render request with defaults that can be overridden."""
    defaults = {
        "asset_provider": "aws",
        "protocol_type": "AnyTLS",
        "node_name": "test-node",
        "xboard_api_host": "https://panel.example.com",
        "xboard_api_key": "test_api_key_12345",
        "xboard_node_id": 12345,
        "server_host": "sf-12345.example.com",
        "correlation_id": "test-correlation-id-001",
        "domain_name": "sf-12345.example.com",
    }
    defaults.update(overrides)
    return UserDataRenderRequest(**defaults)


class TestGetProtocolCapabilities:
    """Tests for get_protocol_capabilities function."""

    def test_anytls_capabilities(self) -> None:
        """AnyTLS should have correct capabilities."""
        caps = get_protocol_capabilities("AnyTLS")
        assert caps.protocol_type == "AnyTLS"
        assert caps.v2bx_node_type == "anytls"
        assert caps.core_type == "sing"
        assert caps.requires_dns_record is True
        assert caps.supports_cdn_proxy is False
        assert "aws" in caps.supported_asset_providers
        assert "self_hosted" in caps.supported_asset_providers
        assert caps.enable_tfo is False

    def test_trojan_capabilities(self) -> None:
        """Trojan should have correct capabilities."""
        caps = get_protocol_capabilities("Trojan")
        assert caps.protocol_type == "Trojan"
        assert caps.v2bx_node_type == "trojan"
        assert caps.core_type == "xray"
        assert caps.requires_dns_record is True
        assert caps.supports_cdn_proxy is True
        assert caps.enable_tfo is True

    def test_vless_capabilities(self) -> None:
        """VLESS should have correct capabilities."""
        caps = get_protocol_capabilities("vless")
        assert caps.protocol_type == "vless"
        assert caps.v2bx_node_type == "vless"
        assert caps.core_type == "xray"
        assert caps.enable_tfo is True

    def test_vmess_capabilities(self) -> None:
        """VMess should have correct capabilities."""
        caps = get_protocol_capabilities("vmess")
        assert caps.protocol_type == "vmess"
        assert caps.v2bx_node_type == "vmess"
        assert caps.core_type == "xray"

    def test_hysteria2_capabilities(self) -> None:
        """Hysteria2 should only support self_hosted."""
        caps = get_protocol_capabilities("Hysteria2")
        assert caps.protocol_type == "Hysteria2"
        assert caps.v2bx_node_type == "hysteria2"
        assert caps.core_type == "sing"
        assert caps.requires_dns_record is False
        assert caps.supports_cdn_proxy is False
        assert caps.supported_asset_providers == ("self_hosted",)
        assert caps.enable_tfo is False

    def test_unsupported_protocol_raises(self) -> None:
        """Unsupported protocol should raise UserDataRenderError."""
        with pytest.raises(UserDataRenderError, match="Unsupported protocol"):
            get_protocol_capabilities("InvalidProtocol")


class TestRenderUserData:
    """Tests for render_user_data function."""

    def test_render_basic_anytls(self) -> None:
        """Should render valid User-Data for AnyTLS protocol."""
        request = create_valid_request(protocol_type="AnyTLS")
        result = render_user_data(request)

        assert isinstance(result, RenderedUserData)
        assert result.user_data is not None
        assert len(result.user_data) > 0
        assert result.protocol_capabilities.protocol_type == "AnyTLS"

    def test_render_includes_correlation_id(self) -> None:
        """Rendered script should include correlation ID."""
        request = create_valid_request(correlation_id="test-corr-id-123")
        result = render_user_data(request)
        assert "test-corr-id-123" in result.user_data

    def test_render_includes_node_id(self) -> None:
        """Rendered script should include Xboard node ID."""
        request = create_valid_request(xboard_node_id=99999)
        result = render_user_data(request)
        assert "99999" in result.user_data

    def test_render_includes_v2bx_config(self) -> None:
        """Rendered script should include V2bX config JSON."""
        request = create_valid_request()
        result = render_user_data(request)
        assert result.v2bx_config_json is not None
        assert "Nodes" in result.v2bx_config_json

    def test_render_replaces_all_placeholders(self) -> None:
        """All placeholders should be replaced in output."""
        request = create_valid_request()
        result = render_user_data(request)
        assert "__CORRELATION_ID__" not in result.user_data
        assert "__XBOARD_NODE_ID__" not in result.user_data
        assert "__V2BX_CONFIG_JSON__" not in result.user_data
        assert "__V2BX_INSTALL_SCRIPT_URL__" not in result.user_data

    def test_render_sing_origin_block_for_sing_core(self) -> None:
        """sing-origin block should be present for sing-core protocols."""
        request = create_valid_request(protocol_type="AnyTLS")
        result = render_user_data(request)
        assert "sing_origin" in result.user_data
        assert "EOF_V2BX_SING_ORIGIN" in result.user_data

    def test_render_no_sing_origin_for_xray_core(self) -> None:
        """sing-origin block should not be present for xray-core protocols."""
        request = create_valid_request(protocol_type="Trojan")
        result = render_user_data(request)
        assert "EOF_V2BX_SING_ORIGIN" not in result.user_data

    def test_render_with_callback_url(self) -> None:
        """Ready callback URL should be included when provided."""
        request = create_valid_request(
            ready_callback_url="https://callback.example.com/ready",
            ready_callback_token="callback_token_123",
        )
        result = render_user_data(request)
        assert "callback.example.com" in result.user_data
        assert "callback_token_123" in result.user_data

    def test_render_without_callback(self) -> None:
        """Ready callback should be empty when not configured."""
        request = create_valid_request()
        result = render_user_data(request)
        assert "__READY_CALLBACK_URL__" not in result.user_data

    def test_render_self_hosted_hysteria2(self) -> None:
        """Should render for self-hosted Hysteria2 protocol."""
        request = create_valid_request(
            asset_provider="self_hosted",
            protocol_type="Hysteria2",
            domain_name=None,
        )
        result = render_user_data(request)
        assert result.user_data is not None
        assert result.protocol_capabilities.protocol_type == "Hysteria2"


class TestRenderUserDataValidation:
    """Tests for render_user_data input validation."""

    def test_empty_node_name_raises(self) -> None:
        """Empty node_name should raise ValueError."""
        request = create_valid_request(node_name="")
        with pytest.raises(ValueError, match="node_name must not be empty"):
            render_user_data(request)

    def test_invalid_protocol_raises(self) -> None:
        """Invalid protocol type should raise UserDataRenderError."""
        request = create_valid_request(protocol_type="InvalidProtocol")
        with pytest.raises(UserDataRenderError):
            render_user_data(request)

    def test_hysteria2_not_allowed_on_aws(self) -> None:
        """Hysteria2 should not be allowed on AWS assets."""
        request = create_valid_request(
            asset_provider="aws",
            protocol_type="Hysteria2",
            domain_name=None,
        )
        with pytest.raises(UserDataRenderError, match="only supports asset providers"):
            render_user_data(request)

    def test_anytls_requires_domain_name(self) -> None:
        """AnyTLS requires domain_name for DNS linkage."""
        request = create_valid_request(
            asset_provider="aws",
            protocol_type="AnyTLS",
            domain_name=None,
        )
        with pytest.raises(UserDataRenderError, match="requires a domain_name"):
            render_user_data(request)

    def test_callback_url_without_token_raises(self) -> None:
        """ready_callback_url without token should raise."""
        request = create_valid_request(
            ready_callback_url="https://callback.example.com",
            ready_callback_token=None,
        )
        with pytest.raises(UserDataRenderError, match="must be configured together"):
            render_user_data(request)

    def test_callback_token_without_url_raises(self) -> None:
        """ready_callback_token without url should raise."""
        request = create_valid_request(
            ready_callback_url=None,
            ready_callback_token="token",
        )
        with pytest.raises(UserDataRenderError, match="must be configured together"):
            render_user_data(request)

    def test_invalid_timeout_raises(self) -> None:
        """timeout_seconds <= 0 should raise."""
        request = create_valid_request(timeout_seconds=0)
        with pytest.raises(ValueError, match="timeout_seconds must be greater than 0"):
            render_user_data(request)

    def test_negative_traffic_threshold_raises(self) -> None:
        """Negative traffic thresholds should raise."""
        request = create_valid_request(device_online_min_traffic_kb=-1)
        with pytest.raises(ValueError, match="device_online_min_traffic_kb"):
            render_user_data(request)

    def test_negative_report_traffic_raises(self) -> None:
        """Negative min_report_traffic_kb should raise."""
        request = create_valid_request(min_report_traffic_kb=-1)
        with pytest.raises(ValueError, match="min_report_traffic_kb"):
            render_user_data(request)
