"""
域名池管理器单元测试
"""

import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from services.domain_pool_manager import (
    DomainAllocation,
    DomainPoolManager,
)


@pytest.fixture
def mock_runtime():
    """创建模拟的运行时上下文"""
    runtime = MagicMock()
    runtime.logger = MagicMock()
    runtime.logger.getChild = MagicMock(return_value=MagicMock())
    runtime.config = MagicMock()
    runtime.config.cloudflare = MagicMock()
    runtime.config.cloudflare.zone_name = "example.com"
    return runtime


@pytest.fixture
def mock_state_repo():
    """创建模拟的状态仓库"""
    repo = MagicMock()
    repo.list_deleted_nodes_with_domains = MagicMock(return_value=[])
    repo.list_all_nodes_with_domains = MagicMock(return_value=[])
    repo._sqlite_manager = MagicMock()
    repo._sqlite_manager.database_path = ":memory:"
    return repo


@pytest.fixture
def mock_deleted_node():
    """创建模拟的已删除节点"""
    node = MagicMock()
    node.id = 1
    node.domain_name = "atl-100.example.com"
    node.xboard_node_id = 100
    node.status = "deleted"
    node.status_reason = None
    return node


class TestDomainPoolManager:
    """域名池管理器测试"""

    def test_generate_new_domain_anytls(self, mock_runtime):
        """测试生成 anytls 协议域名"""
        manager = DomainPoolManager(mock_runtime)
        domain = manager._generate_new_domain("anytls", 123)

        assert domain == "atl-123.example.com"

    def test_generate_new_domain_trojan(self, mock_runtime):
        """测试生成 trojan 协议域名"""
        manager = DomainPoolManager(mock_runtime)
        domain = manager._generate_new_domain("trojan", 456)

        assert domain == "tro-456.example.com"

    def test_generate_new_domain_vless(self, mock_runtime):
        """测试生成 vless 协议域名"""
        manager = DomainPoolManager(mock_runtime)
        domain = manager._generate_new_domain("vless", 789)

        assert domain == "vls-789.example.com"

    def test_generate_new_domain_vmess(self, mock_runtime):
        """测试生成 vmess 协议域名"""
        manager = DomainPoolManager(mock_runtime)
        domain = manager._generate_new_domain("vmess", 111)

        assert domain == "vms-111.example.com"

    def test_generate_new_domain_hysteria2(self, mock_runtime):
        """测试生成 hysteria2 协议域名"""
        manager = DomainPoolManager(mock_runtime)
        domain = manager._generate_new_domain("hysteria2", 222)

        assert domain == "hy2-222.example.com"

    def test_generate_new_domain_unknown_protocol(self, mock_runtime):
        """测试生成未知协议域名"""
        manager = DomainPoolManager(mock_runtime)
        domain = manager._generate_new_domain("unknown", 333)

        assert domain == "node-333.example.com"

    def test_generate_new_domain_case_insensitive(self, mock_runtime):
        """测试协议类型大小写不敏感"""
        manager = DomainPoolManager(mock_runtime)
        domain1 = manager._generate_new_domain("ANYTLS", 123)
        domain2 = manager._generate_new_domain("AnyTLS", 123)

        assert domain1 == "atl-123.example.com"
        assert domain2 == "atl-123.example.com"

    def test_allocate_domain_no_reusable(self, mock_runtime, mock_state_repo):
        """测试分配域名（无可复用域名）"""
        with patch("database.state_repo.StateRepo", return_value=mock_state_repo):
            manager = DomainPoolManager(mock_runtime)
            domain = manager.allocate_domain("anytls", 123)

        assert domain == "atl-123.example.com"

    def test_allocate_domain_with_reusable(self, mock_runtime, mock_state_repo, mock_deleted_node):
        """测试分配域名（有可复用域名）"""
        mock_state_repo.list_deleted_nodes_with_domains.return_value = [mock_deleted_node]

        # Mock SQLite connection
        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 1
        mock_connection.execute.return_value = mock_cursor

        with patch("database.state_repo.StateRepo", return_value=mock_state_repo):
            with patch("sqlite3.connect", return_value=mock_connection):
                manager = DomainPoolManager(mock_runtime)
                domain = manager.allocate_domain("anytls", 200)

        assert domain == "atl-100.example.com"

    def test_allocate_domain_retry_on_failure(self, mock_runtime, mock_state_repo):
        """测试分配域名失败后重试"""
        mock_state_repo.list_deleted_nodes_with_domains.side_effect = [
            Exception("Database error"),
            []
        ]

        with patch("database.state_repo.StateRepo", return_value=mock_state_repo):
            with patch("time.sleep"):
                manager = DomainPoolManager(mock_runtime)
                domain = manager.allocate_domain("anytls", 123)

        assert domain == "atl-123.example.com"

    def test_allocate_domain_max_retries_exceeded(self, mock_runtime, mock_state_repo):
        """测试分配域名超过最大重试次数"""
        mock_state_repo.list_deleted_nodes_with_domains.side_effect = Exception("Database error")

        with patch("database.state_repo.StateRepo", return_value=mock_state_repo):
            with patch("time.sleep"):
                manager = DomainPoolManager(mock_runtime)

                with pytest.raises(Exception):
                    manager.allocate_domain("anytls", 123)

    def test_find_and_claim_reusable_domain_success(self, mock_runtime, mock_state_repo, mock_deleted_node):
        """测试成功声明可复用域名"""
        mock_state_repo.list_deleted_nodes_with_domains.return_value = [mock_deleted_node]

        # Mock SQLite connection
        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 1
        mock_connection.execute.return_value = mock_cursor

        with patch("sqlite3.connect", return_value=mock_connection):
            manager = DomainPoolManager(mock_runtime)
            domain = manager._find_and_claim_reusable_domain(mock_state_repo, "anytls", 200)

        assert domain == "atl-100.example.com"
        mock_connection.commit.assert_called_once()

    def test_find_and_claim_reusable_domain_already_claimed(self, mock_runtime, mock_state_repo, mock_deleted_node):
        """测试域名已被其他请求声明"""
        mock_state_repo.list_deleted_nodes_with_domains.return_value = [mock_deleted_node]

        # Mock SQLite connection - rowcount = 0 表示更新失败
        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 0
        mock_connection.execute.return_value = mock_cursor

        with patch("sqlite3.connect", return_value=mock_connection):
            manager = DomainPoolManager(mock_runtime)
            domain = manager._find_and_claim_reusable_domain(mock_state_repo, "anytls", 200)

        assert domain is None
        mock_connection.rollback.assert_called()

    def test_find_and_claim_reusable_domain_no_deleted_nodes(self, mock_runtime, mock_state_repo):
        """测试没有可复用域名"""
        mock_state_repo.list_deleted_nodes_with_domains.return_value = []

        manager = DomainPoolManager(mock_runtime)
        domain = manager._find_and_claim_reusable_domain(mock_state_repo, "anytls", 200)

        assert domain is None

    def test_find_and_claim_reusable_domain_sqlite_error(self, mock_runtime, mock_state_repo, mock_deleted_node):
        """测试 SQLite 错误处理"""
        mock_state_repo.list_deleted_nodes_with_domains.return_value = [mock_deleted_node]

        # Mock SQLite connection - 抛出异常
        mock_connection = MagicMock()
        mock_connection.execute.side_effect = sqlite3.Error("Database locked")

        with patch("sqlite3.connect", return_value=mock_connection):
            manager = DomainPoolManager(mock_runtime)
            domain = manager._find_and_claim_reusable_domain(mock_state_repo, "anytls", 200)

        assert domain is None
        mock_connection.rollback.assert_called()

    def test_release_domain(self, mock_runtime):
        """测试释放域名"""
        manager = DomainPoolManager(mock_runtime)

        # 释放域名不应该抛出异常
        manager.release_domain("atl-123.example.com", 123)

    def test_get_domain_allocation_status_empty(self, mock_runtime, mock_state_repo):
        """测试获取域名分配状态（空）"""
        mock_state_repo.list_all_nodes_with_domains.return_value = []

        with patch("database.state_repo.StateRepo", return_value=mock_state_repo):
            manager = DomainPoolManager(mock_runtime)
            allocations = manager.get_domain_allocation_status()

        assert len(allocations) == 0

    def test_get_domain_allocation_status_with_nodes(self, mock_runtime, mock_state_repo):
        """测试获取域名分配状态（有节点）"""
        # 创建模拟节点
        node1 = MagicMock()
        node1.domain_name = "atl-100.example.com"
        node1.xboard_node_id = 100
        node1.cloudflare_record_id = "cf-123"
        node1.status = "online"

        node2 = MagicMock()
        node2.domain_name = "tro-200.example.com"
        node2.xboard_node_id = 200
        node2.cloudflare_record_id = "cf-456"
        node2.status = "deleted"

        mock_state_repo.list_all_nodes_with_domains.return_value = [node1, node2]

        with patch("database.state_repo.StateRepo", return_value=mock_state_repo):
            manager = DomainPoolManager(mock_runtime)
            allocations = manager.get_domain_allocation_status()

        assert len(allocations) == 2
        assert allocations[0].domain_name == "atl-100.example.com"
        assert allocations[0].is_allocated is True
        assert allocations[1].domain_name == "tro-200.example.com"
        assert allocations[1].is_allocated is False


class TestDomainAllocation:
    """域名分配记录测试"""

    def test_domain_allocation_creation(self):
        """测试创建域名分配记录"""
        allocation = DomainAllocation(
            domain_name="atl-123.example.com",
            xboard_node_id=123,
            cloudflare_record_id="cf-123",
            is_allocated=True
        )

        assert allocation.domain_name == "atl-123.example.com"
        assert allocation.xboard_node_id == 123
        assert allocation.cloudflare_record_id == "cf-123"
        assert allocation.is_allocated is True

    def test_domain_allocation_with_none_values(self):
        """测试创建域名分配记录（包含 None 值）"""
        allocation = DomainAllocation(
            domain_name="atl-123.example.com",
            xboard_node_id=None,
            cloudflare_record_id=None,
            is_allocated=False
        )

        assert allocation.domain_name == "atl-123.example.com"
        assert allocation.xboard_node_id is None
        assert allocation.cloudflare_record_id is None
        assert allocation.is_allocated is False
