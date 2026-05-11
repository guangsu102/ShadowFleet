from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from api.auth.dependencies import require_operator
from api.deps import get_runtime_context
from services.reality_key_generator import RealityKeyGenerator, RealityKeyGeneratorError
from services.runtime_service import RuntimeContext

router = APIRouter(prefix="/api/v1/utils")


class RealityKeyPairResponse(BaseModel):
    private_key: str
    public_key: str


@router.post("/generate-reality-keys", response_model=RealityKeyPairResponse)
async def generate_reality_keys(
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(require_operator),
) -> RealityKeyPairResponse:
    """生成 Reality 密钥对（用于 VLESS 协议）"""
    try:
        private_key, public_key = RealityKeyGenerator.generate_key_pair()
        return RealityKeyPairResponse(private_key=private_key, public_key=public_key)
    except RealityKeyGeneratorError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        ) from e
