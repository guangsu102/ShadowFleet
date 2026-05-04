from __future__ import annotations

from models.message_models import TelegramMessage, TelegramNotificationType
from services.asset_selector_service import AssetSelectionResult
from services.node_registry_service import NodeStateChangeResult
from services.provisioning_models import ProvisionRequest
from services.runtime_service import RuntimeContext


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
            type=TelegramNotificationType.PROVISION_SUCCESS,
            level="INFO",
            title="节点开通成功",
            body=(
                f"节点名称={request.node_name} 协议={request.protocol_type} "
                f"资产={selection_result.asset_name} 区域={selection_result.region or '-'} "
                f"Xboard节点ID={online_result.xboard_node_id} "
                f"实例ID={instance_id or '-'} IPv6={ipv6_address or '-'} "
                f"域名={domain_name or '-'} Cloudflare记录ID={cloudflare_record_id or '-'}"
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
            type=TelegramNotificationType.PROVISION_FAILURE,
            level="ERROR",
            title="节点开通失败",
            body=(
                f"节点名称={request.node_name} 协议={request.protocol_type} "
                f"资产={selection_result.asset_name} 区域={selection_result.region or '-'} "
                f"Xboard节点ID={xboard_node_id or '-'} 实例ID={instance_id or '-'} "
                f"错误={error}"
            ),
        )
    )
