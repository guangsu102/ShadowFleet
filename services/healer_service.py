from __future__ import annotations

from database.state_repo import FleetNodeEventCreateRequest, StateRepo
from database.xboard_repo import XboardRepo
from database.asset_repo import AssetRepo
from services.account_abandonment_service import AccountAbandonmentService
from services.healing_aws_flow import heal_aws_node
from services.healing_azure_flow import heal_azure_node
from services.healing_failure_handler import handle_healing_failure
from services.healing_vultr_flow import heal_vultr_node
from services.healing_models import AwsAccountBannedError, HealRequest, HealResult, HealerServiceError, InstanceNotFoundError
from services.healing_self_hosted_flow import heal_self_hosted_node
from services.healing_support import (
    build_heal_lock,
    build_heal_lock_key,
    build_healing_context,
    classify_aws_client_error,
    determine_heal_strategy,
    ensure_aws_healing_eligible,
    ensure_azure_healing_eligible,
    ensure_self_hosted_healing_eligible,
    ensure_vultr_healing_eligible,
    get_duration_ms,
)
from services.monitor_support import infer_node_asset_type, is_in_heal_cooldown, utcnow
from services.runtime_service import RuntimeContext


class HealerService:
    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime_context = runtime_context
        self._logger = runtime_context.logger.getChild("services.healer")
        self._state_repo = StateRepo(runtime_context)
        self._asset_repo = AssetRepo(runtime_context)
        self._xboard_repo = XboardRepo(runtime_context)
        self._account_abandonment_service = AccountAbandonmentService(runtime_context)

    def heal_node(self, request: HealRequest) -> HealResult:
        node_record = self._state_repo.get_node_by_xboard_node_id(request.xboard_node_id)
        if node_record is None:
            raise HealerServiceError(
                f"Local fleet node record not found for xboard_node_id={request.xboard_node_id}"
            )

        config = self._runtime_context.config.app
        asset_type = infer_node_asset_type(node_record)
        if is_in_heal_cooldown(
            node_record,
            now_utc=utcnow(),
            cooldown_seconds=config.sentinel_heal_cooldown_seconds,
        ):
            message = "节点处于自愈冷却期内，拒绝重复自愈"
            self._state_repo.create_event(
                FleetNodeEventCreateRequest(
                    node_id=node_record.id,
                    xboard_node_id=node_record.xboard_node_id,
                    event_type="healing_cooldown_blocked",
                    correlation_id=self._runtime_context.correlation_id,
                    from_status=node_record.status,
                    to_status=node_record.status,
                    message=message,
                    payload={"cooldown_seconds": config.sentinel_heal_cooldown_seconds},
                )
            )
            return HealResult(
                xboard_node_id=node_record.xboard_node_id,
                node_name=node_record.node_name,
                node_type=node_record.node_type,
                asset_type=asset_type,
                strategy="cooldown_blocked",
                success=False,
                old_ipv6_address=node_record.ipv6_address,
                new_ipv6_address=None,
                domain_name=node_record.domain_name,
                cloudflare_record_id=node_record.cloudflare_record_id,
                proxied_enabled=None,
                duration_ms=0,
                message=message,
                correlation_id=self._runtime_context.correlation_id,
            )

        context = build_healing_context(request, node_record)
        strategy = determine_heal_strategy(node_record, request)
        if strategy == "manual_review_required":
            message = "当前节点不满足自动自愈条件，需人工介入"
            self._state_repo.update_node_error_state(
                xboard_node_id=node_record.xboard_node_id,
                status_reason=request.reason,
                last_error=message,
            )
            self._state_repo.create_event(
                FleetNodeEventCreateRequest(
                    node_id=node_record.id,
                    xboard_node_id=node_record.xboard_node_id,
                    event_type="healing_manual_review_required",
                    correlation_id=self._runtime_context.correlation_id,
                    from_status=node_record.status,
                    to_status=node_record.status,
                    message=message,
                    payload={
                        "reason": request.reason,
                        "source": request.source,
                        "measurement_payload": request.measurement_payload,
                    },
                )
            )
            return HealResult(
                xboard_node_id=node_record.xboard_node_id,
                node_name=node_record.node_name,
                node_type=node_record.node_type,
                asset_type=asset_type,
                strategy="manual_review_required",
                success=False,
                old_ipv6_address=node_record.ipv6_address,
                new_ipv6_address=node_record.ipv6_address,
                domain_name=node_record.domain_name,
                cloudflare_record_id=node_record.cloudflare_record_id,
                proxied_enabled=None,
                duration_ms=get_duration_ms(context.started_monotonic),
                message=message,
                correlation_id=self._runtime_context.correlation_id,
            )

        lock_request = build_heal_lock(
            node_record,
            self._runtime_context.correlation_id,
            strategy,
        )
        if not self._state_repo.acquire_operation_lock(lock_request):
            message = "节点当前已有自愈任务执行中，已跳过本次请求"
            self._state_repo.create_event(
                FleetNodeEventCreateRequest(
                    node_id=node_record.id,
                    xboard_node_id=node_record.xboard_node_id,
                    event_type="healing_skipped_locked",
                    correlation_id=self._runtime_context.correlation_id,
                    from_status=node_record.status,
                    to_status=node_record.status,
                    message=message,
                    payload={"strategy": strategy},
                )
            )
            return HealResult(
                xboard_node_id=node_record.xboard_node_id,
                node_name=node_record.node_name,
                node_type=node_record.node_type,
                asset_type=asset_type,
                strategy=strategy,
                success=False,
                old_ipv6_address=node_record.ipv6_address,
                new_ipv6_address=node_record.ipv6_address,
                domain_name=node_record.domain_name,
                cloudflare_record_id=node_record.cloudflare_record_id,
                proxied_enabled=None,
                duration_ms=get_duration_ms(context.started_monotonic),
                message=message,
                correlation_id=self._runtime_context.correlation_id,
            )

        try:
            self._state_repo.create_event(
                FleetNodeEventCreateRequest(
                    node_id=node_record.id,
                    xboard_node_id=node_record.xboard_node_id,
                    event_type="healing_started",
                    correlation_id=self._runtime_context.correlation_id,
                    from_status=node_record.status,
                    to_status="healing",
                    message="Healing workflow started.",
                    payload={
                        "reason": request.reason,
                        "source": request.source,
                        "measurement_payload": request.measurement_payload,
                    },
                )
            )
            self._state_repo.create_event(
                FleetNodeEventCreateRequest(
                    node_id=node_record.id,
                    xboard_node_id=node_record.xboard_node_id,
                    event_type="healing_strategy_selected",
                    correlation_id=self._runtime_context.correlation_id,
                    from_status=node_record.status,
                    to_status=node_record.status,
                    message=strategy,
                    payload={"strategy": strategy},
                )
            )
            self._state_repo.update_node_status(
                xboard_node_id=node_record.xboard_node_id,
                status="healing",
                status_reason=request.reason,
                last_error=None,
            )
            if strategy == "aws_ipv6_rotate":
                ensure_aws_healing_eligible(node_record)
                return heal_aws_node(
                    runtime_context=self._runtime_context,
                    asset_repo=self._asset_repo,
                    state_repo=self._state_repo,
                    xboard_repo=self._xboard_repo,
                    node_record=node_record,
                    request=request,
                    started_monotonic=context.started_monotonic,
                )
            if strategy == "azure_ipv6_rotate":
                ensure_azure_healing_eligible(node_record)
                return heal_azure_node(
                    runtime_context=self._runtime_context,
                    asset_repo=self._asset_repo,
                    state_repo=self._state_repo,
                    xboard_repo=self._xboard_repo,
                    node_record=node_record,
                    request=request,
                    started_monotonic=context.started_monotonic,
                )
            if strategy == "vultr_instance_replace":
                ensure_vultr_healing_eligible(node_record)
                return heal_vultr_node(
                    runtime_context=self._runtime_context,
                    asset_repo=self._asset_repo,
                    state_repo=self._state_repo,
                    xboard_repo=self._xboard_repo,
                    node_record=node_record,
                    request=request,
                    started_monotonic=context.started_monotonic,
                )
            ensure_self_hosted_healing_eligible(node_record)
            return heal_self_hosted_node(
                runtime_context=self._runtime_context,
                state_repo=self._state_repo,
                xboard_repo=self._xboard_repo,
                node_record=node_record,
                request=request,
                started_monotonic=context.started_monotonic,
            )
        except BaseException as exc:
            classified_error = classify_aws_client_error(exc, node_record.aws_account_id)
            if isinstance(classified_error, AwsAccountBannedError):
                aws_account_error = classified_error
                abandonment_result = self._account_abandonment_service.abandon_account(
                    aws_account_id=aws_account_error.aws_account_id,
                    error_code=aws_account_error.error_code,
                    error_message=str(aws_account_error),
                    source_xboard_node_id=node_record.xboard_node_id,
                )
                return HealResult(
                    xboard_node_id=node_record.xboard_node_id,
                    node_name=node_record.node_name,
                    node_type=node_record.node_type,
                    asset_type="aws",
                    strategy="aws_account_abandoned",
                    success=False,
                    old_ipv6_address=node_record.ipv6_address,
                    new_ipv6_address=node_record.ipv6_address,
                    domain_name=node_record.domain_name,
                    cloudflare_record_id=node_record.cloudflare_record_id,
                    proxied_enabled=None,
                    duration_ms=get_duration_ms(context.started_monotonic),
                    message=(
                        f"AWS账号已封禁并执行静默弃尸，销毁节点数="
                        f"{abandonment_result.deleted_node_count}"
                    ),
                    correlation_id=self._runtime_context.correlation_id,
                )

            error_message = handle_healing_failure(
                runtime_context=self._runtime_context,
                state_repo=self._state_repo,
                node_id=node_record.id,
                xboard_node_id=node_record.xboard_node_id,
                node_name=node_record.node_name,
                node_type=node_record.node_type,
                previous_status=context.previous_status,
                strategy=strategy,
                request=request,
                error=classified_error,
            )
            self._logger.exception(
                "Healing failed xboard_node_id=%s strategy=%s error=%s",
                node_record.xboard_node_id,
                strategy,
                error_message,
            )
            raise
        finally:
            self._state_repo.release_operation_lock(build_heal_lock_key(node_record.xboard_node_id))
