from __future__ import annotations

from datetime import datetime, timedelta, timezone

from database.state_repo import FleetNodeRecord
from services.monitor_models import MonitorCandidate, XboardSentinelNodeRuntime


def to_monitor_candidate(
    node_record: FleetNodeRecord,
    xboard_runtime: XboardSentinelNodeRuntime,
) -> MonitorCandidate:
    return MonitorCandidate(
        xboard_node_id=node_record.xboard_node_id,
        node_name=node_record.node_name,
        node_type=node_record.node_type,
        asset_type="aws" if node_record.aws_account_id is not None else "self_hosted",
        domain_name=node_record.domain_name,
        host=xboard_runtime.host,
        port=xboard_runtime.port,
        server_port=xboard_runtime.server_port,
        status=node_record.status,
        last_healed_at=node_record.last_healed_at,
        ipv4_address=node_record.ipv4_address,
        ipv6_address=node_record.ipv6_address,
    )


def is_in_heal_cooldown(
    node_record: FleetNodeRecord,
    *,
    now_utc: datetime,
    cooldown_seconds: float,
) -> bool:
    if node_record.last_healed_at is None:
        return False
    healed_at = _parse_iso_datetime(node_record.last_healed_at)
    return (now_utc - healed_at) < timedelta(seconds=cooldown_seconds)


def should_flag_zero_uplink(
    *,
    recent_total_positive: bool,
    recent_zero_uplink_count: int,
    expected_zero_window_minutes: int,
    probe_zero_traffic_nodes: bool = False,
) -> bool:
    # 如果启用探测无流量节点，则即使历史无流量也标记
    if probe_zero_traffic_nodes and recent_zero_uplink_count >= expected_zero_window_minutes:
        return True
    # 默认行为：必须有历史流量且最近窗口上行归零
    return recent_total_positive and recent_zero_uplink_count >= expected_zero_window_minutes


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
