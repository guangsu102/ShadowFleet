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
from database.state_repo import StateRepo
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
        self._state_repo = StateRepo(runtime_context)
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
        # Check if node_name already exists
        existing_node = self._state_repo.get_node_by_node_name(request.node_name)
        if existing_node is not None:
            raise ProvisioningTaskServiceError(
                f"Node name '{request.node_name}' already exists (xboard_node_id={existing_node.xboard_node_id}, status={existing_node.status}). "
                f"Use retry endpoint to retry a failed provisioning, or delete the existing node first."
            )

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

    def delete_task(self, task_id: int) -> None:
        task = self._task_repo.get_task_by_id(task_id)
        if task.status == "running":
            raise ProvisioningTaskServiceError(
                f"Task {task_id} is running and cannot be deleted"
            )
        set_event_type("provision_task_deleted")
        self._logger.info("Deleting task id=%s", task_id)
        self._task_repo.delete_task(task_id)

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
            "cert_mode": request.cert_mode,
            "cert_domain": request.cert_domain,
            "cert_provider": request.cert_provider,
            "cert_email": request.cert_email,
            "cert_dns_env": request.cert_dns_env,
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
            "ssh_host": request.ssh_host,
            "ssh_port": request.ssh_port,
            "ssh_username": request.ssh_username,
            "ssh_password": request.ssh_password,
            "ssh_private_key": request.ssh_private_key,
        }

    @staticmethod
    def _deserialize_provision_request(payload: dict[str, JsonValue]) -> ProvisionRequest:
        def _str(val: JsonValue | None) -> str | None:
            if val is None:
                return None
            return str(val)

        def _int_or_none(val: JsonValue | None) -> int | None:
            if val is None:
                return None
            return int(val)

        def _dict_or_none(val: JsonValue | None) -> dict[str, str] | None:
            if val is None:
                return None
            return dict(val)  # type: ignore[arg-type]

        def _list_or_none(val: JsonValue | None) -> list[JsonValue] | None:
            if val is None:
                return None
            return list(val)  # type: ignore[return-value]

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
                cert_mode=str(payload.get("cert_mode", "none")),
                cert_domain=_str(payload.get("cert_domain")),
                cert_provider=_str(payload.get("cert_provider")),
                cert_email=_str(payload.get("cert_email")),
                cert_dns_env=_dict_or_none(payload.get("cert_dns_env")),
                code=_str(payload.get("code")),
                parent_id=_int_or_none(payload.get("parent_id")),
                group_ids=_list_or_none(payload.get("group_ids")),
                route_ids=_list_or_none(payload.get("route_ids")),
                tags=payload.get("tags"),
                protocol_settings=(
                    None
                    if payload.get("protocol_settings") is None
                    else dict(payload["protocol_settings"])
                ),
                show=bool(payload.get("show", True)),
                sort=_int_or_none(payload.get("sort")),
                rate_time_enable=bool(payload.get("rate_time_enable", False)),
                rate_time_ranges=_list_or_none(payload.get("rate_time_ranges")),
                status_reason=_str(payload.get("status_reason")),
                ssh_host=_str(payload.get("ssh_host")),
                ssh_port=_int_or_none(payload.get("ssh_port")),
                ssh_username=_str(payload.get("ssh_username")),
                ssh_password=_str(payload.get("ssh_password")),
                ssh_private_key=_str(payload.get("ssh_private_key")),
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
