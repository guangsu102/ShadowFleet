from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from api.auth.dependencies import get_current_user
from api.deps import get_runtime_context
from database.xboard_repo import XboardRepo
from services.runtime_service import RuntimeContext


router = APIRouter(prefix="/api/v1/xboard")


class XboardGroupResponse(BaseModel):
    id: int
    name: str


@router.get("/groups", response_model=list[XboardGroupResponse])
async def list_xboard_groups(
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(get_current_user),
) -> list[XboardGroupResponse]:
    if ctx.db_pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Xboard database not configured",
        )
    try:
        repo = XboardRepo(ctx)
        groups = repo.list_groups()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch groups: {e}",
        ) from e
    return [XboardGroupResponse(id=g.id, name=g.name) for g in groups]
