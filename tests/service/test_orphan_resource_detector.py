"""
Unit tests for OrphanResourceDetector service
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from services.orphan_resource_detector import (
    OrphanAssetAllocation,
    OrphanDnsRecord,
    OrphanEc2Instance,
    OrphanResourceDetector,
    OrphanResourceDetectorError,
    OrphanResourceReport,
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
