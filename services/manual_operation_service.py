from __future__ import annotations

from database.asset_repo import AssetRepo
from database.manual_operation_task_repo import (
    ManualOperationTaskCreateRequest,
    ManualOperationTaskRepo,
)
from database.state_repo import FleetNodeEventCreateRequest, StateRepo
from database.xboard_repo import XboardRepo
from services.healer_service import HealerService
from services.healing_models import HealRequest
from services.healing_support import AWS_HEALABLE_PROTOCOLS, SELF_HOSTED_PROXY_PROTOCOLS
from services.monitor_models import MonitorCandidate
from services.monitor_support import is_in_heal_cooldown, to_monitor_candidate, utcnow
from services.node_registry_service import NodeRegistryService
from services.probe_client import ProbeClient
from services.runtime_service import RuntimeContext
from services.manual_operation_models import (
    ManualOperationRequest,
    ManualOperationSubmitResult,
    ManualOperationTaskRecord,
)
from utils.logger import generate_correlation_id, set_correlation_id, set_event_type


class ManualOperationService:
    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime_context = runtime_context
        self._logger = runtime_context.logger.getChild("services.manual_operation")
        self._task_repo = ManualOperationTaskRepo(runtime_context)
        self._state_repo = StateRepo(runtime_context)
        self._asset_repo = AssetRepo(runtime_context)
        self._xboard_repo = XboardRepo(runtime_context) if runtime_context.db_pool is not None else None
        self._probe_client = ProbeClient(runtime_context)
        self._node_registry = NodeRegistryService(runtime_context) if runtime_context.db_pool is not None else None
        self._healer_service = HealerService(runtime_context) if runtime_context.db_pool is not None else None
        self._max_attempts = runtime_context.config.app.max_retries + 1
        self._retry_backoff_seconds = runtime_context.config.app.retry_backoff_seconds

    def submit_task(self, request: ManualOperationRequest) -> ManualOperationSubmitResult:
        self._validate_submit_request(request)
        node_record = self._state_repo.get_node_by_xboard_node_id(request.xboard_node_id)
        if node_record is None:
            raise ValueError(f"节点不存在: xboard_node_id={request.xboard_node_id}")
        self._validate_task_support(request=request, node_type=node_record.node_type, is_aws=node_record.aws_account_id is not None)
        if self._task_repo.has_pending_task(
            xboard_node_id=request.xboard_node_id,
            task_type=request.task_type,
        ):
            raise ValueError("该节点已有同类型人工任务在队列或执行中")
        if request.task_type == "force_heal" and is_in_heal_cooldown(
            node_record,
            now_utc=utcnow(),
            cooldown_seconds=self._runtime_context.config.app.sentinel_heal_cooldown_seconds,
        ):
            raise ValueError("该节点仍处于自愈冷却期，暂不允许再次强制换 IP")
        correlation_id = generate_correlation_id()
        original_correlation_id = self._runtime_context.correlation_id
        set_correlation_id(correlation_id)
        try:
            task_id = self._task_repo.create_task(
                ManualOperationTaskCreateRequest(
                    correlation_id=correlation_id,
                    task_type=request.task_type,
                    xboard_node_id=request.xboard_node_id,
                    operator_name=self._normalize_optional_text(request.operator_name),
                    request_payload={
                        "reason": self._normalize_optional_text(request.reason),
                        "force_strategy": self._normalize_optional_text(request.force_strategy),
                    },
                    max_attempts=self._max_attempts,
                )
            )
            set_event_type("manual_operation_task_submitted")
            self._logger.info(
                "Submitted manual task id=%s type=%s xboard_node_id=%s",
                task_id,
                request.task_type,
                request.xboard_node_id,
            )
            return ManualOperationSubmitResult(
                task_id=task_id,
                correlation_id=correlation_id,
                status="queued",
            )
        finally:
            set_correlation_id(original_correlation_id)
            set_event_type("general")

    def list_recent_tasks(self, limit: int = 20) -> list[ManualOperationTaskRecord]:
        return self._task_repo.list_recent_tasks(limit=limit)

    def process_next_task(self, worker_id: str) -> ManualOperationTaskRecord | None:
        task_record = self._task_repo.claim_next_task(worker_id)
        if task_record is None:
            return None
        original_correlation_id = self._runtime_context.correlation_id
        set_correlation_id(task_record.correlation_id)
        try:
            result_payload = self._execute_task(task_record)
            self._task_repo.mark_task_succeeded(task_record.id, result_payload)
        except Exception as exc:
            error_message = str(exc).strip() or exc.__class__.__name__
            if task_record.attempt_count >= task_record.max_attempts:
                self._task_repo.mark_task_failed(task_record.id, error_message)
            else:
                self._task_repo.mark_task_for_retry(
                    task_record.id,
                    error_message,
                    self._retry_backoff_seconds,
                )
        finally:
            set_correlation_id(original_correlation_id)
            set_event_type("general")
        return self._task_repo.get_task_by_id(task_record.id)

    def _execute_task(self, task_record: ManualOperationTaskRecord) -> dict[str, object]:
        if task_record.task_type == "force_heal":
            return self._execute_force_heal(task_record)
        if task_record.task_type == "decommission_node":
            return self._execute_decommission(task_record)
        if task_record.task_type == "reprobe_node":
            return self._execute_reprobe(task_record)
        return self._execute_manual_review(task_record)

    def _execute_force_heal(self, task_record: ManualOperationTaskRecord) -> dict[str, object]:
        if self._healer_service is None:
            raise RuntimeError("Xboard is not configured; force heal is unavailable")
        result = self._healer_service.heal_node(
            HealRequest(
                xboard_node_id=task_record.xboard_node_id,
                reason=str(task_record.request_payload.get("reason") or "manual_force_heal"),
                source="manual",
                force_strategy=self._to_optional_text(task_record.request_payload.get("force_strategy")),
            )
        )
        return {
            "xboard_node_id": result.xboard_node_id,
            "strategy": result.strategy,
            "success": result.success,
            "message": result.message,
            "correlation_id": result.correlation_id,
        }

    def _execute_decommission(self, task_record: ManualOperationTaskRecord) -> dict[str, object]:
        if self._node_registry is None:
            raise RuntimeError("Xboard is not configured; node decommission is unavailable")
        status_reason = str(task_record.request_payload.get("reason") or "manual_decommission")
        result = self._node_registry.delete_node(
            xboard_node_id=task_record.xboard_node_id,
            status_reason=status_reason,
        )
        released = self._asset_repo.release_allocation_by_xboard_node_id(task_record.xboard_node_id)
        return {
            "xboard_node_id": result.xboard_node_id,
            "status": result.status,
            "local_node_id": result.local_node_id,
        }

    def _execute_reprobe(self, task_record: ManualOperationTaskRecord) -> dict[str, object]:
        if self._xboard_repo is None:
            raise RuntimeError("Xboard is not configured; reprobe is unavailable")
        node_record = self._state_repo.get_node_by_xboard_node_id(task_record.xboard_node_id)
        if node_record is None:
            raise RuntimeError(f"节点不存在: xboard_node_id={task_record.xboard_node_id}")
        xboard_runtime = self._xboard_repo.get_node_runtime(task_record.xboard_node_id)
        candidate: MonitorCandidate = to_monitor_candidate(node_record, xboard_runtime)
        probe_result = self._probe_client.probe_node(candidate)
        self._state_repo.create_event(
            FleetNodeEventCreateRequest(
                node_id=node_record.id,
                xboard_node_id=node_record.xboard_node_id,
                event_type="manual_reprobe_completed",
                correlation_id=self._runtime_context.correlation_id,
                from_status=node_record.status,
                to_status=node_record.status,
                message=probe_result.reason,
                payload={
                    "provider": probe_result.provider,
                    "status": probe_result.status,
                    "success_region_count": probe_result.success_region_count,
                    "failed_region_count": probe_result.failed_region_count,
                    "raw_payload": probe_result.raw_payload,
                },
            )
        )
        return {
            "xboard_node_id": candidate.xboard_node_id,
            "probe_status": probe_result.status,
            "probe_reason": probe_result.reason,
            "provider": probe_result.provider,
        }

    def _execute_manual_review(self, task_record: ManualOperationTaskRecord) -> dict[str, object]:
        node_record = self._state_repo.get_node_by_xboard_node_id(task_record.xboard_node_id)
        if node_record is None:
            raise RuntimeError(f"节点不存在: xboard_node_id={task_record.xboard_node_id}")
        reason = str(task_record.request_payload.get("reason") or "manual_review_requested")
        self._state_repo.update_node_error_state(
            xboard_node_id=node_record.xboard_node_id,
            status_reason=reason,
            last_error="需要人工复核",
        )
        self._state_repo.create_event(
            FleetNodeEventCreateRequest(
                node_id=node_record.id,
                xboard_node_id=node_record.xboard_node_id,
                event_type="manual_review_requested",
                correlation_id=self._runtime_context.correlation_id,
                from_status=node_record.status,
                to_status=node_record.status,
                message=reason,
                payload={"operator_name": task_record.operator_name},
            )
        )
        return {
            "xboard_node_id": node_record.xboard_node_id,
            "status": node_record.status,
            "message": reason,
        }

    @staticmethod
    def _validate_submit_request(request: ManualOperationRequest) -> None:
        if request.xboard_node_id <= 0:
            raise ValueError("节点 ID 必须大于 0")

    @staticmethod
    def _validate_task_support(
        *,
        request: ManualOperationRequest,
        node_type: str,
        is_aws: bool,
    ) -> None:
        if request.task_type in {"reprobe_node", "mark_manual_review", "decommission_node"}:
            return
        if request.task_type != "force_heal":
            raise ValueError(f"不支持的人工任务类型: {request.task_type}")
        if is_aws and node_type not in AWS_HEALABLE_PROTOCOLS:
            raise ValueError(f"AWS 节点协议不支持强制换 IP: {node_type}")
        if not is_aws and node_type not in SELF_HOSTED_PROXY_PROTOCOLS:
            raise ValueError(f"自建节点协议不支持 Cloudflare 保底: {node_type}")

    @staticmethod
    def _normalize_optional_text(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _to_optional_text(value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
