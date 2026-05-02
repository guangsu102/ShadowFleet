from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


DashboardAlertLevel = Literal["healthy", "warning", "critical"]


@dataclass(frozen=True)
class DashboardOverview:
    expected_node_count: int
    total_node_count: int
    online_node_count: int
    healing_node_count: int
    offline_or_failed_node_count: int
    overall_survival_rate: float
    monthly_healing_count: int
    total_asset_count: int
    active_asset_count: int
    full_asset_count: int
    banned_asset_count: int
    deploying_asset_count: int
    offline_asset_count: int
    aws_asset_count: int
    active_aws_asset_count: int
    full_aws_asset_count: int
    banned_aws_asset_count: int
    allocated_aws_node_count: int
    target_aws_capacity: int
    max_aws_capacity: int
    aws_capacity_utilization_rate: float
    total_probe_count: int
    active_probe_count: int
    offline_probe_count: int
    disabled_probe_count: int


@dataclass(frozen=True)
class RegionProtocolHealthRow:
    region: str
    protocol_type: str
    desired_count: int
    min_alert_threshold: int
    online_count: int
    total_count: int
    gap_count: int
    survival_rate: float
    alert_level: DashboardAlertLevel


@dataclass(frozen=True)
class AssetHealthRow:
    asset_id: int
    asset_name: str
    asset_type: str
    region: str | None
    status: str
    aws_account_id: str | None
    account_total_vcpu: int | None
    allocated_count: int
    target_count: int
    max_count: int
    supported_protocols: tuple[str, ...]
    cpu_cores: int | None
    memory_gb: float | None
    remarks: str | None
    updated_at: str


@dataclass(frozen=True)
class FleetNodeDashboardRow:
    xboard_node_id: int
    node_name: str
    protocol_type: str
    asset_type: str
    region: str | None
    status: str
    instance_id: str | None
    domain_name: str | None
    ipv6_address: str | None
    aws_account_id: str | None
    last_healed_at: str | None
    updated_at: str
    last_error: str | None


@dataclass(frozen=True)
class NodeEventRow:
    event_id: int
    event_type: str
    from_status: str | None
    to_status: str | None
    message: str | None
    correlation_id: str
    created_at: str


@dataclass(frozen=True)
class MonitorCycleSummary:
    cycle_id: int
    status: str
    candidate_count: int
    confirmed_count: int
    healed_count: int
    failed_count: int
    started_at: str
    finished_at: str | None
    error_message: str | None


@dataclass(frozen=True)
class ProbeHealthRow:
    probe_id: str
    probe_name: str
    status: str
    public_ip: str | None
    region: str | None
    isp: str | None
    tags: tuple[str, ...]
    config_version: int
    last_seen_at: str | None
    updated_at: str


@dataclass(frozen=True)
class ProbeMeasurementRow:
    measurement_id: str
    xboard_node_id: int
    final_status: str
    reason: str | None
    created_at: str
    finished_at: str | None


@dataclass(frozen=True)
class DashboardSnapshot:
    overview: DashboardOverview
    region_protocol_rows: tuple[RegionProtocolHealthRow, ...]
    asset_rows: tuple[AssetHealthRow, ...]
    node_rows: tuple[FleetNodeDashboardRow, ...]
    latest_monitor_cycle: MonitorCycleSummary | None
    probe_rows: tuple[ProbeHealthRow, ...]
    probe_measurement_rows: tuple[ProbeMeasurementRow, ...]
