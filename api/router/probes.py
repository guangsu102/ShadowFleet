from __future__ import annotations

import secrets
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.auth.dependencies import get_current_user, require_operator
from api.deps import get_runtime_context
from database.monitor_repo import MonitorRepo
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
    detection_type: str
    detection_status: str
    reason: str | None = None
    probe_provider: str | None = None
    created_at: str = ""


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


@router.get("/monitor/cycles", response_model=list[MonitorCycleResponse])
async def list_monitor_cycles(
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(get_current_user),
    limit: int = 20,
) -> list[MonitorCycleResponse]:
    cycles = MonitorRepo(ctx).list_recent_cycles(limit=limit)
    return [
        MonitorCycleResponse(
            cycle_id=c.id, status=c.status, candidate_count=c.candidate_count,
            confirmed_count=c.confirmed_count, healed_count=c.healed_count,
            failed_count=c.failed_count, started_at=c.started_at,
            finished_at=c.finished_at, error_message=c.error_message,
        )
        for c in cycles
    ]


@router.get("/monitor/cycles/{cycle_id}", response_model=MonitorCycleResponse)
async def get_monitor_cycle(
    cycle_id: int,
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(get_current_user),
) -> MonitorCycleResponse:
    cycles = MonitorRepo(ctx).list_recent_cycles(limit=1000)
    for c in cycles:
        if c.id == cycle_id:
            return MonitorCycleResponse(
                cycle_id=c.id, status=c.status, candidate_count=c.candidate_count,
                confirmed_count=c.confirmed_count, healed_count=c.healed_count,
                failed_count=c.failed_count, started_at=c.started_at,
                finished_at=c.finished_at, error_message=c.error_message,
            )
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor cycle not found")


@router.get("/monitor/detections", response_model=list[DetectionRecordResponse])
async def list_detections(
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(get_current_user),
    cycle_id: int | None = None,
    node_id: int | None = None,
    detection_status: str | None = None,
    limit: int = 100,
) -> list[DetectionRecordResponse]:
    repo = MonitorRepo(ctx)
    if cycle_id is not None:
        records = repo.list_detections_by_cycle(cycle_id)
    elif node_id is not None:
        records = repo.list_detections_by_node(node_id, limit=limit)
    else:
        records = []
    if detection_status is not None:
        records = [r for r in records if r.get("detection_status") == detection_status]
    return [
        DetectionRecordResponse(
            id=i, cycle_id=r.get("cycle_id", 0), xboard_node_id=r.get("xboard_node_id", 0),
            detection_type=r.get("detection_type", ""),
            detection_status=r.get("detection_status", ""),
            reason=r.get("reason"), probe_provider=r.get("probe_provider"),
            created_at=r.get("created_at", ""),
        )
        for i, r in enumerate(records, 1)
    ]
