from __future__ import annotations

import socket
import time
from uuid import uuid4

from database.asset_models import AssetRecord
from database.asset_repo import AssetRepo
from database.state_repo import FleetNodeEventCreateRequest, FleetNodeRecord, StateRepo
from database.xboard_repo import XboardRepo
from infrastructure.cloudflare.cf_client import CFClient
from infrastructure.vultr import (
    VultrClient,
    VultrFirewallEnsureResult,
    VultrInstanceLaunchRequest,
    VultrInstanceLaunchResult,
)
from services.healing_models import HealRequest, HealResult, HealerServiceError
from services.healing_notifier import notify_healing_success
from services.healing_support import get_duration_ms
from services.runtime_service import RuntimeContext
from utils.logger import set_event_type


def heal_vultr_node(
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
        raise HealerServiceError("Vultr node instance ID is required")
    if not node_record.domain_name:
        raise HealerServiceError("Vultr node domain_name is required for healing")
    if not runtime_context.config.cloudflare.enabled:
        raise HealerServiceError("Cloudflare must be enabled for Vultr healing")

    asset = _resolve_vultr_asset(asset_repo=asset_repo, node_record=node_record)
    if not asset.aws_access_key:
        raise HealerServiceError("Vultr asset token is missing")
    vultr_client = VultrClient(
        runtime_context,
        api_token=asset.aws_access_key,
    )
    cf_client = CFClient(runtime_context)
    source_instance = vultr_client.get_instance(node_record.aws_instance_id)
    source_user_data = vultr_client.get_instance_user_data(node_record.aws_instance_id)
    source_vpc_ids = tuple(
        str(vpc.get("id") or "").strip()
        for vpc in vultr_client.list_instance_vpcs(node_record.aws_instance_id)
        if str(vpc.get("id") or "").strip()
    )
    xboard_runtime = xboard_repo.get_node_runtime(node_record.xboard_node_id)

    firewall_result: VultrFirewallEnsureResult | None = None
    replacement: VultrInstanceLaunchResult | None = None
    dns_changed = False
    state_committed = False
    old_ipv6_address = (
        node_record.ipv6_address
        or _optional_text(source_instance.get("v6_main_ip"))
    )
    try:
        firewall_result = vultr_client.ensure_firewall_ports(
            firewall_group_id=(
                _optional_text(source_instance.get("firewall_group_id"))
                or node_record.aws_security_group_id
            ),
            label=node_record.node_name,
            inbound_ports=tuple(dict.fromkeys((22, xboard_runtime.server_port))),
        )
        replacement = vultr_client.launch_instance(
            VultrInstanceLaunchRequest(
                label=_replacement_label(node_record.node_name),
                region=_required_text(
                    source_instance.get("region") or node_record.aws_region,
                    "region",
                ),
                plan=_required_text(source_instance.get("plan"), "plan"),
                os_id=_positive_int(source_instance.get("os_id"), "os_id"),
                user_data=source_user_data,
                vpc_ids=source_vpc_ids,
                firewall_group_id=firewall_result.firewall_group_id,
                tags=_shadowfleet_tags(source_instance.get("tags")),
            )
        )
        new_ipv6_address = _required_text(
            replacement.ipv6_address,
            "replacement IPv6 address",
        )
        _wait_for_tcp_endpoint(
            new_ipv6_address,
            xboard_runtime.server_port,
            timeout_seconds=300,
            poll_interval_seconds=5.0,
        )
        cloudflare_record_id = cf_client.sync_aaaa_record(
            record_name=node_record.domain_name,
            ipv6_address=new_ipv6_address,
            proxied=False,
        )
        dns_changed = True

        state_repo.update_node_runtime_metadata(
            xboard_node_id=node_record.xboard_node_id,
            aws_instance_id=replacement.instance_id,
            aws_subnet_id=replacement.subnet_id,
            aws_security_group_id=firewall_result.firewall_group_id,
            instance_type=replacement.plan,
            cloudflare_record_id=cloudflare_record_id,
            domain_name=node_record.domain_name,
            ipv4_address=replacement.ipv4_address,
            ipv6_address=new_ipv6_address,
            last_known_host=node_record.domain_name,
        )
        state_committed = True
        xboard_repo.update_node_host(
            node_record.xboard_node_id,
            node_record.domain_name,
        )
        xboard_repo.mark_node_online(node_record.xboard_node_id)
        state_repo.update_node_status(
            xboard_node_id=node_record.xboard_node_id,
            status="online",
            status_reason=None,
            last_error=None,
        )
    except Exception:
        if state_committed:
            _delete_instance_best_effort(
                vultr_client,
                node_record.aws_instance_id,
                runtime_context,
                "old",
            )
        else:
            if dns_changed and old_ipv6_address:
                try:
                    cf_client.sync_aaaa_record(
                        record_name=node_record.domain_name,
                        ipv6_address=old_ipv6_address,
                        proxied=False,
                    )
                except Exception:
                    runtime_context.logger.exception(
                        "Failed to restore Vultr AAAA record during healing rollback"
                    )
            if replacement is not None:
                _delete_instance_best_effort(
                    vultr_client,
                    replacement.instance_id,
                    runtime_context,
                    "replacement",
                )
            if firewall_result is not None and firewall_result.created:
                try:
                    vultr_client.delete_firewall_group(
                        firewall_result.firewall_group_id
                    )
                except Exception:
                    runtime_context.logger.exception(
                        "Failed to delete Vultr firewall during healing rollback"
                    )
        raise

    _delete_instance_best_effort(
        vultr_client,
        node_record.aws_instance_id,
        runtime_context,
        "old",
    )
    duration_ms = get_duration_ms(started_monotonic)
    state_repo.create_event(
        FleetNodeEventCreateRequest(
            node_id=node_record.id,
            xboard_node_id=node_record.xboard_node_id,
            event_type="healing_completed",
            correlation_id=runtime_context.correlation_id,
            from_status="healing",
            to_status="online",
            message="Vultr instance replacement healing completed.",
            payload={
                "strategy": "vultr_instance_replace",
                "reason": request.reason,
                "source": request.source,
                "old_instance_id": node_record.aws_instance_id,
                "new_instance_id": replacement.instance_id,
                "old_ipv6_address": old_ipv6_address,
                "new_ipv6_address": replacement.ipv6_address,
                "domain_name": node_record.domain_name,
                "cloudflare_record_id": cloudflare_record_id,
                "duration_ms": duration_ms,
                "measurement_payload": request.measurement_payload,
            },
        )
    )
    set_event_type("healing_completed")
    result = HealResult(
        xboard_node_id=node_record.xboard_node_id,
        node_name=node_record.node_name,
        node_type=node_record.node_type,
        asset_type="vultr",
        strategy="vultr_instance_replace",
        success=True,
        old_ipv6_address=old_ipv6_address,
        new_ipv6_address=replacement.ipv6_address,
        domain_name=node_record.domain_name,
        cloudflare_record_id=cloudflare_record_id,
        proxied_enabled=False,
        duration_ms=duration_ms,
        message="Vultr ????????",
        correlation_id=runtime_context.correlation_id,
    )
    notify_healing_success(runtime_context, result)
    return result


def _resolve_vultr_asset(
    *,
    asset_repo: AssetRepo,
    node_record: FleetNodeRecord,
) -> AssetRecord:
    allocated_asset = asset_repo.get_asset_by_xboard_node_id(
        node_record.xboard_node_id
    )
    if allocated_asset is not None:
        if allocated_asset.asset_type != "vultr":
            raise HealerServiceError(
                "Vultr node allocation points to a non-Vultr asset"
            )
        return allocated_asset
    if node_record.aws_account_id:
        for asset in asset_repo.list_assets_by_aws_account_id(
            node_record.aws_account_id
        ):
            if asset.asset_type == "vultr":
                return asset
    raise HealerServiceError(
        f"Vultr asset not found for xboard_node_id={node_record.xboard_node_id}"
    )


def _wait_for_tcp_endpoint(
    address: str,
    port: int,
    *,
    timeout_seconds: int,
    poll_interval_seconds: float,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((address, port), timeout=5.0):
                return
        except OSError as exc:
            last_error = exc
            time.sleep(poll_interval_seconds)
    message = f"Timed out waiting for Vultr replacement endpoint [{address}]:{port}"
    if last_error is not None:
        message = f"{message}: {last_error}"
    raise HealerServiceError(message)


def _delete_instance_best_effort(
    client: VultrClient,
    instance_id: str,
    runtime_context: RuntimeContext,
    role: str,
) -> None:
    try:
        client.delete_instance(instance_id)
    except Exception:
        runtime_context.logger.exception(
            "Failed to delete %s Vultr instance id=%s",
            role,
            instance_id,
        )


def _replacement_label(node_name: str) -> str:
    return f"{node_name[:40]}-heal-{uuid4().hex[:8]}"


def _shadowfleet_tags(value: object) -> tuple[str, ...]:
    raw_tags = value if isinstance(value, list) else []
    tags = tuple(str(tag).strip() for tag in raw_tags if str(tag).strip())
    return tuple(dict.fromkeys(("shadowfleet", *tags)))


def _required_text(value: object, field_name: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise HealerServiceError(f"Vultr source instance is missing {field_name}")
    return text


def _positive_int(value: object, field_name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise HealerServiceError(
            f"Vultr source instance has invalid {field_name}"
        ) from exc
    if parsed <= 0:
        raise HealerServiceError(
            f"Vultr source instance has invalid {field_name}"
        )
    return parsed


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
