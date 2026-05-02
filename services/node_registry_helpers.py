from __future__ import annotations

from decimal import Decimal
import logging

from database.state_repo import FleetNodeRecord, StateRepo
from database.xboard_repo import XboardRepo
from services.node_registry_models import NodeRegistryServiceError, RegisterNodeRequest
from utils.logger import set_event_type


def validate_register_request(request: RegisterNodeRequest) -> None:
    if not request.node_type or not request.node_type.strip():
        raise ValueError("node_type must not be empty")
    if not request.node_name or not request.node_name.strip():
        raise ValueError("node_name must not be empty")
    if not request.host or not request.host.strip():
        raise ValueError("host must not be empty")
    if not request.port or not request.port.strip():
        raise ValueError("port must not be empty")
    if request.server_port <= 0:
        raise ValueError("server_port must be greater than 0")
    if request.rate <= Decimal("0"):
        raise ValueError("rate must be greater than 0")


def require_registered_node(state_repo: StateRepo, xboard_node_id: int) -> FleetNodeRecord:
    node_record = state_repo.get_node_by_xboard_node_id(xboard_node_id)
    if node_record is None:
        raise NodeRegistryServiceError(
            f"Local fleet node record not found for xboard_node_id={xboard_node_id}"
        )
    return node_record


def rollback_offline_transition(
    xboard_repo: XboardRepo,
    logger: logging.Logger,
    xboard_node_id: int,
) -> None:
    set_event_type("node_offline_compensating")
    try:
        xboard_repo.mark_node_online(xboard_node_id)
    except Exception as exc:
        logger.exception(
            "Failed to rollback Xboard node visibility during offline compensation xboard_node_id=%s",
            xboard_node_id,
        )
        raise NodeRegistryServiceError("Node offline compensation failed; manual review required") from exc

    set_event_type("node_offline_compensated")
    logger.info(
        "Rolled back Xboard node visibility after offline failure xboard_node_id=%s",
        xboard_node_id,
    )


def rollback_online_transition(
    xboard_repo: XboardRepo,
    logger: logging.Logger,
    xboard_node_id: int,
    previous_host: str | None,
) -> None:
    set_event_type("node_online_compensating")
    try:
        xboard_repo.mark_node_offline(xboard_node_id)
        if previous_host is not None:
            xboard_repo.update_node_host(xboard_node_id, previous_host)
    except Exception as exc:
        logger.exception("Failed to rollback Xboard online transition xboard_node_id=%s", xboard_node_id)
        raise NodeRegistryServiceError("Node online compensation failed; manual review required") from exc

    set_event_type("node_online_compensated")
    logger.info(
        "Rolled back Xboard online transition after local failure xboard_node_id=%s",
        xboard_node_id,
    )


def compensate_registration_failure(
    state_repo: StateRepo,
    xboard_repo: XboardRepo,
    logger: logging.Logger,
    xboard_node_id: int,
    local_node_id: int | None,
) -> None:
    set_event_type("node_registration_compensating")
    logger.exception(
        "Node registration failed; starting compensation for xboard_node_id=%s local_node_id=%s",
        xboard_node_id,
        local_node_id,
    )

    local_cleanup_error: BaseException | None = None
    if local_node_id is not None:
        try:
            state_repo.purge_node_record(xboard_node_id)
        except Exception as exc:
            local_cleanup_error = exc
            logger.exception(
                "Failed to purge local node during compensation xboard_node_id=%s",
                xboard_node_id,
            )

    xboard_cleanup_error: BaseException | None = None
    try:
        xboard_repo.delete_node(xboard_node_id)
    except Exception as exc:
        xboard_cleanup_error = exc
        logger.exception(
            "Failed to delete Xboard node during compensation xboard_node_id=%s",
            xboard_node_id,
        )

    if local_cleanup_error is None and xboard_cleanup_error is None:
        set_event_type("node_registration_compensated")
        logger.info("Node registration compensation completed for xboard_node_id=%s", xboard_node_id)
        return

    raise NodeRegistryServiceError("Node registration compensation failed; manual cleanup may be required")
