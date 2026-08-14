from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from api.auth.dependencies import get_current_user, require_operator
from api.deps import get_runtime_context
from services.account_abandonment_service import (
    AccountAbandonmentService,
    AccountAbandonmentServiceError,
)
from services.runtime_service import RuntimeContext


router = APIRouter(prefix="/api/v1/abandonment")


class AbandonmentRequest(BaseModel):
    aws_account_id: str
    error_code: str
    error_message: str
    source_xboard_node_id: int | None = None


class AbandonmentResultResponse(BaseModel):
    aws_account_id: str
    deleted_node_count: int
    asset_count: int


class QuotaRowResponse(BaseModel):
    aws_account_id: str
    region: str | None
    active_count: int
    full_count: int
    banned_count: int
    total: int


@router.get("/quota", response_model=list[QuotaRowResponse])
async def list_quotas(
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(get_current_user),
) -> list[QuotaRowResponse]:
    from database.asset_models import AssetRecord
    from database.asset_repo import AssetRepo

    repo = AssetRepo(ctx)
    all_statuses = ["active", "full", "banned", "offline"]
    grouped: dict[str, list[AssetRecord]] = {}
    for status_val in all_statuses:
        for asset in repo.list_assets_by_status(status_val):
            if asset.asset_type != "aws":
                continue
            account_id = asset.aws_account_id or "Unknown"
            grouped.setdefault(account_id, []).append(asset)

    rows: list[QuotaRowResponse] = []
    for account_id, group in sorted(grouped.items()):
        rows.append(
            QuotaRowResponse(
                aws_account_id=account_id,
                region=group[0].region,
                active_count=sum(1 for a in group if a.status == "active"),
                full_count=sum(1 for a in group if a.status == "full"),
                banned_count=sum(1 for a in group if a.status == "banned"),
                total=len(group),
            )
        )
    return rows


@router.post(
    "",
    response_model=AbandonmentResultResponse,
    status_code=status.HTTP_201_CREATED,
)
async def abandon_account(
    request: AbandonmentRequest,
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(require_operator),
) -> AbandonmentResultResponse:
    if ctx.db_pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Xboard PostgreSQL is not configured. Cannot perform abandonment operation.",
        )
    service = AccountAbandonmentService(ctx)
    try:
        result = service.abandon_account(
            aws_account_id=request.aws_account_id,
            error_code=request.error_code,
            error_message=request.error_message,
            source_xboard_node_id=request.source_xboard_node_id,
        )
        return AbandonmentResultResponse(
            aws_account_id=result.aws_account_id,
            deleted_node_count=result.deleted_node_count,
            asset_count=result.asset_count,
        )
    except AccountAbandonmentServiceError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
