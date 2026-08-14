from __future__ import annotations

from database.state_repo import FleetNodeEventCreateRequest, FleetNodeRecord, StateRepo
from database.xboard_repo import XboardRepo
from infrastructure.cloudflare.cf_client import CFClient
from services.healing_models import HealRequest, HealResult, HealerServiceError
from services.healing_notifier import notify_healing_success
from services.healing_support import get_duration_ms
from services.monitor_support import infer_node_asset_type
from services.runtime_service import RuntimeContext
from utils.logger import set_event_type


def heal_self_hosted_node(
    *,
    runtime_context: RuntimeContext,
    state_repo: StateRepo,
    xboard_repo: XboardRepo,
    node_record: FleetNodeRecord,
    request: HealRequest,
    started_monotonic: float,
) -> HealResult:
    if not runtime_context.config.cloudflare.enabled:
        raise HealerServiceError("Cloudflare must be enabled for proxy healing")
    if node_record.domain_name is None:
        raise HealerServiceError("Node domain_name is required for Cloudflare healing")

    cf_client = CFClient(runtime_context)
    record_ids = _enable_proxy_for_domain_records(
        cf_client=cf_client,
        domain_name=node_record.domain_name,
        preferred_record_id=node_record.cloudflare_record_id,
    )
    if not record_ids:
        raise HealerServiceError(
            f"No Cloudflare DNS record found for node domain={node_record.domain_name}"
        )

    primary_record_id = record_ids[0]
    xboard_repo.update_node_host(node_record.xboard_node_id, node_record.domain_name)
    xboard_repo.mark_node_online(node_record.xboard_node_id)
    state_repo.update_node_runtime_metadata(
        xboard_node_id=node_record.xboard_node_id,
        cloudflare_record_id=primary_record_id,
        domain_name=node_record.domain_name,
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
            message="Cloudflare proxy fallback completed.",
            payload={
                "strategy": "cloudflare_enable_proxy",
                "reason": request.reason,
                "source": request.source,
                "domain_name": node_record.domain_name,
                "cloudflare_record_ids": record_ids,
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
        asset_type=infer_node_asset_type(node_record),
        strategy="cloudflare_enable_proxy",
        success=True,
        old_ipv6_address=node_record.ipv6_address,
        new_ipv6_address=node_record.ipv6_address,
        domain_name=node_record.domain_name,
        cloudflare_record_id=primary_record_id,
        proxied_enabled=True,
        duration_ms=duration_ms,
        message="Cloudflare 代理保底成功",
        correlation_id=runtime_context.correlation_id,
    )
    notify_healing_success(runtime_context, result)
    return result


def _enable_proxy_for_domain_records(
    *,
    cf_client: CFClient,
    domain_name: str,
    preferred_record_id: str | None,
) -> list[str]:
    record_ids: list[str] = []
    if preferred_record_id is not None:
        cf_client.set_record_proxied(preferred_record_id, True)
        record_ids.append(preferred_record_id)

    for record_type in ("A", "AAAA"):
        record = cf_client.get_dns_record(record_name=domain_name, record_type=record_type)
        if record is None or not record.get("id"):
            continue
        record_id = str(record["id"])
        if record_id in record_ids:
            continue
        cf_client.set_record_proxied(record_id, True)
        record_ids.append(record_id)
    return record_ids
