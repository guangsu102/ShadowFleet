from __future__ import annotations

import json
from utils.template_models import (
    DEFAULT_TEMPLATE_PATH,
    DEFAULT_V2BX_INSTALL_SCRIPT_URL,
    GITHUB_ARTIFACT_MANIFEST,
    UNRESOLVED_PLACEHOLDER_PATTERN,
    RenderedUserData,
    UserDataRenderError,
    UserDataRenderRequest,
    V2bxCertConfig,
    V2bxProtocolCapabilities,
    get_protocol_capabilities,
)

__all__ = [
    "RenderedUserData",
    "UserDataRenderError",
    "UserDataRenderRequest",
    "V2bxCertConfig",
    "render_user_data",
]


def render_user_data(request: UserDataRenderRequest) -> RenderedUserData:
    capabilities = get_protocol_capabilities(request.protocol_type)
    _validate_request(request=request, capabilities=capabilities)
    template_content = DEFAULT_TEMPLATE_PATH.read_text(encoding="utf-8")
    _HEREDOC_TERMINATOR = "EOF_V2BX_CONFIG"
    v2bx_config_json = _build_v2bx_config_json(request=request, capabilities=capabilities)
    # Escape heredoc terminator if it appears inside JSON to prevent injection
    escaped_config = v2bx_config_json.replace(
        _HEREDOC_TERMINATOR, _HEREDOC_TERMINATOR[0] + _HEREDOC_TERMINATOR
    )
    user_data = template_content
    user_data = user_data.replace("__CORRELATION_ID__", request.correlation_id.strip())
    user_data = user_data.replace("__XBOARD_NODE_ID__", str(request.xboard_node_id))

    # Daemon artifact cache: node fetches install.sh from daemon (IPv6) instead of GitHub.
    # If daemon has no public IPv6, we fall back to direct GitHub download.
    use_daemon_cache = bool(request.daemon_artifact_base_url) and bool(request.daemon_ipv6)
    daemon_base = request.daemon_artifact_base_url.strip() if use_daemon_cache else ""
    user_data = user_data.replace("__DAEMON_ARTIFACT_BASE_URL__", daemon_base)
    user_data = user_data.replace(
        "__DAEMON_ARTIFACT_BASE_URL__/",
        f"{daemon_base}/" if daemon_base else "",
    )
    if use_daemon_cache:
        user_data = user_data.replace(
            "__DAEMON_INSTALL_SCRIPT_URL__",
            _build_daemon_artifact_url(daemon_base, "install.sh"),
        )
        user_data = user_data.replace(
            "__DAEMON_V2BX_SH_URL__",
            _build_daemon_artifact_url(daemon_base, "V2bX.sh"),
        )
        user_data = user_data.replace(
            "__DAEMON_INITCONFIG_SH_URL__",
            _build_daemon_artifact_url(daemon_base, "initconfig.sh"),
        )
    else:
        for placeholder in ("__DAEMON_INSTALL_SCRIPT_URL__", "__DAEMON_V2BX_SH_URL__", "__DAEMON_INITCONFIG_SH_URL__"):
            user_data = user_data.replace(placeholder, "")
    user_data = user_data.replace(
        "__V2BX_INSTALL_SCRIPT_URL__",
        DEFAULT_V2BX_INSTALL_SCRIPT_URL if not use_daemon_cache
        else _build_daemon_artifact_url(daemon_base, "install.sh"),
    )
    # Fallback install script URL when daemon is not configured (direct GitHub download)
    user_data = user_data.replace(
        "__GITHUB_INSTALL_SCRIPT_URL__",
        DEFAULT_V2BX_INSTALL_SCRIPT_URL,
    )
    # Inject cached V2bX version so install.sh skips its GitHub API call entirely
    cached_version = request.cached_v2bx_version or ""
    user_data = user_data.replace("__CACHED_V2BX_VERSION__", cached_version)
    user_data = user_data.replace(
        "__V2BX_INSTALL_COMMAND__",
        _build_install_command(request.v2bx_version),
    )
    user_data = user_data.replace("__V2BX_CONFIG_JSON__", escaped_config)
    user_data = user_data.replace(
        "__READY_CALLBACK_URL__",
        request.ready_callback_url.strip() if request.ready_callback_url else "",
    )
    user_data = user_data.replace(
        "__READY_CALLBACK_TOKEN__",
        request.ready_callback_token.strip() if request.ready_callback_token else "",
    )
    user_data = user_data.replace(
        "__V2BX_SING_ORIGIN_WRITE_BLOCK__",
        _build_sing_origin_write_block(request=request, capabilities=capabilities),
    )
    user_data = user_data.replace(
        "__NGINX_CONFIG_BLOCK__",
        _build_security_hardening_block(request=request, capabilities=capabilities),
    )

    unresolved_placeholders = sorted(set(UNRESOLVED_PLACEHOLDER_PATTERN.findall(user_data)))
    if unresolved_placeholders:
        raise UserDataRenderError(
            f"User-Data template contains unresolved placeholders: {unresolved_placeholders}"
        )

    return RenderedUserData(
        user_data=user_data,
        protocol_capabilities=capabilities,
        v2bx_config_json=v2bx_config_json,
    )


def _build_v2bx_config_json(
    request: UserDataRenderRequest,
    capabilities: V2bxProtocolCapabilities,
) -> str:
    config_payload = {
        "Log": {
            "Level": request.log_level,
            "Output": "",
        },
        "Cores": [_build_core_config(request=request, capabilities=capabilities)],
        "Nodes": [_build_node_config(request=request, capabilities=capabilities)],
    }
    return json.dumps(config_payload, ensure_ascii=True, indent=2)


def _build_core_config(
    request: UserDataRenderRequest,
    capabilities: V2bxProtocolCapabilities,
) -> dict[str, object]:
    if capabilities.core_type == "xray":
        return {
            "Type": "xray",
            "Log": {
                "Level": request.log_level,
                "AccessPath": "",
                "ErrorPath": "",
            },
            "AssetPath": "/etc/V2bX/",
            "DnsConfigPath": "/etc/V2bX/dns.json",
            "RouteConfigPath": "/etc/V2bX/route.json",
            "ConnectionConfig": {
                "handshake": 4,
                "connIdle": 300,
                "uplinkOnly": 2,
                "downlinkOnly": 5,
                "statsUserUplink": False,
                "statsUserDownlink": False,
                "bufferSize": 4,
            },
            "InboundConfigPath": "/etc/V2bX/custom_inbound.json",
            "OutboundConfigPath": "/etc/V2bX/custom_outbound.json",
        }

    return {
        "Type": "sing",
        "Name": "shadowfleet-sing",
        "Log": {
            "Level": request.log_level,
            "Timestamp": True,
        },
        "NTP": {
            "Enable": request.protocol_type == "vmess",
            "Server": "time.apple.com",
            "ServerPort": 0,
        },
        "OriginalPath": "/etc/V2bX/sing_origin.json",
    }


def _build_node_config(
    request: UserDataRenderRequest,
    capabilities: V2bxProtocolCapabilities,
) -> dict[str, object]:
    node_config: dict[str, object] = {
        "Name": request.node_name.strip(),
        "Core": capabilities.core_type,
        "CoreName": "shadowfleet-sing" if capabilities.core_type == "sing" else "",
        "ApiHost": request.xboard_api_host.strip(),
        "ApiKey": request.xboard_api_key.strip(),
        "NodeID": request.xboard_node_id,
        "NodeType": capabilities.v2bx_node_type,
        "Timeout": request.timeout_seconds,
        "ListenIP": request.listen_ip.strip(),
        "SendIP": request.send_ip.strip(),
        "ListenPort": (
            request.nginx_internal_port
            if capabilities.requires_nginx_stream
            else request.listen_port
        ),
        "DeviceOnlineMinTraffic": request.device_online_min_traffic_kb,
        "MinReportTraffic": request.min_report_traffic_kb,
        "EnableTFO": capabilities.enable_tfo,
        "CertConfig": _build_cert_config(request.cert_config),
    }

    if capabilities.core_type == "xray":
        node_config.update(
            {
                "EnableUot": False,
                "DisableIVCheck": False,
                "DisableSniffing": False,
            }
        )
    else:
        node_config.update(
            {
                "MultiplexConfig": {
                    "Enable": request.protocol_type != "Hysteria2",
                    "Padding": request.protocol_type == "AnyTLS",
                    "Brutal": {
                        "Enable": False,
                        "UpMbps": 0,
                        "DownMbps": 0,
                    },
                }
            }
        )

    return node_config


def _build_cert_config(cert_config: V2bxCertConfig) -> dict[str, object]:
    payload: dict[str, object] = {
        "CertMode": cert_config.cert_mode,
        "RejectUnknownSni": cert_config.reject_unknown_sni,
        "CertDomain": cert_config.cert_domain or "",
        "CertFile": cert_config.cert_file,
        "KeyFile": cert_config.key_file,
    }
    if cert_config.email is not None:
        payload["Email"] = cert_config.email
    if cert_config.provider is not None:
        payload["Provider"] = cert_config.provider
    if cert_config.dns_env:
        payload["DNSEnv"] = cert_config.dns_env
    return payload


def _build_install_command(v2bx_version: str | None) -> str:
    if v2bx_version is None:
        return 'printf \'n\\n\' | sudo bash "${INSTALL_SCRIPT_PATH}"'
    return f'printf \'n\\n\' | sudo bash "${{INSTALL_SCRIPT_PATH}}" "{v2bx_version.strip()}"'


# Daemon artifact base URL injected into the template at download-time.
# If daemon has a public IPv6, install.sh is fetched from the daemon (faster).
# If daemon has no IPv6, the node downloads install.sh directly from GitHub.
# install.sh contains the versioned binary download:
#   https://github.com/wyx2685/V2bX/releases/download/${version}/V2bX-linux-${arch}.zip
# and V2BX.sh / initconfig.sh from raw.githubusercontent.com.
# All of these are pre-cached on the daemon so the node never contacts GitHub.
DAEMON_ARTIFACT_MANIFEST: dict[str, str] = GITHUB_ARTIFACT_MANIFEST


def _build_daemon_artifact_url(base_url: str | None, filename: str) -> str:
    if not base_url:
        return ""
    return f"{base_url.rstrip('/')}/{filename}"


def _build_sing_origin_write_block(
    request: UserDataRenderRequest,
    capabilities: V2bxProtocolCapabilities,
) -> str:
    if capabilities.core_type != "sing":
        return ""

    sing_origin_payload = {
        "dns": {
            "servers": [
                {
                    "tag": "cf",
                    "address": "1.1.1.1",
                }
            ],
            "strategy": "prefer_ipv6" if request.listen_ip.strip() == "::" else "prefer_ipv4",
        },
        "outbounds": [
            {
                "tag": "direct",
                "type": "direct",
                "domain_resolver": {
                    "server": "cf",
                    "strategy": "prefer_ipv6" if request.listen_ip.strip() == "::" else "prefer_ipv4",
                },
            },
            {
                "type": "block",
                "tag": "block",
            },
        ],
        "route": {
            "rules": [
                {
                    "ip_is_private": True,
                    "outbound": "block",
                },
                {
                    "outbound": "direct",
                    "network": ["udp", "tcp"],
                },
            ]
        },
        "experimental": {
            "cache_file": {
                "enabled": True,
            }
        },
    }
    sing_origin_json = json.dumps(sing_origin_payload, ensure_ascii=True, indent=2)
    return (
        "log \"Writing V2bX sing origin config\"\n"
        "sudo tee /etc/V2bX/sing_origin.json >/dev/null <<'EOF_V2BX_SING_ORIGIN'\n"
        f"{sing_origin_json}\n"
        "EOF_V2BX_SING_ORIGIN"
    )


def _build_connlimit_block(
    port: int,
) -> str:
    """Generate idempotent iptables connlimit rules for a given port (IPv4 + IPv6).
    Uses -C (check) before -A (append) so multiple nodes on same machine are safe.
    """
    return (
        "# --- Base iptables rules (idempotent, first-run only) ---\n"
        "sudo iptables -C INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT 2>/dev/null "
        "|| sudo iptables -A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT\n"
        "sudo iptables -C INPUT -i lo -j ACCEPT 2>/dev/null "
        "|| sudo iptables -A INPUT -i lo -j ACCEPT\n"
        "sudo iptables -C INPUT -p icmp -j ACCEPT 2>/dev/null "
        "|| sudo iptables -A INPUT -p icmp -j ACCEPT\n"
        "sudo iptables -C INPUT -p tcp --dport 22 -j ACCEPT 2>/dev/null "
        "|| sudo iptables -A INPUT -p tcp --dport 22 -j ACCEPT\n"
        "sudo iptables -C INPUT -p udp --dport 53 -j ACCEPT 2>/dev/null "
        "|| sudo iptables -A INPUT -p udp --dport 53 -j ACCEPT\n"
        "sudo iptables -C INPUT -p udp --dport 67 -j ACCEPT 2>/dev/null "
        "|| sudo iptables -A INPUT -p udp --dport 67 -j ACCEPT\n"
        "sudo iptables -C INPUT -j DROP 2>/dev/null "
        "|| sudo iptables -A INPUT -j DROP\n"
        # Connlimit rules per port (idempotent)
        "sudo iptables -C INPUT -p tcp --syn --dport "
        f"{port}"
        " -m connlimit --connlimit-above 500 --connlimit-mask 32 -j DROP 2>/dev/null "
        "|| sudo iptables -A INPUT -p tcp --syn --dport "
        f"{port}"
        " -m connlimit --connlimit-above 500 --connlimit-mask 32 -j DROP\n"
        "sudo iptables -C INPUT -p tcp --dport "
        f"{port}"
        " -j ACCEPT 2>/dev/null "
        "|| sudo iptables -A INPUT -p tcp --dport "
        f"{port}"
        " -j ACCEPT\n"
        # IPv6 connlimit
        "sudo ip6tables -C INPUT -p tcp --syn --dport "
        f"{port}"
        " -m connlimit --connlimit-above 500 --connlimit-mask 128 -j DROP 2>/dev/null "
        "|| sudo ip6tables -A INPUT -p tcp --syn --dport "
        f"{port}"
        " -m connlimit --connlimit-above 500 --connlimit-mask 128 -j DROP\n"
        "sudo ip6tables -C INPUT -p tcp --dport "
        f"{port}"
        " -j ACCEPT 2>/dev/null "
        "|| sudo ip6tables -A INPUT -p tcp --dport "
        f"{port}"
        " -j ACCEPT\n"
    )


def _build_nginx_stream_block(
    nginx_internal_port: int,
    node_id: int,
) -> str:
    """Generate Nginx per-node stream config for AnyTLS passthrough.
    Uses a unique file per node to support multiple AnyTLS nodes on same machine.
    Nginx stream configs MUST go in /etc/nginx/conf.d/ (not sites-available/).
    NOTE: Debian's default nginx package does NOT include stream module.
          Must install nginx-full and add load_module directive to nginx.conf.
    """
    safe_node_id = str(node_id)
    # Stream configs must be in conf.d/ with .conf extension for nginx to load them
    stream_config_path = f"/etc/nginx/conf.d/v2bx-stream-{safe_node_id}.conf"

    # Build nginx stream config
    nginx_template = (
        "# AnyTLS stream proxy for node {node_id}\n"
        "stream {{\n"
        "    upstream v2bx_backend_{node_id} {{\n"
        "        server 127.0.0.1:{internal_port};\n"
        "    }}\n"
        "    server {{\n"
        "        listen 443;\n"
        "        proxy_pass v2bx_backend_{node_id};\n"
        "        proxy_protocol off;\n"
        "        proxy_timeout 300s;\n"
        "        proxy_connect_timeout 10s;\n"
        "    }}\n"
        "}}\n"
    ).format(node_id=safe_node_id, internal_port=nginx_internal_port)

    # Load module directive - must be at top of nginx.conf, before any other directives
    # Use a separate file in /etc/nginx/modules-enabled/ for clean modularity
    stream_load_module_conf = "/etc/nginx/modules-enabled/99-stream.conf"

    return (
        f'log "Installing Nginx reverse proxy for AnyTLS passthrough"\n'
        "sudo apt-get update -y\n"
        # nginx-full includes stream module; basic nginx does NOT
        "sudo apt-get install -y nginx-full\n"
        # Enable stream module (required for nginx stream directive)
        # Debian: load_module must be at top level, before 'events' block
        f"sudo tee {stream_load_module_conf} >/dev/null <<'EOF_LOAD_MODULE'\n"
        "load_module modules/ngx_stream_module.so;\n"
        "EOF_LOAD_MODULE\n"
        # Ensure conf.d directory exists
        "sudo mkdir -p /etc/nginx/conf.d\n"
        # Write stream config (idempotent: overwrite on each run)
        f"sudo tee {stream_config_path} >/dev/null <<'EOF_NGINX'\n"
        f"{nginx_template}"
        "EOF_NGINX\n"
        # Test and reload nginx (start if not running)
        "sudo nginx -t && sudo systemctl enable nginx 2>/dev/null || true\n"
        "sudo systemctl reload nginx || sudo systemctl start nginx\n"
    )


def _build_nginx_base_stream_config() -> str:
    """Generate shared Nginx base stream config with common settings.
    Includes all known node upstreams and is included from each node config.
    """
    return (
        "# Nginx base stream config - included by all v2bx-node-*.conf files\n"
        "# This file should be symlinked to sites-enabled on first run\n"
        "# Do NOT listen here - each node config handles its own listen directive\n"
    )


def _build_security_hardening_block(
    request: UserDataRenderRequest,
    capabilities: V2bxProtocolCapabilities,
) -> str:
    """Generate Nginx stream proxy and/or iptables connlimit based on protocol capabilities.
    All rules are idempotent and safe for multi-node (same machine) deployments.
    """
    parts: list[str] = []

    if capabilities.requires_nginx_stream:
        # _build_nginx_stream_block includes: apt-get install nginx + config + nginx reload
        parts.append(_build_nginx_stream_block(request.nginx_internal_port, request.xboard_node_id))

    if capabilities.connlimit_port is not None:
        parts.append(
            'log "Configuring iptables connection limit (500 conn/IP on port '
            f"{capabilities.connlimit_port}"
            ')"\n'
            + _build_connlimit_block(capabilities.connlimit_port)
        )

    if not parts:
        return ""
    return "".join(parts) + "\n"


def _validate_request(
    request: UserDataRenderRequest,
    capabilities: V2bxProtocolCapabilities,
) -> None:
    if request.asset_provider not in capabilities.supported_asset_providers:
        supported_asset_providers = ", ".join(capabilities.supported_asset_providers)
        raise UserDataRenderError(
            f"Protocol {request.protocol_type} only supports asset providers: "
            f"{supported_asset_providers}"
        )
    if not request.node_name or not request.node_name.strip():
        raise ValueError("node_name must not be empty")
    if request.xboard_node_id <= 0:
        raise ValueError("xboard_node_id must be greater than 0")
    if not request.server_host or not request.server_host.strip():
        raise ValueError("server_host must not be empty")
    if not request.correlation_id or not request.correlation_id.strip():
        raise ValueError("correlation_id must not be empty")
    if request.ready_callback_url is not None and not request.ready_callback_url.strip():
        raise ValueError("ready_callback_url must not be empty when provided")
    if request.ready_callback_token is not None and not request.ready_callback_token.strip():
        raise ValueError("ready_callback_token must not be empty when provided")
    if (request.ready_callback_url is None) != (request.ready_callback_token is None):
        raise UserDataRenderError(
            "ready_callback_url and ready_callback_token must be configured together"
        )
    if capabilities.requires_dns_record:
        if not request.domain_name or not request.domain_name.strip():
            raise UserDataRenderError(
                f"Protocol {request.protocol_type} requires a domain_name for DNS linkage"
            )
    if request.enable_cdn_proxy and not capabilities.supports_cdn_proxy:
        raise UserDataRenderError(
            f"Protocol {request.protocol_type} does not support CDN proxy mode"
        )
    if request.timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than 0")
    if request.device_online_min_traffic_kb < 0:
        raise ValueError("device_online_min_traffic_kb must be greater than or equal to 0")
    if request.min_report_traffic_kb < 0:
        raise ValueError("min_report_traffic_kb must be greater than or equal to 0")
    if capabilities.requires_dns_record and request.cert_config.cert_mode != "none":
        if not request.cert_config.cert_domain or not request.cert_config.cert_domain.strip():
            raise UserDataRenderError(
                f"Protocol {request.protocol_type} requires cert_domain when TLS is enabled"
            )
    if request.cert_config.cert_mode == "dns":
        if not request.cert_config.provider or not request.cert_config.provider.strip():
            raise UserDataRenderError("provider is required when cert_mode is dns")
        if not request.cert_config.dns_env:
            raise UserDataRenderError("dns_env is required when cert_mode is dns")
