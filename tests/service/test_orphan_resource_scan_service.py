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
