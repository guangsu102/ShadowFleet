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
    """
    补偿节点注册失败，确保所有回滚操作都尝试执行

    改进：
    1. 即使某个回滚失败，也继续执行其他回滚
    2. 收集所有失败的回滚操作
    3. 记录孤儿资源以便后续清理
    """
    set_event_type("node_registration_compensating")
    logger.error(
        "Node registration failed; starting compensation for xboard_node_id=%s local_node_id=%s",
        xboard_node_id,
        local_node_id,
    )

    rollback_errors = []

    # 1. 清理本地 SQLite 记录
    if local_node_id is not None:
        try:
            state_repo.purge_node_record(xboard_node_id)
            logger.info(
                "Successfully purged local node during compensation xboard_node_id=%s",
                xboard_node_id,
            )
        except Exception as exc:
            rollback_errors.append(("local_node", exc))
            logger.exception(
                "Failed to purge local node during compensation xboard_node_id=%s",
                xboard_node_id,
            )

    # 2. 清理 Xboard 节点（即使本地清理失败也要执行）
    try:
        xboard_repo.delete_node(xboard_node_id)
        logger.info(
            "Successfully deleted Xboard node during compensation xboard_node_id=%s",
            xboard_node_id,
        )
    except Exception as exc:
        rollback_errors.append(("xboard_node", exc))
        logger.exception(
            "Failed to delete Xboard node during compensation xboard_node_id=%s",
            xboard_node_id,
        )

    # 3. 如果所有回滚都成功，返回
    if not rollback_errors:
        set_event_type("node_registration_compensated")
        logger.info("Node registration compensation completed for xboard_node_id=%s", xboard_node_id)
        return

    # 4. 记录孤儿资源到数据库（供后续清理）
    try:
        _record_orphan_node(
            state_repo=state_repo,
            xboard_node_id=xboard_node_id,
            local_node_id=local_node_id,
            rollback_errors=rollback_errors,
        )
    except Exception as exc:
        logger.exception(
            "Failed to record orphan node xboard_node_id=%s: %s",
            xboard_node_id,
            exc,
        )

    # 5. 抛出异常，但不阻止调用方继续执行
    error_summary = "; ".join([f"{name}: {str(err)}" for name, err in rollback_errors])
    raise NodeRegistryServiceError(
        f"Node registration compensation partially failed for xboard_node_id={xboard_node_id}. "
        f"Errors: {error_summary}. Manual cleanup may be required."
    )


def _record_orphan_node(
    state_repo: StateRepo,
    xboard_node_id: int,
    local_node_id: int | None,
    rollback_errors: list[tuple[str, Exception]],
) -> None:
    """
    记录孤儿节点到数据库，供后续清理任务处理

    注意：这是一个辅助函数，如果记录失败不应该影响主流程
    """
    from database.state_repo import FleetNodeEventCreateRequest

    error_details = {
        "xboard_node_id": xboard_node_id,
        "local_node_id": local_node_id,
        "rollback_errors": [
            {"resource": name, "error": str(err)}
            for name, err in rollback_errors
        ],
    }

    # 如果本地节点存在，记录事件
    if local_node_id:
        try:
            state_repo.create_event(
                FleetNodeEventCreateRequest(
                    node_id=local_node_id,
                    xboard_node_id=xboard_node_id,
                    event_type="orphan_resource_detected",
                    correlation_id="compensation",
                    message="Node registration compensation failed, orphan resources detected",
                    payload=error_details,
                )
            )
        except Exception:
            # 忽略事件记录失败，不影响主流程
            pass
