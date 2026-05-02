from __future__ import annotations

from services.asset_selector_service import AssetSelectionResult
from services.node_registry_service import NodeStateChangeResult
from services.provisioning_models import ProvisionRequest
from services.runtime_service import RuntimeContext
from models.message_models import TelegramMessage


def notify_success(
    runtime_context: RuntimeContext,
    request: ProvisionRequest,
    selection_result: AssetSelectionResult,
    online_result: NodeStateChangeResult,
    instance_id: str | None,
    ipv6_address: str | None,
    domain_name: str | None,
    cloudflare_record_id: str | None,
) -> None:
    runtime_context.tg_reporter.send(
        TelegramMessage(
            level="INFO",
            title="ShadowFleet provision succeeded",
            body=(
                f"node={request.node_name} protocol={request.protocol_type} "
                f"asset={selection_result.asset_name} region={selection_result.region or '-'} "
                f"xboard_node_id={online_result.xboard_node_id} "
                f"instance_id={instance_id or '-'} ipv6={ipv6_address or '-'} "
                f"domain={domain_name or '-'} cf_record_id={cloudflare_record_id or '-'}"
            ),
        )
    )


def notify_failure(
    runtime_context: RuntimeContext,
    request: ProvisionRequest,
    selection_result: AssetSelectionResult,
    error: BaseException,
    instance_id: str | None,
    xboard_node_id: int | None,
) -> None:
    runtime_context.tg_reporter.send(
        TelegramMessage(
            level="ERROR",
            title="ShadowFleet provision failed",
            body=(
                f"node={request.node_name} protocol={request.protocol_type} "
                f"asset={selection_result.asset_name} region={selection_result.region or '-'} "
                f"xboard_node_id={xboard_node_id or '-'} instance_id={instance_id or '-'} "
                f"error={error}"
            ),
        )
    )
