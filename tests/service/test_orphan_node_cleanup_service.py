from __future__ import annotations

from unittest.mock import MagicMock, patch

from services.node_registry_service import NodeRegistryServiceError
from services.orphan_node_cleanup_service import OrphanNodeCleanupService


def _cleanup_service() -> OrphanNodeCleanupService:
    runtime = MagicMock()
    runtime.correlation_id = "test-correlation"
    runtime.logger.getChild.return_value = MagicMock()
    runtime.config.fleet_scheduler.enabled = True
    with (
        patch("services.orphan_node_cleanup_service.StateRepo"),
        patch("services.orphan_node_cleanup_service.AssetRepo"),
        patch("services.orphan_node_cleanup_service.NodeRegistryService"),
    ):
        return OrphanNodeCleanupService(runtime)


def test_cleanup_failure_preserves_local_node_allocation_and_capacity() -> None:
    service = _cleanup_service()
    node = MagicMock(
        id=7,
        xboard_node_id=1007,
        node_name="azure-node",
        node_type="AnyTLS",
        status="online",
        aws_region="japaneast",
    )
    service._node_registry.delete_node.side_effect = NodeRegistryServiceError(
        "Azure credentials not found"
    )

    result = service.cleanup_orphan_node(
        node_record=node,
        reason="Azure VM not found",
    )

    assert result.deleted is False
    assert result.replenishment_triggered is False
    assert result.replenishment_task_ids == []
    service._state_repo.mark_node_deleted.assert_not_called()
    service._asset_repo.release_allocation_by_xboard_node_id.assert_not_called()
    assert service._scheduler is None
    failure_event = service._state_repo.create_event.call_args_list[-1].args[0]
    assert failure_event.event_type == "orphan_cleanup_failed"
    assert failure_event.to_status == "online"
