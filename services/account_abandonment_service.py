from __future__ import annotations

from dataclasses import dataclass

from database.asset_models import AssetNotFoundError
from database.asset_repo import AssetEventCreateRequest, AssetRepo
from database.state_models import FleetNodeRecord
from database.state_repo import FleetNodeEventCreateRequest, StateRepo
from services.account_abandonment_notifier import notify_account_abandoned
from services.fleet_scheduler_service import FleetSchedulerService
from services.node_registry_service import NodeRegistryService, NodeRegistryServiceError
from services.runtime_service import RuntimeContext
from utils.logger import set_event_type


@dataclass(frozen=True)
class AccountAbandonmentResult:
    aws_account_id: str
    deleted_node_count: int
    asset_count: int


class AccountAbandonmentServiceError(RuntimeError):
    pass


class AccountAbandonmentService:
    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime_context = runtime_context
        self._logger = runtime_context.logger.getChild("services.account_abandonment")
        self._asset_repo = AssetRepo(runtime_context)
        self._state_repo = StateRepo(runtime_context)
        self._node_registry = NodeRegistryService(runtime_context)
        self._scheduler: FleetSchedulerService | None = None

    @property
    def _scheduler_service(self) -> FleetSchedulerService:
        if self._scheduler is None:
            self._scheduler = FleetSchedulerService(self._runtime_context)
        return self._scheduler

    def abandon_account(
        self,
        *,
        aws_account_id: str,
        error_code: str,
        error_message: str,
        source_xboard_node_id: int | None,
    ) -> AccountAbandonmentResult:
        if not aws_account_id or not aws_account_id.strip():
            raise ValueError("aws_account_id must not be empty")
        normalized_account_id = aws_account_id.strip()
        assets = self._asset_repo.list_assets_by_aws_account_id(normalized_account_id)
        if not assets:
            raise AccountAbandonmentServiceError(
                f"No assets found for aws_account_id={normalized_account_id}"
            )

        set_event_type("aws_account_abandoned")
        self._logger.error(
            "Abandoning AWS account aws_account_id=%s error_code=%s source_xboard_node_id=%s",
            normalized_account_id,
            error_code,
            source_xboard_node_id,
        )

        for asset in assets:
            self._asset_repo.update_asset_status(asset.id, "banned")
            self._asset_repo.create_asset_event(
                AssetEventCreateRequest(
                    asset_id=asset.id,
                    event_type="aws_account_abandoned",
                    correlation_id=self._runtime_context.correlation_id,
                    message=error_message,
                    payload={
                        "aws_account_id": normalized_account_id,
                        "error_code": error_code,
                        "source_xboard_node_id": source_xboard_node_id,
                    },
                )
            )

        deleted_node_count = 0
        nodes = self._state_repo.list_nodes_by_aws_account_id(normalized_account_id)
        for node_record in nodes:
            self._state_repo.create_event(
                FleetNodeEventCreateRequest(
                    node_id=node_record.id,
                    xboard_node_id=node_record.xboard_node_id,
                    event_type="account_abandoned_node_delete_started",
                    correlation_id=self._runtime_context.correlation_id,
                    from_status=node_record.status,
                    to_status="deleting",
                    message="AWS account banned; deleting node from Xboard.",
                    payload={
                        "aws_account_id": normalized_account_id,
                        "error_code": error_code,
                    },
                )
            )
            try:
                self._node_registry.delete_node(
                    xboard_node_id=node_record.xboard_node_id,
                    status_reason="AWS账号封禁，节点已从Xboard销毁",
                )
            except NodeRegistryServiceError as exc:
                self._logger.exception(
                    "Failed to delete node during account abandonment xboard_node_id=%s",
                    node_record.xboard_node_id,
                )
                self._state_repo.update_node_error_state(
                    xboard_node_id=node_record.xboard_node_id,
                    status_reason="AWS账号封禁，节点销毁失败",
                    last_error=str(exc),
                )
                self._state_repo.create_event(
                    FleetNodeEventCreateRequest(
                        node_id=node_record.id,
                        xboard_node_id=node_record.xboard_node_id,
                        event_type="account_abandoned_node_delete_failed",
                        correlation_id=self._runtime_context.correlation_id,
                        from_status=node_record.status,
                        to_status=node_record.status,
                        message=str(exc),
                        payload={
                            "aws_account_id": normalized_account_id,
                            "error_code": error_code,
                        },
                    )
                )
                continue

            try:
                self._asset_repo.release_allocation_by_xboard_node_id(node_record.xboard_node_id)
            except AssetNotFoundError:
                self._logger.warning(
                    "No active allocation found during account abandonment xboard_node_id=%s",
                    node_record.xboard_node_id,
                )
            self._state_repo.create_event(
                FleetNodeEventCreateRequest(
                    node_id=node_record.id,
                    xboard_node_id=node_record.xboard_node_id,
                    event_type="account_abandoned_node_deleted",
                    correlation_id=self._runtime_context.correlation_id,
                    from_status=node_record.status,
                    to_status="deleted",
                    message="Node deleted from Xboard after AWS account abandonment.",
                    payload={
                        "aws_account_id": normalized_account_id,
                        "error_code": error_code,
                    },
                )
            )
            deleted_node_count += 1

        notify_account_abandoned(
            runtime_context=self._runtime_context,
            aws_account_id=normalized_account_id,
            region=assets[0].region,
            source_xboard_node_id=source_xboard_node_id,
            error_code=error_code,
            error_message=error_message,
            deleted_node_count=deleted_node_count,
        )

        self._trigger_emergency_replenishment(
            deleted_nodes=nodes,
            region=assets[0].region,
            deleted_count=deleted_node_count,
        )

        return AccountAbandonmentResult(
            aws_account_id=normalized_account_id,
            deleted_node_count=deleted_node_count,
            asset_count=len(assets),
        )

    def _trigger_emergency_replenishment(
        self,
        deleted_nodes: list[FleetNodeRecord],
        region: str | None,
        deleted_count: int,
    ) -> None:
        """Trigger emergency replenishment after account abandonment."""
        if not self._runtime_context.config.fleet_scheduler.enabled:
            self._logger.info(
                "Fleet scheduler disabled, skipping emergency replenishment"
            )
            return

        self._logger.info(
            "Triggering emergency replenishment for %d deleted nodes in region=%s",
            len(deleted_nodes),
            region,
        )

        protocol_counts: dict[str, int] = {}
        for node in deleted_nodes:
            protocol = getattr(node, "node_type", None)
            if protocol:
                protocol_counts[protocol] = protocol_counts.get(protocol, 0) + 1

        total_submitted = 0
        for protocol, count in protocol_counts.items():
            if region is None:
                self._logger.warning(
                    "Cannot trigger replenishment for protocol=%s: region is unknown",
                    protocol,
                )
                continue

            task_ids = self._scheduler_service.fill_gap_for_region_protocol(
                region=region,
                protocol_type=protocol,
                count=count,
                reason=f"abandonment_replenishment:{deleted_count}",
            )
            total_submitted += len(task_ids)
            if task_ids:
                self._logger.info(
                    "Submitted %d replenishment tasks for %s/%s",
                    len(task_ids),
                    region,
                    protocol,
                )

        if total_submitted > 0:
            self._logger.warning(
                "Emergency replenishment triggered: %d tasks submitted for %d protocols",
                total_submitted,
                len(protocol_counts),
            )
