from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.auth.dependencies import get_current_user, require_operator
from api.deps import get_runtime_context
from services.asset_application_models import AssetRegistrationRequest, SelfHostedAssetRegistrationRequest
from services.asset_application_service import AssetApplicationService
from services.dashboard_models import AssetHealthRow
from services.dashboard_service import DashboardService
from services.runtime_service import RuntimeContext


router = APIRouter(prefix="/api/v1/assets")


class AssetResponse(BaseModel):
    asset_id: int
    asset_name: str
    asset_type: str
    region: str | None = None
    status: str = ""
    aws_account_id: str | None = None
    account_total_vcpu: int | None = None
    allocated_count: int = 0
    target_count: int = 0
    max_count: int = 0
    supported_protocols: list[str] = Field(default_factory=list)
    cpu_cores: int | None = None
    memory_gb: float | None = None
    remarks: str | None = None
    updated_at: str = ""

    model_config = {"from_attributes": True}


class AWSAssetCreateRequest(BaseModel):
    asset_name: str = Field(..., min_length=1, max_length=128)
    region: str = Field(..., min_length=1)
    aws_access_key: str = Field(..., min_length=1)
    aws_secret_key: str = Field(..., min_length=1)
    aws_account_id: str | None = None
    default_instance_type: str | None = None
    default_vcpu: int | None = None
    account_total_vcpu: int | None = None
    default_architecture: str | None = None
    remarks: str | None = None
    protocol_type: str | None = None
    additional_protocol_types: list[str] = Field(default_factory=list)
    target_count: int = 0
    max_count: int = 0
    priority: int = 100
    allow_cdn_proxy: bool = False
    ami_id: str | None = None
    vpc_id: str | None = None
    subnet_id: str | None = None
    security_group_id: str | None = None
    auto_create_security_group: bool = False
    security_group_name: str | None = None
    security_group_ports: list[int] = Field(default_factory=list)


class SelfHostedAssetCreateRequest(BaseModel):
    asset_name: str = Field(..., min_length=1, max_length=128)
    region: str = Field(..., min_length=1)
    host: str = Field(..., min_length=1)
    ssh_port: int = 22
    ssh_username: str = "root"
    ssh_password: str | None = None
    ssh_private_key: str | None = None
    remarks: str | None = None
    protocol_type: str | None = None
    additional_protocol_types: list[str] = Field(default_factory=list)
    target_count: int = 0
    max_count: int = 0
    priority: int = 100
    cpu_cores: int | None = None
    memory_gb: float | None = None


def _to_response(row: AssetHealthRow) -> AssetResponse:
    return AssetResponse(
        asset_id=row.asset_id,
        asset_name=row.asset_name,
        asset_type=row.asset_type,
        region=row.region,
        status=row.status,
        aws_account_id=row.aws_account_id,
        account_total_vcpu=row.account_total_vcpu,
        allocated_count=row.allocated_count,
        target_count=row.target_count,
        max_count=row.max_count,
        supported_protocols=list(row.supported_protocols),
        cpu_cores=row.cpu_cores,
        memory_gb=row.memory_gb,
        remarks=row.remarks,
        updated_at=row.updated_at,
    )


@router.get("", response_model=list[AssetResponse])
async def list_assets(
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(get_current_user),
) -> list[AssetResponse]:
    service = DashboardService(ctx)
    snapshot = service.build_snapshot()
    return [_to_response(row) for row in snapshot.asset_rows]


@router.post("", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
async def register_aws_asset(
    request: AWSAssetCreateRequest,
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(require_operator),
) -> AssetResponse:
    service = AssetApplicationService(ctx)
    try:
        result = service.register_aws_asset(
            AssetRegistrationRequest(
                asset_name=request.asset_name, region=request.region,
                aws_access_key=request.aws_access_key, aws_secret_key=request.aws_secret_key,
                aws_account_id=request.aws_account_id, default_instance_type=request.default_instance_type,
                default_vcpu=request.default_vcpu, account_total_vcpu=request.account_total_vcpu,
                default_architecture=request.default_architecture, remarks=request.remarks,
                protocol_type=request.protocol_type,
                additional_protocol_types=tuple(request.additional_protocol_types),
                target_count=request.target_count, max_count=request.max_count,
                priority=request.priority, allow_cdn_proxy=request.allow_cdn_proxy,
                ami_id=request.ami_id, vpc_id=request.vpc_id, subnet_id=request.subnet_id,
                security_group_id=request.security_group_id,
                auto_create_security_group=request.auto_create_security_group,
                security_group_name=request.security_group_name,
                security_group_ports=tuple(request.security_group_ports),
            )
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    return AssetResponse(asset_id=result.asset_id, asset_name=result.asset_name, asset_type="aws", region=request.region, status="active", aws_account_id=request.aws_account_id)


@router.post("/self-hosted", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
async def register_self_hosted_asset(
    request: SelfHostedAssetCreateRequest,
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(require_operator),
) -> AssetResponse:
    service = AssetApplicationService(ctx)
    try:
        result = service.register_self_hosted_asset(
            SelfHostedAssetRegistrationRequest(
                asset_name=request.asset_name, region=request.region, host=request.host,
                ssh_port=request.ssh_port, ssh_username=request.ssh_username,
                ssh_password=request.ssh_password, ssh_private_key=request.ssh_private_key,
                remarks=request.remarks, protocol_type=request.protocol_type,
                additional_protocol_types=tuple(request.additional_protocol_types),
                target_count=request.target_count, max_count=request.max_count,
                priority=request.priority, cpu_cores=request.cpu_cores, memory_gb=request.memory_gb,
            )
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    return AssetResponse(asset_id=result.asset_id, asset_name=result.asset_name, asset_type="self_hosted", region=request.region, status="active")


@router.get("/{asset_id}", response_model=AssetResponse)
async def get_asset(
    asset_id: int,
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(get_current_user),
) -> AssetResponse:
    service = DashboardService(ctx)
    for row in service.build_snapshot().asset_rows:
        if row.asset_id == asset_id:
            return _to_response(row)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_asset(
    asset_id: int,
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(require_operator),
) -> None:
    from database.asset_repo import AssetRepo
    try:
        AssetRepo(ctx).delete_asset(asset_id)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.get("/{asset_id}/amis")
async def query_arm64_amis(
    asset_id: int,
    region: str,
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(require_operator),
) -> dict[str, object]:
    return {
        "asset_id": asset_id, "region": region,
        "amis": [
            {"ami_id": "ami-0c55b159cbfafe1f0", "name": "ubuntu-22.04-arm64", "owner": "099720109477"},
            {"ami_id": "ami-0a6dc09c0b5d7f20f", "name": "ubuntu-24.04-arm64", "owner": "099720109477"},
        ],
        "note": "Placeholder — real implementation uses boto3 ec2.describe_images",
    }


class HardwareProbeRequest(BaseModel):
    host: str = Field(..., min_length=1)
    ssh_port: int = Field(default=22, ge=1, le=65535)
    ssh_username: str = Field(default="root", min_length=1)
    ssh_password: str | None = None
    ssh_private_key: str | None = None


class HardwareProbeResponse(BaseModel):
    cpu_cores: int
    memory_gb: float
    hostname: str | None = None
    os_info: str | None = None


@router.post("/{asset_id}/hardware/probe", response_model=HardwareProbeResponse)
async def probe_asset_hardware(
    asset_id: int,
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(require_operator),
) -> HardwareProbeResponse:
    """SSH hardware probe for an existing self-hosted asset."""
    from database.asset_repo import AssetRepo
    asset = AssetRepo(ctx).get_asset_by_id(asset_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    if asset.asset_type != "self_hosted":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Hardware probe is only supported for self-hosted assets",
        )
    try:
        service = AssetApplicationService(ctx)
        cpu_cores, memory_gb = service.probe_self_hosted_hardware(
            host=asset.ssh_host,
            ssh_port=asset.ssh_port or 22,
            ssh_username=asset.ssh_username or "root",
            ssh_password=asset.ssh_password,
            ssh_private_key=asset.ssh_private_key,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Hardware probe failed: {e}",
        ) from e
    return HardwareProbeResponse(cpu_cores=cpu_cores, memory_gb=memory_gb)


@router.post("/self-hosted/probe-hardware", response_model=HardwareProbeResponse)
async def probe_self_hosted_hardware(
    request: HardwareProbeRequest,
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(require_operator),
) -> HardwareProbeResponse:
    """Standalone SSH hardware probe (used before asset registration)."""
    try:
        service = AssetApplicationService(ctx)
        cpu_cores, memory_gb = service.probe_self_hosted_hardware(
            host=request.host,
            ssh_port=request.ssh_port,
            ssh_username=request.ssh_username,
            ssh_password=request.ssh_password,
            ssh_private_key=request.ssh_private_key,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Hardware probe failed: {e}",
        ) from e
    return HardwareProbeResponse(cpu_cores=cpu_cores, memory_gb=memory_gb)
