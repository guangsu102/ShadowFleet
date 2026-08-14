from __future__ import annotations

from database.asset_repo import AssetAllocationCreateRequest, AssetEventCreateRequest, AssetRepo
from infrastructure.vultr import (
    VultrClient,
    VultrFirewallEnsureResult,
    VultrInstanceLaunchRequest,
    VultrInstanceLaunchResult,
)
from services.provisioning_dns_service import rollback_dns_records, sync_dns_records
from services.provisioning_models import DnsSyncResult, ProvisionRequest, ProvisionResult
from services.provisioning_notifier import notify_failure, notify_success
from services.provisioning_support import (
    ProvisioningDependencies,
    build_register_node_request,
    build_user_data_render_request,
    require_non_empty,
    require_task_id,
    resolve_effective_domain_name,
    select_asset,
)
from utils.logger import set_event_type
from utils.template_engine import render_user_data


DEFAULT_VULTR_PLAN = "vc2-1c-1gb"
DEFAULT_VULTR_OS_ID = 2284


def provision_vultr_node(
    dependencies: ProvisioningDependencies,
    asset_repo: AssetRepo,
    request: ProvisionRequest,
) -> ProvisionResult:
    set_event_type("provisioning_started")
    dependencies.logger.info(
        "Starting Vultr provisioning for node=%s protocol=%s region=%s",
        request.node_name,
        request.protocol_type,
        request.region,
    )
    selection_result = select_asset(dependencies.asset_selector, request)
    asset_repo.create_asset_event(
        AssetEventCreateRequest(
            asset_id=selection_result.asset_id,
            event_type="provisioning_selected",
            correlation_id=dependencies.runtime_context.correlation_id,
            message="Vultr asset selected for provisioning.",
            payload={
                "protocol_type": request.protocol_type,
                "node_name": request.node_name,
                "region": selection_result.region,
            },
        )
    )

    registered_node_result = None
    dns_sync_result: DnsSyncResult | None = None
    cloudflare_record_id: str | None = None
    launch_result: VultrInstanceLaunchResult | None = None
    vultr_client: VultrClient | None = None
    firewall_ensure_result: VultrFirewallEnsureResult | None = None
    effective_domain_name: str | None = None

    try:
        registered_node_result = dependencies.node_registry.register_node(
            build_register_node_request(dependencies.runtime_context, request)
        )
        from services.node_auto_config_service import NodeAutoConfigService

        NodeAutoConfigService(dependencies.runtime_context).auto_configure_node(
            xboard_node_id=registered_node_result.xboard_node_id,
            protocol_type=request.protocol_type,
            protocol_settings=request.protocol_settings,
            sni_domain=request.sni_domain,
            reality_private_key=request.reality_private_key,
            reality_public_key=request.reality_public_key,
            reality_dest=request.reality_dest,
            allow_insecure=request.allow_insecure,
            network=request.network,
            flow=request.flow,
        )
        effective_domain_name = resolve_effective_domain_name(
            runtime_context=dependencies.runtime_context,
            request=request,
            selection_result=selection_result,
            xboard_node_id=registered_node_result.xboard_node_id,
        )
        ready_callback_registration = dependencies.ready_callback_service.register_callback(
            task_id=require_task_id(request),
            xboard_node_id=registered_node_result.xboard_node_id,
            correlation_id=dependencies.runtime_context.correlation_id,
        )
        rendered_user_data = render_user_data(
            build_user_data_render_request(
                runtime_context=dependencies.runtime_context,
                request=request,
                selection_result=selection_result,
                xboard_node_id=registered_node_result.xboard_node_id,
                ready_callback_registration=ready_callback_registration,
                effective_domain_name=effective_domain_name,
            )
        )

        provider_config = selection_result.provider_config or {}
        plan = (selection_result.instance_type or DEFAULT_VULTR_PLAN).strip()
        os_id = _parse_os_id(selection_result.ami_id)
        vpc_ids = _string_tuple(provider_config.get("vpc_ids"))
        if not vpc_ids:
            legacy_vpc_id = _optional_text(provider_config.get("vpc2")) or selection_result.subnet_id
            vpc_ids = (legacy_vpc_id,) if legacy_vpc_id else ()
        firewall_group_id = _optional_text(provider_config.get("firewall_group_id"))
        vultr_client = VultrClient(
            runtime_context=dependencies.runtime_context,
            api_token=require_non_empty(selection_result.aws_access_key, "vultr_token"),
        )
        firewall_ensure_result = vultr_client.ensure_firewall_ports(
            firewall_group_id=firewall_group_id,
            label=request.node_name,
            inbound_ports=tuple(dict.fromkeys((22, request.server_port))),
        )
        firewall_group_id = firewall_ensure_result.firewall_group_id
        launch_result = vultr_client.launch_instance(
            VultrInstanceLaunchRequest(
                label=request.node_name,
                region=require_non_empty(selection_result.region, "region"),
                plan=plan,
                os_id=os_id,
                user_data=rendered_user_data.user_data,
                ssh_key_ids=_string_tuple(provider_config.get("ssh_key_ids")),
                vpc_ids=vpc_ids,
                firewall_group_id=firewall_group_id,
                tags=tuple(dict.fromkeys(("shadowfleet", *_string_tuple(provider_config.get("tags"))))),
            )
        )
        if selection_result.requires_dns_record:
            dns_sync_result = sync_dns_records(
                runtime_context=dependencies.runtime_context,
                protocol_type=request.protocol_type,
                domain_name=require_non_empty(effective_domain_name, "domain_name"),
                selection_result=selection_result,
                require_cdn_proxy=request.require_cdn_proxy,
                ipv4_address=launch_result.ipv4_address,
                ipv6_address=launch_result.ipv6_address,
            )
            cloudflare_record_id = dns_sync_result.primary_record_id

        dependencies.ready_callback_service.wait_for_ready_callback(require_task_id(request))
        online_result = dependencies.node_registry.mark_node_online(
            xboard_node_id=registered_node_result.xboard_node_id,
            host=effective_domain_name or request.node_name,
            aws_account_id=selection_result.aws_account_id,
            aws_region=selection_result.region,
            aws_instance_id=launch_result.instance_id,
            aws_subnet_id=vpc_ids[0] if vpc_ids else None,
            aws_security_group_id=firewall_group_id,
            instance_type=plan,
            cloudflare_record_id=cloudflare_record_id,
            domain_name=effective_domain_name,
            ipv4_address=launch_result.ipv4_address,
            ipv6_address=launch_result.ipv6_address,
            status_reason=request.status_reason,
        )
        dependencies.ready_callback_service.mark_callback_completed(require_task_id(request))
        asset_repo.create_allocation(
            AssetAllocationCreateRequest(
                asset_id=selection_result.asset_id,
                fleet_node_id=online_result.local_node_id,
                xboard_node_id=online_result.xboard_node_id,
                protocol_type=request.protocol_type,
                vcpu_count=selection_result.vcpu or 1,
            )
        )
        asset_repo.create_asset_event(
            AssetEventCreateRequest(
                asset_id=selection_result.asset_id,
                event_type="provisioning_succeeded",
                correlation_id=dependencies.runtime_context.correlation_id,
                message="Vultr provisioning completed successfully.",
                payload={
                    "xboard_node_id": online_result.xboard_node_id,
                    "instance_id": launch_result.instance_id,
                    "ipv4_address": launch_result.ipv4_address,
                    "ipv6_address": launch_result.ipv6_address,
                    "domain_name": effective_domain_name,
                    "cloudflare_record_id": cloudflare_record_id,
                },
            )
        )
        notify_success(
            runtime_context=dependencies.runtime_context,
            request=request,
            selection_result=selection_result,
            online_result=online_result,
            instance_id=launch_result.instance_id,
            ipv6_address=launch_result.ipv6_address,
            domain_name=effective_domain_name,
            cloudflare_record_id=cloudflare_record_id,
        )
        set_event_type("provisioning_completed")
        return ProvisionResult(
            local_node_id=online_result.local_node_id,
            xboard_node_id=online_result.xboard_node_id,
            asset_id=selection_result.asset_id,
            asset_type=selection_result.asset_type,
            protocol_type=request.protocol_type,
            node_name=request.node_name,
            status=online_result.status,
            aws_account_id=selection_result.aws_account_id,
            region=selection_result.region,
            instance_id=launch_result.instance_id,
            network_interface_id=None,
            ipv4_address=launch_result.ipv4_address,
            ipv6_address=launch_result.ipv6_address,
            domain_name=effective_domain_name,
            cloudflare_record_id=cloudflare_record_id,
            cloudflare_a_record_id=(dns_sync_result.a_record_id if dns_sync_result else None),
            cloudflare_aaaa_record_id=(dns_sync_result.aaaa_record_id if dns_sync_result else None),
        )
    except Exception as exc:
        _handle_vultr_provision_failure(
            dependencies=dependencies,
            asset_repo=asset_repo,
            request=request,
            selection_result=selection_result,
            registered_node_result=registered_node_result,
            launch_result=launch_result,
            vultr_client=vultr_client,
            firewall_ensure_result=firewall_ensure_result,
            dns_sync_result=dns_sync_result,
            cloudflare_record_id=cloudflare_record_id,
            error=exc,
        )
        raise


def _handle_vultr_provision_failure(
    dependencies: ProvisioningDependencies,
    asset_repo: AssetRepo,
    request: ProvisionRequest,
    selection_result,
    registered_node_result,
    launch_result: VultrInstanceLaunchResult | None,
    vultr_client: VultrClient | None,
    firewall_ensure_result: VultrFirewallEnsureResult | None,
    dns_sync_result: DnsSyncResult | None,
    cloudflare_record_id: str | None,
    error: BaseException,
) -> None:
    logger = dependencies.logger
    runtime_context = dependencies.runtime_context
    set_event_type("provisioning_failed")
    logger.exception(
        "Vultr provisioning failed for node=%s asset_id=%s skip_rollback=%s",
        request.node_name,
        selection_result.asset_id,
        runtime_context.config.app.skip_rollback_on_failure,
    )
    asset_repo.create_asset_event(
        AssetEventCreateRequest(
            asset_id=selection_result.asset_id,
            event_type="provisioning_failed",
            correlation_id=runtime_context.correlation_id,
            message=str(error),
            payload={
                "node_name": request.node_name,
                "protocol_type": request.protocol_type,
                "cloudflare_record_id": cloudflare_record_id,
                "instance_id": getattr(launch_result, "instance_id", None),
                "xboard_node_id": getattr(registered_node_result, "xboard_node_id", None),
            },
        )
    )
    if not runtime_context.config.app.skip_rollback_on_failure:
        if dns_sync_result is not None:
            try:
                rollback_dns_records(runtime_context, dns_sync_result)
            except Exception:
                logger.exception("Failed to rollback DNS records for Vultr provisioning")
        if launch_result is not None and vultr_client is not None:
            try:
                vultr_client.delete_instance(launch_result.instance_id)
            except Exception:
                logger.exception("Failed to delete Vultr instance during rollback")
        elif vultr_client is not None and vultr_client.created_instance_id is not None:
            try:
                vultr_client.delete_instance(vultr_client.created_instance_id)
            except Exception:
                logger.exception("Failed to delete pending Vultr instance during rollback")
        if (
            firewall_ensure_result is not None
            and firewall_ensure_result.created
            and vultr_client is not None
        ):
            try:
                vultr_client.delete_firewall_group(
                    firewall_ensure_result.firewall_group_id
                )
            except Exception:
                logger.exception("Failed to delete Vultr firewall group during rollback")
        if registered_node_result is not None:
            xboard_node_id = getattr(registered_node_result, "xboard_node_id", None)
            if xboard_node_id:
                try:
                    dependencies.node_registry.delete_node(xboard_node_id)
                except Exception:
                    logger.exception("Failed to delete registered node during rollback")
    notify_failure(
        runtime_context=runtime_context,
        request=request,
        selection_result=selection_result,
        error=error,
        instance_id=getattr(launch_result, "instance_id", None),
        xboard_node_id=getattr(registered_node_result, "xboard_node_id", None),
    )


def _parse_os_id(value: str | None) -> int:
    if value is None or not value.strip():
        return DEFAULT_VULTR_OS_ID
    try:
        os_id = int(value)
    except ValueError as exc:
        raise ValueError("Vultr OS ID must be a positive integer") from exc
    if os_id <= 0:
        raise ValueError("Vultr OS ID must be a positive integer")
    return os_id


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())
