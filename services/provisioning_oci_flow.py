from __future__ import annotations

from database.asset_repo import AssetAllocationCreateRequest, AssetEventCreateRequest, AssetRepo
from infrastructure.oci import (
    OCIClient,
    OCICredentials,
    OCIInstanceLaunchRequest,
    OCIInstanceLaunchResult,
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


DEFAULT_OCI_SHAPE = "VM.Standard.E4.Flex"


def provision_oci_node(
    dependencies: ProvisioningDependencies,
    asset_repo: AssetRepo,
    request: ProvisionRequest,
) -> ProvisionResult:
    set_event_type("provisioning_started")
    dependencies.logger.info(
        "Starting OCI provisioning for node=%s protocol=%s region=%s",
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
            message="OCI asset selected for provisioning.",
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
    launch_result: OCIInstanceLaunchResult | None = None
    oci_client: OCIClient | None = None
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
        tenancy_ocid = _required_config(config, "tenancy_ocid")
        compartment_ocid = _required_config(config, "compartment_ocid")
        subnet_ocid = (
            _optional_text(config.get("subnet_ocid"))
            or require_non_empty(selection_result.subnet_id, "subnet_ocid")
        )
        nsg_ocid = (
            _optional_text(config.get("network_security_group_ocid"))
            or require_non_empty(selection_result.security_group_id, "network_security_group_ocid")
        )
        image_ocid = (
            _optional_text(config.get("image_ocid"))
            or require_non_empty(selection_result.ami_id, "image_ocid")
        )
        shape = (selection_result.instance_type or DEFAULT_OCI_SHAPE).strip()
        availability_domain = _required_config(config, "availability_domain")
        oci_client = OCIClient(
            runtime_context=dependencies.runtime_context,
            credentials=OCICredentials(
                tenancy_ocid=tenancy_ocid,
                user_ocid=require_non_empty(selection_result.aws_access_key, "user_ocid"),
                fingerprint=_required_config(config, "fingerprint"),
                private_key=require_non_empty(selection_result.aws_secret_key, "private_key"),
                private_key_passphrase=_optional_text(config.get("private_key_passphrase")),
            ),
            region=require_non_empty(selection_result.region, "region"),
        )
        oci_client.ensure_network_security_group_ports(
            nsg_ocid,
            tuple(dict.fromkeys((22, request.server_port))),
        )
        launch_result = oci_client.launch_instance(
            OCIInstanceLaunchRequest(
                display_name=request.node_name,
                compartment_ocid=compartment_ocid,
                availability_domain=availability_domain,
                shape=shape,
                image_ocid=image_ocid,
                subnet_ocid=subnet_ocid,
                network_security_group_ocid=nsg_ocid,
                ssh_public_key=_required_config(config, "ssh_public_key"),
                user_data=rendered_user_data.user_data,
                ocpus=_optional_float(config.get("ocpus")),
                memory_in_gbs=_optional_float(config.get("memory_in_gbs")),
                freeform_tags=_string_mapping(config.get("freeform_tags")),
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
            aws_subnet_id=subnet_ocid,
            aws_security_group_id=nsg_ocid,
            instance_type=shape,
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
                message="OCI provisioning completed successfully.",
                payload={
                    "xboard_node_id": online_result.xboard_node_id,
                    "instance_id": launch_result.instance_id,
                    "vnic_id": launch_result.vnic_id,
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
            network_interface_id=launch_result.vnic_id,
            ipv4_address=launch_result.ipv4_address,
            ipv6_address=launch_result.ipv6_address,
            domain_name=effective_domain_name,
            cloudflare_record_id=cloudflare_record_id,
            cloudflare_a_record_id=(dns_sync_result.a_record_id if dns_sync_result else None),
            cloudflare_aaaa_record_id=(
                dns_sync_result.aaaa_record_id if dns_sync_result else None
            ),
        )
    except Exception as exc:
        _handle_oci_provision_failure(
            dependencies=dependencies,
            asset_repo=asset_repo,
            request=request,
            selection_result=selection_result,
            registered_node_result=registered_node_result,
            launch_result=launch_result,
            oci_client=oci_client,
            dns_sync_result=dns_sync_result,
            cloudflare_record_id=cloudflare_record_id,
            error=exc,
        )
        raise


def _handle_oci_provision_failure(
    *,
    dependencies: ProvisioningDependencies,
    asset_repo: AssetRepo,
    request: ProvisionRequest,
    selection_result,
    registered_node_result,
    launch_result: OCIInstanceLaunchResult | None,
    oci_client: OCIClient | None,
    dns_sync_result: DnsSyncResult | None,
    cloudflare_record_id: str | None,
    error: BaseException,
) -> None:
    runtime_context = dependencies.runtime_context
    set_event_type("provisioning_failed")
    dependencies.logger.exception(
        "OCI provisioning failed for node=%s asset_id=%s skip_rollback=%s",
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
                dependencies.logger.exception("Failed to rollback DNS records for OCI provisioning")
        instance_id = getattr(launch_result, "instance_id", None)
        if instance_id is None and oci_client is not None:
            instance_id = oci_client.created_instance_id
        if instance_id and oci_client is not None:
            try:
                oci_client.delete_instance(instance_id)
            except Exception:
                dependencies.logger.exception("Failed to terminate OCI instance during rollback")
        if registered_node_result is not None:
            xboard_node_id = getattr(registered_node_result, "xboard_node_id", None)
            if xboard_node_id:
                try:
                    dependencies.node_registry.delete_node(xboard_node_id)
                except Exception:
                    dependencies.logger.exception("Failed to delete registered node during rollback")
    notify_failure(
        runtime_context=runtime_context,
        request=request,
        selection_result=selection_result,
        error=error,
        instance_id=getattr(launch_result, "instance_id", None),
        xboard_node_id=getattr(registered_node_result, "xboard_node_id", None),
    )


def _required_config(config: dict[str, object], name: str) -> str:
    value = _optional_text(config.get(name))
    if value is None:
        raise ValueError(f"OCI provider config is missing {name}")
    return value


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    parsed = float(value)
    if parsed <= 0:
        raise ValueError("OCI shape configuration values must be greater than 0")
    return parsed


def _string_mapping(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key).strip(): str(item).strip()
        for key, item in value.items()
        if str(key).strip() and str(item).strip()
    }
