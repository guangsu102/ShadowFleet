from __future__ import annotations

from database.state_repo import FleetNodeEventCreateRequest, StateRepo
from services.healing_models import HealRequest, InstanceNotFoundError
from services.healing_notifier import notify_healing_failure
from services.healing_support import build_failure_message
from services.orphan_node_cleanup_service import OrphanNodeCleanupService
from services.runtime_service import RuntimeContext
from utils.logger import set_event_type


def handle_healing_failure(
    *,
    runtime_context: RuntimeContext,
    state_repo: StateRepo,
    node_id: int,
    xboard_node_id: int,
    node_name: str,
    node_type: str,
    previous_status: str,
    strategy: str,
    request: HealRequest,
    error: BaseException,
) -> str:
    error_message = build_failure_message(error)

    # Special handling for instance not found (EC2 manually terminated)
    if isinstance(error, InstanceNotFoundError):
        return _handle_instance_not_found(
            runtime_context=runtime_context,
            state_repo=state_repo,
            node_id=node_id,
            xboard_node_id=xboard_node_id,
            node_name=node_name,
            node_type=node_type,
            request=request,
            error=error,
        )

    set_event_type("healing_failed")
    state_repo.update_node_status(
        xboard_node_id=xboard_node_id,
        status=previous_status,
        status_reason=request.reason,
        last_error=error_message,
    )
    state_repo.create_event(
        FleetNodeEventCreateRequest(
            node_id=node_id,
            xboard_node_id=xboard_node_id,
            event_type="healing_failed",
            correlation_id=runtime_context.correlation_id,
            from_status="healing",
            to_status=previous_status,
            message=error_message,
            payload={
                "reason": request.reason,
                "source": request.source,
                "strategy": strategy,
                "measurement_payload": request.measurement_payload,
            },
        )
    )
    notify_healing_failure(
        runtime_context=runtime_context,
        request=request,
        node_name=node_name,
        node_type=node_type,
        strategy=strategy,
        error_message=error_message,
    )
    return error_message


def _handle_instance_not_found(
    *,
    runtime_context: RuntimeContext,
    state_repo: StateRepo,
    node_id: int,
    xboard_node_id: int,
    node_name: str,
    node_type: str,
    request: HealRequest,
    error: InstanceNotFoundError,
) -> str:
    """
    Handle the case where the EC2 instance no longer exists (manually terminated).
    This will clean up the orphan node and trigger replenishment.
    """
    set_event_type("healing_instance_not_found")
    runtime_context.logger.warning(
        "EC2 instance no longer exists, triggering orphan node cleanup xboard_node_id=%s instance_id=%s",
        xboard_node_id,
        error.instance_id,
    )

    # Get current node record for cleanup
    node_record = state_repo.get_node_by_xboard_node_id(xboard_node_id)
    if node_record is None:
        error_message = f"Node not found for cleanup: xboard_node_id={xboard_node_id}"
        runtime_context.logger.error(error_message)
        return error_message

    # Perform orphan node cleanup
    cleanup_service = OrphanNodeCleanupService(runtime_context)
    try:
        result = cleanup_service.cleanup_orphan_node(
            node_record=node_record,
            reason=f"EC2 instance not found: {error.instance_id}",
        )
        if result.replenishment_triggered:
            return (
                f"EC2实例已不存在，节点已清理。补充任务已触发 "
                f"(task_ids={result.replenishment_task_ids})"
            )
        else:
            return "EC2实例已不存在，节点已清理（未触发补充：当前容量充足）"
    except Exception as cleanup_error:
        error_message = f"Orphan cleanup failed: {cleanup_error}"
        runtime_context.logger.exception(error_message)
        # Mark node as deleted locally even if Xboard cleanup fails
        state_repo.update_node_status(
            xboard_node_id=xboard_node_id,
            status="deleted",
            status_reason=f"ec2_instance_not_found: {error.instance_id}",
            last_error=error_message,
        )
        return error_message
