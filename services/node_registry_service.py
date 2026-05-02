from __future__ import annotations

from database.state_repo import (
    FleetNodeCreateRequest,
    FleetNodeEventCreateRequest,
    FleetNodeRecord,
    StateRepo,
    StateRepoError,
)
from database.xboard_repo import XboardNodeCreateRequest, XboardNodeNotFoundError, XboardRepo
from services.node_registry_helpers import (
    compensate_registration_failure,
    require_registered_node,
    rollback_offline_transition,
    rollback_online_transition,
    validate_register_request,
)
from services.node_registry_models import (
    NodeRegistryServiceError,
    NodeStateChangeResult,
    RegisterNodeRequest,
    RegisterNodeResult,
)
from services.runtime_service import RuntimeContext
from utils.logger import set_event_type

__all__ = [
    "NodeRegistryService",
    "NodeRegistryServiceError",
    "NodeStateChangeResult",
    "RegisterNodeRequest",
    "RegisterNodeResult",
]


class NodeRegistryService:
    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime_context = runtime_context
        self._logger = runtime_context.logger.getChild("services.node_registry")
        self._xboard_repo = XboardRepo(runtime_context)
        self._state_repo = StateRepo(runtime_context)

    def register_node(self, request: RegisterNodeRequest) -> RegisterNodeResult:
        validate_register_request(request)
        set_event_type("node_registration_started")
        self._logger.info(
            "Starting node registration for name=%s type=%s",
            request.node_name,
            request.node_type,
        )

        xboard_request = XboardNodeCreateRequest(
            node_type=request.node_type,
            name=request.node_name,
            host=request.host,
            port=request.port,
            server_port=request.server_port,
            rate=request.rate,
            code=request.code,
            parent_id=request.parent_id,
            group_ids=request.group_ids,
            route_ids=request.route_ids,
            tags=request.tags,
            protocol_settings=request.protocol_settings,
            show=request.show,
            sort=request.sort,
            rate_time_enable=request.rate_time_enable,
            rate_time_ranges=request.rate_time_ranges,
        )
        xboard_node_id = self._xboard_repo.register_node(xboard_request)
        local_node_id: int | None = None

        try:
            local_node_id = self._state_repo.create_node(
                FleetNodeCreateRequest(
                    xboard_node_id=xboard_node_id,
                    node_name=request.node_name,
                    node_type=request.node_type,
                    status=request.initial_status,
                    status_reason=request.status_reason,
                    aws_account_id=request.aws_account_id,
                    aws_region=request.aws_region,
                    aws_instance_id=request.aws_instance_id,
                    aws_subnet_id=request.aws_subnet_id,
                    aws_security_group_id=request.aws_security_group_id,
                    cloudflare_record_id=request.cloudflare_record_id,
                    domain_name=request.domain_name,
                    ipv4_address=request.ipv4_address,
                    ipv6_address=request.ipv6_address,
                    last_known_host=request.host,
                    last_error=request.last_error,
                )
            )
            self._state_repo.create_event(
                FleetNodeEventCreateRequest(
                    node_id=local_node_id,
                    xboard_node_id=xboard_node_id,
                    event_type="node_registered",
                    correlation_id=self._runtime_context.correlation_id,
                    to_status=request.initial_status,
                    message="Node registered in Xboard and persisted locally.",
                    payload={
                        "node_name": request.node_name,
                        "node_type": request.node_type,
                        "host": request.host,
                        "show": request.show,
                    },
                )
            )
        except StateRepoError as exc:
            compensate_registration_failure(
                state_repo=self._state_repo,
                xboard_repo=self._xboard_repo,
                logger=self._logger,
                xboard_node_id=xboard_node_id,
                local_node_id=local_node_id,
            )
            raise NodeRegistryServiceError("Failed to persist registered node locally") from exc
        except Exception as exc:
            compensate_registration_failure(
                state_repo=self._state_repo,
                xboard_repo=self._xboard_repo,
                logger=self._logger,
                xboard_node_id=xboard_node_id,
                local_node_id=local_node_id,
            )
            raise NodeRegistryServiceError("Unexpected failure during node registration") from exc

        set_event_type("node_registration_completed")
        self._logger.info(
            "Completed node registration xboard_node_id=%s local_node_id=%s",
            xboard_node_id,
            local_node_id,
        )
        return RegisterNodeResult(
            local_node_id=local_node_id,
            xboard_node_id=xboard_node_id,
            status=request.initial_status,
            node_name=request.node_name,
            node_type=request.node_type,
        )

    def get_registered_node(self, xboard_node_id: int) -> FleetNodeRecord | None:
        return self._state_repo.get_node_by_xboard_node_id(xboard_node_id)

    def mark_node_offline(
        self,
        xboard_node_id: int,
        status_reason: str | None = None,
        last_error: str | None = None,
    ) -> NodeStateChangeResult:
        node_record = require_registered_node(self._state_repo, xboard_node_id)
        previous_status = node_record.status
        set_event_type("node_offline_started")
        self._logger.info(
            "Starting node offline orchestration xboard_node_id=%s current_status=%s",
            xboard_node_id,
            previous_status,
        )

        self._xboard_repo.mark_node_offline(xboard_node_id)
        try:
            self._state_repo.update_node_status(
                xboard_node_id=xboard_node_id,
                status="offline",
                status_reason=status_reason,
                last_error=last_error,
            )
            self._state_repo.create_event(
                FleetNodeEventCreateRequest(
                    node_id=node_record.id,
                    xboard_node_id=xboard_node_id,
                    event_type="node_offline",
                    correlation_id=self._runtime_context.correlation_id,
                    from_status=previous_status,
                    to_status="offline",
                    message="Node marked offline in Xboard and SQLite.",
                    payload={
                        "status_reason": status_reason,
                        "last_error": last_error,
                    },
                )
            )
        except Exception as exc:
            rollback_offline_transition(self._xboard_repo, self._logger, xboard_node_id)
            raise NodeRegistryServiceError("Failed to persist node offline state locally") from exc

        set_event_type("node_offline_completed")
        self._logger.info("Completed node offline orchestration xboard_node_id=%s", xboard_node_id)
        return NodeStateChangeResult(
            local_node_id=node_record.id,
            xboard_node_id=xboard_node_id,
            status="offline",
        )

    def mark_node_online(
        self,
        xboard_node_id: int,
        host: str | None = None,
        aws_account_id: str | None = None,
        aws_region: str | None = None,
        aws_instance_id: str | None = None,
        aws_subnet_id: str | None = None,
        aws_security_group_id: str | None = None,
        instance_type: str | None = None,
        cloudflare_record_id: str | None = None,
        domain_name: str | None = None,
        ipv4_address: str | None = None,
        ipv6_address: str | None = None,
        status_reason: str | None = None,
        last_error: str | None = None,
    ) -> NodeStateChangeResult:
        node_record = require_registered_node(self._state_repo, xboard_node_id)
        previous_status = node_record.status
        previous_host = node_record.last_known_host
        normalized_host = host.strip() if host is not None else None
        set_event_type("node_online_started")
        self._logger.info(
            "Starting node online orchestration xboard_node_id=%s current_status=%s",
            xboard_node_id,
            previous_status,
        )

        if normalized_host is not None:
            self._xboard_repo.update_node_host(xboard_node_id, normalized_host)
        self._xboard_repo.mark_node_online(xboard_node_id)
        try:
            self._state_repo.update_node_runtime_metadata(
                xboard_node_id=xboard_node_id,
                aws_account_id=aws_account_id,
                aws_region=aws_region,
                aws_instance_id=aws_instance_id,
                aws_subnet_id=aws_subnet_id,
                aws_security_group_id=aws_security_group_id,
                instance_type=instance_type,
                cloudflare_record_id=cloudflare_record_id,
                domain_name=domain_name,
                ipv4_address=ipv4_address,
                ipv6_address=ipv6_address,
                last_known_host=normalized_host,
                last_error=last_error,
            )
            self._state_repo.update_node_status(
                xboard_node_id=xboard_node_id,
                status="online",
                status_reason=status_reason,
                last_error=last_error,
            )
            self._state_repo.create_event(
                FleetNodeEventCreateRequest(
                    node_id=node_record.id,
                    xboard_node_id=xboard_node_id,
                    event_type="node_online",
                    correlation_id=self._runtime_context.correlation_id,
                    from_status=previous_status,
                    to_status="online",
                    message="Node marked online in Xboard and SQLite.",
                    payload={
                        "host": normalized_host,
                        "aws_account_id": aws_account_id,
                        "aws_region": aws_region,
                        "aws_instance_id": aws_instance_id,
                        "cloudflare_record_id": cloudflare_record_id,
                        "domain_name": domain_name,
                        "ipv4_address": ipv4_address,
                        "ipv6_address": ipv6_address,
                    },
                )
            )
        except Exception as exc:
            rollback_online_transition(self._xboard_repo, self._logger, xboard_node_id, previous_host)
            raise NodeRegistryServiceError("Failed to persist node online state locally") from exc

        set_event_type("node_online_completed")
        self._logger.info("Completed node online orchestration xboard_node_id=%s", xboard_node_id)
        return NodeStateChangeResult(
            local_node_id=node_record.id,
            xboard_node_id=xboard_node_id,
            status="online",
        )

    def delete_node(
        self,
        xboard_node_id: int,
        status_reason: str | None = None,
    ) -> NodeStateChangeResult:
        node_record = require_registered_node(self._state_repo, xboard_node_id)
        previous_status = node_record.status
        set_event_type("node_delete_started")
        self._logger.info(
            "Starting node delete orchestration xboard_node_id=%s current_status=%s",
            xboard_node_id,
            previous_status,
        )

        self._state_repo.update_node_status(
            xboard_node_id=xboard_node_id,
            status="deleting",
            status_reason=status_reason,
        )
        self._state_repo.create_event(
            FleetNodeEventCreateRequest(
                node_id=node_record.id,
                xboard_node_id=xboard_node_id,
                event_type="node_delete_started",
                correlation_id=self._runtime_context.correlation_id,
                from_status=previous_status,
                to_status="deleting",
                message="Node delete orchestration started.",
                payload={"status_reason": status_reason},
            )
        )

        try:
            self._xboard_repo.delete_node(xboard_node_id)
            self._state_repo.update_node_status(
                xboard_node_id=xboard_node_id,
                status="deleted",
                status_reason=status_reason,
            )
            self._state_repo.create_event(
                FleetNodeEventCreateRequest(
                    node_id=node_record.id,
                    xboard_node_id=xboard_node_id,
                    event_type="node_deleted",
                    correlation_id=self._runtime_context.correlation_id,
                    from_status="deleting",
                    to_status="deleted",
                    message="Node deleted from Xboard and marked deleted locally.",
                    payload={"status_reason": status_reason},
                )
            )
            set_event_type("node_delete_completed")
            self._logger.info("Completed node delete orchestration xboard_node_id=%s", xboard_node_id)
            return NodeStateChangeResult(
                local_node_id=node_record.id,
                xboard_node_id=xboard_node_id,
                status="deleted",
            )
        except XboardNodeNotFoundError:
            set_event_type("node_delete_xboard_not_found")
            self._logger.warning(
                "Node already absent from Xboard, marking deleted locally xboard_node_id=%s",
                xboard_node_id,
            )
            try:
                self._state_repo.update_node_status(
                    xboard_node_id=xboard_node_id,
                    status="deleted",
                    status_reason=status_reason or "xboard_node_already_absent",
                )
                self._state_repo.create_event(
                    FleetNodeEventCreateRequest(
                        node_id=node_record.id,
                        xboard_node_id=xboard_node_id,
                        event_type="node_deleted",
                        correlation_id=self._runtime_context.correlation_id,
                        from_status="deleting",
                        to_status="deleted",
                        message="Node was already absent from Xboard; marked deleted locally.",
                        payload={"status_reason": status_reason or "xboard_node_already_absent"},
                    )
                )
            except Exception:
                set_event_type("node_delete_local_finalize_failed")
                self._logger.exception(
                    "Node already absent from Xboard, but local finalize also failed xboard_node_id=%s",
                    xboard_node_id,
                )
            set_event_type("node_delete_completed")
            self._logger.info(
                "Completed node delete orchestration (Xboard already absent) xboard_node_id=%s",
                xboard_node_id,
            )
            return NodeStateChangeResult(
                local_node_id=node_record.id,
                xboard_node_id=xboard_node_id,
                status="deleted",
            )
        except Exception as exc:
            set_event_type("node_delete_local_finalize_failed")
            self._logger.exception(
                "Node delete failed xboard_node_id=%s",
                xboard_node_id,
            )
            raise NodeRegistryServiceError(
                "Node delete failed; manual review required"
            ) from exc

