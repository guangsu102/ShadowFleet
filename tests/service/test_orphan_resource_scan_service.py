"""
Unit tests for OrphanResourceScanService
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from services.orphan_resource_scan_service import (
    DatabaseConsistencyResult,
    OrphanCleanupResult,
    OrphanResourceInfo,
    OrphanResourceScanService,
)


@pytest.fixture
def mock_ctx() -> MagicMock:
    """Create a mock RuntimeContext."""
    ctx = MagicMock()
    ctx.correlation_id = "test-correlation-123"
    ctx.logger = MagicMock()
    ctx.config = MagicMock()
    ctx.config.app = MagicMock()
    return ctx


@pytest.fixture
def mock_state_repo() -> MagicMock:
    """Create a mock StateRepo."""
    mock = MagicMock()
    mock.list_active_nodes.return_value = []
    mock.get_node_by_xboard_node_id.return_value = None
    return mock


@pytest.fixture
def mock_asset_repo() -> MagicMock:
    """Create a mock AssetRepo."""
    mock = MagicMock()
    mock.list_assets_by_status.return_value = []
    mock.list_assets_by_aws_account_id.return_value = []
    return mock


@pytest.fixture
def mock_node_registry() -> MagicMock:
    """Create a mock NodeRegistryService."""
    mock = MagicMock()
    mock.list_all_nodes.return_value = []
    mock.delete_node.return_value = None
    return mock


@pytest.fixture
def scan_service(mock_ctx: MagicMock) -> OrphanResourceScanService:
    """Create an OrphanResourceScanService instance."""
    with patch("services.orphan_resource_scan_service.StateRepo"), \
         patch("services.orphan_resource_scan_service.AssetRepo"), \
         patch("services.orphan_resource_scan_service.NodeRegistryService"), \
         patch("services.orphan_resource_scan_service.OrphanNodeCleanupService"), \
         patch("services.orphan_resource_scan_service.AssetSelectorService"):
        return OrphanResourceScanService(mock_ctx)


class TestOrphanResourceInfo:
    """Test OrphanResourceInfo dataclass."""

    def test_orphan_info_creation(self) -> None:
        """Test creating orphan resource info."""
        info = OrphanResourceInfo(
            resource_type="ec2_instance",
            resource_id="i-1234567890",
            region="ap-northeast-1",
            aws_account_id="aws-001",
            reason="Instance exists in AWS but not in SQLite",
            discovered_at="2026-05-10T10:00:00Z",
        )
        assert info.resource_type == "ec2_instance"
        assert info.resource_id == "i-1234567890"
        assert info.region == "ap-northeast-1"
        assert info.aws_account_id == "aws-001"

    def test_orphan_info_is_frozen(self) -> None:
        """Test that OrphanResourceInfo is immutable."""
        info = OrphanResourceInfo(
            resource_type="xboard_node",
            resource_id="12345",
            xboard_node_id=12345,
        )
        with pytest.raises(AttributeError):
            info.resource_type = "ec2_instance"  # type: ignore


class TestOrphanCleanupResult:
    """Test OrphanCleanupResult dataclass."""

    def test_cleanup_result_creation(self) -> None:
        """Test creating cleanup result."""
        result = OrphanCleanupResult(
            scan_duration_seconds=45.5,
            total_resources_scanned=100,
            orphans_found=5,
            orphans_cleaned=4,
            orphans_failed=1,
            orphans=(),
            errors=("Error 1",),
        )
        assert result.scan_duration_seconds == 45.5
        assert result.total_resources_scanned == 100
        assert result.orphans_found == 5
        assert result.orphans_cleaned == 4
        assert result.orphans_failed == 1


class TestDatabaseConsistencyResult:
    """Test DatabaseConsistencyResult dataclass."""

    def test_consistency_result_creation(self) -> None:
        """Test creating consistency result."""
        result = DatabaseConsistencyResult(
            sqlite_only_nodes=(1, 2, 3),
            xboard_only_nodes=(4, 5),
            status_mismatch=("node-123",),
            inconsistent_allocations=(),
        )
        assert len(result.sqlite_only_nodes) == 3
        assert len(result.xboard_only_nodes) == 2
        assert len(result.status_mismatch) == 1


class TestOrphanResourceScanService:
    """Test OrphanResourceScanService."""

    def test_initialization(self, scan_service: OrphanResourceScanService) -> None:
        """Test service initializes correctly."""
        assert scan_service is not None

    def test_check_database_consistency_no_issues(
        self, scan_service: OrphanResourceScanService
    ) -> None:
        """Test consistency check when databases are in sync."""
        with patch.object(scan_service, "_node_registry") as mock_registry, \
             patch.object(scan_service, "_state_repo") as mock_state:
            # Both have same nodes
            mock_node = MagicMock()
            mock_node.xboard_node_id = 12345
            mock_registry.list_all_nodes.return_value = [mock_node]
            mock_state.list_active_nodes.return_value = [mock_node]

            result = scan_service.check_database_consistency()

            assert len(result.sqlite_only_nodes) == 0
            assert len(result.xboard_only_nodes) == 0

    def test_check_database_consistency_sqlite_only(
        self, scan_service: OrphanResourceScanService
    ) -> None:
        """Test consistency check finds SQLite-only nodes."""
        with patch.object(scan_service, "_node_registry") as mock_registry, \
             patch.object(scan_service, "_state_repo") as mock_state:
            # SQLite has node that Xboard doesn't
            sqlite_node = MagicMock()
            sqlite_node.xboard_node_id = 12345
            mock_registry.list_all_nodes.return_value = []
            mock_state.list_active_nodes.return_value = [sqlite_node]

            result = scan_service.check_database_consistency()

            assert 12345 in result.sqlite_only_nodes
            assert len(result.xboard_only_nodes) == 0

    def test_check_database_consistency_xboard_only(
        self, scan_service: OrphanResourceScanService
    ) -> None:
        """Test consistency check finds Xboard-only nodes."""
        with patch.object(scan_service, "_node_registry") as mock_registry, \
             patch.object(scan_service, "_state_repo") as mock_state:
            # Xboard has node that SQLite doesn't
            xboard_node = MagicMock()
            xboard_node.xboard_node_id = 67890
            mock_registry.list_all_nodes.return_value = [xboard_node]
            mock_state.list_active_nodes.return_value = []

            result = scan_service.check_database_consistency()

            assert 67890 in result.xboard_only_nodes
            assert len(result.sqlite_only_nodes) == 0

    def test_scan_ec2_orphans_no_orphans(
        self, scan_service: OrphanResourceScanService
    ) -> None:
        """Test EC2 orphan scan when no orphans exist."""
        with patch.object(scan_service, "_asset_repo") as mock_asset, \
             patch.object(scan_service, "_state_repo") as mock_state:
            mock_asset.list_assets_by_status.return_value = []
            mock_state.list_active_nodes.return_value = []

            orphans = scan_service._scan_ec2_orphans()

            assert len(orphans) == 0

    def test_scan_node_orphans_no_orphans(
        self, scan_service: OrphanResourceScanService
    ) -> None:
        """Test node orphan scan when no orphans exist."""
        with patch.object(scan_service, "_state_repo") as mock_state:
            mock_state.list_active_nodes.return_value = []

            orphans = scan_service._scan_node_orphans()

            assert len(orphans) == 0

    def test_scan_node_orphans_finds_terminated_instance(
        self, scan_service: OrphanResourceScanService
    ) -> None:
        """Test node orphan scan finds nodes with terminated instances."""
        with patch.object(scan_service, "_state_repo") as mock_state, \
             patch.object(scan_service, "_asset_repo") as mock_asset, \
             patch("services.orphan_resource_scan_service.EC2Client") as mock_ec2_cls:
            # Setup node with terminated instance
            node = MagicMock()
            node.xboard_node_id = 12345
            node.aws_instance_id = "i-terminated"
            node.aws_account_id = "aws-001"
            node.aws_region = "ap-northeast-1"
            mock_state.list_active_nodes.return_value = [node]

            # Setup asset
            asset = MagicMock()
            asset.aws_access_key = "key"
            mock_asset.list_assets_by_aws_account_id.return_value = [asset]

            # Setup EC2 client to return terminated state
            mock_ec2 = MagicMock()
            mock_ec2.get_instance_state.return_value = "terminated"
            mock_ec2_cls.return_value = mock_ec2

            orphans = scan_service._scan_node_orphans()

            assert len(orphans) == 1
            assert orphans[0].resource_type == "xboard_node"
            assert orphans[0].xboard_node_id == 12345

    def test_scan_node_orphans_checks_vultr_with_vultr_api(
        self, scan_service: OrphanResourceScanService
    ) -> None:
        node = MagicMock()
        node.xboard_node_id = 12345
        node.aws_instance_id = "vultr-instance"
        node.aws_account_id = "vultr:account"
        node.aws_region = "sgp"
        node.asset_type = "vultr"
        asset = MagicMock(asset_type="vultr", aws_access_key="token")
        scan_service._state_repo.list_active_nodes.return_value = [node]
        scan_service._asset_repo.get_asset_by_xboard_node_id.return_value = asset
        with patch("services.orphan_resource_scan_service.VultrClient") as client_cls:
            from infrastructure.vultr import VultrClientError
            client_cls.return_value.get_instance.side_effect = VultrClientError(
                "not found", status_code=404
            )

            orphans = scan_service._scan_node_orphans()

        assert len(orphans) == 1
        assert orphans[0].resource_type == "xboard_node"
        assert orphans[0].reason == "Vultr instance not found"

    def test_scan_vultr_node_uses_account_asset_when_allocation_is_missing(
        self, scan_service: OrphanResourceScanService
    ) -> None:
        node = MagicMock()
        node.xboard_node_id = 12346
        node.aws_instance_id = "vultr-instance"
        node.aws_account_id = "vultr:account"
        node.aws_region = "sgp"
        node.asset_type = "vultr"
        asset = MagicMock(asset_type="vultr", aws_access_key="token")
        scan_service._asset_repo.get_asset_by_xboard_node_id.return_value = None
        scan_service._asset_repo.list_assets_by_aws_account_id.return_value = [asset]

        with patch("services.orphan_resource_scan_service.VultrClient") as client_cls:
            orphan = scan_service._scan_vultr_node_orphan(node)

        assert orphan is None
        client_cls.return_value.get_instance.assert_called_once_with("vultr-instance")
        scan_service._asset_repo.list_assets_by_aws_account_id.assert_called_once_with(
            "vultr:account"
        )

    def test_scan_node_orphans_skips_aws_when_asset_credentials_are_missing(
        self, scan_service: OrphanResourceScanService
    ) -> None:
        node = MagicMock(
            xboard_node_id=12347,
            aws_instance_id="i-unknown",
            aws_account_id="aws-missing",
            aws_region="ap-northeast-1",
            asset_type="aws",
        )
        scan_service._state_repo.list_active_nodes.return_value = [node]
        scan_service._asset_repo.list_assets_by_aws_account_id.return_value = []

        assert scan_service._scan_node_orphans() == []

    def test_scan_node_orphans_skips_azure_when_credentials_are_missing(
        self, scan_service: OrphanResourceScanService
    ) -> None:
        node = MagicMock(
            xboard_node_id=12348,
            aws_instance_id="/subscriptions/sub/resourceGroups/rg/providers/"
            "Microsoft.Compute/virtualMachines/vm",
            aws_account_id="azure:sub",
            aws_region="japaneast",
            asset_type="azure",
        )
        scan_service._state_repo.list_active_nodes.return_value = [node]
        scan_service._asset_repo.get_asset_by_xboard_node_id.return_value = None
        scan_service._asset_repo.list_assets_by_aws_account_id.return_value = []

        assert scan_service._scan_node_orphans() == []

    def test_scan_node_orphans_treats_azure_forbidden_as_indeterminate(
        self, scan_service: OrphanResourceScanService
    ) -> None:
        from infrastructure.azure import AzureClientError

        node = MagicMock(
            xboard_node_id=12349,
            aws_instance_id="/subscriptions/sub/resourceGroups/rg/providers/"
            "Microsoft.Compute/virtualMachines/vm",
            aws_account_id="azure:sub",
            aws_region="japaneast",
            asset_type="azure",
        )
        asset = MagicMock(asset_type="azure")
        scan_service._state_repo.list_active_nodes.return_value = [node]
        scan_service._asset_repo.get_asset_by_xboard_node_id.return_value = asset
        with patch.object(scan_service, "_build_azure_client") as build_client:
            build_client.return_value.get_vm.side_effect = AzureClientError(
                "forbidden", status_code=403
            )

            orphans = scan_service._scan_node_orphans()

        assert orphans == []

    def test_scan_node_orphans_confirms_azure_orphan_on_not_found(
        self, scan_service: OrphanResourceScanService
    ) -> None:
        from infrastructure.azure import AzureClientError

        node = MagicMock(
            xboard_node_id=12350,
            aws_instance_id="/subscriptions/sub/resourceGroups/rg/providers/"
            "Microsoft.Compute/virtualMachines/vm",
            aws_account_id="azure:sub",
            aws_region="japaneast",
            asset_type="azure",
        )
        asset = MagicMock(asset_type="azure")
        scan_service._state_repo.list_active_nodes.return_value = [node]
        scan_service._asset_repo.get_asset_by_xboard_node_id.return_value = asset
        with patch.object(scan_service, "_build_azure_client") as build_client:
            build_client.return_value.get_vm.side_effect = AzureClientError(
                "not found", status_code=404
            )

            orphans = scan_service._scan_node_orphans()

        assert len(orphans) == 1
        assert orphans[0].resource_type == "xboard_node"
        assert orphans[0].reason == "Azure VM not found"

    def test_scan_azure_orphans_includes_old_network_resources_without_vm(
        self, scan_service: OrphanResourceScanService
    ) -> None:
        old_timestamp = "2000-01-01T00:00:00Z"
        tags = {
            "shadowfleet": "true",
            "shadowfleet_created_at": old_timestamp,
        }
        asset = MagicMock(
            id=11,
            asset_type="azure",
            aws_account_id="azure:sub",
            region="japaneast",
            provider_config={"resource_group": "rg", "subscription_id": "sub"},
        )
        duplicate_scope_asset = MagicMock(
            id=12,
            asset_type="azure",
            aws_account_id="azure:sub",
            region="eastus",
            provider_config={"resource_group": "RG", "subscription_id": "SUB"},
        )
        scan_service._asset_repo.list_assets_by_status.return_value = [
            asset,
            duplicate_scope_asset,
        ]
        scan_service._state_repo.list_active_nodes.return_value = []
        with patch.object(scan_service, "_build_azure_client") as build_client:
            client = build_client.return_value
            client.list_virtual_machines.return_value = []
            client.list_network_interfaces.return_value = [
                {
                    "id": "nic",
                    "name": "orphan-nic",
                    "location": "japaneast",
                    "tags": tags,
                },
                {
                    "id": "legacy-nic",
                    "name": "legacy-nic",
                    "location": "japaneast",
                    "tags": {"shadowfleet": "true"},
                },
            ]
            client.list_public_ip_addresses.return_value = [
                {
                    "id": "pip",
                    "name": "orphan-ipv6",
                    "location": "japaneast",
                    "tags": tags,
                }
            ]
            client.list_network_security_groups.return_value = [
                {
                    "id": "nsg",
                    "name": "orphan-nsg",
                    "location": "japaneast",
                    "tags": tags,
                }
            ]

            orphans = scan_service._scan_azure_orphans()

        assert [orphan.resource_type for orphan in orphans] == [
            "azure_network_interface",
            "azure_public_ip_address",
            "azure_network_security_group",
        ]
        assert [orphan.resource_id for orphan in orphans] == ["nic", "pip", "nsg"]
        assert build_client.call_count == 1

    def test_scan_azure_orphans_returns_no_partial_results_on_list_failure(
        self, scan_service: OrphanResourceScanService
    ) -> None:
        asset = MagicMock(
            id=11,
            asset_type="azure",
            aws_account_id="azure:sub",
            region="japaneast",
            provider_config={"resource_group": "rg", "subscription_id": "sub"},
        )
        scan_service._asset_repo.list_assets_by_status.return_value = [asset]
        scan_service._state_repo.list_active_nodes.return_value = []
        with patch.object(scan_service, "_build_azure_client") as build_client:
            client = build_client.return_value
            client.list_virtual_machines.return_value = [
                {
                    "id": "vm",
                    "name": "orphan",
                    "tags": {"shadowfleet": "true"},
                    "properties": {"timeCreated": "2000-01-01T00:00:00Z"},
                }
            ]
            client.list_network_interfaces.return_value = []
            client.list_public_ip_addresses.side_effect = RuntimeError(
                "Azure list failed"
            )

            orphans = scan_service._scan_azure_orphans()

        assert orphans == []

    def test_cleanup_azure_network_orphan_dispatches_by_resource_type(
        self, scan_service: OrphanResourceScanService
    ) -> None:
        orphan = OrphanResourceInfo(
            resource_type="azure_public_ip_address",
            resource_id="pip",
            asset_id=11,
        )
        asset = MagicMock(asset_type="azure")
        scan_service._asset_repo.get_asset_by_id.return_value = asset
        with patch.object(scan_service, "_build_azure_client") as build_client:
            cleaned = scan_service._cleanup_azure_network_orphan(orphan)

        assert cleaned is True
        build_client.return_value.delete_public_ip_address.assert_called_once_with(
            "pip"
        )

    def test_cleanup_orphan_resource_ec2(
        self, scan_service: OrphanResourceScanService
    ) -> None:
        """Test cleanup of EC2 orphan instance."""
        orphan = OrphanResourceInfo(
            resource_type="ec2_instance",
            resource_id="i-orphan",
            aws_account_id="aws-001",
            region="ap-northeast-1",
        )

        with patch.object(scan_service, "_cleanup_ec2_orphan", return_value=True):
            result = scan_service._cleanup_orphan_resource(orphan)
            assert result is True

    def test_cleanup_orphan_resource_node(
        self, scan_service: OrphanResourceScanService
    ) -> None:
        """Test cleanup of node orphan."""
        orphan = OrphanResourceInfo(
            resource_type="xboard_node",
            resource_id="12345",
            xboard_node_id=12345,
        )

        with patch.object(scan_service, "_cleanup_node_orphan", return_value=True):
            result = scan_service._cleanup_orphan_resource(orphan)
            assert result is True

    def test_cleanup_orphan_resource_unknown_type(
        self, scan_service: OrphanResourceScanService
    ) -> None:
        """Test cleanup of unknown orphan type."""
        orphan = OrphanResourceInfo(
            resource_type="unknown_type",
            resource_id="test",
        )

        result = scan_service._cleanup_orphan_resource(orphan)
        assert result is False

    def test_run_orphan_scan_cycle_success(
        self, scan_service: OrphanResourceScanService
    ) -> None:
        """Test successful orphan scan cycle."""
        with patch.object(scan_service, "check_database_consistency") as mock_check, \
             patch.object(scan_service, "_scan_ec2_orphans", return_value=[]), \
             patch.object(scan_service, "_scan_node_orphans", return_value=[]), \
             patch.object(scan_service, "_scan_allocation_orphans", return_value=[]), \
             patch.object(scan_service, "_log_consistency_issues"), \
             patch.object(scan_service, "_send_orphan_alert"):
            mock_check.return_value = DatabaseConsistencyResult(
                sqlite_only_nodes=(),
                xboard_only_nodes=(),
                status_mismatch=(),
                inconsistent_allocations=(),
            )

            result = scan_service.run_orphan_scan_cycle()

            assert isinstance(result, OrphanCleanupResult)
            assert result.orphans_found == 0
            assert result.orphans_cleaned == 0
            assert result.orphans_failed == 0

    def test_run_orphan_scan_cycle_with_orphans(
        self, scan_service: OrphanResourceScanService
    ) -> None:
        """Test orphan scan cycle finds and cleans orphans."""
        orphan = OrphanResourceInfo(
            resource_type="ec2_instance",
            resource_id="i-orphan",
            aws_account_id="aws-001",
        )

        with patch.object(scan_service, "check_database_consistency") as mock_check, \
             patch.object(scan_service, "_scan_ec2_orphans", return_value=[orphan]), \
             patch.object(scan_service, "_scan_node_orphans", return_value=[]), \
             patch.object(scan_service, "_scan_allocation_orphans", return_value=[]), \
             patch.object(scan_service, "_cleanup_orphan_resource", return_value=True), \
             patch.object(scan_service, "_log_consistency_issues"), \
             patch.object(scan_service, "_send_orphan_alert"):
            mock_check.return_value = DatabaseConsistencyResult(
                sqlite_only_nodes=(),
                xboard_only_nodes=(),
                status_mismatch=(),
                inconsistent_allocations=(),
            )

            result = scan_service.run_orphan_scan_cycle()

            assert result.orphans_found == 1
            assert result.orphans_cleaned == 1
            assert result.orphans_failed == 0

    def test_run_orphan_scan_cycle_cleanup_failure(
        self, scan_service: OrphanResourceScanService
    ) -> None:
        """Test orphan scan cycle handles cleanup failures."""
        orphan = OrphanResourceInfo(
            resource_type="ec2_instance",
            resource_id="i-orphan",
            aws_account_id="aws-001",
        )

        with patch.object(scan_service, "check_database_consistency") as mock_check, \
             patch.object(scan_service, "_scan_ec2_orphans", return_value=[orphan]), \
             patch.object(scan_service, "_scan_node_orphans", return_value=[]), \
             patch.object(scan_service, "_scan_allocation_orphans", return_value=[]), \
             patch.object(scan_service, "_cleanup_orphan_resource", return_value=False), \
             patch.object(scan_service, "_log_consistency_issues"), \
             patch.object(scan_service, "_send_orphan_alert"):
            mock_check.return_value = DatabaseConsistencyResult(
                sqlite_only_nodes=(),
                xboard_only_nodes=(),
                status_mismatch=(),
                inconsistent_allocations=(),
            )

            result = scan_service.run_orphan_scan_cycle()

            assert result.orphans_found == 1
            assert result.orphans_cleaned == 0
            assert result.orphans_failed == 1

    def test_get_scan_history(
        self, scan_service: OrphanResourceScanService
    ) -> None:
        """Test getting scan history."""
        # Add some results to history
        result1 = OrphanCleanupResult(
            scan_duration_seconds=10.0,
            total_resources_scanned=50,
            orphans_found=2,
            orphans_cleaned=2,
            orphans_failed=0,
            orphans=(),
            errors=(),
        )
        scan_service._scan_history.append(result1)

        history = scan_service.get_scan_history(limit=10)

        assert len(history) == 1
        assert history[0].orphans_found == 2
