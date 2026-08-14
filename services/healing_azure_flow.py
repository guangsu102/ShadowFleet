from __future__ import annotations

from database.asset_models import AssetRecord
from database.asset_repo import AssetRepo
from database.state_repo import FleetNodeEventCreateRequest, FleetNodeRecord, StateRepo
from database.xboard_repo import XboardRepo
from infrastructure.azure import AzureClient, AzureCredentials
from infrastructure.cloudflare.cf_client import CFClient
from services.healing_models import HealRequest, HealResult, HealerServiceError
from services.healing_notifier import notify_healing_success
from services.healing_support import get_duration_ms
from services.runtime_service import RuntimeContext
from utils.logger import set_event_type


def _resolve_azure_asset(
    *,
    asset_repo: AssetRepo,
    node_record: FleetNodeRecord,
) -> AssetRecord:
    allocated_asset = asset_repo.get_asset_by_xboard_node_id(
        node_record.xboard_node_id
    )
    if allocated_asset is not None:
        if allocated_asset.asset_type != "azure":
            raise HealerServiceError(
                "Azure node allocation points to a non-Azure asset"
            )
        return allocated_asset
    if node_record.aws_account_id:
        for asset in asset_repo.list_assets_by_aws_account_id(
            node_record.aws_account_id
        ):
            if asset.asset_type == "azure":
                return asset
    raise HealerServiceError(
        f"Azure asset not found for xboard_node_id={node_record.xboard_node_id}"
    )


def _azure_credentials(
    asset: AssetRecord,
    node_record: FleetNodeRecord,
) -> AzureCredentials:
    provider_config = asset.provider_config
    if not isinstance(provider_config, dict):
        raise HealerServiceError("Azure asset provider_config is missing")
    tenant_id = str(provider_config.get("tenant_id") or "").strip()
    account_subscription = _subscription_from_account_id(
        node_record.aws_account_id
    )
    subscription_id = (
        str(provider_config.get("subscription_id") or "").strip()
        or account_subscription
    )
    client_id = str(asset.aws_access_key or "").strip()
    client_secret = str(asset.aws_secret_key or "").strip()
    if not tenant_id or not subscription_id or not client_id or not client_secret:
        raise HealerServiceError("Azure asset credentials are incomplete")

    vm_subscription = _subscription_from_resource_id(
        node_record.aws_instance_id
    )
    for expected_subscription in (account_subscription, vm_subscription):
        if expected_subscription and (
            expected_subscription.casefold() != subscription_id.casefold()
        ):
            raise HealerServiceError(
                "Azure node subscription does not match its allocated asset"
            )
    return AzureCredentials(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
        subscription_id=subscription_id,
    )


def _subscription_from_account_id(account_id: str | None) -> str | None:
    value = str(account_id or "").strip()
    if not value.casefold().startswith("azure:"):
        return None
    return value.split(":", 1)[1].strip() or None


def _subscription_from_resource_id(resource_id: str | None) -> str | None:
    parts = [part for part in str(resource_id or "").strip("/").split("/") if part]
    if len(parts) >= 2 and parts[0].casefold() == "subscriptions":
        return parts[1]
    return None


def heal_azure_node(
    *,
    runtime_context: RuntimeContext,
    asset_repo: AssetRepo,
    state_repo: StateRepo,
    xboard_repo: XboardRepo,
    node_record: FleetNodeRecord,
    request: HealRequest,
    started_monotonic: float,
) -> HealResult:
    if not node_record.aws_instance_id:
        raise HealerServiceError("Azure node VM resource ID is required")
    if not node_record.domain_name:
        raise HealerServiceError(
            "Azure node domain_name is required for IPv6 healing"
        )
    if not runtime_context.config.cloudflare.enabled:
        raise HealerServiceError(
            "Cloudflare must be enabled for Azure IPv6 healing"
        )

    # Constructing the client validates DNS credentials before ARM is mutated.
    cf_client = CFClient(runtime_context)
    asset = _resolve_azure_asset(
        asset_repo=asset_repo,
        node_record=node_record,
    )
    azure_client = AzureClient(
        runtime_context,
        credentials=_azure_credentials(asset, node_record),
    )
    old_ipv6_address, new_ipv6_address = (
        azure_client.rotate_vm_ipv6_public_ip(node_record.aws_instance_id)
    )

    # Persist the cloud-side fact before DNS. If Cloudflare fails, a retry or
    # operator still sees the address that is actually attached to the NIC.
    state_repo.update_node_runtime_metadata(
        xboard_node_id=node_record.xboard_node_id,
        ipv6_address=new_ipv6_address,
    )
    cloudflare_record_id = cf_client.sync_aaaa_record(
        record_name=node_record.domain_name,
        ipv6_address=new_ipv6_address,
        proxied=False,
    )
    return _complete_azure_healing(
        runtime_context=runtime_context,
        state_repo=state_repo,
        xboard_repo=xboard_repo,
        node_record=node_record,
        request=request,
        started_monotonic=started_monotonic,
        old_ipv6_address=old_ipv6_address,
        new_ipv6_address=new_ipv6_address,
        cloudflare_record_id=cloudflare_record_id,
    )


def _complete_azure_healing(
    *,
    runtime_context: RuntimeContext,
    state_repo: StateRepo,
    xboard_repo: XboardRepo,
    node_record: FleetNodeRecord,
    request: HealRequest,
    started_monotonic: float,
    old_ipv6_address: str,
    new_ipv6_address: str,
    cloudflare_record_id: str,
) -> HealResult:
    xboard_repo.update_node_host(
        node_record.xboard_node_id, node_record.domain_name
    )
    xboard_repo.mark_node_online(node_record.xboard_node_id)
    state_repo.update_node_runtime_metadata(
        xboard_node_id=node_record.xboard_node_id,
        cloudflare_record_id=cloudflare_record_id,
        domain_name=node_record.domain_name,
        ipv6_address=new_ipv6_address,
        last_known_host=node_record.domain_name,
    )
    state_repo.update_node_status(
        xboard_node_id=node_record.xboard_node_id,
        status="online",
        status_reason=None,
        last_error=None,
    )
    duration_ms = get_duration_ms(started_monotonic)
    _record_azure_healing_event(
        runtime_context=runtime_context,
        state_repo=state_repo,
        node_record=node_record,
        request=request,
        old_ipv6_address=old_ipv6_address,
        new_ipv6_address=new_ipv6_address,
        cloudflare_record_id=cloudflare_record_id,
        duration_ms=duration_ms,
    )
    set_event_type("healing_completed")
    result = HealResult(
        xboard_node_id=node_record.xboard_node_id,
        node_name=node_record.node_name,
        node_type=node_record.node_type,
        asset_type="azure",
        strategy="azure_ipv6_rotate",
        success=True,
        old_ipv6_address=old_ipv6_address,
        new_ipv6_address=new_ipv6_address,
        domain_name=node_record.domain_name,
        cloudflare_record_id=cloudflare_record_id,
        proxied_enabled=False,
        duration_ms=duration_ms,
        message="Azure IPv6 热切换自愈成功",
        correlation_id=runtime_context.correlation_id,
    )
    notify_healing_success(runtime_context, result)
    return result


def _record_azure_healing_event(
    *,
    runtime_context: RuntimeContext,
    state_repo: StateRepo,
    node_record: FleetNodeRecord,
    request: HealRequest,
    old_ipv6_address: str,
    new_ipv6_address: str,
    cloudflare_record_id: str,
    duration_ms: int,
) -> None:
    state_repo.create_event(
        FleetNodeEventCreateRequest(
            node_id=node_record.id,
            xboard_node_id=node_record.xboard_node_id,
            event_type="healing_completed",
            correlation_id=runtime_context.correlation_id,
            from_status="healing",
            to_status="online",
            message="Azure IPv6 Public IP rotation healing completed.",
            payload={
                "strategy": "azure_ipv6_rotate",
                "reason": request.reason,
                "source": request.source,
                "old_ipv6_address": old_ipv6_address,
                "new_ipv6_address": new_ipv6_address,
                "domain_name": node_record.domain_name,
                "cloudflare_record_id": cloudflare_record_id,
                "duration_ms": duration_ms,
                "measurement_payload": request.measurement_payload,
            },
        )
    )
