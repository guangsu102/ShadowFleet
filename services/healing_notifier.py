from __future__ import annotations

from models.message_models import TelegramMessage
from services.healing_models import HealRequest, HealResult
from services.runtime_service import RuntimeContext


def notify_healing_success(runtime_context: RuntimeContext, result: HealResult) -> None:
    runtime_context.tg_reporter.send(
        TelegramMessage(
            level="INFO",
            title="战损自愈完成",
            body=(
                f"节点={result.node_name} 协议={result.node_type} 策略={result.strategy} "
                f"Xboard节点ID={result.xboard_node_id} 资产类型={result.asset_type} "
                f"旧IPv6={result.old_ipv6_address or '-'} 新IPv6={result.new_ipv6_address or '-'} "
                f"域名={result.domain_name or '-'} Cloudflare记录ID={result.cloudflare_record_id or '-'} "
                f"小黄云={'开启' if result.proxied_enabled else '关闭'} "
                f"耗时={result.duration_ms}ms Correlation-ID={result.correlation_id}"
            ),
        )
    )


def notify_healing_failure(
    runtime_context: RuntimeContext,
    request: HealRequest,
    node_name: str,
    node_type: str,
    strategy: str,
    error_message: str,
) -> None:
    runtime_context.tg_reporter.send(
        TelegramMessage(
            level="ERROR",
            title="战损自愈失败",
            body=(
                f"节点={node_name} 协议={node_type} 策略={strategy} "
                f"原因={request.reason} 错误={error_message} 来源={request.source} "
                f"Xboard节点ID={request.xboard_node_id} "
                f"Correlation-ID={runtime_context.correlation_id}"
            ),
        )
    )
