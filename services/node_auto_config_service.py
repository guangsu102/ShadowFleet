"""
节点自动配置服务
在节点创建后自动配置 SNI、节点ID、权限组等
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from services.node_id_generator import NodeIdGenerator
from services.protocol_config_builder import ProtocolConfigBuilder

if TYPE_CHECKING:
    from services.runtime_service import RuntimeContext


class NodeAutoConfigService:
    """节点自动配置服务"""

    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime_context = runtime_context
        self._logger = runtime_context.logger.getChild("services.node_auto_config")

    def auto_configure_node(
        self,
        xboard_node_id: int,
        protocol_type: str,
        protocol_settings: dict[str, Any] | None = None,
        sni_domain: str | None = None,
        reality_private_key: str | None = None,
        reality_public_key: str | None = None,
        reality_dest: str | None = None,
        allow_insecure: bool = True,
        network: str = "grpc",
        flow: str | None = None,
    ) -> None:
        """
        自动配置节点

        Args:
            xboard_node_id: Xboard 节点 ID
            protocol_type: 协议类型
            protocol_settings: 用户提供的协议配置（如果有）
            sni_domain: SNI 伪装域名（可选）
            reality_private_key: Reality 私钥（vless 协议需要）
            reality_public_key: Reality 公钥（vless 协议需要）
            reality_dest: Reality 伪装站点（可选）
            allow_insecure: 是否允许不安全连接
            network: 传输协议（grpc, ws, tcp）
            flow: 流控模式（vless 协议）
        """
        from database.xboard_repo import XboardRepo
        from services.reality_key_generator import RealityKeyGenerator

        xboard_repo = XboardRepo(self._runtime_context)

        # 1. 生成并更新节点 ID
        node_id_gen = NodeIdGenerator(self._runtime_context)
        code = node_id_gen.generate_node_id(protocol_type, xboard_node_id)
        xboard_repo.update_node_code(xboard_node_id, code)
        self._logger.info(
            "Auto-configured node code: xboard_node_id=%s code=%s",
            xboard_node_id,
            code,
        )

        # 2. 如果是 VLESS 且没有提供 Reality 密钥，自动生成
        if protocol_type.lower() == "vless":
            if not reality_private_key or not reality_public_key:
                self._logger.info(
                    "Generating Reality key pair for VLESS node xboard_node_id=%s",
                    xboard_node_id
                )
                reality_private_key, reality_public_key = RealityKeyGenerator.generate_key_pair()
                self._logger.info(
                    "Generated Reality keys for node xboard_node_id=%s: public=%s...",
                    xboard_node_id,
                    reality_public_key[:16] if reality_public_key else "None"
                )

        # 3. 如果没有提供协议配置，自动生成
        if not protocol_settings:
            protocol_settings = self._build_protocol_settings(
                protocol_type=protocol_type,
                sni_domain=sni_domain,
                reality_private_key=reality_private_key,
                reality_public_key=reality_public_key,
                reality_dest=reality_dest,
                allow_insecure=allow_insecure,
                network=network,
                flow=flow,
            )

            # 更新 Xboard 中的 protocol_settings
            if protocol_settings:
                xboard_repo.update_node_protocol_settings(xboard_node_id, protocol_settings)
                self._logger.info(
                    "Auto-configured protocol settings: xboard_node_id=%s protocol=%s",
                    xboard_node_id,
                    protocol_type,
                )

    def _build_protocol_settings(
        self,
        protocol_type: str,
        sni_domain: str | None,
        reality_private_key: str | None,
        reality_public_key: str | None,
        reality_dest: str | None,
        allow_insecure: bool,
        network: str,
        flow: str | None,
    ) -> dict[str, Any] | None:
        """
        构建协议配置

        Args:
            protocol_type: 协议类型
            sni_domain: SNI 伪装域名
            reality_private_key: Reality 私钥
            reality_public_key: Reality 公钥
            reality_dest: Reality 伪装站点
            allow_insecure: 是否允许不安全连接
            network: 传输协议
            flow: 流控模式

        Returns:
            协议配置字典，如果协议不需要配置则返回 None
        """
        protocol_type_lower = protocol_type.lower()

        if protocol_type_lower == "anytls":
            return ProtocolConfigBuilder.build_anytls_config(
                sni_domain=sni_domain,
                allow_insecure=allow_insecure
            )
        elif protocol_type_lower == "trojan":
            return ProtocolConfigBuilder.build_trojan_config(
                sni_domain=sni_domain,
                allow_insecure=allow_insecure,
                network=network
            )
        elif protocol_type_lower == "vmess":
            return ProtocolConfigBuilder.build_vmess_config(
                tls_enabled=True,
                network=network,
                sni_domain=sni_domain,
                allow_insecure=allow_insecure
            )
        elif protocol_type_lower == "vless":
            return ProtocolConfigBuilder.build_vless_config(
                sni_domain=sni_domain or "www.bilibili.com",
                allow_insecure=allow_insecure,
                network=network,
                flow=flow or "xtls-rprx-vision",
                reality_enabled=True,
                reality_dest=reality_dest or "www.bilibili.com",
                reality_private_key=reality_private_key,
                reality_public_key=reality_public_key,
            )
        else:
            return None

    def get_default_group_ids(self) -> list[int]:
        """
        获取默认权限组 ID（所有权限组）

        Returns:
            权限组 ID 列表
        """
        from database.xboard_repo import XboardRepo

        xboard_repo = XboardRepo(self._runtime_context)
        return xboard_repo.get_all_group_ids()
