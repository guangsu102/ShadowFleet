from __future__ import annotations

import socket
import time
from uuid import uuid4

from database.asset_models import AssetRecord
from database.asset_repo import AssetRepo
from database.state_repo import FleetNodeEventCreateRequest, FleetNodeRecord, StateRepo
from database.xboard_repo import XboardRepo
from infrastructure.cloudflare.cf_client import CFClient
from infrastructure.oci import OCIClient, OCICredentials
from services.healing_models import HealRequest, HealResult, HealerServiceError
from services.healing_notifier import notify_healing_success
from services.healing_support import get_duration_ms
from services.runtime_service import RuntimeContext
from utils.logger import set_event_type


def heal_oci_node(
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
        raise HealerServiceError("OCI node instance ID is required")
    if not node_record.domain_name:
        raise HealerServiceError("OCI node domain_name is required for healing")
    if not runtime_context.config.cloudflare.enabled:
        raise HealerServiceError("Cloudflare must be enabled for OCI healing")

    asset = _resolve_oci_asset(asset_repo=asset_repo, node_record=node_record)
    config = asset.provider_config or {}
    client = _build_oci_client(runtime_context, asset)
    compartment_ocid = _required_config(config, "compartment_ocid")
    vnic = client.get_primary_vnic(compartment_ocid, node_record.aws_instance_id)
    vnic_id = _required_text(vnic.get("id"), "VNIC ID")
    ipv6_resources = client.list_ipv6_addresses(compartment_ocid, vnic_id)
    old_ipv6 = _find_ipv6_resource(ipv6_resources, node_record.ipv6_address)
    old_ipv6_address = (
        node_record.ipv6_address
        or (_optional_text(old_ipv6.get("ipAddress")) if old_ipv6 else None)
    )
    xboard_runtime = xboard_repo.get_node_runtime(node_record.xboard_node_id)
    cf_client = CFClient(runtime_context)

    replacement: dict[str, object] | None = None
    replacement_ocid: str | None = None
    replacement_address: str | None = None
    dns_changed = False
    state_committed = False
    try:
        replacement = client.create_ipv6_address(
            vnic_id,
            display_name=f"{node_record.node_name[:40]}-heal-{uuid4().hex[:8]}",
        )
        replacement_ocid = _required_text(replacement.get("id"), "replacement IPv6 OCID")
        replacement_address = _required_text(
            replacement.get("ipAddress"),
            "replacement IPv6 address",
        )
        _wait_for_tcp_endpoint(
            replacement_address,
            xboard_runtime.server_port,
            timeout_seconds=300,
            poll_interval_seconds=5.0,
        )
        cloudflare_record_id = cf_client.sync_aaaa_record(
            record_name=node_record.domain_name,
            ipv6_address=replacement_address,
            proxied=False,
        )
        dns_changed = True
        xboard_repo.update_node_host(
            node_record.xboard_node_id,
            node_record.domain_name,
        )
        xboard_repo.mark_node_online(node_record.xboard_node_id)
        state_repo.update_node_runtime_metadata(
            xboard_node_id=node_record.xboard_node_id,
            aws_instance_id=node_record.aws_instance_id,
            aws_subnet_id=node_record.aws_subnet_id,
            aws_security_group_id=node_record.aws_security_group_id,
            cloudflare_record_id=cloudflare_record_id,
            domain_name=node_record.domain_name,
            ipv4_address=node_record.ipv4_address,
            ipv6_address=replacement_address,
            last_known_host=node_record.domain_name,
        )
        state_repo.update_node_status(
            xboard_node_id=node_record.xboard_node_id,
            status="online",
            status_reason=None,
            last_error=None,
        )
        state_committed = True
    except Exception:
        if not state_committed:
            if dns_changed and old_ipv6_address:
                try:
                    cf_client.sync_aaaa_record(
                        record_name=node_record.domain_name,
                        ipv6_address=old_ipv6_address,
                        proxied=False,
                    )
                except Exception:
                    runtime_context.logger.exception(
                        "Failed to restore OCI AAAA record during healing rollback"
                    )
            if replacement_ocid:
                _delete_ipv6_best_effort(client, replacement_ocid, runtime_context, "replacement")
        raise

    old_ipv6_ocid = _optional_text(old_ipv6.get("id")) if old_ipv6 else None
    if old_ipv6_ocid and old_ipv6_ocid != replacement_ocid:
        _delete_ipv6_best_effort(client, old_ipv6_ocid, runtime_context, "old")

    duration_ms = get_duration_ms(started_monotonic)
    state_repo.create_event(
        FleetNodeEventCreateRequest(
            node_id=node_record.id,
            xboard_node_id=node_record.xboard_node_id,
            event_type="healing_completed",
            correlation_id=runtime_context.correlation_id,
            from_status="healing",
            to_status="online",
            message="OCI native IPv6 rotation completed.",
            payload={
                "strategy": "oci_ipv6_rotate",
                "reason": request.reason,
                "source": request.source,
                "instance_id": node_record.aws_instance_id,
                "vnic_id": vnic_id,
                "old_ipv6_ocid": old_ipv6_ocid,
                "new_ipv6_ocid": replacement_ocid,
                "old_ipv6_address": old_ipv6_address,
                "new_ipv6_address": replacement_address,
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
        asset_type="oci",
        strategy="oci_ipv6_rotate",
        success=True,
        old_ipv6_address=old_ipv6_address,
        new_ipv6_address=replacement_address,
        domain_name=node_record.domain_name,
        cloudflare_record_id=cloudflare_record_id,
        proxied_enabled=False,
        duration_ms=duration_ms,
        message="OCI IPv6 地址更换完成",
        correlation_id=runtime_context.correlation_id,
    )
    notify_healing_success(runtime_context, result)
    return result


def _resolve_oci_asset(
    *,
    asset_repo: AssetRepo,
    node_record: FleetNodeRecord,
) -> AssetRecord:
    allocated = asset_repo.get_asset_by_xboard_node_id(node_record.xboard_node_id)
    if allocated is not None:
        if allocated.asset_type != "oci":
            raise HealerServiceError("OCI node allocation points to a non-OCI asset")
        return allocated
    if node_record.aws_account_id:
        for asset in asset_repo.list_assets_by_aws_account_id(node_record.aws_account_id):
            if asset.asset_type == "oci":
                return asset
    raise HealerServiceError(
        f"OCI asset not found for xboard_node_id={node_record.xboard_node_id}"
    )


def _build_oci_client(runtime_context: RuntimeContext, asset: AssetRecord) -> OCIClient:
    config = asset.provider_config or {}
    return OCIClient(
        runtime_context,
        credentials=OCICredentials(
            tenancy_ocid=_required_config(config, "tenancy_ocid"),
            user_ocid=_required_text(asset.aws_access_key, "user_ocid"),
            fingerprint=_required_config(config, "fingerprint"),
            private_key=_required_text(asset.aws_secret_key, "private_key"),
            private_key_passphrase=_optional_text(config.get("private_key_passphrase")),
        ),
        region=_required_text(asset.region, "region"),
    )


def _find_ipv6_resource(
    resources: list[dict[str, object]],
    expected_address: str | None,
) -> dict[str, object] | None:
    if expected_address:
        for resource in resources:
            if _optional_text(resource.get("ipAddress")) == expected_address:
                return resource
    for resource in resources:
        if str(resource.get("lifecycleState") or "AVAILABLE").upper() == "AVAILABLE":
            return resource
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
    message = f"Timed out waiting for OCI IPv6 endpoint [{address}]:{port}"
    if last_error is not None:
        message = f"{message}: {last_error}"
    raise HealerServiceError(message)


def _delete_ipv6_best_effort(
    client: OCIClient,
    ipv6_ocid: str,
    runtime_context: RuntimeContext,
    role: str,
) -> None:
    try:
        client.delete_ipv6_address(ipv6_ocid)
    except Exception:
        runtime_context.logger.exception(
            "Failed to delete %s OCI IPv6 resource id=%s",
            role,
            ipv6_ocid,
        )


def _required_config(config: dict[str, object], name: str) -> str:
    value = _optional_text(config.get(name))
    if value is None:
        raise HealerServiceError(f"OCI provider config is missing {name}")
    return value


def _required_text(value: object, field_name: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise HealerServiceError(f"OCI node is missing {field_name}")
    return text


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
