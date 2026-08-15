from __future__ import annotations

import socket
import time

from database.asset_models import AssetRecord
from database.asset_repo import AssetRepo
from database.state_repo import FleetNodeEventCreateRequest, FleetNodeRecord, StateRepo
from database.xboard_repo import XboardRepo
from infrastructure.cloudflare.cf_client import CFClient
from infrastructure.gcp import GCPClient, GCPCredentials
from services.healing_models import HealRequest, HealResult, HealerServiceError
from services.healing_notifier import notify_healing_success
from services.healing_support import get_duration_ms
from services.runtime_service import RuntimeContext
from utils.logger import set_event_type


def heal_gcp_node(
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
        raise HealerServiceError("GCP node instance name is required")
    if not node_record.aws_region:
        raise HealerServiceError("GCP node zone is required")
    if not node_record.domain_name:
        raise HealerServiceError("GCP node domain_name is required for healing")
    if not runtime_context.config.cloudflare.enabled:
        raise HealerServiceError("Cloudflare must be enabled for GCP healing")

    asset = _resolve_gcp_asset(asset_repo=asset_repo, node_record=node_record)
    client = _build_gcp_client(runtime_context, asset)
    old_ipv4 = node_record.ipv4_address
    xboard_runtime = xboard_repo.get_node_runtime(node_record.xboard_node_id)
    new_ipv4 = client.rotate_external_ipv4(
        node_record.aws_region,
        node_record.aws_instance_id,
    )
    _wait_for_tcp_endpoint(
        new_ipv4,
        xboard_runtime.server_port,
        timeout_seconds=300,
        poll_interval_seconds=5.0,
    )
    cloudflare_record_id = CFClient(runtime_context).sync_a_record(
        record_name=node_record.domain_name,
        ipv4_address=new_ipv4,
        proxied=False,
    )
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
        ipv4_address=new_ipv4,
        ipv6_address=node_record.ipv6_address,
        last_known_host=node_record.domain_name,
    )
    state_repo.update_node_status(
        xboard_node_id=node_record.xboard_node_id,
        status="online",
        status_reason=None,
        last_error=None,
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
            message="GCP native external IPv4 rotation completed.",
            payload={
                "strategy": "gcp_ipv4_rotate",
                "reason": request.reason,
                "source": request.source,
                "instance_name": node_record.aws_instance_id,
                "zone": node_record.aws_region,
                "old_ipv4_address": old_ipv4,
                "new_ipv4_address": new_ipv4,
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
        asset_type="gcp",
        strategy="gcp_ipv4_rotate",
        success=True,
        old_ipv6_address=node_record.ipv6_address,
        new_ipv6_address=node_record.ipv6_address,
        domain_name=node_record.domain_name,
        cloudflare_record_id=cloudflare_record_id,
        proxied_enabled=False,
        duration_ms=duration_ms,
        message="GCP 公网 IPv4 更换完成",
        correlation_id=runtime_context.correlation_id,
        old_ipv4_address=old_ipv4,
        new_ipv4_address=new_ipv4,
    )
    notify_healing_success(runtime_context, result)
    return result


def _resolve_gcp_asset(
    *,
    asset_repo: AssetRepo,
    node_record: FleetNodeRecord,
) -> AssetRecord:
    allocated = asset_repo.get_asset_by_xboard_node_id(node_record.xboard_node_id)
    if allocated is not None:
        if allocated.asset_type != "gcp":
            raise HealerServiceError("GCP node allocation points to a non-GCP asset")
        return allocated
    if node_record.aws_account_id:
        for asset in asset_repo.list_assets_by_aws_account_id(
            node_record.aws_account_id
        ):
            if asset.asset_type == "gcp":
                return asset
    raise HealerServiceError(
        f"GCP asset not found for xboard_node_id={node_record.xboard_node_id}"
    )


def _build_gcp_client(
    runtime_context: RuntimeContext,
    asset: AssetRecord,
) -> GCPClient:
    config = asset.provider_config or {}
    return GCPClient(
        runtime_context,
        credentials=GCPCredentials(
            project_id=_required_config(config, "project_id"),
            client_email=_required_text(asset.aws_access_key, "client_email"),
            private_key=_required_text(asset.aws_secret_key, "private_key"),
            private_key_id=_optional_text(config.get("private_key_id")),
            client_id=_optional_text(config.get("client_id")),
            token_uri=_optional_text(config.get("token_uri"))
            or "https://oauth2.googleapis.com/token",
        ),
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
    message = f"Timed out waiting for GCP IPv4 endpoint {address}:{port}"
    if last_error is not None:
        message = f"{message}: {last_error}"
    raise HealerServiceError(message)


def _required_config(config: dict[str, object], name: str) -> str:
    value = _optional_text(config.get(name))
    if value is None:
        raise HealerServiceError(f"GCP provider config is missing {name}")
    return value


def _required_text(value: object, field_name: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise HealerServiceError(f"GCP node is missing {field_name}")
    return text


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
