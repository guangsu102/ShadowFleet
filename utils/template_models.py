from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Literal


AssetProvider = Literal["aws", "self_hosted"]
ProtocolType = Literal["AnyTLS", "Trojan", "vless", "vmess", "Hysteria2"]
CertMode = Literal["none", "http", "dns", "self"]
V2bxLogLevel = Literal["info", "warn", "error", "none"]

DEFAULT_V2BX_INSTALL_SCRIPT_URL = (
    "https://raw.githubusercontent.com/wyx2685/V2bX-script/master/install.sh"
)
DEFAULT_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "user_data.sh"
UNRESOLVED_PLACEHOLDER_PATTERN = re.compile(r"__[A-Z0-9_]+__")


class UserDataRenderError(RuntimeError):
    pass


@dataclass(frozen=True)
class V2bxProtocolCapabilities:
    protocol_type: ProtocolType
    v2bx_node_type: str
    core_type: Literal["xray", "sing"]
    requires_dns_record: bool
    supports_cdn_proxy: bool
    supported_asset_providers: tuple[AssetProvider, ...]
    enable_tfo: bool
    requires_nginx_stream: bool = False
    connlimit_port: int | None = None


@dataclass(frozen=True)
class V2bxCertConfig:
    cert_mode: CertMode = "none"
    cert_domain: str | None = None
    reject_unknown_sni: bool = False
    cert_file: str = "/etc/V2bX/cert/node.pem"
    key_file: str = "/etc/V2bX/cert/node.key"
    email: str | None = None
    provider: str | None = None
    dns_env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class UserDataRenderRequest:
    asset_provider: AssetProvider
    protocol_type: ProtocolType
    node_name: str
    xboard_api_host: str
    xboard_api_key: str
    xboard_node_id: int
    server_host: str
    correlation_id: str
    ready_callback_url: str | None = None
    ready_callback_token: str | None = None
    domain_name: str | None = None
    enable_cdn_proxy: bool = False
    v2bx_version: str | None = None
    panel_type: str = "V2board"
    listen_ip: str = "::"
    send_ip: str = "::"
    timeout_seconds: int = 30
    device_online_min_traffic_kb: int = 100
    min_report_traffic_kb: int = 0
    log_level: V2bxLogLevel = "error"
    cert_config: V2bxCertConfig = field(default_factory=V2bxCertConfig)
    nginx_internal_port: int = 5105
    listen_port: int = 443
    daemon_artifact_base_url: str | None = None
    cached_v2bx_version: str | None = None
    daemon_ipv6: str | None = None


@dataclass(frozen=True)
class RenderedUserData:
    user_data: str
    protocol_capabilities: V2bxProtocolCapabilities
    v2bx_config_json: str


PROTOCOL_CAPABILITIES: dict[ProtocolType, V2bxProtocolCapabilities] = {
    "AnyTLS": V2bxProtocolCapabilities(
        protocol_type="AnyTLS",
        v2bx_node_type="anytls",
        core_type="sing",
        requires_dns_record=True,
        supports_cdn_proxy=False,
        supported_asset_providers=("aws", "self_hosted"),
        enable_tfo=False,
        requires_nginx_stream=True,
        connlimit_port=443,
    ),
    "Trojan": V2bxProtocolCapabilities(
        protocol_type="Trojan",
        v2bx_node_type="trojan",
        core_type="xray",
        requires_dns_record=True,
        supports_cdn_proxy=True,
        supported_asset_providers=("aws", "self_hosted"),
        enable_tfo=True,
        connlimit_port=443,
    ),
    "vless": V2bxProtocolCapabilities(
        protocol_type="vless",
        v2bx_node_type="vless",
        core_type="xray",
        requires_dns_record=True,
        supports_cdn_proxy=True,
        supported_asset_providers=("aws", "self_hosted"),
        enable_tfo=True,
        connlimit_port=443,
    ),
    "vmess": V2bxProtocolCapabilities(
        protocol_type="vmess",
        v2bx_node_type="vmess",
        core_type="xray",
        requires_dns_record=True,
        supports_cdn_proxy=True,
        supported_asset_providers=("aws", "self_hosted"),
        enable_tfo=True,
        connlimit_port=443,
    ),
    "Hysteria2": V2bxProtocolCapabilities(
        protocol_type="Hysteria2",
        v2bx_node_type="hysteria2",
        core_type="sing",
        requires_dns_record=False,
        supports_cdn_proxy=False,
        supported_asset_providers=("self_hosted",),
        enable_tfo=False,
    ),
}


def get_protocol_capabilities(protocol_type: ProtocolType) -> V2bxProtocolCapabilities:
    try:
        return PROTOCOL_CAPABILITIES[protocol_type]
    except KeyError as exc:
        raise UserDataRenderError(f"Unsupported protocol type: {protocol_type}") from exc


GITHUB_ARTIFACT_MANIFEST: dict[str, str] = {
    "install.sh": "https://raw.githubusercontent.com/wyx2685/V2bX-script/master/install.sh",
    "V2bX.sh": "https://raw.githubusercontent.com/wyx2685/V2bX-script/master/V2bX.sh",
    "initconfig.sh": "https://raw.githubusercontent.com/wyx2685/V2bX-script/master/initconfig.sh",
}
"""GitHub origin URLs for V2bX install scripts. Shared by daemon artifact cache sync and template rendering."""
