from __future__ import annotations

from database.asset_models import AssetNotFoundError
from database.asset_repo import AssetRepo
from database.state_repo import (
    FleetNodeCreateRequest,
    FleetNodeEventCreateRequest,
    FleetNodeRecord,
    StateRepo,
    StateRepoError,
)
from database.xboard_repo import XboardNodeCreateRequest, XboardNodeNotFoundError, XboardRepo, XboardRepoError
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
        self._asset_repo = AssetRepo(runtime_context)

    def register_node(self, request: RegisterNodeRequest) -> RegisterNodeResult:
        validate_register_request(request)
        set_event_type("node_registration_started")
        self._logger.info(
            "Starting node registration for name=%s type=%s",
            request.node_name,
            request.node_type,
        )

        # Check if a node with the same node_name already exists (for retry scenarios)
        existing_node = self._state_repo.get_node_by_node_name(request.node_name)
        if existing_node is not None:
            old_xboard_node_id = existing_node.xboard_node_id
            self._logger.info(
                "Found existing node for name=%s old_xboard_node_id=%s, status=%s. "
                "Creating new xboard node and cleaning up old one.",
                request.node_name,
                old_xboard_node_id,
                existing_node.status,
            )

            # Create new xboard node
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
            new_xboard_node_id = self._xboard_repo.register_node(xboard_request)

            # Update local record with new xboard_node_id
            self._state_repo.update_node_xboard_id(
                node_id=existing_node.id,
                new_xboard_node_id=new_xboard_node_id,
                old_xboard_node_id=old_xboard_node_id,
            )
            self._state_repo.update_node_status(
                xboard_node_id=new_xboard_node_id,
                status="provisioning",
                status_reason=request.status_reason,
            )
            self._state_repo.create_event(
                FleetNodeEventCreateRequest(
                    node_id=existing_node.id,
                    xboard_node_id=new_xboard_node_id,
                    event_type="node_retry",
                    correlation_id=self._runtime_context.correlation_id,
                    from_status=existing_node.status,
                    to_status="provisioning",
                    message=f"Node registration retried. Old xboard_node_id={old_xboard_node_id} replaced with new xboard_node_id={new_xboard_node_id}.",
                    payload={
                        "node_name": request.node_name,
                        "node_type": request.node_type,
                        "host": request.host,
                        "show": request.show,
                        "old_xboard_node_id": old_xboard_node_id,
                        "new_xboard_node_id": new_xboard_node_id,
                    },
                )
            )

            # Delete old xboard node
            try:
                self._xboard_repo.delete_node(old_xboard_node_id)
                self._logger.info(
                    "Deleted old xboard node xboard_node_id=%s for node_name=%s",
                    old_xboard_node_id,
                    request.node_name,
                )
            except XboardNodeNotFoundError:
                self._logger.warning(
                    "Old xboard node not found (may have been deleted already) xboard_node_id=%s",
                    old_xboard_node_id,
                )

            set_event_type("node_registration_completed")
            return RegisterNodeResult(
                local_node_id=existing_node.id,
                xboard_node_id=new_xboard_node_id,
                status="provisioning",
                node_name=request.node_name,
                node_type=request.node_type,
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
            # Release the allocation associated with this node
            try:
                self._asset_repo.release_allocation_by_xboard_node_id(xboard_node_id)
                self._logger.info(
                    "Released allocation for xboard_node_id=%s after node deletion",
                    xboard_node_id,
                )
            except AssetNotFoundError:
                self._logger.debug(
                    "No active allocation found for xboard_node_id=%s",
                    xboard_node_id,
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
                # Release the allocation associated with this node
                try:
                    self._asset_repo.release_allocation_by_xboard_node_id(xboard_node_id)
                    self._logger.info(
                        "Released allocation for xboard_node_id=%s after node deletion",
                        xboard_node_id,
                    )
                except AssetNotFoundError:
                    self._logger.debug(
                        "No active allocation found for xboard_node_id=%s",
                        xboard_node_id,
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

    def sync_with_xboard(self) -> dict[str, int]:
        """
        Synchronize local node records with xboard.
        - xboard has sf- node, local doesn't → create new local record
        - local has node, xboard doesn't → mark local as deleted
        - Both have same node_name → no action (already synced)

        Returns summary: {created, orphan_local_deleted, already_synced}
        Returns summary with -1 values if xboard is unavailable.
        """
        from dataclasses import dataclass

        @dataclass
        class SyncSummary:
            created: int = 0
            orphan_local_deleted: int = 0
            already_synced: int = 0

        summary = SyncSummary()

        try:
            xboard_nodes = self._xboard_repo.list_all_shadowfleet_nodes()
        except XboardRepoError as exc:
            self._logger.warning(
                "Xboard unavailable during sync, skipping synchronization: %s",
                exc,
            )
            set_event_type("node_sync_skipped_xboard_unavailable")
            return {
                "created": -1,
                "orphan_local_deleted": -1,
                "already_synced": -1,
            }

        local_nodes = self._state_repo.list_active_nodes()

        xboard_names_stripped = {self._strip_sf_prefix(n.node_name) for n in xboard_nodes}
        local_names = {n.node_name for n in local_nodes}

        for node in xboard_nodes:
            name_stripped = self._strip_sf_prefix(node.node_name)
            if name_stripped in local_names:
                summary.already_synced += 1
            else:
                self._logger.info(
                    "Found xboard node without local record, creating new: id=%s name=%s type=%s",
                    node.node_id,
                    node.node_name,
                    node.node_type,
                )
                try:
                    self._state_repo.create_node(
                        FleetNodeCreateRequest(
                            xboard_node_id=node.node_id,
                            node_name=name_stripped,
                            node_type=node.node_type,
                            status="offline",
                            status_reason="sync: created from xboard",
                        )
                    )
                    summary.created += 1
                except StateRepoError as exc:
                    self._logger.warning(
                        "Failed to create local record for xboard node id=%s: %s",
                        node.node_id,
                        exc,
                    )

        for local_node in local_nodes:
            if local_node.node_name not in xboard_names_stripped:
                self._logger.info(
                    "Found orphan local node without xboard record: id=%s xboard_node_id=%s name=%s. Marking deleted.",
                    local_node.id,
                    local_node.xboard_node_id,
                    local_node.node_name,
                )
                self._state_repo.mark_node_deleted(
                    xboard_node_id=local_node.xboard_node_id,
                    reason="sync: node not found in xboard",
                )
                self._state_repo.create_event(
                    FleetNodeEventCreateRequest(
                        node_id=local_node.id,
                        xboard_node_id=local_node.xboard_node_id,
                        event_type="node_sync_deleted",
                        correlation_id=self._runtime_context.correlation_id,
                        from_status=local_node.status,
                        to_status="deleted",
                        message=f"Node deleted during xboard sync: not found in xboard",
                    )
                )
                summary.orphan_local_deleted += 1

        set_event_type("node_sync_completed")
        self._logger.info(
            "Xboard sync completed: created=%s orphan_local_deleted=%s already_synced=%s",
            summary.created,
            summary.orphan_local_deleted,
            summary.already_synced,
        )
        return {
            "created": summary.created,
            "orphan_local_deleted": summary.orphan_local_deleted,
            "already_synced": summary.already_synced,
        }

    @staticmethod
    def _strip_sf_prefix(name: str) -> str:
        """Strip sf- prefix from node name for comparison."""
        if name.startswith("sf-"):
            return name[3:]
        return name

