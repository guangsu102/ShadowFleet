"""
协议配置自动生成器
根据协议类型自动生成完整的 protocol_settings 配置

配置优先级规则：
1. 用户显式传入的参数（最高优先级）
2. 协议特定的默认值
3. 全局默认值（最低优先级）

使用示例：
    # 使用默认配置
    config = ProtocolConfigBuilder.build_anytls_config()

    # 覆盖特定参数
    config = ProtocolConfigBuilder.build_anytls_config(
        sni_domain="custom.example.com",
        allow_insecure=False
    )
"""
from __future__ import annotations

from typing import Any


class ProtocolConfigBuilder:
    """协议配置构建器"""

    # 默认伪装域名列表（可以从配置文件读取）
    DEFAULT_SNI_DOMAINS = [
        "www.bilibili.com",
        "api.bilibili.com",
        "www.microsoft.com",
        "www.cloudflare.com",
    ]

    @staticmethod
    def build_anytls_config(
        sni_domain: str | None = None,
        allow_insecure: bool = True,
    ) -> dict[str, Any]:
        """
        构建 AnyTLS 协议配置

        优先级：
        1. sni_domain 参数（如果提供）
        2. DEFAULT_SNI_DOMAINS[0]（默认）

        Args:
            sni_domain: SNI 伪装域名，如果为 None 则使用默认域名
            allow_insecure: 是否允许不安全连接

        Returns:
            完整的 protocol_settings 配置
        """
        if sni_domain is None:
            sni_domain = ProtocolConfigBuilder.DEFAULT_SNI_DOMAINS[0]

        return {
            "padding_scheme": [
                "stop=8",
                "0=30-30",
                "1=100-400",
                "2=400-500,c,500-1000,c,500-1000,c,500-1000,c,500-1000",
                "3=9-9,500-1000",
                "4=500-1000",
                "5=500-1000",
                "6=500-1000",
                "7=500-1000"
            ],
            "tls": {
                "server_name": sni_domain,
                "allow_insecure": allow_insecure,
            }
        }

    @staticmethod
    def build_trojan_config(
        sni_domain: str | None = None,
        allow_insecure: bool = True,
        network: str = "grpc",
    ) -> dict[str, Any]:
        """
        构建 Trojan 协议配置

        优先级：
        1. 传入的参数（如果提供）
        2. 函数默认值

        Args:
            sni_domain: SNI 伪装域名
            allow_insecure: 是否允许不安全连接
            network: 传输协议（grpc, ws, tcp）

        Returns:
            完整的 protocol_settings 配置（符合 Xboard 字段结构）
        """
        if sni_domain is None:
            sni_domain = ProtocolConfigBuilder.DEFAULT_SNI_DOMAINS[0]

        config: dict[str, Any] = {
            "allow_insecure": allow_insecure,
            "server_name": sni_domain,
            "network": network,
        }

        if network == "grpc":
            config["network_settings"] = {
                "serviceName": "",
            }

        return config

    @staticmethod
    def build_vmess_config(
        tls_enabled: bool = True,
        network: str = "grpc",
        sni_domain: str | None = None,
    ) -> dict[str, Any]:
        """
        构建 VMess 协议配置

        优先级：
        1. 传入的参数（如果提供）
        2. 函数默认值

        Args:
            tls_enabled: 是否启用 TLS
            network: 传输协议（grpc, ws, tcp）
            sni_domain: SNI 伪装域名（可选）

        Returns:
            完整的 protocol_settings 配置
        """
        config: dict[str, Any] = {
            "tls": 1 if tls_enabled else 0,
            "network": network,
        }

        if network == "grpc":
            config["network_settings"] = {
                "serviceName": "",
            }

        # 如果启用 TLS 且提供了 SNI 域名，添加 tls_settings
        if tls_enabled and sni_domain:
            config["tls_settings"] = {
                "server_name": sni_domain,
            }

        return config

    @staticmethod
    def build_vless_config(
        sni_domain: str | None = None,
        allow_insecure: bool = True,
        network: str = "grpc",
        flow: str = "xtls-rprx-vision",
        reality_enabled: bool = True,
        reality_dest: str | None = None,
        reality_private_key: str | None = None,
        reality_public_key: str | None = None,
    ) -> dict[str, Any]:
        """
        构建 VLESS 协议配置（支持 Reality）

        优先级：
        1. 传入的参数（如果提供）
        2. 函数默认值
        3. 从其他参数推导（如 reality_dest 默认使用 sni_domain）

        Args:
            sni_domain: SNI 伪装域名
            allow_insecure: 是否允许不安全连接
            network: 传输协议（grpc, ws, tcp）
            flow: 流控模式（xtls-rprx-vision）
            reality_enabled: 是否启用 Reality
            reality_dest: Reality 伪装站点
            reality_private_key: Reality 私钥
            reality_public_key: Reality 公钥

        Returns:
            完整的 protocol_settings 配置
        """
        if sni_domain is None:
            sni_domain = ProtocolConfigBuilder.DEFAULT_SNI_DOMAINS[0]

        if reality_dest is None:
            reality_dest = sni_domain

        config: dict[str, Any] = {
            "tls": 1,
            "network": network,
            "flow": flow,
        }

        # 构建 tls_settings（符合 Xboard 结构）
        tls_settings: dict[str, Any] = {}

        if reality_enabled and reality_private_key and reality_public_key:
            # Reality 配置
            tls_settings["server_name"] = sni_domain
            tls_settings["allow_insecure"] = allow_insecure
            tls_settings["public_key"] = reality_public_key
            tls_settings["private_key"] = reality_private_key
            tls_settings["short_id"] = ""
            tls_settings["server_port"] = reality_dest

        if tls_settings:
            config["tls_settings"] = tls_settings

        if network == "grpc":
            config["network_settings"] = {
                "serviceName": "",
            }

        return config

    @staticmethod
    def build_protocol_config(
        protocol_type: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        根据协议类型自动构建配置

        优先级：
        1. kwargs 中的参数（最高优先级）
        2. 协议特定的构建函数默认值
        3. 全局默认值（最低优先级）

        Args:
            protocol_type: 协议类型（AnyTLS, Trojan, vless, vmess, Hysteria2）
            **kwargs: 协议特定参数

        Returns:
            完整的 protocol_settings 配置
        """
        protocol_type_lower = protocol_type.lower()

        if protocol_type_lower == "anytls":
            return ProtocolConfigBuilder.build_anytls_config(**kwargs)
        elif protocol_type_lower == "trojan":
            return ProtocolConfigBuilder.build_trojan_config(**kwargs)
        elif protocol_type_lower == "vmess":
            return ProtocolConfigBuilder.build_vmess_config(**kwargs)
        elif protocol_type_lower == "vless":
            return ProtocolConfigBuilder.build_vless_config(**kwargs)
        else:
            # 其他协议返回空配置
            return {}

    @staticmethod
    def merge_protocol_config(
        base_config: dict[str, Any],
        override_config: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """
        合并协议配置，override_config 优先级更高

        优先级规则：
        1. override_config 中的值（最高优先级）
        2. base_config 中的值（默认值）

        Args:
            base_config: 基础配置（默认值）
            override_config: 覆盖配置（用户提供的值）

        Returns:
            合并后的配置
        """
        if override_config is None:
            return base_config

        merged = base_config.copy()

        for key, value in override_config.items():
            if isinstance(value, dict) and key in merged and isinstance(merged[key], dict):
                # 递归合并嵌套字典
                merged[key] = ProtocolConfigBuilder.merge_protocol_config(merged[key], value)
            else:
                # 直接覆盖
                merged[key] = value

        return merged
