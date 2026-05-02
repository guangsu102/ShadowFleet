from __future__ import annotations

from models.message_models import TelegramMessage
from services.runtime_service import RuntimeContext


def notify_account_abandoned(
    runtime_context: RuntimeContext,
    aws_account_id: str,
    region: str | None,
    source_xboard_node_id: int | None,
    error_code: str,
    error_message: str,
    deleted_node_count: int,
) -> None:
    runtime_context.tg_reporter.send(
        TelegramMessage(
            level="CRITICAL",
            title="AWS账号封禁，已执行静默弃尸",
            body=(
                f"AWS账号={aws_account_id} 区域={region or '-'} 触发节点={source_xboard_node_id or '-'} "
                f"错误码={error_code} 错误信息={error_message} "
                f"已销毁节点数={deleted_node_count} Correlation-ID={runtime_context.correlation_id}"
            ),
        )
    )
