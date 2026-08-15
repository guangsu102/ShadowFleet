from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from database.asset_models import AssetRecord
from infrastructure.gcp import GCPProvisioningTarget
from services.asset_application_models import GCPAssetRegistrationRequest
from services.asset_application_service import AssetApplicationService, _gcp_firewall_rule_name
from services.fleet_scheduler_service import FleetSchedulerService
from services.healing_models import HealRequest
from services.healing_support import determine_heal_strategy
from services.monitor_support import infer_node_asset_type
from services.node_registry_service import NodeRegistryService
from services.orphan_resource_cleaner import OrphanResourceCleaner
from services.orphan_resource_detector import (
    OrphanGCPInstance,
    OrphanResourceDetector,
)
from services.orphan_resource_scan_service import (
    OrphanResourceInfo,
    OrphanResourceScanService,
)


PRIVATE_KEY = "-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----\n"


def _asset() -> AssetRecord:
    return AssetRecord(
        id=29,
        asset_type="gcp",
        asset_name="gcp-asia-east1",
        status="active",
        region="asia-east1-a",
        aws_account_id="gcp:shadowfleet-test",
        aws_access_key="shadowfleet@example.iam.gserviceaccount.com",
        aws_secret_key=PRIVATE_KEY,
        ssh_host=None,
        ssh_port=None,
        ssh_username=None,
        ssh_password=None,
        ssh_private_key=None,
        default_instance_type="e2-small",
        default_vcpu=2,
        account_total_vcpu=None,
        default_architecture="x64",
        provider_config={
            "project_id": "shadowfleet-test",
            "ssh_public_key": "ssh-ed25519 AAAA test",
        },
    )


def _service_account_json() -> str:
    return json.dumps(
        {
            "type": "service_account",
            "project_id": "shadowfleet-test",
            "client_email": "shadowfleet@example.iam.gserviceaccount.com",
            "private_key": PRIVATE_KEY,
            "private_key_id": "key-id",
            "client_id": "client-id",
        }
    )


def _registration_service() -> tuple[AssetApplicationService, MagicMock, MagicMock]:
    service = object.__new__(AssetApplicationService)
    service._runtime_context = MagicMock(correlation_id="asset-correlation")
    service._logger = MagicMock()
    service._asset_repo = MagicMock()
    service._asset_repo.create_asset.return_value = 29
    service._asset_repo.upsert_asset_protocol_config.side_effect = [83, 84]
    client = MagicMock()
    client.validate_provisioning_target.return_value = GCPProvisioningTarget(
        zone="asia-east1-a",
        region="asia-east1",
        machine_type="e2-small",
        source_image="https://compute.googleapis.com/compute/v1/projects/ubuntu-os-cloud/global/images/ubuntu-2404",
        network="https://compute.googleapis.com/compute/v1/projects/shadowfleet-test/global/networks/default",
        subnetwork="https://compute.googleapis.com/compute/v1/projects/shadowfleet-test/regions/asia-east1/subnetworks/default",
        architecture="x64",
        guest_cpus=2,
    )
    service._build_gcp_client = MagicMock(return_value=client)
    return service, service._asset_repo, client


def test_gcp_firewall_rule_name_is_stable_and_scoped_to_network() -> None:
    assert _gcp_firewall_rule_name("projects/p/global/networks/default") == "shadowfleet-ingress"
    assert (
        _gcp_firewall_rule_name("projects/p/global/networks/production-vpc")
        == "shadowfleet-ingress-production-vpc"
    )


def test_register_gcp_asset_validates_target_and_persists_provider_config() -> None:
    service, repo, client = _registration_service()
    request = GCPAssetRegistrationRequest(
        asset_name=" GCP Asia East ",
        project_id="shadowfleet-test",
        service_account_json=_service_account_json(),
        zone="asia-east1-a",
        machine_type="e2-small",
        source_image="projects/ubuntu-os-cloud/global/images/family/ubuntu-2404-lts-amd64",
        network="default",
        subnetwork="default",
        ssh_username="ubuntu",
        ssh_public_key="ssh-ed25519 AAAA test",
        labels=("environment=test", "managed"),
        protocol_type="AnyTLS",
        additional_protocol_types=("Trojan",),
        target_count=1,
        max_count=3,
    )

    result = service.register_gcp_asset(request)

    assert result.asset_id == 29
    assert result.protocol_config_id == 83
    client.validate_project.assert_called_once_with()
    client.validate_provisioning_target.assert_called_once_with(
        zone="asia-east1-a",
        machine_type="e2-small",
        source_image="projects/ubuntu-os-cloud/global/images/family/ubuntu-2404-lts-amd64",
        network="default",
        subnetwork="default",
    )
    create_request = repo.create_asset.call_args.args[0]
    assert create_request.asset_type == "gcp"
    assert create_request.aws_account_id == "gcp:shadowfleet-test"
    assert create_request.aws_access_key == "shadowfleet@example.iam.gserviceaccount.com"
    assert create_request.aws_secret_key == PRIVATE_KEY.strip()
    assert create_request.region == "asia-east1-a"
    assert create_request.default_instance_type == "e2-small"
    assert create_request.default_vcpu == 2
    assert create_request.provider_config["project_id"] == "shadowfleet-test"
    assert create_request.provider_config["region"] == "asia-east1"
    assert create_request.provider_config["labels"] == {
        "environment": "test",
        "managed": "true",
    }
    assert repo.upsert_asset_protocol_config.call_count == 2


def test_query_gcp_catalog_returns_zone_dependent_resources() -> None:
    service, _, client = _registration_service()
    client.list_zones.return_value = [{"name": "asia-east1-a"}]
    client.get_zone.return_value = {
        "region": "projects/shadowfleet-test/regions/asia-east1"
    }
    client.list_machine_types.return_value = [{"name": "e2-small"}]
    client.list_images.return_value = [{"name": "ubuntu-2404"}]
    client.list_networks.return_value = [{"name": "default"}]
    client.list_subnetworks.return_value = [{"name": "default"}]

    result = service.query_gcp_catalog(
        service_account_json=_service_account_json(),
        project_id="shadowfleet-test",
        zone="asia-east1-a",
        image_project="ubuntu-os-cloud",
    )

    client.validate_project.assert_called_once_with()
    client.list_machine_types.assert_called_once_with("asia-east1-a")
    client.list_subnetworks.assert_called_once_with("asia-east1")
    assert result["machine_types"] == [{"name": "e2-small"}]
    assert result["subnetworks"] == [{"name": "default"}]


def test_gcp_node_deletion_terminates_instance_with_allocated_asset() -> None:
    service = object.__new__(NodeRegistryService)
    service._runtime_context = MagicMock(correlation_id="delete-correlation")
    service._asset_repo = MagicMock()
    service._asset_repo.get_asset_by_xboard_node_id.return_value = _asset()
    service._state_repo = MagicMock()
    node = MagicMock(
        id=32,
        xboard_node_id=12351,
        asset_type="gcp",
        aws_account_id="gcp:shadowfleet-test",
        aws_region="asia-east1-a",
        aws_instance_id="sf-gcp-12351",
    )

    with patch("services.node_registry_service.GCPClient") as client_cls:
        service._delete_gcp_instance(node)

    client_cls.return_value.delete_instance.assert_called_once_with(
        "asia-east1-a",
        "sf-gcp-12351",
    )
    event = service._state_repo.create_event.call_args.args[0]
    assert event.event_type == "gcp_instance_deleted"
    assert event.payload == {
        "asset_id": 29,
        "instance_name": "sf-gcp-12351",
        "zone": "asia-east1-a",
    }


def _instances() -> list[dict[str, object]]:
    return [
        {
            "name": "known-instance",
            "status": "RUNNING",
            "creationTimestamp": "2020-01-01T00:00:00Z",
            "labels": {"managed-by": "shadowfleet"},
        },
        {
            "name": "orphan-instance",
            "status": "RUNNING",
            "creationTimestamp": "2020-01-01T00:00:00Z",
            "labels": {"managed-by": "shadowfleet"},
        },
        {
            "name": "unmanaged-instance",
            "status": "RUNNING",
            "creationTimestamp": "2020-01-01T00:00:00Z",
            "labels": {},
        },
    ]


def test_both_orphan_scanners_find_only_old_managed_gcp_instance() -> None:
    client = MagicMock()
    client.list_instances.return_value = _instances()
    active_node = SimpleNamespace(aws_instance_id="known-instance")

    detector = object.__new__(OrphanResourceDetector)
    detector._runtime = MagicMock()
    detector._logger = MagicMock()
    detector._asset_repo = MagicMock()
    detector._asset_repo.list_assets_by_status.return_value = [_asset()]
    detector._state_repo = MagicMock()
    detector._state_repo.list_active_nodes.return_value = [active_node]

    scan_service = object.__new__(OrphanResourceScanService)
    scan_service._runtime_context = MagicMock()
    scan_service._logger = MagicMock()
    scan_service._asset_repo = MagicMock()
    scan_service._asset_repo.list_assets_by_status.return_value = [_asset()]
    scan_service._state_repo = MagicMock()
    scan_service._state_repo.list_active_nodes.return_value = [active_node]
    scan_service._resource_age_exceeded = MagicMock(return_value=True)
    scan_service._build_gcp_client = MagicMock(return_value=client)

    with patch("services.orphan_resource_detector.GCPClient", return_value=client):
        detector_result = detector._scan_orphan_gcp_instances()
    scan_result = scan_service._scan_gcp_orphans()

    assert [item.instance_name for item in detector_result] == ["orphan-instance"]
    assert detector_result[0].asset_id == 29
    assert [item.resource_id for item in scan_result] == ["orphan-instance"]
    assert scan_result[0].resource_type == "gcp_instance"


def test_both_orphan_cleaners_delete_gcp_instance() -> None:
    client = MagicMock()
    cleaner = object.__new__(OrphanResourceCleaner)
    cleaner._runtime = MagicMock()
    cleaner._logger = MagicMock()
    cleaner._asset_repo = MagicMock()
    cleaner._build_gcp_client = MagicMock(return_value=client)
    orphan = OrphanGCPInstance(
        instance_name="orphan-instance",
        asset_id=29,
        project_id="shadowfleet-test",
        zone="asia-east1-a",
        created_at="2020-01-01T00:00:00Z",
        status="RUNNING",
        labels={"managed-by": "shadowfleet"},
    )

    scan_service = object.__new__(OrphanResourceScanService)
    scan_service._runtime_context = MagicMock()
    scan_service._logger = MagicMock()
    scan_service._asset_repo = MagicMock()
    scan_service._asset_repo.get_asset_by_id.return_value = _asset()
    scan_service._build_gcp_client = MagicMock(return_value=client)
    scan_orphan = OrphanResourceInfo(
        resource_type="gcp_instance",
        resource_id="orphan-instance",
        region="asia-east1-a",
        asset_id=29,
    )

    result = cleaner._cleanup_gcp_instances([orphan], dry_run=False)
    assert scan_service._cleanup_gcp_orphan(scan_orphan) is True

    assert result[0].success is True
    assert client.delete_instance.call_count == 2
    client.delete_instance.assert_called_with("asia-east1-a", "orphan-instance")


def test_gcp_provider_inference_healing_and_scheduler_support() -> None:
    node = MagicMock(
        asset_type="aws",
        aws_account_id="gcp:shadowfleet-test",
        node_type="AnyTLS",
    )
    assert infer_node_asset_type(node) == "gcp"
    assert determine_heal_strategy(
        node,
        HealRequest(xboard_node_id=12351, reason="confirmed_blocked"),
    ) == "gcp_ipv4_rotate"

    scheduler = object.__new__(FleetSchedulerService)
    scheduler._runtime = MagicMock()
    scheduler._runtime.config_holder = None
    scheduler._runtime.config.fleet_scheduler.enabled_asset_types = ["gcp"]
    assert scheduler._enabled_cloud_asset_types() == ("gcp",)


def test_default_sqlite_fixture_accepts_gcp(in_memory_sqlite_db) -> None:
    in_memory_sqlite_db.execute(
        """
        INSERT INTO fleet_assets (
            asset_type, asset_name, status, created_at, updated_at
        ) VALUES ('gcp', 'gcp-default-fixture', 'active', 'now', 'now')
        """
    )
    assert in_memory_sqlite_db.execute(
        "SELECT COUNT(*) FROM fleet_assets WHERE asset_type = 'gcp'"
    ).fetchone()[0] == 1


def test_sqlite_asset_constraint_accepts_gcp(full_schema_sqlite_db) -> None:
    ddl = full_schema_sqlite_db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='fleet_assets'"
    ).fetchone()[0]
    assert "'gcp'" in ddl
    full_schema_sqlite_db.execute(
        """
        INSERT INTO fleet_assets (
            asset_type, asset_name, status, created_at, updated_at
        ) VALUES ('gcp', 'gcp-test', 'active', 'now', 'now')
        """
    )
