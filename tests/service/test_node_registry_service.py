"""
Unit tests for NodeRegistryService
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from database.state_models import FleetNodeRecord
from services.node_registry_models import (
    NodeRegistryServiceError,
    RegisterNodeRequest,
)
from services.node_registry_service import NodeRegistryService


@pytest.fixture
def mock_ctx() -> MagicMock:
    """Create a mock RuntimeContext."""
    ctx = MagicMock()
    ctx.correlation_id = "test-correlation-123"
    ctx.logger = MagicMock()
    ctx.config = MagicMock()
    return ctx


@pytest.fixture
def mock_xboard_repo() -> MagicMock:
    """Create a mock XboardRepo."""
    mock = MagicMock()
    mock.register_node.return_value = 12345
    mock.mark_node_online.return_value = None
    mock.mark_node_offline.return_value = None
    mock.delete_node.return_value = None
    mock.update_node_host.return_value = None
    return mock


@pytest.fixture
def mock_state_repo() -> MagicMock:
    """Create a mock StateRepo."""
    mock = MagicMock()
    mock.create_node.return_value = 1
    mock.get_node_by_xboard_node_id.return_value = MagicMock(
        id=1,
        xboard_node_id=12345,
        node_name="test-node",
        status="online",
    )
    mock.get_node_by_node_name.return_value = None
    mock.update_node_status.return_value = None
    mock.update_node_runtime_metadata.return_value = None
    mock.create_event.return_value = None
    return mock


@pytest.fixture
def mock_asset_repo() -> MagicMock:
    """Create a mock AssetRepo."""
    mock = MagicMock()
    mock.release_allocation_by_xboard_node_id.return_value = True
    return mock


@pytest.fixture
def node_registry(mock_ctx: MagicMock) -> NodeRegistryService:
    """Create a NodeRegistryService instance."""
    with patch("services.node_registry_service.XboardRepo"), \
         patch("services.node_registry_service.StateRepo"), \
         patch("services.node_registry_service.AssetRepo"):
        return NodeRegistryService(mock_ctx)


@pytest.fixture
def register_request() -> RegisterNodeRequest:
    """Create a sample RegisterNodeRequest."""
    return RegisterNodeRequest(
        node_name="test-node",
        node_type="AnyTLS",
        host="test.example.com",
        port=443,
        server_port=443,
        rate=1.0,
        show=1,
        initial_status="provisioning",
    )


class TestNodeRegistryService:
    """Test NodeRegistryService."""

    def test_initialization(self, node_registry: NodeRegistryService) -> None:
        """Test service initializes correctly."""
        assert node_registry is not None

    def test_register_node_success(
        self, node_registry: NodeRegistryService, register_request: RegisterNodeRequest
    ) -> None:
        """Test successful node registration."""
        with patch.object(node_registry, "_xboard_repo") as mock_xboard, \
             patch.object(node_registry, "_state_repo") as mock_state, \
             patch("services.node_registry_service.validate_register_request"):
            mock_xboard.register_node.return_value = 12345
            mock_state.create_node.return_value = 1
            mock_state.get_node_by_node_name.return_value = None

            result = node_registry.register_node(register_request)

            assert result.xboard_node_id == 12345
            assert result.local_node_id == 1
            assert result.node_name == "test-node"
            assert result.node_type == "AnyTLS"
            mock_xboard.register_node.assert_called_once()
            mock_state.create_node.assert_called_once()

    def test_register_node_retry_scenario(
        self, node_registry: NodeRegistryService, register_request: RegisterNodeRequest
    ) -> None:
        """Test node registration retry scenario."""
        existing_node = MagicMock()
        existing_node.id = 1
        existing_node.xboard_node_id = 11111
        existing_node.status = "failed"

        with patch.object(node_registry, "_xboard_repo") as mock_xboard, \
             patch.object(node_registry, "_state_repo") as mock_state, \
             patch("services.node_registry_service.validate_register_request"):
            mock_state.get_node_by_node_name.return_value = existing_node
            mock_xboard.register_node.return_value = 12345

            result = node_registry.register_node(register_request)

            assert result.xboard_node_id == 12345
            mock_xboard.delete_node.assert_called_once_with(11111)
            mock_state.update_node_xboard_id.assert_called_once()

    def test_register_node_state_repo_failure(
        self, node_registry: NodeRegistryService, register_request: RegisterNodeRequest
    ) -> None:
        """Test node registration handles StateRepo failure."""
        from database.state_repo import StateRepoError

        with patch.object(node_registry, "_xboard_repo") as mock_xboard, \
             patch.object(node_registry, "_state_repo") as mock_state, \
             patch("services.node_registry_service.validate_register_request"), \
             patch("services.node_registry_service.compensate_registration_failure"):
            mock_xboard.register_node.return_value = 12345
            mock_state.get_node_by_node_name.return_value = None
            mock_state.create_node.side_effect = StateRepoError("Database error")

            with pytest.raises(NodeRegistryServiceError):
                node_registry.register_node(register_request)

    def test_get_registered_node(self, node_registry: NodeRegistryService) -> None:
        """Test getting a registered node."""
        with patch.object(node_registry, "_state_repo") as mock_state:
            mock_node = MagicMock()
            mock_state.get_node_by_xboard_node_id.return_value = mock_node

            result = node_registry.get_registered_node(12345)

            assert result == mock_node
            mock_state.get_node_by_xboard_node_id.assert_called_once_with(12345)

    def test_mark_node_offline_success(self, node_registry: NodeRegistryService) -> None:
        """Test marking node offline."""
        with patch.object(node_registry, "_xboard_repo") as mock_xboard, \
             patch.object(node_registry, "_state_repo") as mock_state, \
             patch("services.node_registry_service.require_registered_node") as mock_require:
            mock_node = MagicMock()
            mock_node.id = 1
            mock_node.status = "online"
            mock_require.return_value = mock_node

            result = node_registry.mark_node_offline(
                xboard_node_id=12345,
                status_reason="Test offline",
            )

            assert result.xboard_node_id == 12345
            assert result.status == "offline"
            mock_xboard.mark_node_offline.assert_called_once_with(12345)
            mock_state.update_node_status.assert_called_once()

    def test_mark_node_offline_rollback_on_failure(
        self, node_registry: NodeRegistryService
    ) -> None:
        """Test that offline transition rolls back on failure."""
        with patch.object(node_registry, "_xboard_repo") as mock_xboard, \
             patch.object(node_registry, "_state_repo") as mock_state, \
             patch("services.node_registry_service.require_registered_node") as mock_require, \
             patch("services.node_registry_service.rollback_offline_transition") as mock_rollback:
            mock_node = MagicMock()
            mock_node.id = 1
            mock_node.status = "online"
            mock_require.return_value = mock_node
            mock_state.update_node_status.side_effect = Exception("Database error")

            with pytest.raises(NodeRegistryServiceError):
                node_registry.mark_node_offline(12345)

            mock_rollback.assert_called_once()

    def test_mark_node_online_success(self, node_registry: NodeRegistryService) -> None:
        """Test marking node online."""
        with patch.object(node_registry, "_xboard_repo") as mock_xboard, \
             patch.object(node_registry, "_state_repo") as mock_state, \
             patch("services.node_registry_service.require_registered_node") as mock_require:
            mock_node = MagicMock()
            mock_node.id = 1
            mock_node.status = "provisioning"
            mock_node.last_known_host = None
            mock_require.return_value = mock_node

            result = node_registry.mark_node_online(
                xboard_node_id=12345,
                host="test.example.com",
                aws_instance_id="i-12345",
                ipv6_address="2600::1",
            )

            assert result.xboard_node_id == 12345
            assert result.status == "online"
            mock_xboard.update_node_host.assert_called_once()
            mock_xboard.mark_node_online.assert_called_once_with(12345)
            mock_state.update_node_runtime_metadata.assert_called_once()
            mock_state.update_node_status.assert_called_once()

    def test_mark_node_online_rollback_on_failure(
        self, node_registry: NodeRegistryService
    ) -> None:
        """Test that online transition rolls back on failure."""
        with patch.object(node_registry, "_xboard_repo") as mock_xboard, \
             patch.object(node_registry, "_state_repo") as mock_state, \
             patch("services.node_registry_service.require_registered_node") as mock_require, \
             patch("services.node_registry_service.rollback_online_transition") as mock_rollback:
            mock_node = MagicMock()
            mock_node.id = 1
            mock_node.status = "provisioning"
            mock_node.last_known_host = None
            mock_require.return_value = mock_node
            mock_state.update_node_status.side_effect = Exception("Database error")

            with pytest.raises(NodeRegistryServiceError):
                node_registry.mark_node_online(12345, host="test.example.com")

            mock_rollback.assert_called_once()

    def test_delete_node_success(self, node_registry: NodeRegistryService) -> None:
        """Test deleting a node."""
        with patch.object(node_registry, "_xboard_repo") as mock_xboard, \
             patch.object(node_registry, "_state_repo") as mock_state, \
             patch.object(node_registry, "_asset_repo") as mock_asset, \
             patch("services.node_registry_service.require_registered_node") as mock_require:
            mock_node = MagicMock()
            mock_node.id = 1
            mock_node.status = "offline"
            mock_require.return_value = mock_node
            mock_asset.release_allocation_by_xboard_node_id.return_value = True

            result = node_registry.delete_node(
                xboard_node_id=12345,
                status_reason="Test deletion",
            )

            assert result.xboard_node_id == 12345
            assert result.status == "deleted"
            mock_xboard.delete_node.assert_called_once_with(12345)
            mock_asset.release_allocation_by_xboard_node_id.assert_called_once_with(12345)

    def test_delete_node_already_absent_from_xboard(
        self, node_registry: NodeRegistryService
    ) -> None:
        """Test deleting node that's already absent from Xboard."""
        from database.xboard_repo import XboardNodeNotFoundError

        with patch.object(node_registry, "_xboard_repo") as mock_xboard, \
             patch.object(node_registry, "_state_repo") as mock_state, \
             patch.object(node_registry, "_asset_repo") as mock_asset, \
             patch("services.node_registry_service.require_registered_node") as mock_require:
            mock_node = MagicMock()
            mock_node.id = 1
            mock_node.status = "offline"
            mock_require.return_value = mock_node
            mock_xboard.delete_node.side_effect = XboardNodeNotFoundError("Node not found")

            result = node_registry.delete_node(12345)

            assert result.status == "deleted"
            mock_state.update_node_status.assert_called()

    def test_delete_vultr_node_deletes_instance_first(
        self, node_registry: NodeRegistryService
    ) -> None:
        with patch.object(node_registry, "_xboard_repo") as mock_xboard, \
             patch.object(node_registry, "_state_repo") as mock_state, \
             patch.object(node_registry, "_asset_repo") as mock_asset, \
             patch("services.node_registry_service.require_registered_node") as mock_require, \
             patch("services.node_registry_service.VultrClient") as mock_vultr:
            node = MagicMock()
            node.id = 1
            node.status = "offline"
            node.asset_type = "vultr"
            node.aws_instance_id = "vultr-instance-1"
            node.xboard_node_id = 12345
            mock_require.return_value = node
            asset = MagicMock(id=8, asset_type="vultr", aws_access_key="token")
            mock_asset.get_asset_by_xboard_node_id.return_value = asset

            result = node_registry.delete_node(12345)

            assert result.status == "deleted"
            mock_vultr.return_value.delete_instance.assert_called_once_with("vultr-instance-1")
            mock_xboard.delete_node.assert_called_once_with(12345)

    def test_delete_vultr_node_recovers_asset_without_allocation(
        self, node_registry: NodeRegistryService
    ) -> None:
        with patch.object(node_registry, "_asset_repo") as mock_asset, \
             patch("services.node_registry_service.VultrClient") as mock_vultr:
            node = MagicMock()
            node.id = 1
            node.asset_type = "aws"
            node.aws_account_id = "vultr"
            node.aws_instance_id = "vultr-instance-legacy"
            node.xboard_node_id = 12346
            asset = MagicMock(id=9, asset_type="vultr", aws_access_key="legacy-token")
            mock_asset.get_asset_by_xboard_node_id.return_value = None
            mock_asset.list_assets_by_aws_account_id.return_value = [asset]

            node_registry._delete_vultr_instance(node)

            mock_vultr.return_value.delete_instance.assert_called_once_with(
                "vultr-instance-legacy"
            )
            mock_asset.list_assets_by_aws_account_id.assert_called_once_with("vultr")

    def test_delete_azure_node_recovers_asset_without_allocation(
        self, node_registry: NodeRegistryService
    ) -> None:
        with patch.object(node_registry, "_asset_repo") as mock_asset, \
             patch("services.node_registry_service.AzureClient") as azure_client:
            node = MagicMock(
                id=1,
                asset_type="aws",
                aws_account_id="azure:sub-id",
                aws_instance_id="/subscriptions/sub-id/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/sf-node",
                xboard_node_id=12347,
            )
            asset = MagicMock(
                id=10,
                asset_type="azure",
                aws_access_key="client",
                aws_secret_key="secret",
                provider_config={"tenant_id": "tenant", "subscription_id": "sub-id"},
            )
            mock_asset.get_asset_by_xboard_node_id.return_value = None
            mock_asset.list_assets_by_aws_account_id.return_value = [asset]

            node_registry._delete_azure_instance(node)

            azure_client.return_value.delete_vm.assert_called_once_with(node.aws_instance_id)
            mock_asset.list_assets_by_aws_account_id.assert_called_once_with("azure:sub-id")

    def test_sync_with_xboard_creates_new_nodes(
        self, node_registry: NodeRegistryService
    ) -> None:
        """Test sync creates new local nodes from Xboard."""
        with patch.object(node_registry, "_xboard_repo") as mock_xboard, \
             patch.object(node_registry, "_state_repo") as mock_state, \
             patch.object(node_registry, "_asset_repo") as mock_asset:
            xboard_node = MagicMock()
            xboard_node.node_id = 12345
            xboard_node.node_name = "sf-test-node"
            xboard_node.node_type = "AnyTLS"
            mock_xboard.list_all_shadowfleet_nodes.return_value = [xboard_node]
            mock_state.list_active_nodes.return_value = []
            mock_state.get_deleted_node_by_xboard_id.return_value = None
            mock_asset.restore_allocation_by_xboard_node_id.return_value = 0

            result = node_registry.sync_with_xboard()

            assert result["created"] == 1
            assert result["already_synced"] == 0
            mock_state.create_node.assert_called_once()

    def test_sync_with_xboard_restores_deleted_nodes(
        self, node_registry: NodeRegistryService
    ) -> None:
        """Test sync restores deleted nodes found in Xboard."""
        with patch.object(node_registry, "_xboard_repo") as mock_xboard, \
             patch.object(node_registry, "_state_repo") as mock_state, \
             patch.object(node_registry, "_asset_repo") as mock_asset:
            xboard_node = MagicMock()
            xboard_node.node_id = 12345
            xboard_node.node_name = "sf-test-node"
            xboard_node.node_type = "AnyTLS"
            mock_xboard.list_all_shadowfleet_nodes.return_value = [xboard_node]
            mock_state.list_active_nodes.return_value = []

            deleted_node = MagicMock()
            deleted_node.id = 1
            deleted_node.xboard_node_id = 12345
            mock_state.get_deleted_node_by_xboard_id.return_value = deleted_node
            mock_state.restore_deleted_node.return_value = True
            mock_asset.restore_allocation_by_xboard_node_id.return_value = 1

            result = node_registry.sync_with_xboard()

            assert result["restored"] == 1
            mock_state.restore_deleted_node.assert_called_once_with(12345, status="online")

    def test_sync_with_xboard_marks_orphan_nodes_deleted(
        self, node_registry: NodeRegistryService
    ) -> None:
        """Test sync marks orphan local nodes as deleted."""
        with patch.object(node_registry, "_xboard_repo") as mock_xboard, \
             patch.object(node_registry, "_state_repo") as mock_state:
            mock_xboard.list_all_shadowfleet_nodes.return_value = []

            local_node = MagicMock()
            local_node.id = 1
            local_node.xboard_node_id = 12345
            local_node.node_name = "test-node"
            local_node.status = "online"
            mock_state.list_active_nodes.return_value = [local_node]

            result = node_registry.sync_with_xboard()

            assert result["orphan_local_deleted"] == 1
            mock_state.mark_node_deleted.assert_called_once()

    def test_sync_with_xboard_handles_xboard_unavailable(
        self, node_registry: NodeRegistryService
    ) -> None:
        """Test sync handles Xboard being unavailable."""
        from database.xboard_repo import XboardRepoError

        with patch.object(node_registry, "_xboard_repo") as mock_xboard:
            mock_xboard.list_all_shadowfleet_nodes.side_effect = XboardRepoError("Connection failed")

            result = node_registry.sync_with_xboard()

            assert result["created"] == -1
            assert result["restored"] == -1
            assert result["orphan_local_deleted"] == -1
            assert result["already_synced"] == -1

    def test_strip_sf_prefix(self) -> None:
        """Test stripping sf- prefix from node names."""
        assert NodeRegistryService._strip_sf_prefix("sf-test-node") == "test-node"
        assert NodeRegistryService._strip_sf_prefix("test-node") == "test-node"
        assert NodeRegistryService._strip_sf_prefix("sf-") == ""
