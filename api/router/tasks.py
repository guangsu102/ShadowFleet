from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.auth.dependencies import get_current_user, require_operator
from api.deps import get_runtime_context
from services.manual_operation_models import ManualOperationRequest, ManualTaskType
from services.manual_operation_service import ManualOperationService
from services.provisioning_models import ProvisionRequest, ProtocolType
from services.provisioning_task_service import ProvisioningTaskService
from services.runtime_service import RuntimeContext


router = APIRouter(prefix="/api/v1")


class ProvisionTaskCreateRequest(BaseModel):
    protocol_type: str = Field(...)
    node_name: str = Field(...)
    port: str = Field(...)
    server_port: int = Field(..., ge=1, le=65535)
    rate: float = Field(default=1.0, ge=0)
    asset_type: str = "aws"
    region: str | None = None
    domain_name: str | None = None
    require_cdn_proxy: bool = False
    cert_mode: str = "none"
    code: str | None = None
    parent_id: int | None = None
    tags: list[str] | None = None
    show: bool = True
    group_ids: list[int] | None = None
    route_ids: list[int] | None = None
    sort: int | None = None
    rate_time_enable: bool = False
    protocol_settings: dict | None = None
    rate_time_ranges: list | None = None
    status_reason: str | None = None


class ManualTaskCreateRequest(BaseModel):
    task_type: str = Field(...)
    xboard_node_id: int
    operator_name: str | None = None
    reason: str | None = None
    force_strategy: str | None = None


class TaskResponse(BaseModel):
    id: int
    task_type: str
    status: str
    correlation_id: str
    attempt_count: int = 0
    max_attempts: int = 1
    locked_by: str | None = None
    next_run_at: str = ""
    created_at: str = ""
    updated_at: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    last_error: str | None = None


class SubmitResult(BaseModel):
    task_id: int
    correlation_id: str
    status: str


def _to_response(record) -> TaskResponse:
    return TaskResponse(
        id=record.id, task_type=record.task_type, status=record.status,
        correlation_id=record.correlation_id, attempt_count=record.attempt_count,
        max_attempts=record.max_attempts, locked_by=record.locked_by,
        next_run_at=record.next_run_at, created_at=record.created_at, updated_at=record.updated_at,
        started_at=getattr(record, "started_at", None),
        finished_at=getattr(record, "finished_at", None),
        last_error=getattr(record, "last_error", None),
    )


class TaskStatsResponse(BaseModel):
    total: int = 0
    queued: int = 0
    running: int = 0
    succeeded: int = 0
    failed: int = 0


@router.get("/tasks", response_model=list[TaskResponse])
async def list_provisioning_tasks(
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(get_current_user),
    limit: int = 50,
) -> list[TaskResponse]:
    tasks = ProvisioningTaskService(ctx).list_recent_tasks(limit=limit)
    return [_to_response(t) for t in tasks]


@router.get("/tasks/stats", response_model=TaskStatsResponse)
async def get_task_stats(
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(get_current_user),
) -> TaskStatsResponse:
    stats = ProvisioningTaskService(ctx).get_task_stats()
    return TaskStatsResponse(
        total=stats.get("total", 0),
        queued=stats.get("queued", 0),
        running=stats.get("running", 0),
        succeeded=stats.get("succeeded", 0),
        failed=stats.get("failed", 0),
    )


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_provisioning_task(
    task_id: int,
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(get_current_user),
) -> TaskResponse:
    try:
        record = ProvisioningTaskService(ctx).get_task_by_id(task_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return _to_response(record)


@router.post("/tasks", response_model=SubmitResult, status_code=status.HTTP_201_CREATED)
async def submit_provisioning_task(
    request: ProvisionTaskCreateRequest,
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(require_operator),
) -> SubmitResult:
    try:
        result = ProvisioningTaskService(ctx).submit_provision_task(
            ProvisionRequest(
                protocol_type=ProtocolType(request.protocol_type), node_name=request.node_name,
                port=request.port, server_port=request.server_port, rate=request.rate,
                asset_type=request.asset_type or "aws", region=request.region,
                domain_name=request.domain_name, require_cdn_proxy=request.require_cdn_proxy,
                cert_mode=request.cert_mode or "none", code=request.code,
                parent_id=request.parent_id, tags=request.tags, show=request.show,
            ),
            group_ids=request.group_ids,
            route_ids=request.route_ids,
            sort=request.sort,
            rate_time_enable=request.rate_time_enable,
            protocol_settings=request.protocol_settings,
            rate_time_ranges=request.rate_time_ranges,
            status_reason=request.status_reason,
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    return SubmitResult(task_id=result.task_id, correlation_id=result.correlation_id, status=result.status)


@router.post("/tasks/{task_id}/retry", response_model=TaskResponse)
async def retry_provisioning_task(
    task_id: int,
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(require_operator),
) -> TaskResponse:
    try:
        record = ProvisioningTaskService(ctx).retry_failed_task(task_id)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    return _to_response(record)


@router.get("/manual-tasks", response_model=list[TaskResponse])
async def list_manual_tasks(
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(get_current_user),
    limit: int = 50,
) -> list[TaskResponse]:
    tasks = ManualOperationService(ctx).list_recent_tasks(limit=limit)
    return [_to_response(t) for t in tasks]


@router.post("/manual-tasks", response_model=SubmitResult, status_code=status.HTTP_201_CREATED)
async def submit_manual_task(
    request: ManualTaskCreateRequest,
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(require_operator),
) -> SubmitResult:
    try:
        result = ManualOperationService(ctx).submit_task(
            ManualOperationRequest(
                task_type=ManualTaskType(request.task_type),
                xboard_node_id=request.xboard_node_id,
                operator_name=request.operator_name,
                reason=request.reason,
                force_strategy=request.force_strategy,
            )
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    return SubmitResult(task_id=result.task_id, correlation_id=result.correlation_id, status=result.status)
