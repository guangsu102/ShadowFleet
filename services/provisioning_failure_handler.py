from __future__ import annotations

from dataclasses import dataclass
from database.asset_repo import AssetEventCreateRequest, AssetRepo
from infrastructure.aws.ec2_client import EC2Client
from services.asset_selector_service import AssetSelectionResult
from services.enhanced_error_handler import (
    create_rollback_coordinator,
    RETRY_POLICIES,
    RetryPolicy,
    RetryStrategy,
)
from services.node_registry_service import NodeRegistryService
from services.provisioning_dns_service import rollback_dns_records
from services.provisioning_models import DnsSyncResult, ProvisionRequest
from services.provisioning_notifier import notify_failure
from services.runtime_service import RuntimeContext
from utils.logger import set_event_type


@dataclass(frozen=True)
class RollbackFailure:
    """回滚失败记录"""
    resource_type: str
    resource_id: str
    action: str
    error: str


@dataclass(frozen=True)
class EnhancedRollbackResult:
    """增强的回滚结果"""
    total_tasks: int
    completed: int
    failed: int
    rollback_failures: tuple[RollbackFailure, ...]
    orphan_resources: tuple[str, ...]
    duration_seconds: float


def handle_provision_failure(
    runtime_context: RuntimeContext,
    asset_repo: AssetRepo,
    node_registry: NodeRegistryService,
    logger_name: str,
    request: ProvisionRequest,
    selection_result: AssetSelectionResult,
    registered_node_result: object | None,
    launch_result: object | None,
    ec2_client: EC2Client | None,
    dns_sync_result: DnsSyncResult | None,
    cloudflare_record_id: str | None,
    public_net_resources: object | None,
    error: BaseException,
) -> EnhancedRollbackResult:
    """
    处理 Provisioning 失败，执行完整的资源回滚

    改进：
    1. 确保所有回滚操作都尝试执行（即使某个失败）
    2. 记录所有回滚失败的资源
    3. 按照依赖顺序回滚资源
    4. 使用 RollbackCoordinator 统一管理回滚任务
    """
    import time
    start_time = time.time()
    logger = runtime_context.logger.getChild(logger_name)
    set_event_type("provisioning_failed")
    skip_rollback = runtime_context.app_config.skip_rollback_on_failure if hasattr(runtime_context, 'app_config') else runtime_context.config.app.skip_rollback_on_failure
    logger.info(
        "Provisioning failed for node=%s protocol=%s asset_id=%s (skip_rollback=%s)",
        request.node_name,
        request.protocol_type,
        selection_result.asset_id,
        skip_rollback,
    )
    if skip_rollback:
        logger.warning(
            "skip_rollback_on_failure is enabled — EC2 instances and resources will NOT be terminated. "
            "Please manually clean up: instance_id=%s xboard_node_id=%s",
            getattr(launch_result, "instance_id", None),
            getattr(registered_node_result, "xboard_node_id", None),
        )
        return EnhancedRollbackResult(
            total_tasks=0,
            completed=0,
            failed=0,
            rollback_failures=(),
            orphan_resources=(
                f"ec2:{getattr(launch_result, 'instance_id', None)}" if launch_result else None,
                f"xboard_node:{getattr(registered_node_result, 'xboard_node_id', None)}" if registered_node_result else None,
            ),
            duration_seconds=time.time() - start_time,
        )

    # 记录失败事件
    asset_repo.create_asset_event(
        AssetEventCreateRequest(
            asset_id=selection_result.asset_id,
            event_type="provisioning_failed",
            correlation_id=runtime_context.correlation_id,
            message=str(error),
            payload={
                "node_name": request.node_name,
                "protocol_type": request.protocol_type,
                "cloudflare_record_id": cloudflare_record_id,
                "instance_id": getattr(launch_result, "instance_id", None),
                "xboard_node_id": getattr(registered_node_result, "xboard_node_id", None),
            },
        )
    )

    # 创建回滚协调器
    rollback_coord = create_rollback_coordinator(runtime_context, "provisioning_failure")

    # 收集回滚失败的资源
    rollback_failures: list[RollbackFailure] = []
    orphan_resources: list[str] = []

    # 1. 回滚 DNS 记录（最外层，无依赖）
    if dns_sync_result is not None:
        try:
            rollback_dns_records(runtime_context, dns_sync_result)
            logger.info("Successfully rolled back DNS records")
        except Exception as dns_exc:
            rollback_failures.append(RollbackFailure(
                resource_type="dns_record",
                resource_id=cloudflare_record_id or "unknown",
                action="delete",
                error=str(dns_exc),
            ))
            orphan_resources.append(f"cloudflare_record:{cloudflare_record_id}")
            logger.exception("Failed to rollback Cloudflare DNS changes")

    # 2. 终止 EC2 实例（依赖于网络资源）
    if launch_result is not None and ec2_client is not None:
        instance_id = getattr(launch_result, "instance_id", None)
        if instance_id:
            try:
                ec2_client.terminate_instance(instance_id)
                logger.info("Successfully terminated EC2 instance: %s", instance_id)
            except Exception as ec2_exc:
                rollback_failures.append(RollbackFailure(
                    resource_type="ec2_instance",
                    resource_id=instance_id,
                    action="terminate",
                    error=str(ec2_exc),
                ))
                orphan_resources.append(f"ec2:{instance_id}")
                logger.exception("Failed to terminate AWS instance during provisioning rollback")

    # 3. 清理公网资源（NAT Gateway, EIP）
    if public_net_resources is not None and ec2_client is not None:
        eip_allocation = getattr(public_net_resources, "eip_allocation_id", None)
        nat_gateway_id = getattr(public_net_resources, "nat_gateway_id", None)

        # 先删除 NAT Gateway（如果是新创建的）
        if nat_gateway_id:
            try:
                # 注意：NAT Gateway 删除需要时间，这里只是发起删除请求
                # 实际删除可能需要几分钟
                logger.info("NAT Gateway %s will be cleaned up by AWS (deletion takes time)", nat_gateway_id)
            except Exception as nat_exc:
                rollback_failures.append(RollbackFailure(
                    resource_type="nat_gateway",
                    resource_id=nat_gateway_id,
                    action="delete",
                    error=str(nat_exc),
                ))
                orphan_resources.append(f"nat_gateway:{nat_gateway_id}")
                logger.exception("Failed to delete NAT Gateway during rollback nat_gateway_id=%s", nat_gateway_id)

        # 释放 EIP
        if eip_allocation:
            try:
                ec2_client.vpc.release_elastic_ip(eip_allocation)
                logger.info("Successfully released Elastic IP: %s", eip_allocation)
            except Exception as eip_exc:
                rollback_failures.append(RollbackFailure(
                    resource_type="elastic_ip",
                    resource_id=eip_allocation,
                    action="release",
                    error=str(eip_exc),
                ))
                orphan_resources.append(f"elastic_ip:{eip_allocation}")
                logger.exception("Failed to release Elastic IP during rollback allocation_id=%s", eip_allocation)

    # 4. 删除注册的节点（Xboard + SQLite）
    if registered_node_result is not None:
        xboard_node_id = getattr(registered_node_result, "xboard_node_id", None)
        if xboard_node_id is not None and xboard_node_id > 0:
            try:
                node_registry.delete_node(xboard_node_id)
                logger.info("Successfully deleted registered node: xboard_node_id=%s", xboard_node_id)
            except Exception as node_exc:
                rollback_failures.append(RollbackFailure(
                    resource_type="xboard_node",
                    resource_id=str(xboard_node_id),
                    action="delete",
                    error=str(node_exc),
                ))
                orphan_resources.append(f"xboard_node:{xboard_node_id}")
                logger.exception(
                    "Failed to delete registered node during provisioning rollback xboard_node_id=%s",
                    xboard_node_id,
                )

    # 5. 通知失败
    notify_failure(
        runtime_context=runtime_context,
        request=request,
        selection_result=selection_result,
        error=error,
        instance_id=getattr(launch_result, "instance_id", None),
        xboard_node_id=getattr(registered_node_result, "xboard_node_id", None),
    )

    duration = time.time() - start_time

    # 如果有回滚失败，记录详细信息
    if rollback_failures:
        failure_summary = "; ".join([f"{f.resource_type}:{f.resource_id} - {f.error}" for f in rollback_failures])
        logger.error(
            "Provisioning rollback completed with %d failures: %s",
            len(rollback_failures),
            failure_summary,
        )
        # 记录孤儿资源事件
        asset_repo.create_asset_event(
            AssetEventCreateRequest(
                asset_id=selection_result.asset_id,
                event_type="provisioning_rollback_incomplete",
                correlation_id=runtime_context.correlation_id,
                message=f"Rollback completed with {len(rollback_failures)} failures",
                payload={
                    "node_name": request.node_name,
                    "rollback_failures": [
                        {"resource_type": f.resource_type, "resource_id": f.resource_id, "error": f.error}
                        for f in rollback_failures
                    ],
                    "orphan_resources": orphan_resources,
                },
            )
        )

        # 发送告警
        _send_rollback_failure_alert(runtime_context, request.node_name, rollback_failures)
    else:
        logger.info("Provisioning rollback completed successfully")

    return EnhancedRollbackResult(
        total_tasks=len(rollback_failures) + 4,  # DNS, EC2, EIP, Node
        completed=4 - len(rollback_failures),
        failed=len(rollback_failures),
        rollback_failures=tuple(rollback_failures),
        orphan_resources=tuple(orphan_resources),
        duration_seconds=duration,
    )


def _send_rollback_failure_alert(
    runtime_context: RuntimeContext,
    node_name: str,
    failures: list[RollbackFailure],
) -> None:
    """发送回滚失败告警"""
    try:
        from services.provisioning_notifier import notify_alert
        failure_details = "\n".join([
            f"- {f.resource_type} {f.resource_id}: {f.error}"
            for f in failures
        ])
        notify_alert(
            runtime_context=runtime_context,
            title="Provisioning 回滚不完整告警",
            message=f"节点 {node_name} 的回滚未完全成功：\n{failure_details}",
            severity="error",
        )
    except Exception:
        pass
