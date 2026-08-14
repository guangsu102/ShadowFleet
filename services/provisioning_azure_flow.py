from __future__ import annotations

from database.asset_repo import AssetAllocationCreateRequest, AssetEventCreateRequest, AssetRepo
from infrastructure.azure import (
    AzureClient,
    AzureCredentials,
    AzureVmLaunchRequest,
    AzureVmLaunchResult,
    resolve_azure_vnet_name,
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


DEFAULT_AZURE_VM_SIZE = "Standard_B1s"


def provision_azure_node(
    dependencies: ProvisioningDependencies,
    asset_repo: AssetRepo,
    request: ProvisionRequest,
) -> ProvisionResult:
    set_event_type("provisioning_started")
    dependencies.logger.info(
        "Starting Azure provisioning for node=%s protocol=%s region=%s",
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
            message="Azure asset selected for provisioning.",
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
    launch_result: AzureVmLaunchResult | None = None
    azure_client: AzureClient | None = None
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
        subscription_id = require_non_empty(
            _optional_text(provider_config.get("subscription_id")) or _subscription_from_account_id(selection_result.aws_account_id),
            "subscription_id",
        )
        azure_client = AzureClient(
            runtime_context=dependencies.runtime_context,
            credentials=AzureCredentials(
                tenant_id=require_non_empty(_optional_text(provider_config.get("tenant_id")), "tenant_id"),
                client_id=require_non_empty(selection_result.aws_access_key, "client_id"),
                client_secret=require_non_empty(selection_result.aws_secret_key, "client_secret"),
                subscription_id=subscription_id,
            ),
        )
        vm_size = (selection_result.instance_type or DEFAULT_AZURE_VM_SIZE).strip()
        location = require_non_empty(selection_result.region, "region")
        launch_result = azure_client.launch_vm(
            AzureVmLaunchRequest(
                name=request.node_name,
                location=location,
                resource_group=require_non_empty(
                    _optional_text(provider_config.get("resource_group")), "resource_group"
                ),
                vm_size=vm_size,
                admin_username=require_non_empty(
                    _optional_text(provider_config.get("admin_username")), "admin_username"
                ),
                ssh_public_key=require_non_empty(
                    _optional_text(provider_config.get("ssh_public_key")), "ssh_public_key"
                ),
                user_data=rendered_user_data.user_data,
                image_publisher=_optional_text(provider_config.get("image_publisher")) or "Canonical",
                image_offer=_optional_text(provider_config.get("image_offer")) or "0001-com-ubuntu-server-jammy",
                image_sku=_optional_text(provider_config.get("image_sku")) or "22_04-lts-gen2",
                image_version=_optional_text(provider_config.get("image_version")) or "latest",
                vnet_name=resolve_azure_vnet_name(
                    location,
                    _optional_text(provider_config.get("vnet_name")),
                ),
                subnet_name=_optional_text(provider_config.get("subnet_name")) or "default",
                tags=_string_tuple(provider_config.get("tags")),
                inbound_ports=tuple(dict.fromkeys((22, request.server_port))),
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
            aws_subnet_id=launch_result.subnet_id,
            aws_security_group_id=launch_result.network_security_group_id,
            instance_type=vm_size,
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
                message="Azure provisioning completed successfully.",
                payload={
                    "xboard_node_id": online_result.xboard_node_id,
                    "vm_id": launch_result.instance_id,
                    "network_interface_id": launch_result.network_interface_id,
                    "ipv4_address": launch_result.ipv4_address,
                    "ipv6_address": launch_result.ipv6_address,
                    "domain_name": effective_domain_name,
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
            network_interface_id=launch_result.network_interface_id,
            ipv4_address=launch_result.ipv4_address,
            ipv6_address=launch_result.ipv6_address,
            domain_name=effective_domain_name,
            cloudflare_record_id=cloudflare_record_id,
            cloudflare_a_record_id=dns_sync_result.a_record_id if dns_sync_result else None,
            cloudflare_aaaa_record_id=dns_sync_result.aaaa_record_id if dns_sync_result else None,
        )
    except Exception as exc:
        _handle_azure_provision_failure(
            dependencies,
            asset_repo,
            request,
            selection_result,
            registered_node_result,
            launch_result,
            azure_client,
            dns_sync_result,
            cloudflare_record_id,
            exc,
        )
        raise


def _handle_azure_provision_failure(
    dependencies: ProvisioningDependencies,
    asset_repo: AssetRepo,
    request: ProvisionRequest,
    selection_result,
    registered_node_result,
    launch_result: AzureVmLaunchResult | None,
    azure_client: AzureClient | None,
    dns_sync_result: DnsSyncResult | None,
    cloudflare_record_id: str | None,
    error: BaseException,
) -> None:
    runtime_context = dependencies.runtime_context
    logger = dependencies.logger
    set_event_type("provisioning_failed")
    logger.exception("Azure provisioning failed for node=%s asset_id=%s", request.node_name, selection_result.asset_id)
    asset_repo.create_asset_event(
        AssetEventCreateRequest(
            asset_id=selection_result.asset_id,
            event_type="provisioning_failed",
            correlation_id=runtime_context.correlation_id,
            message=str(error),
            payload={
                "node_name": request.node_name,
                "protocol_type": request.protocol_type,
                "vm_id": getattr(launch_result, "instance_id", None),
                "xboard_node_id": getattr(registered_node_result, "xboard_node_id", None),
                "cloudflare_record_id": cloudflare_record_id,
            },
        )
    )
    if not runtime_context.config.app.skip_rollback_on_failure:
        if dns_sync_result is not None:
            try:
                rollback_dns_records(runtime_context, dns_sync_result)
            except Exception:
                logger.exception("Failed to rollback DNS records for Azure provisioning")
        if azure_client is not None:
            try:
                azure_client.rollback_created_resources()
            except Exception:
                logger.exception("Failed to rollback Azure resources")
        if registered_node_result is not None:
            try:
                dependencies.node_registry.delete_node(registered_node_result.xboard_node_id)
            except Exception:
                logger.exception("Failed to delete registered node during Azure rollback")
    notify_failure(
        runtime_context=runtime_context,
        request=request,
        selection_result=selection_result,
        error=error,
        instance_id=getattr(launch_result, "instance_id", None),
        xboard_node_id=getattr(registered_node_result, "xboard_node_id", None),
    )


def _subscription_from_account_id(account_id: str | None) -> str | None:
    if not account_id or not account_id.lower().startswith("azure:"):
        return None
    return account_id.split(":", 1)[1].strip() or None


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())
