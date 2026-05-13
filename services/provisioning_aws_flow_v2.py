"""
集成新的 Provisioning Pipeline

将新的 Pipeline 集成到现有的 provisioning_aws_flow.py 中，
同时保留向后兼容性。
"""

from __future__ import annotations

from database.asset_repo import AssetRepo
from services.provisioning_models import ProvisionRequest, ProvisionResult
from services.provisioning_support import ProvisioningDependencies
from utils.logger import set_event_type


def provision_aws_node_with_pipeline(
    dependencies: ProvisioningDependencies,
    asset_repo: AssetRepo,
    request: ProvisionRequest,
) -> ProvisionResult:
    """
    使用新的 Pipeline 模式进行 AWS 节点 Provisioning
    """
    from services.provisioning_pipeline import create_aws_provisioning_pipeline
    from database.asset_repo import AssetEventCreateRequest

    set_event_type("provisioning_pipeline_started")
    dependencies.logger.info(
        "Starting AWS provisioning with pipeline: node=%s protocol=%s",
        request.node_name,
        request.protocol_type,
    )

    try:
        # 创建并执行 Pipeline
        pipeline = create_aws_provisioning_pipeline(dependencies.runtime_context)
        context = pipeline.execute(request)

        # 记录成功事件
        asset_repo.create_asset_event(
            AssetEventCreateRequest(
                asset_id=context.selection_result.asset_id,
                event_type="provisioning_succeeded",
                correlation_id=dependencies.runtime_context.correlation_id,
                message="Provisioning completed successfully using pipeline.",
                payload={
                    "xboard_node_id": context.online_result.xboard_node_id,
                    "instance_id": context.launch_result.instance_id,
                },
            )
        )

        # 发送成功通知
        from services.provisioning_notifier import notify_success

        ipv6_address = (
            context.launch_result.ipv6_addresses[0]
            if context.launch_result.ipv6_addresses
            else None
        )
        ipv4_address = context.launch_result.ipv4_address

        notify_success(
            runtime_context=dependencies.runtime_context,
            request=request,
            selection_result=context.selection_result,
            online_result=context.online_result,
            instance_id=context.launch_result.instance_id,
            ipv6_address=ipv6_address,
            domain_name=context.effective_domain_name,
            cloudflare_record_id=context.cloudflare_record_id,
        )

        # 构建返回结果
        return ProvisionResult(
            local_node_id=context.online_result.local_node_id,
            xboard_node_id=context.online_result.xboard_node_id,
            asset_id=context.selection_result.asset_id,
            asset_type=context.selection_result.asset_type,
            protocol_type=request.protocol_type,
            node_name=request.node_name,
            status=context.online_result.status,
            aws_account_id=context.selection_result.aws_account_id,
            region=context.selection_result.region,
            instance_id=context.launch_result.instance_id,
            network_interface_id=context.launch_result.network_interface_id,
            ipv4_address=ipv4_address,
            ipv6_address=ipv6_address,
            domain_name=context.effective_domain_name,
            cloudflare_record_id=context.cloudflare_record_id,
            cloudflare_a_record_id=(
                context.dns_sync_result.a_record_id if context.dns_sync_result else None
            ),
            cloudflare_aaaa_record_id=(
                context.dns_sync_result.aaaa_record_id if context.dns_sync_result else None
            ),
        )

    except Exception as exc:
        set_event_type("provisioning_pipeline_failed")
        dependencies.logger.exception("AWS provisioning with pipeline failed: %s", exc)
        raise
