from __future__ import annotations

import re

from database.asset_models import (
    AssetAllocationCreateRequest,
    AssetEventCreateRequest,
)
from database.asset_repo import AssetRepo
from infrastructure.gcp import (
    GCPClient,
    GCPCredentials,
    GCPInstanceLaunchRequest,
    GCPInstanceLaunchResult,
)
from services.provisioning_dns_service import (
    rollback_dns_records,
    sync_dns_records,
)
from services.provisioning_models import (
    DnsSyncResult,
    ProvisionRequest,
    ProvisionResult,
)
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


DEFAULT_GCP_MACHINE_TYPE = "e2-small"


def provision_gcp_node(
    dependencies: ProvisioningDependencies,
    asset_repo: AssetRepo,
    request: ProvisionRequest,
) -> ProvisionResult:
    set_event_type("provisioning_started")
    dependencies.logger.info(
        "Starting GCP provisioning for node=%s protocol=%s zone=%s",
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
            message="GCP asset selected for provisioning.",
            payload={
                "protocol_type": request.protocol_type,
                "node_name": request.node_name,
                "zone": selection_result.region,
            },
        )
    )

    registered_node_result = None
    dns_sync_result: DnsSyncResult | None = None
    cloudflare_record_id: str | None = None
    launch_result: GCPInstanceLaunchResult | None = None
    gcp_client: GCPClient | None = None
    effective_domain_name: str | None = None
    instance_name: str | None = None

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
        callback_registration = dependencies.ready_callback_service.register_callback(
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
                ready_callback_registration=callback_registration,
                effective_domain_name=effective_domain_name,
            )
        )

        config = selection_result.provider_config or {}
        zone = require_non_empty(selection_result.region, "gcp_zone")
        project_id = _required_config(config, "project_id")
        network = _required_config(config, "network")
        subnetwork = _optional_text(config.get("subnetwork"))
        source_image = (
            _optional_text(config.get("source_image"))
            or require_non_empty(selection_result.ami_id, "source_image")
        )
        machine_type = (
            selection_result.instance_type or DEFAULT_GCP_MACHINE_TYPE
        ).strip()
        gcp_client = GCPClient(
            runtime_context=dependencies.runtime_context,
            credentials=GCPCredentials(
                project_id=project_id,
                client_email=require_non_empty(
                    selection_result.aws_access_key,
                    "client_email",
                ),
                private_key=require_non_empty(
                    selection_result.aws_secret_key,
                    "private_key",
                ),
                private_key_id=_optional_text(config.get("private_key_id")),
                client_id=_optional_text(config.get("client_id")),
                token_uri=_optional_text(config.get("token_uri"))
                or "https://oauth2.googleapis.com/token",
            ),
        )
        firewall_rule_name = (
            _optional_text(config.get("firewall_rule_name"))
            or "shadowfleet-ingress"
        )
        gcp_client.ensure_firewall_ports(
            network=network,
            inbound_ports=tuple(dict.fromkeys((22, request.server_port))),
            rule_name=firewall_rule_name,
        )
        instance_name = _gcp_instance_name(
            request.node_name,
            registered_node_result.xboard_node_id,
        )
        launch_result = gcp_client.launch_instance(
            GCPInstanceLaunchRequest(
                name=instance_name,
                zone=zone,
                machine_type=machine_type,
                source_image=source_image,
                network=network,
                subnetwork=subnetwork,
                ssh_username=_required_config(config, "ssh_username"),
                ssh_public_key=_required_config(config, "ssh_public_key"),
                startup_script=rendered_user_data.user_data,
                labels=_string_mapping(config.get("labels")),
            )
        )
        if selection_result.requires_dns_record:
            dns_sync_result = sync_dns_records(
                runtime_context=dependencies.runtime_context,
                protocol_type=request.protocol_type,
                domain_name=require_non_empty(
                    effective_domain_name,
                    "domain_name",
                ),
                selection_result=selection_result,
                require_cdn_proxy=request.require_cdn_proxy,
                ipv4_address=launch_result.ipv4_address,
                ipv6_address=launch_result.ipv6_address,
            )
            cloudflare_record_id = dns_sync_result.primary_record_id

        dependencies.ready_callback_service.wait_for_ready_callback(
            require_task_id(request)
        )
        online_result = dependencies.node_registry.mark_node_online(
            xboard_node_id=registered_node_result.xboard_node_id,
            host=effective_domain_name or request.node_name,
            aws_account_id=selection_result.aws_account_id,
            aws_region=zone,
            aws_instance_id=launch_result.name,
            aws_subnet_id=subnetwork,
            aws_security_group_id=firewall_rule_name,
            instance_type=machine_type,
            cloudflare_record_id=cloudflare_record_id,
            domain_name=effective_domain_name,
            ipv4_address=launch_result.ipv4_address,
            ipv6_address=launch_result.ipv6_address,
            status_reason=request.status_reason,
        )
        dependencies.ready_callback_service.mark_callback_completed(
            require_task_id(request)
        )
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
                message="GCP provisioning completed successfully.",
                payload={
                    "xboard_node_id": online_result.xboard_node_id,
                    "instance_name": launch_result.name,
                    "zone": zone,
                    "ipv4_address": launch_result.ipv4_address,
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
            instance_id=launch_result.name,
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
            region=zone,
            instance_id=launch_result.name,
            network_interface_id=launch_result.network_interface,
            ipv4_address=launch_result.ipv4_address,
            ipv6_address=launch_result.ipv6_address,
            domain_name=effective_domain_name,
            cloudflare_record_id=cloudflare_record_id,
            cloudflare_a_record_id=(
                dns_sync_result.a_record_id if dns_sync_result else None
            ),
            cloudflare_aaaa_record_id=(
                dns_sync_result.aaaa_record_id if dns_sync_result else None
            ),
        )
    except Exception as exc:
        _handle_gcp_provision_failure(
            dependencies=dependencies,
            asset_repo=asset_repo,
            request=request,
            selection_result=selection_result,
            registered_node_result=registered_node_result,
            instance_name=instance_name,
            zone=_optional_text(selection_result.region),
            gcp_client=gcp_client,
            dns_sync_result=dns_sync_result,
            cloudflare_record_id=cloudflare_record_id,
            error=exc,
        )
        raise


def _handle_gcp_provision_failure(
    *,
    dependencies: ProvisioningDependencies,
    asset_repo: AssetRepo,
    request: ProvisionRequest,
    selection_result,
    registered_node_result,
    instance_name: str | None,
    zone: str | None,
    gcp_client: GCPClient | None,
    dns_sync_result: DnsSyncResult | None,
    cloudflare_record_id: str | None,
    error: BaseException,
) -> None:
    runtime_context = dependencies.runtime_context
    set_event_type("provisioning_failed")
    dependencies.logger.exception(
        "GCP provisioning failed for node=%s asset_id=%s skip_rollback=%s",
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
                "instance_name": instance_name,
                "xboard_node_id": getattr(
                    registered_node_result,
                    "xboard_node_id",
                    None,
                ),
            },
        )
    )
    if not runtime_context.config.app.skip_rollback_on_failure:
        if dns_sync_result is not None:
            try:
                rollback_dns_records(runtime_context, dns_sync_result)
            except Exception:
                dependencies.logger.exception(
                    "Failed to rollback DNS records for GCP provisioning"
                )
        rollback_name = instance_name
        rollback_zone = zone
        if gcp_client is not None:
            rollback_name = rollback_name or gcp_client.created_instance_name
            rollback_zone = rollback_zone or gcp_client.created_instance_zone
        if rollback_name and rollback_zone and gcp_client is not None:
            try:
                gcp_client.delete_instance(rollback_zone, rollback_name)
            except Exception:
                dependencies.logger.exception(
                    "Failed to delete GCP instance during rollback"
                )
        if registered_node_result is not None:
            xboard_node_id = getattr(
                registered_node_result,
                "xboard_node_id",
                None,
            )
            if xboard_node_id:
                try:
                    dependencies.node_registry.delete_node(xboard_node_id)
                except Exception:
                    dependencies.logger.exception(
                        "Failed to delete registered node during GCP rollback"
                    )
    notify_failure(
        runtime_context=runtime_context,
        request=request,
        selection_result=selection_result,
        error=error,
        instance_id=instance_name,
        xboard_node_id=getattr(
            registered_node_result,
            "xboard_node_id",
            None,
        ),
    )


def _gcp_instance_name(node_name: str, xboard_node_id: int) -> str:
    normalized = re.sub(r"[^a-z0-9-]+", "-", node_name.casefold()).strip("-")
    if not normalized or not normalized[0].isalpha():
        normalized = f"sf-{normalized}" if normalized else "sf-node"
    suffix = f"-{xboard_node_id}"
    return f"{normalized[:63-len(suffix)].rstrip('-')}{suffix}"


def _required_config(config: dict[str, object], name: str) -> str:
    value = _optional_text(config.get(name))
    if value is None:
        raise ValueError(f"GCP provider config is missing {name}")
    return value


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_mapping(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key).strip(): str(item).strip()
        for key, item in value.items()
        if str(key).strip() and str(item).strip()
    }
