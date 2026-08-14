from __future__ import annotations

import ipaddress
import re
import socket
import time
from uuid import uuid4

from database.asset_models import AssetRecord
from database.asset_repo import AssetRepo
from database.state_repo import FleetNodeEventCreateRequest, FleetNodeRecord, StateRepo
from database.xboard_repo import XboardRepo
from infrastructure.cloudflare.cf_client import CFClient
from infrastructure.kamatera import (
    KamateraClient,
    KamateraServerCloneRequest,
    KamateraServerLaunchResult,
    server_tags,
)
from services.healing_models import HealRequest, HealResult, HealerServiceError
from services.healing_notifier import notify_healing_success
from services.healing_support import get_duration_ms
from services.runtime_service import RuntimeContext
from utils.logger import set_event_type


def heal_kamatera_node(
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
        raise HealerServiceError("Kamatera node server ID is required")
    if not node_record.domain_name:
        raise HealerServiceError("Kamatera node domain_name is required for healing")
    if not runtime_context.config.cloudflare.enabled:
        raise HealerServiceError("Cloudflare must be enabled for Kamatera healing")

    asset = _resolve_kamatera_asset(asset_repo=asset_repo, node_record=node_record)
    if not asset.aws_access_key or not asset.aws_secret_key:
        raise HealerServiceError("Kamatera asset credentials are missing")
    client = KamateraClient(
        runtime_context,
        client_id=asset.aws_access_key,
        secret=asset.aws_secret_key,
    )
    source = client.get_server(node_record.aws_instance_id)
    provider_config = asset.provider_config or {}
    source_tags = server_tags(source) or client.list_server_tags(node_record.aws_instance_id)
    xboard_runtime = xboard_repo.get_node_runtime(node_record.xboard_node_id)
    old_ipv4, old_ipv6 = _node_addresses(node_record, source)
    cf_client = CFClient(runtime_context)
    old_a_record = cf_client.get_dns_record(node_record.domain_name, "A")
    old_aaaa_record = cf_client.get_dns_record(node_record.domain_name, "AAAA")

    replacement: KamateraServerLaunchResult | None = None
    dns_changed = False
    state_committed = False
    try:
        replacement = client.clone_server(
            KamateraServerCloneRequest(
                source_id=node_record.aws_instance_id,
                name=_replacement_name(node_record.node_name),
                ssh_public_key=_optional_text(provider_config.get("ssh_public_key")) or "",
                tags=tuple(dict.fromkeys(("shadowfleet", *source_tags))),
            )
        )
        endpoint = replacement.ipv6_address or replacement.ipv4_address
        if endpoint is None:
            raise HealerServiceError("Kamatera replacement server has no public IP address")
        _wait_for_tcp_endpoint(
            endpoint,
            xboard_runtime.server_port,
            timeout_seconds=300,
            poll_interval_seconds=5.0,
        )

        # Restoring both snapshots is safe even if the first DNS write fails,
        # and covers partial A/AAAA updates when the second write raises.
        dns_changed = True
        a_record_id = _sync_or_remove_record(
            cf_client,
            node_record.domain_name,
            "A",
            replacement.ipv4_address,
        )
        aaaa_record_id = _sync_or_remove_record(
            cf_client,
            node_record.domain_name,
            "AAAA",
            replacement.ipv6_address,
        )
        cloudflare_record_id = aaaa_record_id or a_record_id

        state_repo.update_node_runtime_metadata(
            xboard_node_id=node_record.xboard_node_id,
            aws_instance_id=replacement.instance_id,
            aws_subnet_id=None,
            aws_security_group_id=None,
            instance_type=replacement.cpu or asset.default_instance_type,
            cloudflare_record_id=cloudflare_record_id,
            domain_name=node_record.domain_name,
            ipv4_address=replacement.ipv4_address,
            ipv6_address=replacement.ipv6_address,
            last_known_host=node_record.domain_name,
        )
        state_committed = True
        xboard_repo.update_node_host(node_record.xboard_node_id, node_record.domain_name)
        xboard_repo.mark_node_online(node_record.xboard_node_id)
        state_repo.update_node_status(
            xboard_node_id=node_record.xboard_node_id,
            status="online",
            status_reason=None,
            last_error=None,
        )
    except Exception:
        if state_committed:
            _delete_server_best_effort(
                client,
                node_record.aws_instance_id,
                runtime_context,
                "old",
            )
        else:
            if dns_changed:
                _restore_dns_best_effort(
                    cf_client,
                    node_record.domain_name,
                    old_a_record,
                    old_aaaa_record,
                    runtime_context,
                )
            replacement_id = (
                replacement.instance_id
                if replacement is not None
                else client.created_server_id
            )
            if replacement_id or client.created_server_name:
                try:
                    client.delete_server(
                        replacement_id,
                        name=client.created_server_name,
                    )
                except Exception:
                    runtime_context.logger.exception(
                        "Failed to delete replacement Kamatera server during healing rollback"
                    )
        raise

    _delete_server_best_effort(
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
            message="Kamatera clone replacement healing completed.",
            payload={
                "strategy": "kamatera_instance_replace",
                "reason": request.reason,
                "source": request.source,
                "old_instance_id": node_record.aws_instance_id,
                "new_instance_id": replacement.instance_id,
                "old_ipv4_address": old_ipv4,
                "new_ipv4_address": replacement.ipv4_address,
                "old_ipv6_address": old_ipv6,
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
        asset_type="kamatera",
        strategy="kamatera_instance_replace",
        success=True,
        old_ipv6_address=old_ipv6,
        new_ipv6_address=replacement.ipv6_address,
        domain_name=node_record.domain_name,
        cloudflare_record_id=cloudflare_record_id,
        proxied_enabled=False,
        duration_ms=duration_ms,
        message="Kamatera clone replacement completed.",
        correlation_id=runtime_context.correlation_id,
    )
    notify_healing_success(runtime_context, result)
    return result


def _resolve_kamatera_asset(
    *,
    asset_repo: AssetRepo,
    node_record: FleetNodeRecord,
) -> AssetRecord:
    allocated_asset = asset_repo.get_asset_by_xboard_node_id(node_record.xboard_node_id)
    if allocated_asset is not None:
        if allocated_asset.asset_type != "kamatera":
            raise HealerServiceError(
                "Kamatera node allocation points to a non-Kamatera asset"
            )
        return allocated_asset
    if node_record.aws_account_id:
        for asset in asset_repo.list_assets_by_aws_account_id(node_record.aws_account_id):
            if asset.asset_type == "kamatera":
                return asset
    raise HealerServiceError(
        f"Kamatera asset not found for xboard_node_id={node_record.xboard_node_id}"
    )


def _node_addresses(
    node_record: FleetNodeRecord,
    source: dict[str, object],
) -> tuple[str | None, str | None]:
    ipv4 = node_record.ipv4_address
    ipv6 = node_record.ipv6_address
    networks = source.get("networks")
    if not isinstance(networks, list):
        return ipv4, ipv6
    for network in networks:
        if not isinstance(network, dict):
            continue
        name = str(network.get("network") or network.get("name") or "").lower()
        if name and not (name == "wan" or name.startswith("wan-")):
            continue
        ips = network.get("ips")
        if not isinstance(ips, list):
            continue
        for raw in ips:
            value = raw.get("ip") if isinstance(raw, dict) else raw
            text = str(value or "").split("/")[0].strip()
            try:
                address = ipaddress.ip_address(text)
            except ValueError:
                continue
            if address.version == 4 and ipv4 is None:
                ipv4 = str(address)
            elif address.version == 6 and ipv6 is None:
                ipv6 = str(address)
    return ipv4, ipv6


def _sync_or_remove_record(
    client: CFClient,
    domain_name: str,
    record_type: str,
    address: str | None,
) -> str | None:
    if address:
        if record_type == "A":
            return client.sync_a_record(domain_name, address, proxied=False)
        return client.sync_aaaa_record(domain_name, address, proxied=False)
    existing = client.get_dns_record(domain_name, record_type)
    if existing is not None and existing.get("id"):
        client.delete_dns_record(str(existing["id"]))
    return None


def _restore_dns_best_effort(
    client: CFClient,
    domain_name: str,
    old_a_record: dict[str, object] | None,
    old_aaaa_record: dict[str, object] | None,
    runtime_context: RuntimeContext,
) -> None:
    try:
        _restore_record(client, domain_name, "A", old_a_record)
        _restore_record(client, domain_name, "AAAA", old_aaaa_record)
    except Exception:
        runtime_context.logger.exception(
            "Failed to restore Kamatera DNS records during healing rollback"
        )


def _restore_record(
    client: CFClient,
    domain_name: str,
    record_type: str,
    snapshot: dict[str, object] | None,
) -> None:
    if snapshot is not None and snapshot.get("content"):
        address = str(snapshot["content"])
        proxied = bool(snapshot.get("proxied", False))
        if record_type == "A":
            client.sync_a_record(domain_name, address, proxied=proxied)
        else:
            client.sync_aaaa_record(domain_name, address, proxied=proxied)
        return
    current = client.get_dns_record(domain_name, record_type)
    if current is not None and current.get("id"):
        client.delete_dns_record(str(current["id"]))


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
    message = f"Timed out waiting for Kamatera replacement endpoint {address}:{port}"
    if last_error is not None:
        message = f"{message}: {last_error}"
    raise HealerServiceError(message)


def _delete_server_best_effort(
    client: KamateraClient,
    server_id: str,
    runtime_context: RuntimeContext,
    role: str,
) -> None:
    try:
        client.delete_server(server_id)
    except Exception:
        runtime_context.logger.exception(
            "Failed to delete %s Kamatera server id=%s",
            role,
            server_id,
        )


def _replacement_name(node_name: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9()_-]+", "-", node_name)
    normalized = normalized.strip("-") or "node"
    return f"sf-{normalized[:24]}-heal-{uuid4().hex[:8]}"[:40]


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
