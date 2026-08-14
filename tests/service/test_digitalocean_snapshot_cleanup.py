from __future__ import annotations

from unittest.mock import MagicMock, patch

from services.orphan_resource_cleaner import OrphanResourceCleaner
from services.orphan_resource_detector import (
    OrphanDigitalOceanSnapshot,
    OrphanResourceDetector,
)
from services.orphan_resource_scan_service import OrphanResourceScanService


def _asset() -> MagicMock:
    return MagicMock(
        id=18,
        asset_type="digitalocean",
        asset_name="do-sgp1",
        aws_account_id="account-do",
        aws_access_key="dop_v1_test",
    )


def _snapshot() -> dict[str, object]:
    return {
        "id": "snapshot-1",
        "name": "shadowfleet-heal-sf-do-deadbeef",
        "created_at": "2020-01-01T00:00:00Z",
        "resource_id": 1001,
        "tags": ["shadowfleet"],
    }


def test_detector_reports_only_shadowfleet_healing_snapshots() -> None:
    detector = object.__new__(OrphanResourceDetector)
    detector._runtime = MagicMock()
    detector._logger = MagicMock()
    detector._asset_repo = MagicMock()
    detector._asset_repo.list_assets_by_status.return_value = [_asset()]
    client = MagicMock()
    client.list_snapshots.return_value = [
        _snapshot(),
        {
            "id": "user-snapshot",
            "name": "long-term-backup",
            "created_at": "2020-01-01T00:00:00Z",
        },
    ]

    with patch(
        "services.orphan_resource_detector.DigitalOceanClient",
        return_value=client,
    ):
        result = detector._scan_orphan_digitalocean_snapshots()

    assert result == [
        OrphanDigitalOceanSnapshot(
            snapshot_id="snapshot-1",
            asset_id=18,
            name="shadowfleet-heal-sf-do-deadbeef",
            created_at="2020-01-01T00:00:00Z",
            resource_id="1001",
            tags=("shadowfleet",),
        )
    ]


def test_cleaner_deletes_orphan_healing_snapshot() -> None:
    cleaner = object.__new__(OrphanResourceCleaner)
    cleaner._runtime = MagicMock()
    cleaner._logger = MagicMock()
    cleaner._asset_repo = MagicMock()
    cleaner._asset_repo.get_asset_by_id.return_value = _asset()
    snapshot = OrphanDigitalOceanSnapshot(
        snapshot_id="snapshot-1",
        asset_id=18,
        name="shadowfleet-heal-sf-do-deadbeef",
        created_at="2020-01-01T00:00:00Z",
        resource_id="1001",
        tags=("shadowfleet",),
    )

    with patch(
        "services.orphan_resource_cleaner.DigitalOceanClient"
    ) as client_type:
        result = cleaner._cleanup_digitalocean_snapshots(
            [snapshot],
            dry_run=False,
        )

    client_type.return_value.delete_snapshot.assert_called_once_with("snapshot-1")
    assert result[0].success is True


def test_background_scan_and_cleanup_support_healing_snapshots() -> None:
    service = object.__new__(OrphanResourceScanService)
    service._runtime_context = MagicMock()
    service._logger = MagicMock()
    service._asset_repo = MagicMock()
    service._asset_repo.list_assets_by_status.return_value = [_asset()]
    service._asset_repo.get_asset_by_id.return_value = _asset()
    client = MagicMock()
    client.list_snapshots.return_value = [_snapshot()]

    with patch(
        "services.orphan_resource_scan_service.DigitalOceanClient",
        return_value=client,
    ):
        orphans = service._scan_digitalocean_snapshot_orphans()
        cleaned = service._cleanup_digitalocean_snapshot_orphan(orphans[0])

    assert orphans[0].resource_type == "digitalocean_snapshot"
    assert cleaned is True
    client.delete_snapshot.assert_called_once_with("snapshot-1")
