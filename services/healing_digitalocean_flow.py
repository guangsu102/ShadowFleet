from __future__ import annotations

import socket
import time
from uuid import uuid4

from database.asset_models import AssetRecord
from database.asset_repo import AssetRepo
from database.state_repo import FleetNodeEventCreateRequest, FleetNodeRecord, StateRepo
from database.xboard_repo import XboardRepo
from infrastructure.cloudflare.cf_client import CFClient
from infrastructure.digitalocean import (
    DigitalOceanClient,
    DigitalOceanDropletLaunchRequest,
    DigitalOceanDropletLaunchResult,
)
from services.healing_models import HealRequest, HealResult, HealerServiceError
from services.healing_notifier import notify_healing_success
from services.healing_support import get_duration_ms
from services.runtime_service import RuntimeContext
from utils.logger import set_event_type


def heal_digitalocean_node(
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
        raise HealerServiceError("DigitalOcean node Droplet ID is required")
    if not node_record.domain_name:
        raise HealerServiceError("DigitalOcean node domain_name is required for healing")
    if not runtime_context.config.cloudflare.enabled:
        raise HealerServiceError("Cloudflare must be enabled for DigitalOcean healing")

    asset = _resolve_digitalocean_asset(asset_repo=asset_repo, node_record=node_record)
    if not asset.aws_access_key:
        raise HealerServiceError("DigitalOcean asset token is missing")

    client = DigitalOceanClient(runtime_context, api_token=asset.aws_access_key)
    cf_client = CFClient(runtime_context)
    source = client.get_droplet(node_record.aws_instance_id)
    xboard_runtime = xboard_repo.get_node_runtime(node_record.xboard_node_id)
    source_region = _source_region(source, node_record.aws_region or asset.region)
    source_size = _required_text(source.get("size_slug"), "size_slug")
    source_vpc_uuid = _optional_text(source.get("vpc_uuid")) or node_record.aws_subnet_id
    old_ipv4_address = node_record.ipv4_address or _public_address(source, "v4")
    old_ipv6_address = node_record.ipv6_address or _public_address(source, "v6")

    snapshot: dict[str, object] | None = None
    replacement: DigitalOceanDropletLaunchResult | None = None
    a_record_changed = False
    aaaa_record_changed = False
    state_committed = False
    try:
        snapshot = client.create_droplet_snapshot(
            node_record.aws_instance_id,
            _snapshot_name(node_record.node_name),
        )
        snapshot_id = _required_text(snapshot.get("id"), "snapshot ID")
        replacement = client.launch_droplet(
            DigitalOceanDropletLaunchRequest(
                name=_replacement_name(node_record.node_name),
                region=source_region,
                size=source_size,
                image=snapshot_id,
                user_data="",
                vpc_uuid=source_vpc_uuid,
                tags=_shadowfleet_tags(source.get("tags")),
            )
        )
        new_ipv6_address = _first_text(replacement.ipv6_addresses)
        if new_ipv6_address is None:
            raise HealerServiceError(
                "DigitalOcean replacement Droplet has no public IPv6 address"
            )
        _wait_for_tcp_endpoint(
            new_ipv6_address,
            xboard_runtime.server_port,
            timeout_seconds=300,
            poll_interval_seconds=5.0,
        )

        if replacement.ipv4_address:
            cf_client.sync_a_record(
                record_name=node_record.domain_name,
                ipv4_address=replacement.ipv4_address,
                proxied=False,
            )
            a_record_changed = True
        cloudflare_record_id = cf_client.sync_aaaa_record(
            record_name=node_record.domain_name,
            ipv6_address=new_ipv6_address,
            proxied=False,
        )
        aaaa_record_changed = True

        state_repo.update_node_runtime_metadata(
            xboard_node_id=node_record.xboard_node_id,
            aws_instance_id=replacement.instance_id,
            aws_subnet_id=source_vpc_uuid,
            aws_security_group_id=node_record.aws_security_group_id,
            instance_type=replacement.size,
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
            _delete_droplet_best_effort(
                client,
                node_record.aws_instance_id,
                runtime_context,
                "old",
            )
        else:
            if aaaa_record_changed and old_ipv6_address:
                _restore_aaaa_best_effort(
                    cf_client,
                    node_record.domain_name,
                    old_ipv6_address,
                    runtime_context,
                )
            if a_record_changed and old_ipv4_address:
                _restore_a_best_effort(
                    cf_client,
                    node_record.domain_name,
                    old_ipv4_address,
                    runtime_context,
                )
            replacement_id = (
                replacement.instance_id
                if replacement is not None
                else str(client.created_droplet_id or "")
            )
            if replacement_id:
                _delete_droplet_best_effort(
                    client,
                    replacement_id,
                    runtime_context,
                    "replacement",
                )
        raise
    finally:
        if snapshot is not None and snapshot.get("id") is not None:
            _delete_snapshot_best_effort(
                client,
                str(snapshot["id"]),
                runtime_context,
            )

    _delete_droplet_best_effort(
        client,
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
            message="DigitalOcean instance replacement healing completed.",
            payload={
                "strategy": "digitalocean_instance_replace",
                "reason": request.reason,
                "source": request.source,
                "old_instance_id": node_record.aws_instance_id,
                "new_instance_id": replacement.instance_id,
                "old_ipv4_address": old_ipv4_address,
                "new_ipv4_address": replacement.ipv4_address,
                "old_ipv6_address": old_ipv6_address,
                "new_ipv6_address": replacement.ipv6_addresses[0],
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
        asset_type="digitalocean",
        strategy="digitalocean_instance_replace",
        success=True,
        old_ipv6_address=old_ipv6_address,
        new_ipv6_address=replacement.ipv6_addresses[0],
        domain_name=node_record.domain_name,
        cloudflare_record_id=cloudflare_record_id,
        proxied_enabled=False,
        duration_ms=duration_ms,
        message="DigitalOcean instance replacement completed.",
        correlation_id=runtime_context.correlation_id,
    )
    notify_healing_success(runtime_context, result)
    return result


def _resolve_digitalocean_asset(
    *,
    asset_repo: AssetRepo,
    node_record: FleetNodeRecord,
) -> AssetRecord:
    allocated_asset = asset_repo.get_asset_by_xboard_node_id(
        node_record.xboard_node_id
    )
    if allocated_asset is not None:
        if allocated_asset.asset_type != "digitalocean":
            raise HealerServiceError(
                "DigitalOcean node allocation points to a non-DigitalOcean asset"
            )
        return allocated_asset
    if node_record.aws_account_id:
        for asset in asset_repo.list_assets_by_aws_account_id(
            node_record.aws_account_id
        ):
            if asset.asset_type == "digitalocean":
                return asset
    raise HealerServiceError(
        "DigitalOcean asset not found for "
        f"xboard_node_id={node_record.xboard_node_id}"
    )


def _source_region(source: dict[str, object], fallback: str | None) -> str:
    region = source.get("region")
    if isinstance(region, dict):
        value = _optional_text(region.get("slug"))
        if value:
            return value
    return _required_text(region or fallback, "region")


def _public_address(source: dict[str, object], family: str) -> str | None:
    networks = source.get("networks")
    if not isinstance(networks, dict):
        return None
    entries = networks.get(family)
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if isinstance(entry, dict) and entry.get("type") == "public":
            value = _optional_text(entry.get("ip_address"))
            if value:
                return value
    return None


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
    message = (
        f"Timed out waiting for DigitalOcean replacement endpoint "
        f"[{address}]:{port}"
    )
    if last_error is not None:
        message = f"{message}: {last_error}"
    raise HealerServiceError(message)


def _delete_droplet_best_effort(
    client: DigitalOceanClient,
    droplet_id: str,
    runtime_context: RuntimeContext,
    role: str,
) -> None:
    try:
        client.delete_droplet(droplet_id)
    except Exception:
        runtime_context.logger.exception(
            "Failed to delete %s DigitalOcean Droplet id=%s",
            role,
            droplet_id,
        )


def _delete_snapshot_best_effort(
    client: DigitalOceanClient,
    snapshot_id: str,
    runtime_context: RuntimeContext,
) -> None:
    try:
        client.delete_snapshot(snapshot_id)
    except Exception:
        runtime_context.logger.exception(
            "Failed to delete DigitalOcean healing snapshot id=%s",
            snapshot_id,
        )


def _restore_a_best_effort(
    client: CFClient,
    domain_name: str,
    address: str,
    runtime_context: RuntimeContext,
) -> None:
    try:
        client.sync_a_record(
            record_name=domain_name,
            ipv4_address=address,
            proxied=False,
        )
    except Exception:
        runtime_context.logger.exception(
            "Failed to restore DigitalOcean A record during healing rollback"
        )


def _restore_aaaa_best_effort(
    client: CFClient,
    domain_name: str,
    address: str,
    runtime_context: RuntimeContext,
) -> None:
    try:
        client.sync_aaaa_record(
            record_name=domain_name,
            ipv6_address=address,
            proxied=False,
        )
    except Exception:
        runtime_context.logger.exception(
            "Failed to restore DigitalOcean AAAA record during healing rollback"
        )


def _replacement_name(node_name: str) -> str:
    return f"{node_name[:44]}-heal-{uuid4().hex[:8]}"


def _snapshot_name(node_name: str) -> str:
    return f"shadowfleet-heal-{node_name[:32]}-{uuid4().hex[:8]}"


def _shadowfleet_tags(value: object) -> tuple[str, ...]:
    raw_tags = value if isinstance(value, list) else []
    tags = tuple(str(tag).strip() for tag in raw_tags if str(tag).strip())
    return tuple(dict.fromkeys(("shadowfleet", *tags)))


def _first_text(values: tuple[str, ...]) -> str | None:
    for value in values:
        text = value.strip()
        if text:
            return text
    return None


def _required_text(value: object, field_name: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise HealerServiceError(
            f"DigitalOcean source Droplet is missing {field_name}"
        )
    return text


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
