from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from database.asset_repo import AssetRepo


def _repo(sqlite_connection) -> AssetRepo:
    runtime = MagicMock()
    runtime.logger = MagicMock(spec=logging.Logger)
    runtime.logger.getChild.return_value = runtime.logger
    sqlite_manager = MagicMock()
    sqlite_manager.connection.return_value.__enter__.return_value = sqlite_connection
    sqlite_manager.connection.return_value.__exit__.return_value = False
    runtime.sqlite_manager = sqlite_manager
    return AssetRepo(runtime)


def _seed_allocations(connection) -> int:
    connection.execute(
        """
        INSERT INTO fleet_assets (
            asset_type, asset_name, status, created_at, updated_at
        ) VALUES ('vultr', 'vultr-test', 'active', '2026-01-01', '2026-01-01')
        """
    )
    allocation_id = int(
        connection.execute(
            """
            INSERT INTO fleet_asset_allocations (
                asset_id, fleet_node_id, xboard_node_id, protocol_type,
                allocation_status, vcpu_count, created_at, updated_at
            ) VALUES (1, NULL, 9001, 'Trojan', 'allocated', 1, '2026-01-01', '2026-01-01')
            """
        ).lastrowid
    )
    connection.execute(
        """
        INSERT INTO fleet_asset_port_allocations (
            asset_id, fleet_node_id, xboard_node_id, server_port,
            protocol_type, allocation_status, created_at, updated_at
        ) VALUES (1, NULL, 9001, 443, 'Trojan', 'allocated', '2026-01-01', '2026-01-01')
        """
    )
    connection.execute(
        """
        INSERT INTO fleet_asset_port_allocations (
            asset_id, fleet_node_id, xboard_node_id, server_port,
            protocol_type, allocation_status, created_at, updated_at
        ) VALUES (1, NULL, 9002, 8443, 'Trojan', 'allocated', '2026-01-01', '2026-01-01')
        """
    )
    connection.commit()
    return allocation_id


def test_release_allocation_by_id_releases_only_linked_ports(
    in_memory_sqlite_db,
) -> None:
    allocation_id = _seed_allocations(in_memory_sqlite_db)
    repo = _repo(in_memory_sqlite_db)

    assert repo.release_allocation_by_id(allocation_id) is True

    allocation = in_memory_sqlite_db.execute(
        "SELECT allocation_status FROM fleet_asset_allocations WHERE id = ?",
        (allocation_id,),
    ).fetchone()
    ports = in_memory_sqlite_db.execute(
        """
        SELECT xboard_node_id, allocation_status
        FROM fleet_asset_port_allocations
        ORDER BY xboard_node_id
        """
    ).fetchall()
    assert allocation["allocation_status"] == "released"
    assert [(row["xboard_node_id"], row["allocation_status"]) for row in ports] == [
        (9001, "released"),
        (9002, "allocated"),
    ]


def test_release_allocation_by_id_is_idempotent(in_memory_sqlite_db) -> None:
    allocation_id = _seed_allocations(in_memory_sqlite_db)
    repo = _repo(in_memory_sqlite_db)

    assert repo.release_allocation_by_id(allocation_id) is True
    assert repo.release_allocation_by_id(allocation_id) is False


def test_release_allocation_by_id_rejects_invalid_id(in_memory_sqlite_db) -> None:
    repo = _repo(in_memory_sqlite_db)

    with pytest.raises(ValueError, match="greater than 0"):
        repo.release_allocation_by_id(0)
