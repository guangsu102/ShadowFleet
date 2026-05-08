from __future__ import annotations

import secrets
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.auth.dependencies import get_current_user, require_operator
from api.deps import get_runtime_context
from database.monitor_repo import MonitorCycleRecord, MonitorRepo
from services.dashboard_models import ProbeHealthRow
from services.dashboard_service import DashboardService
from services.runtime_service import RuntimeContext


router = APIRouter(prefix="/api/v1")


class ProbeResponse(BaseModel):
    probe_id: str
    probe_name: str
    status: str
    public_ip: str | None = None
    region: str | None = None
    isp: str | None = None
    tags: list[str] = Field(default_factory=list)
    config_version: int = 1
    last_seen_at: str | None = None
    updated_at: str = ""


class ProbeStatusUpdateRequest(BaseModel):
    status: str = Field(..., description="active | disabled")


class MonitorCycleResponse(BaseModel):
    cycle_id: int
    status: str
    candidate_count: int = 0
    confirmed_count: int = 0
    healed_count: int = 0
    failed_count: int = 0
    started_at: str = ""
    finished_at: str | None = None
    error_message: str | None = None


class DetectionRecordResponse(BaseModel):
    id: int
    cycle_id: int
    xboard_node_id: int
    node_name: str | None = None
    region: str | None = None
    protocol_type: str | None = None
    status: str | None = None
    uplink_bytes: int | None = None
    downlink_bytes: int | None = None
    total_bytes: int | None = None
    detection_type: str
    detection_status: str
    reason: str | None = None
    probe_provider: str | None = None
    created_at: str = ""
    # Detailed probe information
    probe_status: str | None = None
    probe_failure_stage: str | None = None
    probe_latency_ms: int | None = None
    probe_success_region_count: int | None = None
    probe_failed_region_count: int | None = None
    probe_resolved_ip: str | None = None
    measurement_id: str | None = None
    selected_probe_ids: list[str] = Field(default_factory=list)


class MonitorSummaryStats(BaseModel):
    total_cycles: int
    total_confirmed: int
    total_healed: int
    pending_healing: int


class MonitorSummaryResponse(BaseModel):
    latest_cycle: MonitorCycleResponse | None = None
    stats: MonitorSummaryStats


def _probe_to_response(row: ProbeHealthRow) -> ProbeResponse:
    return ProbeResponse(
        probe_id=row.probe_id, probe_name=row.probe_name, status=row.status,
        public_ip=row.public_ip, region=row.region, isp=row.isp,
        tags=list(row.tags), config_version=row.config_version,
        last_seen_at=row.last_seen_at, updated_at=row.updated_at,
    )


@router.get("/probes", response_model=list[ProbeResponse])
async def list_probes(
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(get_current_user),
) -> list[ProbeResponse]:
    snapshot = DashboardService(ctx).build_snapshot()
    return [_probe_to_response(row) for row in snapshot.probe_rows]


@router.get("/probes/{probe_id}", response_model=ProbeResponse)
async def get_probe(
    probe_id: str,
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(get_current_user),
) -> ProbeResponse:
    snapshot = DashboardService(ctx).build_snapshot()
    for row in snapshot.probe_rows:
        if row.probe_id == probe_id:
            return _probe_to_response(row)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Probe not found")


@router.put("/probes/{probe_id}/status", response_model=ProbeResponse)
async def update_probe_status(
    probe_id: str,
    request: ProbeStatusUpdateRequest,
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(require_operator),
) -> ProbeResponse:
    from database.probe_repo import ProbeRepo
    ProbeRepo(ctx).update_probe_status(probe_id, request.status)
    snapshot = DashboardService(ctx).build_snapshot()
    for row in snapshot.probe_rows:
        if row.probe_id == probe_id:
            return _probe_to_response(row)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Probe not found")


@router.delete("/probes/{probe_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_probe(
    probe_id: str,
    ctx: RuntimeContext = Depends(get_runtime_context),
    _: None = Depends(require_operator),
) -> None:
    from database.probe_repo import ProbeRepo
    ProbeRepo(ctx).delete_probe(probe_id)


@router.get("/probe-tokens", response_model=list[dict])
async def list_bootstrap_tokens(
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(get_current_user),
) -> list[dict]:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    return [{"token": t, "created_at": now} for t in ctx.config.app.probe_bootstrap_tokens]


@router.post("/probe-tokens", response_model=dict, status_code=status.HTTP_201_CREATED)
async def generate_bootstrap_token(
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(require_operator),
) -> dict:
    from datetime import datetime, timezone
    return {
        "token": secrets.token_urlsafe(32),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "note": "Save this token — it cannot be retrieved later",
    }


def _cycle_to_response(c: MonitorCycleRecord) -> MonitorCycleResponse:
    return MonitorCycleResponse(
        cycle_id=c.id, status=c.status, candidate_count=c.candidate_count,
        confirmed_count=c.confirmed_count, healed_count=c.healed_count,
        failed_count=c.failed_count, started_at=c.started_at,
        finished_at=c.finished_at, error_message=c.error_message,
    )


@router.get("/monitor/cycles", response_model=list[MonitorCycleResponse])
async def list_monitor_cycles(
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(get_current_user),
    limit: int = 20,
) -> list[MonitorCycleResponse]:
    cycles = MonitorRepo(ctx).list_recent_cycles(limit=limit)
    return [_cycle_to_response(c) for c in cycles]


@router.get("/monitor/cycles/{cycle_id}", response_model=MonitorCycleResponse)
async def get_monitor_cycle(
    cycle_id: int,
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(get_current_user),
) -> MonitorCycleResponse:
    c = MonitorRepo(ctx).get_cycle_by_id(cycle_id)
    if c is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor cycle not found")
    return _cycle_to_response(c)


@router.get("/monitor/summary", response_model=MonitorSummaryResponse)
async def get_monitor_summary(
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(get_current_user),
) -> MonitorSummaryResponse:
    repo = MonitorRepo(ctx)
    latest = repo.get_latest_cycle()
    cycles = repo.list_recent_cycles(limit=1000)

    total_confirmed = sum(c.confirmed_count for c in cycles)
    total_healed = sum(c.healed_count for c in cycles)
    pending = total_confirmed - total_healed

    return MonitorSummaryResponse(
        latest_cycle=_cycle_to_response(latest) if latest else None,
        stats=MonitorSummaryStats(
            total_cycles=len(cycles),
            total_confirmed=total_confirmed,
            total_healed=total_healed,
            pending_healing=max(0, pending),
        ),
    )


@router.post("/monitor/trigger-scan")
async def trigger_scan_cycle(
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(get_current_user),
) -> MonitorCycleResponse:
    import asyncio
    from services.monitor import MonitorService
    service = MonitorService(ctx)
    result = await asyncio.to_thread(service.run_scan_cycle)
    return MonitorCycleResponse(
        cycle_id=result.cycle_id, status="succeeded",
        candidate_count=result.candidate_count, confirmed_count=result.confirmed_count,
        healed_count=result.healed_count, failed_count=result.failed_count,
        started_at="", finished_at=None, error_message=None,
    )


@router.get("/monitor/detections", response_model=list[DetectionRecordResponse])
async def list_detections(
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(get_current_user),
    cycle_id: int | None = None,
    node_id: int | None = None,
    detection_status: str | None = None,
    limit: int = 100,
) -> list[DetectionRecordResponse]:
    from database.state_repo import StateRepo
    repo = MonitorRepo(ctx)
    state_repo = StateRepo(ctx)

    if cycle_id is not None:
        records = repo.list_detections_by_cycle(cycle_id)
    elif node_id is not None:
        records = repo.list_detections_by_node(node_id, limit=limit)
    else:
        records = []
    if detection_status is not None:
        records = [r for r in records if r.get("detection_status") == detection_status]

    results = []
    for i, r in enumerate(records, 1):
        xboard_node_id = r.get("xboard_node_id", 0)
        node_record = state_repo.get_node_by_xboard_node_id(xboard_node_id)

        # Extract traffic and probe data from payload_json
        payload = r.get("payload_json")
        uplink_bytes = None
        downlink_bytes = None
        total_bytes = None
        probe_status = None
        probe_failure_stage = None
        probe_latency_ms = None
        probe_success_region_count = None
        probe_failed_region_count = None
        probe_resolved_ip = None
        measurement_id = None
        selected_probe_ids: list[str] = []

        if payload:
            import json as _json
            try:
                p = _json.loads(payload) if isinstance(payload, str) else payload
                uplink_bytes = p.get("uplink_bytes")
                downlink_bytes = p.get("downlink_bytes")
                total_bytes = p.get("total_bytes")

                # Extract probe details from control_plane_result
                control_plane = p.get("control_plane_result")
                if control_plane and isinstance(control_plane, dict):
                    probe_status = control_plane.get("status")
                    probe_failure_stage = control_plane.get("failure_stage")
                    probe_latency_ms = control_plane.get("latency_ms")
                    probe_success_region_count = control_plane.get("success_region_count")
                    probe_failed_region_count = control_plane.get("failed_region_count")
                    probe_resolved_ip = control_plane.get("resolved_ip")

                # Extract measurement info
                measurement_id = p.get("measurement_id")
                selected_probe_ids = p.get("selected_probe_ids", [])
                if not isinstance(selected_probe_ids, list):
                    selected_probe_ids = []
            except Exception:
                pass

        results.append(
            DetectionRecordResponse(
                id=i,
                cycle_id=r.get("cycle_id", 0),
                xboard_node_id=xboard_node_id,
                node_name=node_record.node_name if node_record else None,
                region=node_record.region if node_record else None,
                protocol_type=node_record.node_type if node_record else None,
                status=node_record.status if node_record else None,
                uplink_bytes=uplink_bytes,
                downlink_bytes=downlink_bytes,
                total_bytes=total_bytes,
                detection_type=r.get("detection_type", ""),
                detection_status=r.get("detection_status", ""),
                reason=r.get("reason"),
                probe_provider=r.get("probe_provider"),
                created_at=r.get("created_at", ""),
                probe_status=probe_status,
                probe_failure_stage=probe_failure_stage,
                probe_latency_ms=probe_latency_ms,
                probe_success_region_count=probe_success_region_count,
                probe_failed_region_count=probe_failed_region_count,
                probe_resolved_ip=probe_resolved_ip,
                measurement_id=measurement_id,
                selected_probe_ids=selected_probe_ids,
            )
        )
    return results
