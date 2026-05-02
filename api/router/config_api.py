from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.auth.dependencies import require_admin
from api.deps import get_runtime_context
from services.runtime_service import RuntimeContext
from utils.config_parser import load_raw_config, save_raw_config


router = APIRouter(prefix="/api/v1/config")


class ConfigResponse(BaseModel):
    app: dict
    logging: dict
    telegram: dict
    cloudflare: dict
    aws_proxy: dict
    xboard: dict | None
    fleet_matrix: dict


class FleetMatrixUpdateRequest(BaseModel):
    fleet_matrix: dict


class SentinelUpdateRequest(BaseModel):
    sentinel_enabled: bool | None = None
    sentinel_poll_interval_seconds: float | None = None
    sentinel_probe_timeout_seconds: int | None = None
    sentinel_heal_cooldown_seconds: float | None = None
    sentinel_probe_confirm_cycles: int | None = None


class DashboardUpdateRequest(BaseModel):
    dashboard_require_password: bool | None = None
    dashboard_password: str | None = None


class ConfigValidateRequest(BaseModel):
    config: dict


@router.get("", response_model=ConfigResponse)
async def get_config(
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(require_admin),
) -> ConfigResponse:
    raw = load_raw_config()
    return ConfigResponse(
        app=raw.get("app", {}),
        logging=raw.get("logging", {}),
        telegram=raw.get("telegram", {}),
        cloudflare=raw.get("cloudflare", {}),
        aws_proxy=raw.get("aws_proxy", {}),
        xboard=raw.get("xboard"),
        fleet_matrix=raw.get("fleet_matrix", {}),
    )


@router.put("/fleet-matrix")
async def update_fleet_matrix(
    request: FleetMatrixUpdateRequest,
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(require_admin),
) -> dict:
    raw = load_raw_config()
    raw["fleet_matrix"] = request.fleet_matrix
    save_raw_config(None, raw)
    return {"status": "ok", "message": "Fleet matrix updated. Restart the daemon to apply."}


@router.put("/sentinel")
async def update_sentinel(
    request: SentinelUpdateRequest,
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(require_admin),
) -> dict:
    raw = load_raw_config()
    app = raw.setdefault("app", {})
    if request.sentinel_enabled is not None:
        app["sentinel_enabled"] = request.sentinel_enabled
    if request.sentinel_poll_interval_seconds is not None:
        app["sentinel_poll_interval_seconds"] = request.sentinel_poll_interval_seconds
    if request.sentinel_probe_timeout_seconds is not None:
        app["sentinel_probe_timeout_seconds"] = request.sentinel_probe_timeout_seconds
    if request.sentinel_heal_cooldown_seconds is not None:
        app["sentinel_heal_cooldown_seconds"] = request.sentinel_heal_cooldown_seconds
    if request.sentinel_probe_confirm_cycles is not None:
        app["sentinel_probe_confirm_cycles"] = request.sentinel_probe_confirm_cycles
    save_raw_config(None, raw)
    return {"status": "ok", "message": "Sentinel settings updated. Restart the daemon to apply."}


@router.put("/dashboard")
async def update_dashboard(
    request: DashboardUpdateRequest,
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(require_admin),
) -> dict:
    raw = load_raw_config()
    app = raw.setdefault("app", {})
    if request.dashboard_require_password is not None:
        app["dashboard_require_password"] = request.dashboard_require_password
    if request.dashboard_password is not None:
        app["dashboard_password"] = request.dashboard_password
    save_raw_config(None, raw)
    return {"status": "ok", "message": "Dashboard settings updated."}


@router.post("/validate")
async def validate_config(
    request: ConfigValidateRequest,
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(require_admin),
) -> dict:
    from models.config_models import AppConfig
    from pydantic import ValidationError
    try:
        AppConfig.model_validate(request.config)
        return {"valid": True, "message": "Configuration is valid"}
    except ValidationError as e:
        return {"valid": False, "errors": e.errors()}
