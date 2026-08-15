from __future__ import annotations

import logging
from unittest.mock import MagicMock

from api.router.tasks import ManualTaskCreateRequest
from database.state_models import FleetNodeCreateRequest
from database.state_repo import StateRepo
from services.dashboard_service import DashboardService


def _runtime(sqlite_connection) -> MagicMock:
    runtime = MagicMock()
    runtime.logger = MagicMock(spec=logging.Logger)
    runtime.logger.getChild.return_value = runtime.logger
    runtime.correlation_id = "gcp-regression-correlation"
    manager = MagicMock()
    manager.connection.return_value.__enter__.return_value = sqlite_connection
    manager.connection.return_value.__exit__.return_value = False
    runtime.sqlite_manager = manager
    return runtime


def test_manual_task_api_accepts_gcp_ipv4_rotation_strategy() -> None:
    request = ManualTaskCreateRequest(
        task_type="force_heal",
        xboard_node_id=12352,
        force_strategy="gcp_ipv4_rotate",
    )

    assert request.force_strategy == "gcp_ipv4_rotate"


def test_state_repo_derives_gcp_type_without_asset_allocation(
    in_memory_sqlite_db,
) -> None:
    repo = StateRepo(_runtime(in_memory_sqlite_db))
    repo.create_node(
        FleetNodeCreateRequest(
            xboard_node_id=12352,
            node_name="gcp-node",
            node_type="Trojan",
            status="provisioning",
            aws_account_id="gcp:shadowfleet-test",
            aws_region="asia-east1-a",
            aws_instance_id="sf-gcp-12352",
        )
    )

    node = repo.get_node_by_xboard_node_id(12352)

    assert node is not None
    assert node.asset_type == "gcp"


def test_dashboard_derives_gcp_type_without_asset_allocation(
    in_memory_sqlite_db,
) -> None:
    runtime = _runtime(in_memory_sqlite_db)
    StateRepo(runtime).create_node(
        FleetNodeCreateRequest(
            xboard_node_id=12353,
            node_name="gcp-dashboard-node",
            node_type="AnyTLS",
            status="online",
            aws_account_id="gcp:shadowfleet-test",
            aws_region="asia-east1-a",
            aws_instance_id="sf-gcp-12353",
        )
    )
    service = object.__new__(DashboardService)
    service._sqlite_manager = runtime.sqlite_manager

    rows = service._list_node_rows()

    row = next(item for item in rows if item.xboard_node_id == 12353)
    assert row.asset_type == "gcp"
