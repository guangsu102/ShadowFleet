"""
Unit tests for OrphanResourceCleaner service
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, call, patch

import pytest

from services.orphan_resource_cleaner import (
    CleanupReport,
    CleanupResult,
    OrphanResourceCleaner,
    OrphanResourceCleanerError,
)
from services.orphan_resource_detector import (
    OrphanAssetAllocation,
    OrphanAzureNetworkResource,
    OrphanAzureVm,
    OrphanDnsRecord,
    OrphanEc2Instance,
    OrphanResourceReport,
    OrphanVultrInstance,
    OrphanXboardNode,
)


@pytest.fixture
def mock_ctx() -> MagicMock:
    """Create a mock RuntimeContext."""
    ctx = MagicMock()
    ctx.correlation_id = "test-correlation-123"
    ctx.logger = MagicMock()
    ctx.logger.getChild.return_value = MagicMock()
    ctx.config = MagicMock()
    return ctx


@pytest.fixture
def cleaner(mock_ctx: MagicMock) -> OrphanResourceCleaner:
    """Create an OrphanResourceCleaner instance."""
    return OrphanResourceCleaner(mock_ctx)


@pytest.fixture
def sample_report() -> OrphanResourceReport:
    """Create a sample orphan resource report."""
    ec2 = OrphanEc2Instance(
        instance_id="i-1234567890",
        region="us-east-1",
        account_id="123456789012",
        launch_time="2026-05-10T10:00:00Z",
        state="running",
        tags={"Name": "orphan-instance"},
    )
    dns = OrphanDnsRecord(
        record_id="rec-123",
        domain_name="orphan.example.com",
        record_type="AAAA",
        content="2600:1f14:804:as03:1234::",
        proxied=True,
        created_on="2026-05-10T10:00:00Z",
    )
    allocation = OrphanAssetAllocation(
        allocation_id=1,
        asset_id=10,
        xboard_node_id=100,
        protocol_type="AnyTLS",
        allocated_at="2026-05-10T10:00:00Z",
    )
    xboard = OrphanXboardNode(
        xboard_node_id=200,
        node_name="sf-orphan-node",
        node_type="Trojan",
        host="orphan-node.example.com",
        show=True,
    )
    return OrphanResourceReport(
        scan_time="2026-05-10T10:00:00Z",
        ec2_instances=[ec2],
        dns_records=[dns],
        asset_allocations=[allocation],
        xboard_nodes=[xboard],
        total_count=4,
    )


class TestCleanupResult:
    """Test CleanupResult dataclass."""

    def test_result_creation_success(self) -> None:
        """Test creating a successful cleanup result."""
        result = CleanupResult(
            resource_type="ec2",
            resource_id="i-1234567890",
            success=True,
            error_message=None,
        )
        assert result.success is True
        assert result.error_message is None

    def test_result_creation_failure(self) -> None:
        """Test creating a failed cleanup result."""
        result = CleanupResult(
            resource_type="dns",
            resource_id="rec-123",
            success=False,
            error_message="API error",
        )
        assert result.success is False
        assert result.error_message == "API error"


class TestCleanupReport:
    """Test CleanupReport dataclass."""

    def test_report_creation(self) -> None:
        """Test creating a cleanup report."""
        results = [
            CleanupResult("ec2", "i-123", True),
            CleanupResult("dns", "rec-123", False, "Error"),
        ]
        report = CleanupReport(
            cleanup_time="2026-05-10T10:00:00Z",
            total_attempted=2,
            total_succeeded=1,
            total_failed=1,
            results=results,
        )
        assert report.total_attempted == 2
        assert report.total_succeeded == 1
        assert len(report.results) == 2


class TestOrphanResourceCleaner:
    """Test OrphanResourceCleaner implementation."""

    def test_initialization(self, cleaner: OrphanResourceCleaner) -> None:
        """Test OrphanResourceCleaner initializes correctly."""
        assert cleaner is not None

    def test_cleanup_vultr_instance_uses_owning_asset(
        self, cleaner: OrphanResourceCleaner
    ) -> None:
        instance = OrphanVultrInstance(
            instance_id="vultr-instance-1",
            asset_id=9,
            region="sgp",
            label="orphan",
            created_at="2026-05-10T10:00:00Z",
            status="running",
            tags=("shadowfleet",),
            firewall_group_id="firewall-id",
        )
        asset = MagicMock(asset_type="vultr", aws_access_key="token")
        with patch.object(cleaner, "_asset_repo") as asset_repo, \
             patch("services.orphan_resource_cleaner.VultrClient") as client_cls:
            asset_repo.get_asset_by_id.return_value = asset
            result = cleaner._cleanup_vultr_instances([instance], dry_run=False)

        assert result[0].success is True
        client_cls.return_value.delete_managed_firewall_group.assert_called_once_with(
            "firewall-id"
        )
        client_cls.return_value.delete_instance.assert_called_once_with("vultr-instance-1")

    def test_cleanup_azure_vm_uses_owning_asset(
        self, cleaner: OrphanResourceCleaner
    ) -> None:
        vm = OrphanAzureVm(
            vm_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/orphan",
            asset_id=10,
            location="japaneast",
            name="orphan",
            created_at="2026-05-10T10:00:00Z",
            state="running",
            tags={"shadowfleet": "true"},
        )
        asset = MagicMock(
            asset_type="azure",
            aws_access_key="client",
            aws_secret_key="secret",
            provider_config={"tenant_id": "tenant", "subscription_id": "sub"},
        )
        with patch.object(cleaner, "_asset_repo") as asset_repo, \
             patch("services.orphan_resource_cleaner.AzureClient") as client_cls:
            asset_repo.get_asset_by_id.return_value = asset
            result = cleaner._cleanup_azure_vms([vm], dry_run=False)

        assert result[0].success is True
        client_cls.return_value.delete_vm.assert_called_once_with(vm.vm_id)

    def test_cleanup_azure_network_resources_uses_dependency_order(
        self, cleaner: OrphanResourceCleaner
    ) -> None:
        common = {
            "asset_id": 10,
            "location": "japaneast",
            "parent_vm_name": "orphan",
            "created_at": "2000-01-01T00:00:00Z",
            "tags": {"shadowfleet": "true"},
        }
        resources = [
            OrphanAzureNetworkResource(
                resource_id="nsg",
                resource_type="azure_network_security_group",
                name="orphan-nsg",
                **common,
            ),
            OrphanAzureNetworkResource(
                resource_id="pip",
                resource_type="azure_public_ip_address",
                name="orphan-ipv4",
                **common,
            ),
            OrphanAzureNetworkResource(
                resource_id="nic",
                resource_type="azure_network_interface",
                name="orphan-nic",
                **common,
            ),
        ]
        client = MagicMock()
        with patch.object(cleaner, "_build_azure_client", return_value=client):
            result = cleaner._cleanup_azure_network_resources(
                resources,
                dry_run=False,
            )

        assert [item.success for item in result] == [True, True, True]
        assert client.method_calls == [
            call.delete_network_interface("nic"),
            call.delete_public_ip_address("pip"),
            call.delete_network_security_group("nsg"),
        ]

    def test_cleanup_empty_report(
        self, cleaner: OrphanResourceCleaner
    ) -> None:
        """Test cleanup with empty report."""
        empty_report = OrphanResourceReport(
            scan_time="2026-05-10T10:00:00Z",
            ec2_instances=[],
            dns_records=[],
            asset_allocations=[],
            xboard_nodes=[],
            total_count=0,
        )

        report = cleaner.cleanup_orphan_resources(empty_report)

        assert report.total_attempted == 0
        assert report.total_succeeded == 0
        assert report.total_failed == 0

    def test_cleanup_dry_run_mode(
        self, cleaner: OrphanResourceCleaner, sample_report: OrphanResourceReport
    ) -> None:
        """Test cleanup in dry run mode."""
        with patch.object(
            cleaner, "_cleanup_ec2_instances"
        ) as mock_ec2, patch.object(
            cleaner, "_cleanup_dns_records"
        ) as mock_dns, patch.object(
            cleaner, "_cleanup_asset_allocations"
        ) as mock_alloc, patch.object(
            cleaner, "_cleanup_xboard_nodes"
        ) as mock_xboard:
            mock_ec2.return_value = [CleanupResult("ec2", "i-1234567890", True)]
            mock_dns.return_value = [CleanupResult("dns", "rec-123", True)]
            mock_alloc.return_value = [CleanupResult("allocation", "1", True)]
            mock_xboard.return_value = [CleanupResult("xboard", "200", True)]

            report = cleaner.cleanup_orphan_resources(
                sample_report, dry_run=True
            )

            mock_ec2.assert_called_once()
            mock_dns.assert_called_once()
            mock_alloc.assert_called_once()
            mock_xboard.assert_called_once()
            assert report.total_attempted == 4

    def test_cleanup_all_resources_success(
        self, cleaner: OrphanResourceCleaner, sample_report: OrphanResourceReport
    ) -> None:
        """Test successful cleanup of all resources."""
        with patch.object(
            cleaner, "_cleanup_ec2_instances"
        ) as mock_ec2, patch.object(
            cleaner, "_cleanup_dns_records"
        ) as mock_dns, patch.object(
            cleaner, "_cleanup_asset_allocations"
        ) as mock_alloc, patch.object(
            cleaner, "_cleanup_xboard_nodes"
        ) as mock_xboard:
            mock_ec2.return_value = [CleanupResult("ec2", "i-1234567890", True)]
            mock_dns.return_value = [CleanupResult("dns", "rec-123", True)]
            mock_alloc.return_value = [CleanupResult("allocation", "1", True)]
            mock_xboard.return_value = [CleanupResult("xboard", "200", True)]

            report = cleaner.cleanup_orphan_resources(sample_report)

            assert report.total_attempted == 4
            assert report.total_succeeded == 4
            assert report.total_failed == 0

    def test_cleanup_partial_failure(
        self, cleaner: OrphanResourceCleaner, sample_report: OrphanResourceReport
    ) -> None:
        """Test cleanup with partial failures."""
        with patch.object(
            cleaner, "_cleanup_ec2_instances"
        ) as mock_ec2, patch.object(
            cleaner, "_cleanup_dns_records"
        ) as mock_dns, patch.object(
            cleaner, "_cleanup_asset_allocations"
        ) as mock_alloc, patch.object(
            cleaner, "_cleanup_xboard_nodes"
        ) as mock_xboard:
            mock_ec2.return_value = [CleanupResult("ec2", "i-1234567890", True)]
            mock_dns.return_value = [CleanupResult(
                "dns", "rec-123", False, "API error"
            )]
            mock_alloc.return_value = [CleanupResult("allocation", "1", True)]
            mock_xboard.return_value = [CleanupResult(
                "xboard", "200", False, "Not found"
            )]

            report = cleaner.cleanup_orphan_resources(sample_report)

            assert report.total_attempted == 4
            assert report.total_succeeded == 2
            assert report.total_failed == 2
