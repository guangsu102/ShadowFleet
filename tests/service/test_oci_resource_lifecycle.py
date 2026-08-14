from __future__ import annotations

from unittest.mock import MagicMock, patch

from services.node_registry_service import NodeRegistryService
from services.orphan_resource_cleaner import OrphanResourceCleaner
from services.orphan_resource_detector import (
    OrphanOCIInstance,
    OrphanResourceDetector,
)
from services.orphan_resource_scan_service import OrphanResourceScanService


def _runtime() -> MagicMock:
    runtime = MagicMock()
    runtime.correlation_id = "oci-lifecycle-correlation"
    runtime.logger.getChild.return_value = MagicMock()
    return runtime


def _asset() -> MagicMock:
    return MagicMock(
        id=7,
        asset_type="oci",
        asset_name="oci-japan",
        status="active",
        region="ap-tokyo-1",
        aws_account_id="oci:tenancy",
        aws_access_key="user-ocid",
        aws_secret_key="private-key",
        provider_config={
            "tenancy_ocid": "tenancy",
            "fingerprint": "aa:bb",
            "compartment_ocid": "compartment",
        },
    )


def _managed_instance(instance_id: str = "instance-ocid") -> dict[str, object]:
    return {
        "id": instance_id,
        "displayName": "sf-orphan",
        "lifecycleState": "RUNNING",
        "timeCreated": "2000-01-01T00:00:00Z",
        "freeformTags": {"ManagedBy": "ShadowFleet"},
    }


def test_node_registry_deletes_oci_instance_before_local_node_removal() -> None:
    runtime = _runtime()
    with patch("services.node_registry_service.XboardRepo"), patch(
        "services.node_registry_service.StateRepo"
    ), patch("services.node_registry_service.AssetRepo"):
        service = NodeRegistryService(runtime)
    asset = _asset()
    service._asset_repo.get_asset_by_xboard_node_id.return_value = asset
    node = MagicMock(
        id=11,
        xboard_node_id=12345,
        asset_type="oci",
        aws_account_id="oci:tenancy",
        aws_instance_id="instance-ocid",
    )

    with patch("services.node_registry_service.OCIClient") as client_type:
        service._delete_oci_instance(node)

    credentials = client_type.call_args.kwargs["credentials"]
    assert credentials.tenancy_ocid == "tenancy"
    assert credentials.user_ocid == "user-ocid"
    client_type.return_value.delete_instance.assert_called_once_with("instance-ocid")
    event = service._state_repo.create_event.call_args.args[0]
    assert event.event_type == "oci_instance_deleted"


def test_legacy_orphan_detector_requires_managed_tag_and_minimum_age() -> None:
    runtime = _runtime()
    with patch("services.orphan_resource_detector.StateRepo"), patch(
        "services.orphan_resource_detector.AssetRepo"
    ), patch("services.orphan_resource_detector.XboardRepo"):
        detector = OrphanResourceDetector(runtime)
    detector._asset_repo.list_assets_by_status.return_value = [_asset()]
    detector._state_repo.list_active_nodes.return_value = []
    young = _managed_instance("young")
    young["timeCreated"] = "2999-01-01T00:00:00Z"
    unmanaged = _managed_instance("unmanaged")
    unmanaged["freeformTags"] = {"ManagedBy": "external"}

    with patch("services.orphan_resource_detector.OCIClient") as client_type:
        client_type.return_value.list_instances.return_value = [
            _managed_instance(),
            young,
            unmanaged,
        ]
        result = detector._scan_orphan_oci_instances()

    assert [item.instance_id for item in result] == ["instance-ocid"]
    assert result[0].asset_id == 7


def test_active_orphan_pipeline_detects_and_cleans_managed_oci_instance() -> None:
    runtime = _runtime()
    with patch("services.orphan_resource_scan_service.StateRepo"), patch(
        "services.orphan_resource_scan_service.AssetRepo"
    ), patch("services.orphan_resource_scan_service.NodeRegistryService"), patch(
        "services.orphan_resource_scan_service.OrphanNodeCleanupService"
    ), patch("services.orphan_resource_scan_service.AssetSelectorService"):
        service = OrphanResourceScanService(runtime)
    asset = _asset()
    service._asset_repo.list_assets_by_status.return_value = [asset]
    service._state_repo.list_active_nodes.return_value = []
    client = MagicMock()
    client.list_instances.return_value = [_managed_instance()]
    with patch.object(service, "_build_oci_client", return_value=client):
        result = service._scan_oci_orphans()

    assert len(result) == 1
    orphan = result[0]
    assert orphan.resource_type == "oci_instance"
    assert orphan.asset_id == 7
    service._asset_repo.get_asset_by_id.return_value = asset
    with patch.object(service, "_build_oci_client", return_value=client):
        assert service._cleanup_oci_orphan(orphan) is True
    client.delete_instance.assert_called_once_with("instance-ocid")


def test_orphan_cleaner_uses_owning_oci_asset_and_honors_dry_run() -> None:
    runtime = _runtime()
    with patch("services.orphan_resource_cleaner.StateRepo"), patch(
        "services.orphan_resource_cleaner.AssetRepo"
    ), patch("services.orphan_resource_cleaner.XboardRepo"):
        cleaner = OrphanResourceCleaner(runtime)
    instance = OrphanOCIInstance(
        instance_id="instance-ocid",
        asset_id=7,
        region="ap-tokyo-1",
        display_name="sf-orphan",
        created_at="2000-01-01T00:00:00Z",
        state="RUNNING",
        tags={"ManagedBy": "ShadowFleet"},
    )
    client = MagicMock()
    with patch.object(cleaner, "_build_oci_client", return_value=client) as build:
        dry_run = cleaner._cleanup_oci_instances([instance], dry_run=True)
        cleaned = cleaner._cleanup_oci_instances([instance], dry_run=False)

    assert dry_run[0].success is True
    assert cleaned[0].success is True
    build.assert_called_once_with(7)
    client.delete_instance.assert_called_once_with("instance-ocid")
