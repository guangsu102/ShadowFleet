from __future__ import annotations

from dataclasses import dataclass

from models.message_models import TelegramMessage
from services.runtime_service import RuntimeContext


@dataclass(frozen=True)
class DaemonWorkerAlertContext:
    worker_name: str
    error_message: str
    correlation_id: str


def notify_daemon_worker_cycle_failed(
    runtime_context: RuntimeContext,
    ctx: DaemonWorkerAlertContext,
) -> None:
    runtime_context.tg_reporter.send(
        TelegramMessage(
            level="ERROR",
            title=f"守护进程 Worker 异常: {ctx.worker_name}",
            body=(
                f"Worker={ctx.worker_name} 周期执行失败 "
                f"错误={ctx.error_message} "
                f"Correlation-ID={ctx.correlation_id}"
            ),
        )
    )
