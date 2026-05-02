from __future__ import annotations

from database.state_repo import FleetNodeEventCreateRequest, StateRepo
from services.healing_models import HealRequest
from services.healing_notifier import notify_healing_failure
from services.healing_support import build_failure_message
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
