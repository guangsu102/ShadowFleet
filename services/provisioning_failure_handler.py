from __future__ import annotations

from database.asset_repo import AssetEventCreateRequest, AssetRepo
from infrastructure.aws.ec2_client import EC2Client
from services.asset_selector_service import AssetSelectionResult
from services.node_registry_service import NodeRegistryService
from services.provisioning_dns_service import rollback_dns_records
from services.provisioning_models import DnsSyncResult, ProvisionRequest
from services.provisioning_notifier import notify_failure
from services.runtime_service import RuntimeContext
from utils.logger import set_event_type


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
    error: BaseException,
) -> None:
    logger = runtime_context.logger.getChild(logger_name)
    set_event_type("provisioning_failed")
    logger.exception(
        "Provisioning failed for node=%s protocol=%s asset_id=%s",
        request.node_name,
        request.protocol_type,
        selection_result.asset_id,
    )
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

    if dns_sync_result is not None:
        try:
            rollback_dns_records(runtime_context, dns_sync_result)
        except Exception:
            logger.exception("Failed to rollback Cloudflare DNS changes")

    if launch_result is not None and ec2_client is not None:
        try:
            ec2_client.terminate_instance(getattr(launch_result, "instance_id"))
        except Exception:
            logger.exception("Failed to terminate AWS instance during provisioning rollback")

    if registered_node_result is not None:
        xboard_node_id = getattr(registered_node_result, "xboard_node_id", None)
        if xboard_node_id is not None and xboard_node_id > 0:
            try:
                node_registry.delete_node(xboard_node_id)
            except Exception:
                logger.exception(
                    "Failed to delete registered node during provisioning rollback xboard_node_id=%s",
                    xboard_node_id,
                )

    notify_failure(
        runtime_context=runtime_context,
        request=request,
        selection_result=selection_result,
        error=error,
        instance_id=getattr(launch_result, "instance_id", None),
        xboard_node_id=getattr(registered_node_result, "xboard_node_id", None),
    )
