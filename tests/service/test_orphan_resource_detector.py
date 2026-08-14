"""
Unit tests for OrphanResourceDetector service
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from services.orphan_resource_detector import (
    OrphanAssetAllocation,
    OrphanAzureNetworkResource,
    OrphanAzureVm,
    OrphanDnsRecord,
    OrphanEc2Instance,
    OrphanResourceDetector,
    OrphanResourceDetectorError,
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
def detector(mock_ctx: MagicMock) -> OrphanResourceDetector:
    """Create an OrphanResourceDetector instance."""
    return OrphanResourceDetector(mock_ctx)


class TestOrphanEc2Instance:
    """Test OrphanEc2Instance dataclass."""

    def test_instance_creation(self) -> None:
        """Test creating an orphan EC2 instance."""
        instance = OrphanEc2Instance(
            instance_id="i-1234567890",
            region="us-east-1",
            account_id="123456789012",
            launch_time="2026-05-10T10:00:00Z",
            state="running",
            tags={"Name": "test-instance"},
        )
        assert instance.instance_id == "i-1234567890"
        assert instance.region == "us-east-1"
        assert instance.state == "running"

    def test_instance_is_frozen(self) -> None:
        """Test that OrphanEc2Instance is immutable."""
        instance = OrphanEc2Instance(
            instance_id="i-1234567890",
            region="us-east-1",
            account_id="123456789012",
            launch_time="2026-05-10T10:00:00Z",
            state="running",
            tags={},
        )
        with pytest.raises(AttributeError):
            instance.state = "stopped"  # type: ignore


class TestOrphanDnsRecord:
    """Test OrphanDnsRecord dataclass."""

    def test_record_creation(self) -> None:
        """Test creating an orphan DNS record."""
        record = OrphanDnsRecord(
            record_id="rec-123",
            domain_name="test.example.com",
            record_type="AAAA",
            content="2600:1f14:804:as03:1234::",
            proxied=True,
            created_on="2026-05-10T10:00:00Z",
        )
        assert record.record_id == "rec-123"
        assert record.domain_name == "test.example.com"
        assert record.proxied is True

    def test_record_is_frozen(self) -> None:
        """Test that OrphanDnsRecord is immutable."""
        record = OrphanDnsRecord(
            record_id="rec-123",
            domain_name="test.example.com",
            record_type="AAAA",
            content="2600::",
            proxied=True,
            created_on="2026-05-10T10:00:00Z",
        )
        with pytest.raises(AttributeError):
            record.proxied = False  # type: ignore


class TestOrphanAssetAllocation:
    """Test OrphanAssetAllocation dataclass."""

    def test_allocation_creation(self) -> None:
        """Test creating an orphan asset allocation."""
        allocation = OrphanAssetAllocation(
            allocation_id=1,
            asset_id=10,
            xboard_node_id=100,
            protocol_type="AnyTLS",
            allocated_at="2026-05-10T10:00:00Z",
        )
        assert allocation.allocation_id == 1
        assert allocation.asset_id == 10
        assert allocation.protocol_type == "AnyTLS"

    def test_allocation_is_frozen(self) -> None:
        """Test that OrphanAssetAllocation is immutable."""
        allocation = OrphanAssetAllocation(
            allocation_id=1,
            asset_id=10,
            xboard_node_id=100,
            protocol_type="AnyTLS",
            allocated_at="2026-05-10T10:00:00Z",
        )
        with pytest.raises(AttributeError):
            allocation.asset_id = 20  # type: ignore


class TestOrphanXboardNode:
    """Test OrphanXboardNode dataclass."""

    def test_node_creation(self) -> None:
        """Test creating an orphan Xboard node."""
        node = OrphanXboardNode(
            xboard_node_id=123,
            node_name="sf-test-node",
            node_type="AnyTLS",
            host="test.example.com",
            show=True,
        )
        assert node.xboard_node_id == 123
        assert node.node_name == "sf-test-node"
        assert node.show is True

    def test_node_is_frozen(self) -> None:
        """Test that OrphanXboardNode is immutable."""
        node = OrphanXboardNode(
            xboard_node_id=123,
            node_name="sf-test-node",
            node_type="AnyTLS",
            host="test.example.com",
            show=True,
        )
        with pytest.raises(AttributeError):
            node.show = False  # type: ignore


class TestOrphanResourceReport:
    """Test OrphanResourceReport dataclass."""

    def test_report_creation(self) -> None:
        """Test creating an orphan resource report."""
        report = OrphanResourceReport(
            scan_time="2026-05-10T10:00:00Z",
            ec2_instances=[],
            dns_records=[],
            asset_allocations=[],
            xboard_nodes=[],
            total_count=0,
        )
        assert report.total_count == 0
        assert len(report.ec2_instances) == 0

    def test_report_with_resources(self) -> None:
        """Test report with orphan resources."""
        ec2 = OrphanEc2Instance(
            instance_id="i-123",
            region="us-east-1",
            account_id="123456789012",
            launch_time="2026-05-10T10:00:00Z",
            state="running",
            tags={},
        )
        dns = OrphanDnsRecord(
            record_id="rec-123",
            domain_name="test.example.com",
            record_type="AAAA",
            content="2600::",
            proxied=True,
            created_on="2026-05-10T10:00:00Z",
        )
        report = OrphanResourceReport(
            scan_time="2026-05-10T10:00:00Z",
            ec2_instances=[ec2],
            dns_records=[dns],
            asset_allocations=[],
            xboard_nodes=[],
            total_count=2,
        )
        assert report.total_count == 2
        assert len(report.ec2_instances) == 1
        assert len(report.dns_records) == 1


class TestOrphanResourceDetector:
    """Test OrphanResourceDetector implementation."""

    def test_initialization(self, detector: OrphanResourceDetector) -> None:
        """Test OrphanResourceDetector initializes correctly."""
        assert detector is not None

    def test_scan_vultr_orphans_filters_known_and_recent_instances(
        self, detector: OrphanResourceDetector
    ) -> None:
        old_timestamp = "2026-05-10T10:00:00Z"
        asset = MagicMock(id=9, asset_type="vultr", aws_access_key="token", region="sgp")
        known_node = MagicMock(aws_instance_id="known-instance")
        with patch.object(detector, "_asset_repo") as asset_repo, \
             patch.object(detector, "_state_repo") as state_repo, \
             patch("services.orphan_resource_detector.VultrClient") as client_cls, \
             patch("services.orphan_resource_detector._is_older_than", return_value=True):
            asset_repo.list_assets_by_status.return_value = [asset]
            state_repo.list_active_nodes.return_value = [known_node]
            client_cls.return_value.list_instances.return_value = [
                {"id": "known-instance", "tags": ["shadowfleet"], "date_created": old_timestamp},
                {"id": "foreign", "tags": ["other"], "date_created": old_timestamp},
                {
                    "id": "orphan",
                    "tags": ["shadowfleet"],
                    "date_created": old_timestamp,
                    "region": "sgp",
                    "firewall_group_id": "firewall-id",
                },
            ]

            result = detector._scan_orphan_vultr_instances()

        assert result == [
            OrphanVultrInstance(
                instance_id="orphan",
                firewall_group_id="firewall-id",
                asset_id=9,
                region="sgp",
                label="",
                created_at=old_timestamp,
                status="unknown",
                tags=("shadowfleet",),
            )
        ]

    def test_scan_azure_orphans_filters_known_and_untagged_vms(
        self, detector: OrphanResourceDetector
    ) -> None:
        old_timestamp = "2026-05-10T10:00:00Z"
        orphan_id = (
            "/subscriptions/sub/resourceGroups/rg/providers/"
            "Microsoft.Compute/virtualMachines/orphan"
        )
        known_id = orphan_id.replace("orphan", "known")
        asset = MagicMock(
            id=10,
            asset_type="azure",
            aws_access_key="client",
            aws_secret_key="secret",
            region="japaneast",
            provider_config={
                "tenant_id": "tenant",
                "subscription_id": "sub",
                "resource_group": "rg",
            },
        )
        duplicate_scope_asset = MagicMock(
            id=12,
            asset_type="azure",
            aws_access_key="other-client",
            aws_secret_key="other-secret",
            region="eastus",
            provider_config={
                "tenant_id": "tenant",
                "subscription_id": "SUB",
                "resource_group": "RG",
            },
        )
        known_node = MagicMock(aws_instance_id=known_id)
        with patch.object(detector, "_asset_repo") as asset_repo, \
             patch.object(detector, "_state_repo") as state_repo, \
             patch("services.orphan_resource_detector.AzureClient") as client_cls, \
             patch("services.orphan_resource_detector._is_older_than", return_value=True):
            asset_repo.list_assets_by_status.return_value = [
                asset,
                duplicate_scope_asset,
            ]
            state_repo.list_active_nodes.return_value = [known_node]
            client_cls.return_value.list_virtual_machines.return_value = [
                {
                    "id": known_id,
                    "name": "known",
                    "location": "japaneast",
                    "tags": {"shadowfleet": "true"},
                    "properties": {"timeCreated": old_timestamp},
                },
                {
                    "id": orphan_id.replace("orphan", "foreign"),
                    "name": "foreign",
                    "location": "japaneast",
                    "tags": {"owner": "other"},
                    "properties": {"timeCreated": old_timestamp},
                },
                {
                    "id": orphan_id,
                    "name": "orphan",
                    "location": "japaneast",
                    "tags": {"shadowfleet": "true"},
                    "properties": {"timeCreated": old_timestamp},
                },
            ]
            client_cls.return_value.get_vm_power_state.return_value = "running"

            result = detector._scan_orphan_azure_vms()

        assert result == [
            OrphanAzureVm(
                vm_id=orphan_id,
                asset_id=10,
                location="japaneast",
                name="orphan",
                created_at=old_timestamp,
                state="running",
                tags={"shadowfleet": "true"},
            )
        ]
        client_cls.return_value.list_virtual_machines.assert_called_once_with("rg")
        assert client_cls.call_count == 1

    def test_scan_azure_network_orphans_requires_missing_parent_and_age_tag(
        self, detector: OrphanResourceDetector
    ) -> None:
        old_timestamp = "2000-01-01T00:00:00Z"
        asset = MagicMock(
            id=10,
            asset_type="azure",
            aws_access_key="client",
            aws_secret_key="secret",
            region="japaneast",
            provider_config={
                "tenant_id": "tenant",
                "subscription_id": "sub",
                "resource_group": "rg",
            },
        )
        duplicate_scope_asset = MagicMock(
            id=12,
            asset_type="azure",
            aws_access_key="other-client",
            aws_secret_key="other-secret",
            region="eastus",
            provider_config={
                "tenant_id": "tenant",
                "subscription_id": "SUB",
                "resource_group": "RG",
            },
        )
        managed_tags = {
            "shadowfleet": "true",
            "shadowfleet_created_at": old_timestamp,
        }
        with (
            patch.object(detector, "_asset_repo") as asset_repo,
            patch("services.orphan_resource_detector.AzureClient") as client_cls,
        ):
            asset_repo.list_assets_by_status.return_value = [
                asset,
                duplicate_scope_asset,
            ]
            client = client_cls.return_value
            client.list_virtual_machines.return_value = [{"name": "live"}]
            client.list_network_interfaces.return_value = [
                {
                    "id": "nic-live",
                    "name": "live-nic",
                    "location": "japaneast",
                    "tags": managed_tags,
                },
                {
                    "id": "nic-orphan",
                    "name": "orphan-nic",
                    "location": "japaneast",
                    "tags": managed_tags,
                },
                {
                    "id": "nic-legacy",
                    "name": "legacy-nic",
                    "location": "japaneast",
                    "tags": {"shadowfleet": "true"},
                },
            ]
            client.list_public_ip_addresses.return_value = [
                {
                    "id": "pip-orphan",
                    "name": "orphan-ipv4",
                    "location": "japaneast",
                    "tags": managed_tags,
                }
            ]
            client.list_network_security_groups.return_value = [
                {
                    "id": "nsg-orphan",
                    "name": "orphan-nsg",
                    "location": "japaneast",
                    "tags": managed_tags,
                },
                {
                    "id": "nsg-foreign",
                    "name": "foreign-nsg",
                    "location": "japaneast",
                    "tags": {"owner": "other"},
                },
            ]

            result = detector._scan_orphan_azure_network_resources()

        assert result == [
            OrphanAzureNetworkResource(
                resource_id="nic-orphan",
                asset_id=10,
                resource_type="azure_network_interface",
                location="japaneast",
                name="orphan-nic",
                parent_vm_name="orphan",
                created_at=old_timestamp,
                tags=managed_tags,
            ),
            OrphanAzureNetworkResource(
                resource_id="pip-orphan",
                asset_id=10,
                resource_type="azure_public_ip_address",
                location="japaneast",
                name="orphan-ipv4",
                parent_vm_name="orphan",
                created_at=old_timestamp,
                tags=managed_tags,
            ),
            OrphanAzureNetworkResource(
                resource_id="nsg-orphan",
                asset_id=10,
                resource_type="azure_network_security_group",
                location="japaneast",
                name="orphan-nsg",
                parent_vm_name="orphan",
                created_at=old_timestamp,
                tags=managed_tags,
            ),
        ]
        assert client_cls.call_count == 1

    def test_scan_all_orphan_resources_empty(
        self, detector: OrphanResourceDetector
    ) -> None:
        """Test scanning when no orphan resources exist."""
        with patch.object(
            detector, "_scan_orphan_ec2_instances"
        ) as mock_ec2, patch.object(
            detector, "_scan_orphan_dns_records"
        ) as mock_dns, patch.object(
            detector, "_scan_orphan_asset_allocations"
        ) as mock_alloc, patch.object(
            detector, "_scan_orphan_xboard_nodes"
        ) as mock_xboard:
            mock_ec2.return_value = []
            mock_dns.return_value = []
            mock_alloc.return_value = []
            mock_xboard.return_value = []

            report = detector.scan_all_orphan_resources()

            assert report.total_count == 0
            assert len(report.ec2_instances) == 0
            assert len(report.dns_records) == 0
            assert len(report.asset_allocations) == 0
            assert len(report.xboard_nodes) == 0

    def test_scan_all_orphan_resources_with_orphans(
        self, detector: OrphanResourceDetector
    ) -> None:
        """Test scanning when orphan resources exist."""
        ec2 = OrphanEc2Instance(
            instance_id="i-123",
            region="us-east-1",
            account_id="123456789012",
            launch_time="2026-05-10T10:00:00Z",
            state="running",
            tags={},
        )
        dns = OrphanDnsRecord(
            record_id="rec-123",
            domain_name="test.example.com",
            record_type="AAAA",
            content="2600::",
            proxied=True,
            created_on="2026-05-10T10:00:00Z",
        )

        with patch.object(
            detector, "_scan_orphan_ec2_instances"
        ) as mock_ec2, patch.object(
            detector, "_scan_orphan_dns_records"
        ) as mock_dns, patch.object(
            detector, "_scan_orphan_asset_allocations"
        ) as mock_alloc, patch.object(
            detector, "_scan_orphan_xboard_nodes"
        ) as mock_xboard:
            mock_ec2.return_value = [ec2]
            mock_dns.return_value = [dns]
            mock_alloc.return_value = []
            mock_xboard.return_value = []

            report = detector.scan_all_orphan_resources()

            assert report.total_count == 2
            assert len(report.ec2_instances) == 1
            assert len(report.dns_records) == 1
            assert report.ec2_instances[0].instance_id == "i-123"
            assert report.dns_records[0].record_id == "rec-123"

    def test_scan_with_selective_scanning(
        self, detector: OrphanResourceDetector
    ) -> None:
        """Test scanning with selective resource types."""
        with patch.object(
            detector, "_scan_orphan_ec2_instances"
        ) as mock_ec2, patch.object(
            detector, "_scan_orphan_dns_records"
        ) as mock_dns, patch.object(
            detector, "_scan_orphan_asset_allocations"
        ) as mock_alloc, patch.object(
            detector, "_scan_orphan_xboard_nodes"
        ) as mock_xboard:
            mock_ec2.return_value = []
            mock_dns.return_value = []
            mock_alloc.return_value = []
            mock_xboard.return_value = []

            report = detector.scan_all_orphan_resources(
                scan_ec2=True,
                scan_dns=False,
                scan_allocations=False,
                scan_xboard=False,
            )

            mock_ec2.assert_called_once()
            mock_dns.assert_not_called()
            mock_alloc.assert_not_called()
            mock_xboard.assert_not_called()

    def test_scan_includes_timestamp(
        self, detector: OrphanResourceDetector
    ) -> None:
        """Test that scan report includes timestamp."""
        with patch.object(
            detector, "_scan_orphan_ec2_instances"
        ) as mock_ec2, patch.object(
            detector, "_scan_orphan_dns_records"
        ) as mock_dns, patch.object(
            detector, "_scan_orphan_asset_allocations"
        ) as mock_alloc, patch.object(
            detector, "_scan_orphan_xboard_nodes"
        ) as mock_xboard:
            mock_ec2.return_value = []
            mock_dns.return_value = []
            mock_alloc.return_value = []
            mock_xboard.return_value = []

            report = detector.scan_all_orphan_resources()

            assert report.scan_time is not None
            datetime.fromisoformat(report.scan_time)

    def test_error_handling(self, detector: OrphanResourceDetector) -> None:
        """Test error handling during scan."""
        with patch.object(
            detector, "_scan_orphan_ec2_instances"
        ) as mock_ec2:
            mock_ec2.side_effect = Exception("AWS API error")

            with pytest.raises(Exception):
                detector.scan_all_orphan_resources()
