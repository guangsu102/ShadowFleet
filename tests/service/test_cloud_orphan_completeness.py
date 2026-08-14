from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from services.node_registry_service import NodeRegistryService
from services.orphan_resource_scan_service import (
    OrphanResourceInfo,
    OrphanResourceScanService,
)


def _scan_service() -> OrphanResourceScanService:
    service = object.__new__(OrphanResourceScanService)
    service._logger = MagicMock()
    service._node_registry = MagicMock()
    service._state_repo = MagicMock()
    service._asset_repo = MagicMock()
    service._runtime_context = MagicMock()
    return service


def test_node_registry_list_all_nodes_delegates_to_xboard_repo() -> None:
    service = object.__new__(NodeRegistryService)
    service._xboard_repo = MagicMock()
    expected = [SimpleNamespace(node_id=7, show=True)]
    service._xboard_repo.list_all_shadowfleet_nodes.return_value = expected

    assert service.list_all_nodes() == expected


def test_database_consistency_detects_xboard_visibility_mismatch() -> None:
    service = _scan_service()
    service._node_registry.list_all_nodes.return_value = [
        SimpleNamespace(node_id=7, show=False),
        SimpleNamespace(node_id=8, show=False),
    ]
    service._state_repo.list_active_nodes.return_value = [
        SimpleNamespace(xboard_node_id=7, status="online"),
        SimpleNamespace(xboard_node_id=8, status="offline"),
    ]

    result = service.check_database_consistency()

    assert result.sqlite_only_nodes == ()
    assert result.xboard_only_nodes == ()
    assert result.status_mismatch == (
        "xboard_node_id=7: sqlite_status=online, xboard_show=False",
    )


def _configure_sqlite(service: OrphanResourceScanService, connection) -> None:
    sqlite_manager = MagicMock()
    sqlite_manager.connection.return_value.__enter__.return_value = connection
    sqlite_manager.connection.return_value.__exit__.return_value = False
    service._runtime_context.sqlite_manager = sqlite_manager


def _insert_allocation(
    connection,
    *,
    xboard_node_id: int | None,
    fleet_node_id: int | None,
) -> int:
    return int(
        connection.execute(
            """
            INSERT INTO fleet_asset_allocations (
                asset_id, fleet_node_id, xboard_node_id, protocol_type,
                allocation_status, vcpu_count, created_at, updated_at
            ) VALUES (1, ?, ?, 'Trojan', 'allocated', 1, '2026-01-01', '2026-01-01')
            """,
            (fleet_node_id, xboard_node_id),
        ).lastrowid
    )


def test_scan_allocation_orphans_covers_every_broken_binding(
    in_memory_sqlite_db,
) -> None:
    service = _scan_service()
    _configure_sqlite(service, in_memory_sqlite_db)
    in_memory_sqlite_db.execute(
        """
        INSERT INTO fleet_assets (
            asset_type, asset_name, status, created_at, updated_at
        ) VALUES ('vultr', 'vultr-test', 'active', '2026-01-01', '2026-01-01')
        """
    )
    node_ids: dict[int, int] = {}
    for xboard_node_id, status, is_deleted in (
        (101, "deleted", 1),
        (102, "online", 0),
        (103, "online", 0),
        (104, "online", 0),
    ):
        node_ids[xboard_node_id] = int(
            in_memory_sqlite_db.execute(
                """
                INSERT INTO fleet_nodes (
                    xboard_node_id, node_name, node_type, status, is_deleted,
                    created_at, updated_at
                ) VALUES (?, ?, 'Trojan', ?, ?, '2026-01-01', '2026-01-01')
                """,
                (
                    xboard_node_id,
                    f"node-{xboard_node_id}",
                    status,
                    is_deleted,
                ),
            ).lastrowid
        )
    orphan_ids = {
        _insert_allocation(
            in_memory_sqlite_db,
            xboard_node_id=None,
            fleet_node_id=None,
        ),
        _insert_allocation(
            in_memory_sqlite_db,
            xboard_node_id=999,
            fleet_node_id=None,
        ),
        _insert_allocation(
            in_memory_sqlite_db,
            xboard_node_id=101,
            fleet_node_id=node_ids[101],
        ),
        _insert_allocation(
            in_memory_sqlite_db,
            xboard_node_id=102,
            fleet_node_id=node_ids[104],
        ),
    }
    valid_id = _insert_allocation(
        in_memory_sqlite_db,
        xboard_node_id=103,
        fleet_node_id=node_ids[103],
    )
    in_memory_sqlite_db.commit()

    result = service._scan_allocation_orphans()

    assert {int(orphan.resource_id) for orphan in result} == orphan_ids
    assert valid_id not in {int(orphan.resource_id) for orphan in result}
    assert {orphan.reason for orphan in result} == {
        "Active allocation has no Xboard node binding",
        "Active allocation references a missing fleet node",
        "Active allocation references a deleted fleet node",
        "Active allocation fleet node binding is inconsistent",
    }


def test_scan_service_vultr_cleanup_deletes_managed_firewall() -> None:
    service = _scan_service()
    service._asset_repo.get_asset_by_id.return_value = SimpleNamespace(
        asset_type="vultr",
        aws_access_key="token",
    )
    orphan = OrphanResourceInfo(
        resource_type="vultr_instance",
        resource_id="instance-id",
        asset_id=9,
        firewall_group_id="firewall-id",
    )

    with patch("services.orphan_resource_scan_service.VultrClient") as client_cls:
        assert service._cleanup_vultr_orphan(orphan) is True

    client_cls.return_value.delete_instance.assert_called_once_with("instance-id")
    client_cls.return_value.delete_managed_firewall_group.assert_called_once_with(
        "firewall-id"
    )
