from __future__ import annotations

import hashlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from database.asset_models import AssetRecord
from services.asset_application_models import KamateraAssetRegistrationRequest
from services.asset_application_service import AssetApplicationService
from services.fleet_scheduler_service import FleetSchedulerService
from services.healing_models import HealRequest
from services.healing_support import determine_heal_strategy
from services.monitor_support import infer_node_asset_type
from services.node_registry_service import NodeRegistryService
from services.orphan_resource_cleaner import OrphanResourceCleaner
from services.orphan_resource_detector import (
    OrphanKamateraServer,
    OrphanResourceDetector,
)
from services.orphan_resource_scan_service import (
    OrphanResourceInfo,
    OrphanResourceScanService,
)


def _asset() -> AssetRecord:
    return AssetRecord(
        id=28,
        asset_type="kamatera",
        asset_name="kamatera-as",
        status="active",
        region="AS",
        aws_account_id="kamatera:account",
        aws_access_key="client-id",
        aws_secret_key="client-secret",
        ssh_host=None,
        ssh_port=None,
        ssh_username=None,
        ssh_password=None,
        ssh_private_key=None,
        default_instance_type="2B",
        default_vcpu=2,
        account_total_vcpu=None,
        default_architecture="x64",
        provider_config={
            "image": "ubuntu_server_24.04_64-bit",
            "ssh_public_key": "ssh-ed25519 test",
        },
    )


def _registration_service() -> tuple[AssetApplicationService, MagicMock, MagicMock]:
    service = object.__new__(AssetApplicationService)
    service._runtime_context = MagicMock(correlation_id="asset-correlation")
    service._logger = MagicMock()
    service._asset_repo = MagicMock()
    service._asset_repo.create_asset.return_value = 28
    service._asset_repo.upsert_asset_protocol_config.side_effect = [81, 82]
    client = MagicMock()
    service._build_kamatera_client = MagicMock(return_value=client)
    return service, service._asset_repo, client


def test_register_kamatera_asset_validates_target_and_persists_provider_config() -> None:
    service, repo, client = _registration_service()
    request = KamateraAssetRegistrationRequest(
        asset_name=" Kamatera AS ",
        datacenter="AS",
        client_id=" client-id ",
        secret=" client-secret ",
        image="ubuntu_server_24.04_64-bit",
        ssh_public_key="ssh-ed25519 test",
        cpu_type="b",
        cpu_cores=2,
        ram_mb=4096,
        disk_sizes_gb=(30, 40),
        daily_backup=True,
        tags=("prod", "shadowfleet"),
        protocol_type="AnyTLS",
        additional_protocol_types=("Trojan",),
        target_count=1,
        max_count=3,
    )

    result = service.register_kamatera_asset(request)

    assert result.asset_id == 28
    assert result.protocol_config_id == 81
    client.validate_account.assert_called_once_with()
    client.validate_provisioning_target.assert_called_once_with(
        datacenter="AS",
        image="ubuntu_server_24.04_64-bit",
    )
    create_request = repo.create_asset.call_args.args[0]
    expected_digest = hashlib.sha256(b"client-id").hexdigest()[:24]
    assert create_request.asset_type == "kamatera"
    assert create_request.aws_account_id == f"kamatera:{expected_digest}"
    assert create_request.aws_access_key == "client-id"
    assert create_request.aws_secret_key == "client-secret"
    assert create_request.default_instance_type == "2B"
    assert create_request.provider_config == {
        "image": "ubuntu_server_24.04_64-bit",
        "ssh_public_key": "ssh-ed25519 test",
        "cpu_type": "B",
        "cpu_cores": 2,
        "ram_mb": 4096,
        "disk_sizes_gb": [30, 40],
        "billing_cycle": "hourly",
        "daily_backup": True,
        "managed": False,
        "tags": ["shadowfleet", "prod"],
    }
    assert repo.upsert_asset_protocol_config.call_count == 2


def test_query_kamatera_catalog_returns_datacenters_images_and_capabilities() -> None:
    service, _, client = _registration_service()
    client.list_datacenters.return_value = [{"id": "AS", "name": "Asia"}]
    client.list_images.return_value = [{"id": "ubuntu"}]
    client.get_capabilities.return_value = {"cpu": ["1B", "2B"]}

    result = service.query_kamatera_catalog(
        client_id="client-id",
        secret="client-secret",
        datacenter=" AS ",
    )

    client.validate_account.assert_called_once_with()
    client.list_images.assert_called_once_with("AS")
    client.get_capabilities.assert_called_once_with("AS")
    assert result == {
        "datacenters": [{"id": "AS", "name": "Asia"}],
        "images": [{"id": "ubuntu"}],
        "capabilities": {"cpu": ["1B", "2B"]},
    }


def test_kamatera_node_deletion_terminates_server_with_allocated_asset() -> None:
    service = object.__new__(NodeRegistryService)
    service._runtime_context = MagicMock(correlation_id="delete-correlation")
    service._asset_repo = MagicMock()
    service._asset_repo.get_asset_by_xboard_node_id.return_value = _asset()
    service._state_repo = MagicMock()
    node = MagicMock(
        id=31,
        xboard_node_id=12349,
        asset_type="kamatera",
        aws_account_id="kamatera:account",
        aws_instance_id="server-31",
    )

    with patch("services.node_registry_service.KamateraClient") as client_cls:
        service._delete_kamatera_instance(node)

    client_cls.assert_called_once_with(
        service._runtime_context,
        client_id="client-id",
        secret="client-secret",
    )
    client_cls.return_value.delete_server.assert_called_once_with("server-31")
    event = service._state_repo.create_event.call_args.args[0]
    assert event.event_type == "kamatera_server_deleted"
    assert event.payload == {"asset_id": 28, "server_id": "server-31"}


def _server_details() -> dict[str, object]:
    return {
        "id": "orphan-server",
        "name": "sf-orphan",
        "datacenter": "AS",
        "created": "2020-01-01T00:00:00Z",
        "power": "on",
        "tags": ["shadowfleet", "test"],
    }


def test_both_orphan_scanners_find_old_tagged_kamatera_server() -> None:
    client = MagicMock()
    client.list_servers.return_value = [
        {"id": "known-server"},
        {"id": "orphan-server", "name": "sf-orphan"},
    ]
    client.get_server.return_value = _server_details()

    detector = object.__new__(OrphanResourceDetector)
    detector._runtime = MagicMock()
    detector._logger = MagicMock()
    detector._asset_repo = MagicMock()
    detector._asset_repo.list_assets_by_status.return_value = [_asset()]
    detector._state_repo = MagicMock()
    detector._state_repo.list_active_nodes.return_value = [
        SimpleNamespace(aws_instance_id="known-server")
    ]

    scan_service = object.__new__(OrphanResourceScanService)
    scan_service._runtime_context = MagicMock()
    scan_service._logger = MagicMock()
    scan_service._asset_repo = MagicMock()
    scan_service._asset_repo.list_assets_by_status.return_value = [_asset()]
    scan_service._state_repo = MagicMock()
    scan_service._state_repo.list_active_nodes.return_value = [
        SimpleNamespace(aws_instance_id="known-server")
    ]
    scan_service._resource_age_exceeded = MagicMock(return_value=True)

    with patch(
        "services.orphan_resource_detector.KamateraClient", return_value=client
    ):
        detector_result = detector._scan_orphan_kamatera_servers()
    with patch(
        "services.orphan_resource_scan_service.KamateraClient", return_value=client
    ):
        scan_result = scan_service._scan_kamatera_orphans()

    assert [server.server_id for server in detector_result] == ["orphan-server"]
    assert detector_result[0].asset_id == 28
    assert [orphan.resource_id for orphan in scan_result] == ["orphan-server"]
    assert scan_result[0].resource_type == "kamatera_server"
    assert scan_result[0].asset_id == 28


def test_both_orphan_cleaners_terminate_kamatera_server() -> None:
    cleaner = object.__new__(OrphanResourceCleaner)
    cleaner._runtime = MagicMock()
    cleaner._logger = MagicMock()
    cleaner._asset_repo = MagicMock()
    cleaner._asset_repo.get_asset_by_id.return_value = _asset()
    orphan = OrphanKamateraServer(
        server_id="orphan-server",
        asset_id=28,
        datacenter="AS",
        name="sf-orphan",
        created_at="2020-01-01T00:00:00Z",
        power="on",
        tags=("shadowfleet",),
    )

    scan_service = object.__new__(OrphanResourceScanService)
    scan_service._runtime_context = MagicMock()
    scan_service._logger = MagicMock()
    scan_service._asset_repo = MagicMock()
    scan_service._asset_repo.get_asset_by_id.return_value = _asset()
    scan_orphan = OrphanResourceInfo(
        resource_type="kamatera_server",
        resource_id="orphan-server",
        asset_id=28,
    )

    with patch("services.orphan_resource_cleaner.KamateraClient") as detector_client:
        result = cleaner._cleanup_kamatera_servers([orphan], dry_run=False)
    with patch("services.orphan_resource_scan_service.KamateraClient") as scan_client:
        assert scan_service._cleanup_kamatera_orphan(scan_orphan) is True

    assert result[0].success is True
    detector_client.return_value.delete_server.assert_called_once_with("orphan-server")
    scan_client.return_value.delete_server.assert_called_once_with("orphan-server")


def test_kamatera_provider_inference_healing_and_scheduler_support() -> None:
    node = MagicMock(
        asset_type="aws",
        aws_account_id="kamatera:account",
        node_type="AnyTLS",
    )
    assert infer_node_asset_type(node) == "kamatera"
    assert determine_heal_strategy(
        node,
        HealRequest(xboard_node_id=12349, reason="confirmed_blocked"),
    ) == "kamatera_instance_replace"

    scheduler = object.__new__(FleetSchedulerService)
    scheduler._runtime = MagicMock()
    scheduler._runtime.config_holder = None
    scheduler._runtime.config.fleet_scheduler.enabled_asset_types = ["kamatera"]
    assert scheduler._enabled_cloud_asset_types() == ("kamatera",)


def test_sqlite_asset_constraint_accepts_kamatera(full_schema_sqlite_db) -> None:
    ddl = full_schema_sqlite_db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='fleet_assets'"
    ).fetchone()[0]
    assert "'kamatera'" in ddl
    full_schema_sqlite_db.execute(
        """
        INSERT INTO fleet_assets (
            asset_type, asset_name, status, created_at, updated_at
        ) VALUES ('kamatera', 'kamatera-test', 'active', 'now', 'now')
        """
    )
    count = full_schema_sqlite_db.execute(
        "SELECT COUNT(*) FROM fleet_assets WHERE asset_type = 'kamatera'"
    ).fetchone()[0]
    assert count == 1
