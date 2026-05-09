from __future__ import annotations

from dataclasses import dataclass

from database.asset_models import AssetNotFoundError
from database.asset_repo import AssetRepo
from database.state_models import FleetNodeRecord
from database.state_repo import FleetNodeEventCreateRequest, StateRepo
from services.fleet_scheduler_service import FleetSchedulerService
from services.node_registry_service import NodeRegistryService, NodeRegistryServiceError
from services.runtime_service import RuntimeContext
from utils.logger import set_event_type


@dataclass(frozen=True)
class OrphanNodeCleanupResult:
    xboard_node_id: int
    node_name: str
    node_type: str
    deleted: bool
    replenishment_triggered: bool
    replenishment_task_ids: list[int]


class OrphanNodeCleanupServiceError(RuntimeError):
    pass


class OrphanNodeCleanupService:
    """
    Handles cleanup of orphan nodes when their underlying infrastructure no longer exists.
    When an EC2 instance is manually terminated, this service:
    1. Deletes the node from Xboard (avoid dirty data)
    2. Marks the local record as deleted
    3. Triggers fleet scheduler to replenish the capacity gap
    """

    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime_context = runtime_context
        self._logger = runtime_context.logger.getChild("services.orphan_cleanup")
        self._state_repo = StateRepo(runtime_context)
        self._asset_repo = AssetRepo(runtime_context)
        self._node_registry = NodeRegistryService(runtime_context)
        self._scheduler: FleetSchedulerService | None = None

    @property
    def _scheduler_service(self) -> FleetSchedulerService:
        if self._scheduler is None:
            self._scheduler = FleetSchedulerService(self._runtime_context)
        return self._scheduler

    def cleanup_orphan_node(
        self,
        *,
        node_record: FleetNodeRecord,
        reason: str,
    ) -> OrphanNodeCleanupResult:
        """
        Clean up an orphan node whose underlying EC2 instance no longer exists.

        Args:
            node_record: The local fleet node record to clean up
            reason: Reason for cleanup (e.g., "ec2_instance_not_found")

        Returns:
            OrphanNodeCleanupResult with cleanup status and replenishment info
        """
        if node_record.xboard_node_id is None or node_record.xboard_node_id <= 0:
            raise OrphanNodeCleanupServiceError(
                f"Invalid xboard_node_id: {node_record.xboard_node_id}"
            )

        set_event_type("orphan_node_cleanup_started")
        self._logger.warning(
            "Cleaning up orphan node xboard_node_id=%s name=%s reason=%s",
            node_record.xboard_node_id,
            node_record.node_name,
            reason,
        )

        # Record the cleanup start event
        self._state_repo.create_event(
            FleetNodeEventCreateRequest(
                node_id=node_record.id,
                xboard_node_id=node_record.xboard_node_id,
                event_type="orphan_cleanup_started",
                correlation_id=self._runtime_context.correlation_id,
                from_status=node_record.status,
                to_status="deleting",
                message=f"Orphan node cleanup started: {reason}",
                payload={"reason": reason},
            )
        )

        # Step 1: Delete from Xboard and mark local record as deleted
        deleted = self._delete_node_from_xboard(node_record)

        # Step 2: Release asset allocation
        self._release_asset_allocation(node_record.xboard_node_id)

        # Step 3: Trigger replenishment if scheduler is enabled
        replenishment_task_ids = self._trigger_replenishment(node_record)
        replenishment_triggered = len(replenishment_task_ids) > 0

        # Record completion event
        self._state_repo.create_event(
            FleetNodeEventCreateRequest(
                node_id=node_record.id,
                xboard_node_id=node_record.xboard_node_id,
                event_type="orphan_cleanup_completed",
                correlation_id=self._runtime_context.correlation_id,
                from_status="deleting",
                to_status="deleted",
                message="Orphan node cleanup completed.",
                payload={
                    "reason": reason,
                    "deleted_from_xboard": deleted,
                    "replenishment_triggered": replenishment_triggered,
                    "replenishment_task_count": len(replenishment_task_ids),
                },
            )
        )

        set_event_type("orphan_node_cleanup_completed")
        self._logger.info(
            "Orphan node cleanup completed xboard_node_id=%s deleted=%s replenishment_triggered=%s",
            node_record.xboard_node_id,
            deleted,
            replenishment_triggered,
        )

        return OrphanNodeCleanupResult(
            xboard_node_id=node_record.xboard_node_id,
            node_name=node_record.node_name,
            node_type=node_record.node_type,
            deleted=deleted,
            replenishment_triggered=replenishment_triggered,
            replenishment_task_ids=replenishment_task_ids,
        )

    def _delete_node_from_xboard(self, node_record: FleetNodeRecord) -> bool:
        """Delete node from Xboard and mark local record as deleted."""
        try:
            self._node_registry.delete_node(
                xboard_node_id=node_record.xboard_node_id,
                status_reason="EC2实例已不存在，节点已从Xboard销毁",
            )
            return True
        except NodeRegistryServiceError as exc:
            self._logger.warning(
                "Failed to delete node from Xboard xboard_node_id=%s: %s",
                node_record.xboard_node_id,
                exc,
            )
            # Even if Xboard deletion fails, mark local record as deleted
            self._mark_local_deleted(node_record, "xboard_deletion_failed")
            return False

    def _mark_local_deleted(self, node_record: FleetNodeRecord, reason: str) -> None:
        """Mark local record as deleted without touching Xboard."""
        self._state_repo.mark_node_deleted(
            xboard_node_id=node_record.xboard_node_id,
            reason=f"orphan_cleanup: {reason}",
        )
        self._logger.info(
            "Marked local node as deleted xboard_node_id=%s reason=%s",
            node_record.xboard_node_id,
            reason,
        )

    def _release_asset_allocation(self, xboard_node_id: int) -> None:
        """Release asset allocation for the node."""
        try:
            self._asset_repo.release_allocation_by_xboard_node_id(xboard_node_id)
            self._logger.info(
                "Released asset allocation for xboard_node_id=%s",
                xboard_node_id,
            )
        except AssetNotFoundError:
            self._logger.debug(
                "No active allocation found for xboard_node_id=%s",
                xboard_node_id,
            )

    def _trigger_replenishment(self, node_record: FleetNodeRecord) -> list[int]:
        """Trigger fleet scheduler replenishment for the deleted node."""
        if not self._runtime_context.config.fleet_scheduler.enabled:
            self._logger.info(
                "Fleet scheduler disabled, skipping replenishment for orphan node xboard_node_id=%s",
                node_record.xboard_node_id,
            )
            return []

        region = node_record.aws_region or "unknown"
        protocol = node_record.node_type

        task_ids = self._scheduler_service.fill_gap_for_region_protocol(
            region=region,
            protocol_type=protocol,
            count=1,
            reason=f"orphan_node_cleanup",
        )

        if task_ids:
            self._logger.info(
                "Triggered replenishment for orphan node: xboard_node_id=%s region=%s protocol=%s task_ids=%s",
                node_record.xboard_node_id,
                region,
                protocol,
                task_ids,
            )
        else:
            self._logger.info(
                "No replenishment triggered for orphan node xboard_node_id=%s (no gap detected)",
                node_record.xboard_node_id,
            )

        return task_ids
