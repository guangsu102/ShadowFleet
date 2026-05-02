from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
import random

from database.provisioning_task_repo import (
    JsonValue,
    ProvisioningTaskCreateRequest,
    ProvisioningTaskRecord,
    ProvisioningTaskRepo,
)
from services.provisioner_service import ProvisionerService
from services.provisioning_models import ProvisionRequest, ProvisionResult
from services.runtime_service import RuntimeContext
from utils.logger import generate_correlation_id, set_correlation_id, set_event_type
from typing import Any


class ProvisioningTaskServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProvisioningTaskSubmitResult:
    task_id: int
    correlation_id: str
    status: str


@dataclass(frozen=True)
class ProvisioningTaskRecoveryResult:
    scanned_task_count: int
    requeued_task_count: int
    failed_task_count: int


class ProvisioningTaskService:
    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime_context = runtime_context
        self._logger = runtime_context.logger.getChild("services.provisioning_task")
        self._task_repo = ProvisioningTaskRepo(runtime_context)
        self._max_attempts = runtime_context.config.app.max_retries + 1
        self._retry_backoff_seconds = runtime_context.config.app.retry_backoff_seconds

    def submit_provision_task(
        self,
        request: ProvisionRequest,
        group_ids: list[int] | None = None,
        route_ids: list[int] | None = None,
        sort: int | None = None,
        rate_time_enable: bool = False,
        protocol_settings: dict[str, Any] | None = None,
        rate_time_ranges: list[Any] | None = None,
        status_reason: str | None = None,
    ) -> ProvisioningTaskSubmitResult:
        enriched = replace(
            request,
            group_ids=group_ids,
            route_ids=route_ids,
            sort=sort,
            rate_time_enable=rate_time_enable,
            protocol_settings=protocol_settings,
            rate_time_ranges=rate_time_ranges,
            status_reason=status_reason,
        )
        correlation_id = generate_correlation_id()
        original_correlation_id = self._runtime_context.correlation_id
        set_correlation_id(correlation_id)
        try:
            task_id = self._task_repo.create_task(
                ProvisioningTaskCreateRequest(
                    correlation_id=correlation_id,
                    request_payload=self._serialize_provision_request(enriched),
                    max_attempts=self._max_attempts,
                )
            )
            set_event_type("provision_task_submitted")
            self._logger.info(
                "Submitted provisioning task id=%s protocol=%s node=%s",
                task_id,
                enriched.protocol_type,
                enriched.node_name,
            )
        finally:
            set_correlation_id(original_correlation_id)
            set_event_type("general")
        return ProvisioningTaskSubmitResult(
            task_id=task_id,
            correlation_id=correlation_id,
            status="queued",
        )

    def get_task_by_id(self, task_id: int) -> ProvisioningTaskRecord:
        return self._task_repo.get_task_by_id(task_id)

    def retry_failed_task(self, task_id: int) -> ProvisioningTaskRecord:
        task = self._task_repo.get_task_by_id(task_id)
        if task.status not in ("failed", "succeeded"):
            raise ProvisioningTaskServiceError(
                f"Task {task_id} is '{task.status}', only failed or succeeded tasks can be retried"
            )
        original_cid = self._runtime_context.correlation_id
        new_cid = generate_correlation_id()
        set_correlation_id(new_cid)
        set_event_type("provision_task_manual_retry")
        self._logger.info("Manual retry requested for task id=%s old_status=%s", task_id, task.status)
        try:
            return self._task_repo.reset_for_retry(task_id)
        finally:
            set_correlation_id(original_cid)
            set_event_type("general")

    def list_recent_tasks(self, limit: int = 20) -> list[ProvisioningTaskRecord]:
        return self._task_repo.list_recent_tasks(limit=limit)

    def get_task_stats(self) -> dict[str, int]:
        return self._task_repo.get_task_stats()

    def recover_stale_running_tasks(
        self,
        worker_id: str,
        running_timeout_seconds: float,
        retry_after_seconds: float,
    ) -> ProvisioningTaskRecoveryResult:
        if not worker_id or not worker_id.strip():
            raise ValueError("worker_id must not be empty")
        if running_timeout_seconds <= 0:
            raise ValueError("running_timeout_seconds must be greater than 0")
        if retry_after_seconds <= 0:
            raise ValueError("retry_after_seconds must be greater than 0")

        stale_tasks = self._task_repo.list_stale_running_tasks(
            running_timeout_seconds=running_timeout_seconds
        )
        if not stale_tasks:
            return ProvisioningTaskRecoveryResult(
                scanned_task_count=0,
                requeued_task_count=0,
                failed_task_count=0,
            )

        original_correlation_id = self._runtime_context.correlation_id
        requeued_task_count = 0
        failed_task_count = 0
        try:
            for task_record in stale_tasks:
                set_correlation_id(task_record.correlation_id)
                set_event_type("provision_task_watchdog_recovery")
                timeout_message = (
                    "Provisioning task exceeded running timeout and was reclaimed by daemon "
                    f"worker={worker_id}"
                )
                if task_record.attempt_count >= task_record.max_attempts:
                    self._task_repo.mark_task_failed(
                        task_id=task_record.id,
                        error_message=timeout_message,
                    )
                    failed_task_count += 1
                else:
                    self._task_repo.mark_task_for_retry(
                        task_id=task_record.id,
                        error_message=timeout_message,
                        retry_after_seconds=retry_after_seconds,
                    )
                    requeued_task_count += 1
                self._logger.warning(
                    "Recovered stale provisioning task id=%s status=%s attempts=%s/%s locked_by=%s",
                    task_record.id,
                    task_record.status,
                    task_record.attempt_count,
                    task_record.max_attempts,
                    task_record.locked_by,
                )
        finally:
            set_correlation_id(original_correlation_id)
            set_event_type("general")

        return ProvisioningTaskRecoveryResult(
            scanned_task_count=len(stale_tasks),
            requeued_task_count=requeued_task_count,
            failed_task_count=failed_task_count,
        )

    def process_next_task(self, worker_id: str) -> ProvisioningTaskRecord | None:
        task_record = self._task_repo.claim_next_task(worker_id=worker_id)
        if task_record is None:
            return None

        original_correlation_id = self._runtime_context.correlation_id
        task_runtime_context = replace(self._runtime_context, correlation_id=task_record.correlation_id)
        set_correlation_id(task_record.correlation_id)
        set_event_type("provision_task_processing")
        self._logger.info(
            "Processing provisioning task id=%s attempt=%s/%s",
            task_record.id,
            task_record.attempt_count,
            task_record.max_attempts,
        )

        try:
            request = replace(
                self._deserialize_provision_request(task_record.request_payload),
                provisioning_task_id=task_record.id,
            )
            result = ProvisionerService(task_runtime_context).provision_node(request)
            self._task_repo.mark_task_succeeded(
                task_id=task_record.id,
                result_payload=self._serialize_provision_result(result),
            )
            return self._task_repo.get_task_by_id(task_record.id)
        except Exception as exc:
            error_message = self._format_error_message(exc)
            if task_record.attempt_count >= task_record.max_attempts:
                self._task_repo.mark_task_failed(task_id=task_record.id, error_message=error_message)
            else:
                self._task_repo.mark_task_for_retry(
                    task_id=task_record.id,
                    error_message=error_message,
                    retry_after_seconds=self._build_retry_delay_seconds(task_record.attempt_count),
                )
            self._logger.exception("Provisioning task execution failed id=%s", task_record.id)
            return self._task_repo.get_task_by_id(task_record.id)
        finally:
            set_correlation_id(original_correlation_id)
            set_event_type("general")

    def _build_retry_delay_seconds(self, attempt_count: int) -> float:
        base_delay = self._retry_backoff_seconds * (2 ** max(attempt_count - 1, 0))
        jitter = base_delay * random.uniform(0.0, 0.5)
        return base_delay + jitter

    @staticmethod
    def _format_error_message(error: BaseException) -> str:
        message = str(error).strip()
        if message:
            return message
        return error.__class__.__name__

    @staticmethod
    def _serialize_provision_request(request: ProvisionRequest) -> dict[str, JsonValue]:
        return {
            "protocol_type": request.protocol_type,
            "node_name": request.node_name,
            "port": request.port,
            "server_port": request.server_port,
            "rate": str(request.rate),
            "asset_type": request.asset_type,
            "region": request.region,
            "domain_name": request.domain_name,
            "require_cdn_proxy": request.require_cdn_proxy,
            "code": request.code,
            "parent_id": request.parent_id,
            "group_ids": request.group_ids,
            "route_ids": request.route_ids,
            "tags": request.tags,
            "protocol_settings": request.protocol_settings,
            "show": request.show,
            "sort": request.sort,
            "rate_time_enable": request.rate_time_enable,
            "rate_time_ranges": request.rate_time_ranges,
            "status_reason": request.status_reason,
        }

    @staticmethod
    def _deserialize_provision_request(payload: dict[str, JsonValue]) -> ProvisionRequest:
        try:
            return ProvisionRequest(
                protocol_type=str(payload["protocol_type"]),
                node_name=str(payload["node_name"]),
                port=str(payload["port"]),
                server_port=int(payload["server_port"]),
                rate=Decimal(str(payload["rate"])),
                asset_type=None if payload.get("asset_type") is None else str(payload["asset_type"]),
                region=None if payload.get("region") is None else str(payload["region"]),
                domain_name=(
                    None if payload.get("domain_name") is None else str(payload["domain_name"])
                ),
                require_cdn_proxy=bool(payload.get("require_cdn_proxy", False)),
                code=None if payload.get("code") is None else str(payload["code"]),
                parent_id=None if payload.get("parent_id") is None else int(payload["parent_id"]),
                group_ids=(
                    None if payload.get("group_ids") is None else list(payload["group_ids"])
                ),
                route_ids=(
                    None if payload.get("route_ids") is None else list(payload["route_ids"])
                ),
                tags=None if payload.get("tags") is None else payload["tags"],
                protocol_settings=(
                    None
                    if payload.get("protocol_settings") is None
                    else dict(payload["protocol_settings"])
                ),
                show=bool(payload.get("show", True)),
                sort=None if payload.get("sort") is None else int(payload["sort"]),
                rate_time_enable=bool(payload.get("rate_time_enable", False)),
                rate_time_ranges=(
                    None if payload.get("rate_time_ranges") is None else payload["rate_time_ranges"]
                ),
                status_reason=(
                    None if payload.get("status_reason") is None else str(payload["status_reason"])
                ),
            )
        except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
            raise ProvisioningTaskServiceError(
                "Provisioning task payload is invalid and cannot be deserialized"
            ) from exc

    @staticmethod
    def _serialize_provision_result(result: ProvisionResult) -> dict[str, JsonValue]:
        return {
            "local_node_id": result.local_node_id,
            "xboard_node_id": result.xboard_node_id,
            "asset_id": result.asset_id,
            "asset_type": result.asset_type,
            "protocol_type": result.protocol_type,
            "node_name": result.node_name,
            "status": result.status,
            "aws_account_id": result.aws_account_id,
            "region": result.region,
            "instance_id": result.instance_id,
            "network_interface_id": result.network_interface_id,
            "ipv6_address": result.ipv6_address,
            "domain_name": result.domain_name,
            "cloudflare_record_id": result.cloudflare_record_id,
            "cloudflare_a_record_id": result.cloudflare_a_record_id,
            "cloudflare_aaaa_record_id": result.cloudflare_aaaa_record_id,
        }
