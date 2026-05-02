from __future__ import annotations

from dataclasses import replace

from database.asset_repo import AssetRepo
from infrastructure.self_hosted.ssh_client import RemoteCommandResult, SelfHostedSshClient, SelfHostedSshClientError
from services.provisioning_dns_service import sync_dns_records
from services.provisioning_failure_handler import handle_provision_failure
from services.provisioning_models import DnsSyncResult, ProvisionRequest, ProvisionResult
from services.provisioning_notifier import notify_success
from services.provisioning_support import (
    ProvisioningDependencies,
    build_register_node_request,
    build_remote_execution_payload,
    build_self_hosted_ssh_config,
    build_user_data_render_request,
    require_non_empty,
    require_task_id,
    resolve_effective_domain_name,
    resolve_self_hosted_ip_addresses,
    select_asset,
)
from utils.logger import set_event_type
from utils.template_engine import render_user_data


SELF_HOSTED_PORT_RANGE_START = 40000
SELF_HOSTED_PORT_RANGE_END = 60000


def provision_self_hosted_node(
    dependencies: ProvisioningDependencies,
    asset_repo: AssetRepo,
    request: ProvisionRequest,
) -> ProvisionResult:
    set_event_type("provisioning_started")
    dependencies.logger.info(
        "Starting self-hosted provisioning for node=%s protocol=%s",
        request.node_name,
        request.protocol_type,
    )

    selection_result = select_asset(dependencies.asset_selector, request)
    asset_repo.create_asset_event(
        AssetEventCreateRequest(
            asset_id=selection_result.asset_id,
            event_type="provisioning_selected",
            correlation_id=dependencies.runtime_context.correlation_id,
            message="Self-hosted asset selected for provisioning.",
            payload={
                "protocol_type": request.protocol_type,
                "node_name": request.node_name,
                "ssh_host": selection_result.ssh_host,
            },
        )
    )

    # --- Auto-allocate server_port for self-hosted ---
    allocated_port: int = 0
    nginx_internal_port: int | None = None
    if request.server_port <= 0:
        allocated_port = asset_repo.allocate_next_free_port(
            asset_id=selection_result.asset_id,
            protocol_type=request.protocol_type,
            port_range_start=SELF_HOSTED_PORT_RANGE_START,
            port_range_end=SELF_HOSTED_PORT_RANGE_END,
        )
        dependencies.logger.info(
            "Auto-allocated server_port=%s for asset_id=%s",
            allocated_port,
            selection_result.asset_id,
        )
    else:
        # User-specified port: validate it is not already in use
        existing = asset_repo._find_active_port_allocation(selection_result.asset_id, request.server_port)
        if existing is not None:
            raise SelfHostedSshClientError(
                f"Port {request.server_port} is already allocated on this machine "
                f"(xboard_node_id={existing.xboard_node_id}). Choose a different port or "
                "leave server_port at 0 for automatic allocation.",
                stage="port_conflict_check",
            )
        allocated_port = request.server_port
        asset_repo.create_port_allocation(
            PortAllocationCreateRequest(
                asset_id=selection_result.asset_id,
                server_port=allocated_port,
                protocol_type=request.protocol_type,
            )
        )

    registered_node_result = None
    ready_callback_registration = None
    dns_sync_result: DnsSyncResult | None = None
    cloudflare_record_id: str | None = None
    effective_domain_name: str | None = None
    resolved_ipv4_address: str | None = None
    resolved_ipv6_address: str | None = None
    remote_command_result: RemoteCommandResult | None = None

    try:
        registered_node_result = dependencies.node_registry.register_node(
            build_register_node_request(request)
        )
        effective_domain_name = resolve_effective_domain_name(
            runtime_context=dependencies.runtime_context,
            request=request,
            selection_result=selection_result,
            xboard_node_id=registered_node_result.xboard_node_id,
        )
        resolved_ipv4_address, resolved_ipv6_address = resolve_self_hosted_ip_addresses(
            require_non_empty(selection_result.ssh_host, "ssh_host")
        )

        if selection_result.requires_dns_record:
            dns_sync_result = sync_dns_records(
                runtime_context=dependencies.runtime_context,
                protocol_type=request.protocol_type,
                domain_name=require_non_empty(effective_domain_name, "domain_name"),
                selection_result=selection_result,
                require_cdn_proxy=request.require_cdn_proxy,
                ipv4_address=resolved_ipv4_address,
                ipv6_address=resolved_ipv6_address,
            )
            cloudflare_record_id = dns_sync_result.primary_record_id

        ready_callback_registration = dependencies.ready_callback_service.register_callback(
            task_id=require_task_id(request),
            xboard_node_id=registered_node_result.xboard_node_id,
            correlation_id=dependencies.runtime_context.correlation_id,
        )

        # Build a modified request with the auto-allocated port
        request_with_port = _with_server_port(request, allocated_port)

        # AnyTLS requires a unique nginx internal port per node on same machine
        from utils.template_models import get_protocol_capabilities
        caps = get_protocol_capabilities(request.protocol_type)
        if caps.requires_nginx_stream:
            nginx_internal_port = asset_repo.allocate_next_free_port(
                asset_id=selection_result.asset_id,
                protocol_type=request.protocol_type,
                port_range_start=51000,
                port_range_end=52000,
            )
            dependencies.logger.info(
                "Auto-allocated nginx_internal_port=%s for AnyTLS node on asset_id=%s",
                nginx_internal_port,
                selection_result.asset_id,
            )

        rendered_user_data = render_user_data(
            build_user_data_render_request(
                runtime_context=dependencies.runtime_context,
                request=request_with_port,
                selection_result=selection_result,
                xboard_node_id=registered_node_result.xboard_node_id,
                ready_callback_registration=ready_callback_registration,
                effective_domain_name=effective_domain_name,
                nginx_internal_port=nginx_internal_port,
            )
        )
        ssh_client = SelfHostedSshClient(
            runtime_context=dependencies.runtime_context,
            ssh_config=build_self_hosted_ssh_config(selection_result),
        )
        remote_command_result = ssh_client.execute_script(rendered_user_data.user_data)
        asset_repo.create_asset_event(
            AssetEventCreateRequest(
                asset_id=selection_result.asset_id,
                event_type="self_hosted_remote_script_succeeded",
                correlation_id=dependencies.runtime_context.correlation_id,
                message="Self-hosted remote provisioning script executed successfully.",
                payload=build_remote_execution_payload(
                    stage="execute_script",
                    command_result=remote_command_result,
                ),
            )
        )

        dependencies.ready_callback_service.wait_for_ready_callback(require_task_id(request))
        online_result = dependencies.node_registry.mark_node_online(
            xboard_node_id=registered_node_result.xboard_node_id,
            host=effective_domain_name or require_non_empty(selection_result.ssh_host, "ssh_host"),
            cloudflare_record_id=cloudflare_record_id,
            domain_name=effective_domain_name,
            ipv4_address=resolved_ipv4_address,
            ipv6_address=resolved_ipv6_address,
            status_reason=request.status_reason,
        )
        dependencies.ready_callback_service.mark_callback_completed(require_task_id(request))

        # Update port allocation with node IDs
        asset_repo.create_port_allocation(
            PortAllocationCreateRequest(
                asset_id=selection_result.asset_id,
                fleet_node_id=online_result.local_node_id,
                xboard_node_id=online_result.xboard_node_id,
                server_port=allocated_port,
                protocol_type=request.protocol_type,
            )
        )
        asset_repo.create_allocation(
            AssetAllocationCreateRequest(
                asset_id=selection_result.asset_id,
                fleet_node_id=online_result.local_node_id,
                xboard_node_id=online_result.xboard_node_id,
                protocol_type=request.protocol_type,
            )
        )
        asset_repo.create_asset_event(
            AssetEventCreateRequest(
                asset_id=selection_result.asset_id,
                event_type="provisioning_succeeded",
                correlation_id=dependencies.runtime_context.correlation_id,
                message="Self-hosted provisioning completed successfully.",
                payload={
                    "xboard_node_id": online_result.xboard_node_id,
                    "server_port": allocated_port,
                    "domain_name": effective_domain_name,
                    "ipv4_address": resolved_ipv4_address,
                    "ipv6_address": resolved_ipv6_address,
                    "cloudflare_record_id": cloudflare_record_id,
                    "cloudflare_a_record_id": (
                        dns_sync_result.a_record_id if dns_sync_result is not None else None
                    ),
                    "cloudflare_aaaa_record_id": (
                        dns_sync_result.aaaa_record_id if dns_sync_result is not None else None
                    ),
                },
            )
        )
        notify_success(
            runtime_context=dependencies.runtime_context,
            request=request,
            selection_result=selection_result,
            online_result=online_result,
            instance_id=None,
            ipv6_address=resolved_ipv6_address,
            domain_name=effective_domain_name,
            cloudflare_record_id=cloudflare_record_id,
        )
        set_event_type("provisioning_completed")
        dependencies.logger.info(
            "Completed self-hosted provisioning xboard_node_id=%s asset_id=%s server_port=%s",
            online_result.xboard_node_id,
            selection_result.asset_id,
            allocated_port,
        )
        return ProvisionResult(
            local_node_id=online_result.local_node_id,
            xboard_node_id=online_result.xboard_node_id,
            asset_id=selection_result.asset_id,
            asset_type=selection_result.asset_type,
            protocol_type=request.protocol_type,
            node_name=request.node_name,
            status=online_result.status,
            aws_account_id=None,
            region=selection_result.region,
            instance_id=None,
            network_interface_id=None,
            ipv6_address=resolved_ipv6_address,
            domain_name=effective_domain_name,
            cloudflare_record_id=cloudflare_record_id,
            cloudflare_a_record_id=(
                dns_sync_result.a_record_id if dns_sync_result is not None else None
            ),
            cloudflare_aaaa_record_id=(
                dns_sync_result.aaaa_record_id if dns_sync_result is not None else None
            ),
        )
    except Exception as exc:
        # Rollback port allocation on any failure
        if allocated_port > 0 and selection_result.asset_id > 0:
            try:
                asset_repo.release_port_allocation_by_asset_and_port(
                    asset_id=selection_result.asset_id,
                    server_port=allocated_port,
                )
                dependencies.logger.info(
                    "Rolled back port allocation server_port=%s asset_id=%s after failure",
                    allocated_port,
                    selection_result.asset_id,
                )
            except Exception as rollback_exc:
                dependencies.logger.warning(
                    "Failed to rollback port allocation: %s",
                    rollback_exc,
                )
        if isinstance(exc, SelfHostedSshClientError):
            asset_repo.create_asset_event(
                AssetEventCreateRequest(
                    asset_id=selection_result.asset_id,
                    event_type="self_hosted_remote_script_failed",
                    correlation_id=dependencies.runtime_context.correlation_id,
                    message=str(exc),
                    payload=build_remote_execution_payload(
                        stage=exc.stage,
                        command_result=remote_command_result,
                        error=exc,
                    ),
                )
            )
        handle_provision_failure(
            runtime_context=dependencies.runtime_context,
            asset_repo=asset_repo,
            node_registry=dependencies.node_registry,
            logger_name=dependencies.logger.name,
            request=request,
            selection_result=selection_result,
            registered_node_result=registered_node_result,
            launch_result=None,
            ec2_client=None,
            dns_sync_result=dns_sync_result,
            cloudflare_record_id=cloudflare_record_id,
            error=exc,
        )
        raise


def _with_server_port(request: ProvisionRequest, server_port: int) -> ProvisionRequest:
    """Create a shallow copy of ProvisionRequest with a different server_port."""
    return replace(request, server_port=server_port)
