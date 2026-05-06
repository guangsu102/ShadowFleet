from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from api.auth.dependencies import get_current_user, require_operator
from api.deps import get_runtime_context
from services.dashboard_models import FleetNodeDashboardRow
from services.dashboard_service import DashboardService
from services.runtime_service import RuntimeContext
from database.state_models import FleetNodeStatus
from database.xboard_repo import XboardNodeNotFoundError


router = APIRouter(prefix="/api/v1/nodes")


class NodeEventResponse(BaseModel):
    event_id: int
    event_type: str
    from_status: str | None = None
    to_status: str | None = None
    message: str | None = None
    correlation_id: str
    created_at: str


class NodeResponse(BaseModel):
    xboard_node_id: int
    node_name: str
    protocol_type: str
    asset_type: str
    region: str | None = None
    status: str
    instance_id: str | None = None
    domain_name: str | None = None
    ipv6_address: str | None = None
    aws_account_id: str | None = None
    last_healed_at: str | None = None
    updated_at: str = ""
    last_error: str | None = None

    model_config = {"from_attributes": True}


class NodeStatusUpdateRequest(BaseModel):
    status: FleetNodeStatus
    reason: str | None = None


def _to_response(row: FleetNodeDashboardRow) -> NodeResponse:
    return NodeResponse(
        xboard_node_id=row.xboard_node_id, node_name=row.node_name,
        protocol_type=row.protocol_type, asset_type=row.asset_type,
        region=row.region, status=row.status, instance_id=row.instance_id,
        domain_name=row.domain_name, ipv6_address=row.ipv6_address,
        aws_account_id=row.aws_account_id, last_healed_at=row.last_healed_at,
        updated_at=row.updated_at, last_error=row.last_error,
    )


@router.get("", response_model=list[NodeResponse])
async def list_nodes(
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(get_current_user),
) -> list[NodeResponse]:
    service = DashboardService(ctx)
    return [_to_response(row) for row in service.build_snapshot().node_rows]


@router.get("/{node_id}", response_model=NodeResponse)
async def get_node(
    node_id: int,
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(get_current_user),
) -> NodeResponse:
    service = DashboardService(ctx)
    for row in service.build_snapshot().node_rows:
        if row.xboard_node_id == node_id:
            return _to_response(row)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Node not found")


@router.get("/{node_id}/events", response_model=list[NodeEventResponse])
async def get_node_events(
    node_id: int,
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(get_current_user),
    limit: int = 20,
) -> list[NodeEventResponse]:
    service = DashboardService(ctx)
    events = service.list_recent_node_events(node_id, limit=limit)
    return [
        NodeEventResponse(
            event_id=e.event_id, event_type=e.event_type,
            from_status=e.from_status, to_status=e.to_status,
            message=e.message, correlation_id=e.correlation_id, created_at=e.created_at,
        )
        for e in events
    ]


@router.put("/{node_id}/status", response_model=NodeResponse)
async def update_node_status(
    node_id: int,
    request: NodeStatusUpdateRequest,
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(require_operator),
) -> NodeResponse:
    from database.state_repo import StateRepo
    StateRepo(ctx).update_node_status(node_id, request.status)
    service = DashboardService(ctx)
    for row in service.build_snapshot().node_rows:
        if row.xboard_node_id == node_id:
            return _to_response(row)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Node not found")


@router.delete("/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_node(
    node_id: int,
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(require_operator),
) -> None:
    from services.node_registry_service import NodeRegistryService, NodeRegistryServiceError
    try:
        NodeRegistryService(ctx).delete_node(node_id)
    except XboardNodeNotFoundError:
        pass
    except NodeRegistryServiceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


class SyncResultResponse(BaseModel):
    created: int
    orphan_local_deleted: int
    already_synced: int


@router.post("/sync", response_model=SyncResultResponse)
async def sync_nodes(
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(require_operator),
) -> SyncResultResponse:
    from services.node_registry_service import NodeRegistryService
    result = NodeRegistryService(ctx).sync_with_xboard()
    return SyncResultResponse(**result)
