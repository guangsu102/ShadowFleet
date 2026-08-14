from __future__ import annotations

import re
from uuid import uuid4

from database.asset_repo import AssetAllocationCreateRequest, AssetEventCreateRequest, AssetRepo
from infrastructure.kamatera import (
    KamateraClient,
    KamateraServerLaunchRequest,
    KamateraServerLaunchResult,
)
from services.provisioning_dns_service import rollback_dns_records, sync_dns_records
from services.provisioning_models import DnsSyncResult, ProvisionRequest, ProvisionResult
from services.provisioning_notifier import notify_failure, notify_success
from services.provisioning_support import (
    ProvisionerServiceError,
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


DEFAULT_CPU = "2B"


def provision_kamatera_node(
    dependencies: ProvisioningDependencies,
    asset_repo: AssetRepo,
    request: ProvisionRequest,
) -> ProvisionResult:
    set_event_type("provisioning_started")
    dependencies.logger.info(
        "Starting Kamatera provisioning for node=%s protocol=%s datacenter=%s",
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
            message="Kamatera asset selected for provisioning.",
            payload={
                "protocol_type": request.protocol_type,
                "node_name": request.node_name,
                "datacenter": selection_result.region,
            },
        )
    )

    registered_node_result = None
    dns_sync_result: DnsSyncResult | None = None
    launch_result: KamateraServerLaunchResult | None = None
    client: KamateraClient | None = None
    effective_domain_name: str | None = None
    server_name: str | None = None

    try:
        registered_node_result = dependencies.node_registry.register_node(
            build_register_node_request(dependencies.runtime_context, request)
        )
        from services.node_auto_config_service import NodeAutoConfigService

        NodeAutoConfigService(dependencies.runtime_context).auto_configure_node(
            xboard_node_id=registered_node_result.xboard_node_id,
            protocol_type=request.protocol_type,
            protocol_settings=request.protocol_settings,
            sni_domain=getattr(request, "sni_domain", None),
            reality_private_key=getattr(request, "reality_private_key", None),
            reality_public_key=getattr(request, "reality_public_key", None),
            reality_dest=getattr(request, "reality_dest", None),
            allow_insecure=getattr(request, "allow_insecure", True),
            network=getattr(request, "network", "grpc"),
            flow=getattr(request, "flow", None),
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
        client = KamateraClient(
            runtime_context=dependencies.runtime_context,
            client_id=require_non_empty(selection_result.aws_access_key, "kamatera_client_id"),
            secret=require_non_empty(selection_result.aws_secret_key, "kamatera_secret"),
        )
        server_name = _server_name(request.node_name)
        cpu = (selection_result.instance_type or _optional_text(provider_config.get("cpu")) or DEFAULT_CPU).strip()
        image = require_non_empty(
            selection_result.ami_id or _optional_text(provider_config.get("image")),
            "kamatera_image",
        )
        launch_result = client.launch_server(
            KamateraServerLaunchRequest(
                name=server_name,
                datacenter=require_non_empty(selection_result.region, "datacenter"),
                image=image,
                cpu=cpu,
                ram_mb=_positive_int(provider_config.get("ram_mb"), 2048),
                disk_sizes_gb=_positive_int_tuple(provider_config.get("disk_sizes_gb"), (20,)),
                startup_script=rendered_user_data.user_data,
                ssh_public_key=require_non_empty(
                    _optional_text(provider_config.get("ssh_public_key")),
                    "kamatera_ssh_public_key",
                ),
                billing_cycle=_optional_text(provider_config.get("billing_cycle")) or "hourly",
                monthly_package=_optional_text(provider_config.get("monthly_package")),
                daily_backup=bool(provider_config.get("daily_backup", False)),
                managed=bool(provider_config.get("managed", False)),
                tags=tuple(dict.fromkeys((*_string_tuple(provider_config.get("tags")), f"shadowfleet-xboard-{registered_node_result.xboard_node_id}"))),
            )
        )
        if launch_result.ipv4_address is None and launch_result.ipv6_address is None:
            raise ProvisionerServiceError("Kamatera server has no public IP address")

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

        dependencies.ready_callback_service.wait_for_ready_callback(require_task_id(request))
        online_result = dependencies.node_registry.mark_node_online(
            xboard_node_id=registered_node_result.xboard_node_id,
            host=(
                effective_domain_name
                or launch_result.ipv6_address
                or launch_result.ipv4_address
                or request.node_name
            ),
            aws_account_id=selection_result.aws_account_id,
            aws_region=selection_result.region,
            aws_instance_id=launch_result.instance_id,
            instance_type=cpu,
            cloudflare_record_id=(
                dns_sync_result.primary_record_id if dns_sync_result is not None else None
            ),
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
                message="Kamatera provisioning completed successfully.",
                payload={
                    "xboard_node_id": online_result.xboard_node_id,
                    "server_id": launch_result.instance_id,
                    "server_name": launch_result.name,
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
            cloudflare_record_id=(
                dns_sync_result.primary_record_id if dns_sync_result is not None else None
            ),
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
            cloudflare_record_id=(
                dns_sync_result.primary_record_id if dns_sync_result is not None else None
            ),
            cloudflare_a_record_id=(
                dns_sync_result.a_record_id if dns_sync_result is not None else None
            ),
            cloudflare_aaaa_record_id=(
                dns_sync_result.aaaa_record_id if dns_sync_result is not None else None
            ),
        )
    except Exception as exc:
        _handle_kamatera_provision_failure(
            dependencies=dependencies,
            asset_repo=asset_repo,
            request=request,
            selection_result=selection_result,
            registered_node_result=registered_node_result,
            dns_sync_result=dns_sync_result,
            launch_result=launch_result,
            client=client,
            server_name=server_name,
            error=exc,
        )
        raise


def _handle_kamatera_provision_failure(
    *,
    dependencies: ProvisioningDependencies,
    asset_repo: AssetRepo,
    request: ProvisionRequest,
    selection_result,
    registered_node_result,
    dns_sync_result: DnsSyncResult | None,
    launch_result: KamateraServerLaunchResult | None,
    client: KamateraClient | None,
    server_name: str | None,
    error: BaseException,
) -> None:
    runtime_context = dependencies.runtime_context
    skip_rollback = runtime_context.config.app.skip_rollback_on_failure
    set_event_type("provisioning_failed")
    dependencies.logger.exception(
        "Kamatera provisioning failed for node=%s asset_id=%s skip_rollback=%s",
        request.node_name,
        selection_result.asset_id,
        skip_rollback,
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
                "server_id": getattr(launch_result, "instance_id", None),
                "server_name": server_name,
                "xboard_node_id": getattr(registered_node_result, "xboard_node_id", None),
            },
        )
    )
    if not skip_rollback:
        if dns_sync_result is not None:
            try:
                rollback_dns_records(runtime_context, dns_sync_result)
            except Exception:
                dependencies.logger.exception("Failed to rollback DNS for Kamatera provisioning")
        if client is not None and (launch_result is not None or client.created_server_id or server_name):
            try:
                client.delete_server(
                    getattr(launch_result, "instance_id", None) or client.created_server_id,
                    name=server_name,
                )
            except Exception:
                dependencies.logger.exception("Failed to delete Kamatera server during rollback")
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


def _server_name(node_name: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9()_-]+", "-", node_name.strip()).strip("-")
    if not normalized:
        normalized = "node"
    return f"sf-{normalized[:25]}-{uuid4().hex[:8]}"[:40]


def _positive_int(value: object, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _positive_int_tuple(value: object, default: tuple[int, ...]) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)):
        return default
    values: list[int] = []
    for item in value:
        try:
            parsed = int(item)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            values.append(parsed)
    return tuple(values[:4]) or default


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
