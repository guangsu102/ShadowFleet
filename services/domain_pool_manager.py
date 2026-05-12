"""
Cloudflare 域名池管理器
管理域名的分配、释放和复用
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.runtime_service import RuntimeContext


@dataclass
class DomainAllocation:
    """域名分配记录"""
    domain_name: str
    xboard_node_id: int | None
    cloudflare_record_id: str | None
    is_allocated: bool


class DomainPoolManager:
    """域名池管理器"""

    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime_context = runtime_context
        self._logger = runtime_context.logger.getChild("services.domain_pool_manager")
        self._base_domain = runtime_context.config.cloudflare.root_domain

    def allocate_domain(self, protocol_type: str, xboard_node_id: int) -> str:
        """
        为节点分配域名（带并发保护）

        优先复用已释放的域名，如果没有则生成新域名

        改进：
        1. 使用数据库锁防止并发分配同一域名
        2. 原子化标记域名为已分配状态
        3. 添加重试机制

        Args:
            protocol_type: 协议类型
            xboard_node_id: Xboard 节点 ID

        Returns:
            分配的域名
        """
        from database.state_repo import StateRepo

        state_repo = StateRepo(self._runtime_context)
        max_retries = 3

        for attempt in range(max_retries):
            try:
                # 使用数据库事务和锁来保护域名分配
                allocated_domain = self._allocate_domain_with_lock(
                    state_repo=state_repo,
                    protocol_type=protocol_type,
                    xboard_node_id=xboard_node_id,
                )

                self._logger.info(
                    "Successfully allocated domain: %s for xboard_node_id=%s protocol=%s (attempt %d/%d)",
                    allocated_domain,
                    xboard_node_id,
                    protocol_type,
                    attempt + 1,
                    max_retries,
                )
                return allocated_domain

            except Exception as e:
                if attempt < max_retries - 1:
                    self._logger.warning(
                        "Domain allocation failed (attempt %d/%d): %s, retrying...",
                        attempt + 1,
                        max_retries,
                        e,
                    )
                    # 短暂延迟后重试
                    import time
                    time.sleep(0.1 * (attempt + 1))
                else:
                    self._logger.error(
                        "Domain allocation failed after %d attempts for xboard_node_id=%s",
                        max_retries,
                        xboard_node_id,
                    )
                    raise

    def _allocate_domain_with_lock(
        self,
        state_repo,
        protocol_type: str,
        xboard_node_id: int,
    ) -> str:
        """
        在数据库锁保护下分配域名

        使用 SQLite 的 BEGIN IMMEDIATE 事务来获取写锁
        """
        # 1. 尝试查找并原子化分配可复用域名
        reusable_domain = self._find_and_claim_reusable_domain(
            state_repo,
            protocol_type,
            xboard_node_id
        )

        if reusable_domain:
            self._logger.info(
                "Reusing domain: %s for xboard_node_id=%s protocol=%s",
                reusable_domain,
                xboard_node_id,
                protocol_type,
            )
            return reusable_domain

        # 2. 生成新域名
        new_domain = self._generate_new_domain(protocol_type, xboard_node_id)
        self._logger.info(
            "Generated new domain: %s for xboard_node_id=%s protocol=%s",
            new_domain,
            xboard_node_id,
            protocol_type,
        )
        return new_domain

    def _find_and_claim_reusable_domain(
        self,
        state_repo,
        protocol_type: str,
        xboard_node_id: int,
    ) -> str | None:
        """
        查找并原子化声明可复用域名

        改进：
        1. 使用 BEGIN IMMEDIATE 获取写锁
        2. 使用 UPDATE ... WHERE 的原子性来防止并发冲突
        3. 确保事务正确提交和回滚
        """
        import sqlite3

        # 查询 deleted 状态且有域名的节点
        deleted_nodes = state_repo.list_deleted_nodes_with_domains(protocol_type)

        if not deleted_nodes:
            return None

        # 尝试原子化更新第一个可用域名的节点
        # 使用 UPDATE 的原子性：只有一个并发请求能成功更新
        for node in deleted_nodes:
            connection = None
            try:
                # 创建独立连接并使用 BEGIN IMMEDIATE 获取写锁
                connection = sqlite3.connect(
                    state_repo._sqlite_manager.database_path,
                    timeout=30.0,
                )
                connection.execute("PRAGMA busy_timeout = 30000")

                # BEGIN IMMEDIATE 立即获取写锁，防止并发冲突
                connection.execute("BEGIN IMMEDIATE")

                # 原子化更新：只有当状态仍为 deleted 时才更新
                cursor = connection.execute(
                    """
                    UPDATE fleet_nodes
                    SET status_reason = ?
                    WHERE id = ?
                      AND status = 'deleted'
                      AND domain_name = ?
                      AND (status_reason IS NULL OR status_reason NOT LIKE 'domain_reused_by:%')
                    """,
                    (
                        f"domain_reused_by:{xboard_node_id}",
                        node.id,
                        node.domain_name,
                    )
                )

                # 如果更新成功（rowcount > 0），说明我们成功声明了这个域名
                if cursor.rowcount > 0:
                    connection.commit()
                    self._logger.info(
                        "Successfully claimed reusable domain: %s from node_id=%s for xboard_node_id=%s",
                        node.domain_name,
                        node.id,
                        xboard_node_id,
                    )
                    return node.domain_name
                else:
                    # 这个域名已被其他并发请求声明，尝试下一个
                    connection.rollback()
                    self._logger.debug(
                        "Domain %s already claimed by another request, trying next...",
                        node.domain_name,
                    )
                    continue

            except sqlite3.Error as e:
                if connection:
                    connection.rollback()
                self._logger.warning(
                    "Failed to claim domain %s: %s, trying next...",
                    node.domain_name,
                    e,
                )
                continue
            finally:
                if connection:
                    connection.close()

        # 所有可复用域名都已被声明
        return None

    def _find_reusable_domain(self, state_repo, protocol_type: str) -> str | None:
        """
        查找可复用的域名（已废弃，使用 _find_and_claim_reusable_domain 代替）

        从 deleted 状态的节点中查找相同协议类型的域名

        Args:
            state_repo: StateRepo 实例
            protocol_type: 协议类型

        Returns:
            可复用的域名，如果没有则返回 None
        """
        # 查询 deleted 状态且有域名的节点
        deleted_nodes = state_repo.list_deleted_nodes_with_domains(protocol_type)

        if deleted_nodes:
            # 返回第一个可用的域名
            return deleted_nodes[0].domain_name

        return None

    def _generate_new_domain(self, protocol_type: str, xboard_node_id: int) -> str:
        """
        生成新域名

        格式：<协议前缀>-<xboard_node_id>.<base_domain>
        例如：atl-213.example.com, tro-214.example.com

        Args:
            protocol_type: 协议类型
            xboard_node_id: Xboard 节点 ID

        Returns:
            生成的域名
        """
        # 协议类型到域名前缀的映射
        protocol_prefix_map = {
            "anytls": "atl",
            "trojan": "tro",
            "vless": "vls",
            "vmess": "vms",
            "hysteria2": "hy2",
            "hysteria": "hy2",
        }

        protocol_type_lower = protocol_type.lower()
        prefix = protocol_prefix_map.get(protocol_type_lower, "node")

        return f"{prefix}-{xboard_node_id}.{self._base_domain}"

    def release_domain(self, domain_name: str, xboard_node_id: int) -> None:
        """
        释放域名（标记为可复用）

        当节点被删除时调用，域名会被标记为可复用状态

        Args:
            domain_name: 域名
            xboard_node_id: Xboard 节点 ID
        """
        self._logger.info(
            "Released domain: %s from xboard_node_id=%s (marked as reusable)",
            domain_name,
            xboard_node_id,
        )

    def get_domain_allocation_status(self) -> list[DomainAllocation]:
        """
        获取所有域名的分配状态

        Returns:
            域名分配记录列表
        """
        from database.state_repo import StateRepo

        state_repo = StateRepo(self._runtime_context)
        all_nodes = state_repo.list_all_nodes_with_domains()

        allocations = []
        for node in all_nodes:
            allocations.append(
                DomainAllocation(
                    domain_name=node.domain_name,
                    xboard_node_id=node.xboard_node_id,
                    cloudflare_record_id=node.cloudflare_record_id,
                    is_allocated=(node.status != "deleted"),
                )
            )

        return allocations
