from __future__ import annotations

from unittest.mock import MagicMock, patch

from infrastructure.digitalocean import DigitalOceanClientError
from services.orphan_resource_cleaner import OrphanResourceCleaner
from services.orphan_resource_detector import (
    OrphanDigitalOceanDroplet,
    OrphanResourceDetector,
)
from services.orphan_resource_scan_service import (
    OrphanResourceInfo,
    OrphanResourceScanService,
)


def _asset() -> MagicMock:
    return MagicMock(
        id=18,
        asset_type="digitalocean",
        asset_name="do-sgp1",
        aws_account_id="account-do",
        aws_access_key="dop_v1_test",
        region="sgp1",
    )


def _droplet() -> dict[str, object]:
    return {
        "id": 1001,
        "name": "sf-orphan",
        "region": {"slug": "sgp1"},
        "created_at": "2020-01-01T00:00:00Z",
        "status": "active",
        "tags": ["shadowfleet"],
    }


def test_detector_reports_orphan_digitalocean_droplet() -> None:
    detector = object.__new__(OrphanResourceDetector)
    detector._runtime = MagicMock()
    detector._logger = MagicMock()
    detector._asset_repo = MagicMock()
    detector._state_repo = MagicMock()
    detector._asset_repo.list_assets_by_status.return_value = [_asset()]
    detector._state_repo.list_active_nodes.return_value = []
    client = MagicMock()
    client.list_droplets.return_value = [_droplet()]

    with patch(
        "services.orphan_resource_detector.DigitalOceanClient",
        return_value=client,
    ):
        result = detector._scan_orphan_digitalocean_droplets()

    assert result == [
        OrphanDigitalOceanDroplet(
            droplet_id="1001",
            asset_id=18,
            region="sgp1",
            name="sf-orphan",
            created_at="2020-01-01T00:00:00Z",
            status="active",
            tags=("shadowfleet",),
        )
    ]
    client.list_droplets.assert_called_once_with(tag_name="shadowfleet")


def test_cleaner_deletes_orphan_digitalocean_droplet() -> None:
    cleaner = object.__new__(OrphanResourceCleaner)
    cleaner._runtime = MagicMock()
    cleaner._logger = MagicMock()
    cleaner._asset_repo = MagicMock()
    cleaner._asset_repo.get_asset_by_id.return_value = _asset()
    droplet = OrphanDigitalOceanDroplet(
        droplet_id="1001",
        asset_id=18,
        region="sgp1",
        name="sf-orphan",
        created_at="2020-01-01T00:00:00Z",
        status="active",
        tags=("shadowfleet",),
    )

    with patch(
        "services.orphan_resource_cleaner.DigitalOceanClient"
    ) as client_type:
        result = cleaner._cleanup_digitalocean_droplets([droplet], dry_run=False)

    client_type.return_value.delete_droplet.assert_called_once_with("1001")
    assert result[0].success is True


def test_background_scan_and_cleanup_support_digitalocean() -> None:
    service = object.__new__(OrphanResourceScanService)
    service._runtime_context = MagicMock()
    service._logger = MagicMock()
    service._asset_repo = MagicMock()
    service._state_repo = MagicMock()
    service._asset_repo.list_assets_by_status.return_value = [_asset()]
    service._asset_repo.get_asset_by_id.return_value = _asset()
    service._state_repo.list_active_nodes.return_value = []
    client = MagicMock()
    client.list_droplets.return_value = [_droplet()]

    with patch(
        "services.orphan_resource_scan_service.DigitalOceanClient",
        return_value=client,
    ):
        orphans = service._scan_digitalocean_orphans()
        cleaned = service._cleanup_digitalocean_orphan(orphans[0])

    assert orphans[0].resource_type == "digitalocean_droplet"
    assert cleaned is True
    client.delete_droplet.assert_called_once_with("1001")


def test_background_scan_marks_node_when_droplet_is_missing() -> None:
    service = object.__new__(OrphanResourceScanService)
    service._runtime_context = MagicMock()
    service._logger = MagicMock()
    service._asset_repo = MagicMock()
    service._asset_repo.get_asset_by_xboard_node_id.return_value = _asset()
    node = MagicMock(
        xboard_node_id=42,
        aws_account_id="account-do",
        aws_region="sgp1",
        aws_instance_id="1001",
    )
    client = MagicMock()
    client.get_droplet.side_effect = DigitalOceanClientError("missing", status_code=404)

    with patch(
        "services.orphan_resource_scan_service.DigitalOceanClient",
        return_value=client,
    ):
        orphan = service._scan_digitalocean_node_orphan(node)

    assert orphan == OrphanResourceInfo(
        resource_type="xboard_node",
        resource_id="42",
        region="sgp1",
        aws_account_id="account-do",
        xboard_node_id=42,
        reason="DigitalOcean Droplet not found",
        discovered_at=orphan.discovered_at,
    )
