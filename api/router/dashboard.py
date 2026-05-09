from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from api.auth.dependencies import get_current_user
from api.deps import get_runtime_context
from services.dashboard_models import DashboardSnapshot
from services.dashboard_service import DashboardService
from services.runtime_service import RuntimeContext


router = APIRouter(prefix="/api/v1/dashboard")


class DashboardOverviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    expected_node_count: int = 0
    total_node_count: int = 0
    online_node_count: int = 0
    healing_node_count: int = 0
    offline_or_failed_node_count: int = 0
    overall_survival_rate: float = 0.0
    monthly_healing_count: int = 0
    total_asset_count: int = 0
    active_asset_count: int = 0
    full_asset_count: int = 0
    banned_asset_count: int = 0
    deploying_asset_count: int = 0
    offline_asset_count: int = 0
    aws_asset_count: int = 0
    active_aws_asset_count: int = 0
    full_aws_asset_count: int = 0
    banned_aws_asset_count: int = 0
    allocated_aws_node_count: int = 0
    target_aws_capacity: int = 0
    max_aws_capacity: int = 0
    aws_capacity_utilization_rate: float = 0.0
    total_probe_count: int = 0
    active_probe_count: int = 0
    offline_probe_count: int = 0
    disabled_probe_count: int = 0


class RegionProtocolHealthRowResponse(BaseModel):
    region: str = ""
    protocol_type: str = ""
    desired_count: int = 0
    min_alert_threshold: int = 0
    online_count: int = 0
    total_count: int = 0
    gap_count: int = 0
    survival_rate: float = 0.0
    alert_level: str = "healthy"


class AssetHealthRowResponse(BaseModel):
    asset_id: int = 0
    asset_name: str = ""
    asset_type: str = ""
    region: str | None = None
    status: str = ""
    aws_account_id: str | None = None
    account_total_vcpu: int | None = None
    allocated_count: int = 0
    target_count: int = 0
    max_count: int = 0
    supported_protocols: list[str] = []
    cpu_cores: int | None = None
    memory_gb: float | None = None
    remarks: str | None = None
    updated_at: str = ""


class FleetNodeDashboardRowResponse(BaseModel):
    xboard_node_id: int = 0
    node_name: str = ""
    protocol_type: str = ""
    asset_type: str = ""
    region: str | None = None
    status: str = ""
    instance_id: str | None = None
    domain_name: str | None = None
    ipv6_address: str | None = None
    aws_account_id: str | None = None
    last_healed_at: str | None = None
    updated_at: str = ""
    last_error: str | None = None
    xboard_status: str | None = None
    xboard_show: bool | None = None
    xboard_updated_at: str | None = None


class MonitorCycleSummaryResponse(BaseModel):
    cycle_id: int = 0
    status: str = ""
    candidate_count: int = 0
    confirmed_count: int = 0
    healed_count: int = 0
    failed_count: int = 0
    started_at: str = ""
    finished_at: str | None = None
    error_message: str | None = None


class ProbeHealthRowResponse(BaseModel):
    probe_id: str = ""
    probe_name: str = ""
    status: str = ""
    public_ip: str | None = None
    region: str | None = None
    isp: str | None = None
    tags: list[str] = []
    config_version: int = 1
    last_seen_at: str | None = None
    updated_at: str = ""


class ProbeMeasurementRowResponse(BaseModel):
    measurement_id: str = ""
    xboard_node_id: int = 0
    final_status: str = ""
    reason: str | None = None
    created_at: str = ""
    finished_at: str | None = None


class DashboardSnapshotResponse(BaseModel):
    overview: DashboardOverviewResponse
    region_protocol_rows: list[RegionProtocolHealthRowResponse] = []
    asset_rows: list[AssetHealthRowResponse] = []
    node_rows: list[FleetNodeDashboardRowResponse] = []
    latest_monitor_cycle: MonitorCycleSummaryResponse | None = None
    probe_rows: list[ProbeHealthRowResponse] = []
    probe_measurement_rows: list[ProbeMeasurementRowResponse] = []


def _snapshot_to_response(s: DashboardSnapshot) -> DashboardSnapshotResponse:
    o = s.overview
    return DashboardSnapshotResponse(
        overview=DashboardOverviewResponse(
            expected_node_count=o.expected_node_count, total_node_count=o.total_node_count,
            online_node_count=o.online_node_count, healing_node_count=o.healing_node_count,
            offline_or_failed_node_count=o.offline_or_failed_node_count,
            overall_survival_rate=o.overall_survival_rate, monthly_healing_count=o.monthly_healing_count,
            total_asset_count=o.total_asset_count, active_asset_count=o.active_asset_count,
            full_asset_count=o.full_asset_count, banned_asset_count=o.banned_asset_count,
            deploying_asset_count=o.deploying_asset_count, offline_asset_count=o.offline_asset_count,
            aws_asset_count=o.aws_asset_count, active_aws_asset_count=o.active_aws_asset_count,
            full_aws_asset_count=o.full_aws_asset_count, banned_aws_asset_count=o.banned_aws_asset_count,
            allocated_aws_node_count=o.allocated_aws_node_count, target_aws_capacity=o.target_aws_capacity,
            max_aws_capacity=o.max_aws_capacity, aws_capacity_utilization_rate=o.aws_capacity_utilization_rate,
            total_probe_count=o.total_probe_count, active_probe_count=o.active_probe_count,
            offline_probe_count=o.offline_probe_count, disabled_probe_count=o.disabled_probe_count,
        ),
        region_protocol_rows=[
            RegionProtocolHealthRowResponse(
                region=r.region, protocol_type=r.protocol_type, desired_count=r.desired_count,
                min_alert_threshold=r.min_alert_threshold, online_count=r.online_count,
                total_count=r.total_count, gap_count=r.gap_count, survival_rate=r.survival_rate,
                alert_level=r.alert_level,
            )
            for r in s.region_protocol_rows
        ],
        asset_rows=[
            AssetHealthRowResponse(
                asset_id=r.asset_id, asset_name=r.asset_name, asset_type=r.asset_type,
                region=r.region, status=r.status, aws_account_id=r.aws_account_id,
                account_total_vcpu=r.account_total_vcpu, allocated_count=r.allocated_count,
                target_count=r.target_count, max_count=r.max_count,
                supported_protocols=list(r.supported_protocols),
                cpu_cores=r.cpu_cores, memory_gb=r.memory_gb,
                remarks=r.remarks, updated_at=r.updated_at,
            )
            for r in s.asset_rows
        ],
        node_rows=[
            FleetNodeDashboardRowResponse(
                xboard_node_id=r.xboard_node_id, node_name=r.node_name,
                protocol_type=r.protocol_type, asset_type=r.asset_type,
                region=r.region, status=r.status, instance_id=r.instance_id,
                domain_name=r.domain_name, ipv6_address=r.ipv6_address,
                aws_account_id=r.aws_account_id, last_healed_at=r.last_healed_at,
                updated_at=r.updated_at, last_error=r.last_error,
                xboard_status=r.xboard_status, xboard_show=r.xboard_show,
                xboard_updated_at=r.xboard_updated_at,
            )
            for r in s.node_rows
        ],
        latest_monitor_cycle=(
            MonitorCycleSummaryResponse(
                cycle_id=s.latest_monitor_cycle.cycle_id, status=s.latest_monitor_cycle.status,
                candidate_count=s.latest_monitor_cycle.candidate_count,
                confirmed_count=s.latest_monitor_cycle.confirmed_count,
                healed_count=s.latest_monitor_cycle.healed_count,
                failed_count=s.latest_monitor_cycle.failed_count,
                started_at=s.latest_monitor_cycle.started_at,
                finished_at=s.latest_monitor_cycle.finished_at,
                error_message=s.latest_monitor_cycle.error_message,
            )
            if s.latest_monitor_cycle else None
        ),
        probe_rows=[
            ProbeHealthRowResponse(
                probe_id=r.probe_id, probe_name=r.probe_name, status=r.status,
                public_ip=r.public_ip, region=r.region, isp=r.isp,
                tags=list(r.tags), config_version=r.config_version,
                last_seen_at=r.last_seen_at, updated_at=r.updated_at,
            )
            for r in s.probe_rows
        ],
        probe_measurement_rows=[
            ProbeMeasurementRowResponse(
                measurement_id=r.measurement_id, xboard_node_id=r.xboard_node_id,
                final_status=r.final_status, reason=r.reason,
                created_at=r.created_at, finished_at=r.finished_at,
            )
            for r in s.probe_measurement_rows
        ],
    )


@router.get("/snapshot", response_model=DashboardSnapshotResponse)
async def get_snapshot(
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(get_current_user),
) -> DashboardSnapshotResponse:
    return _snapshot_to_response(DashboardService(ctx).build_snapshot())
