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
    fleet_scheduler: dict


class FleetMatrixUpdateRequest(BaseModel):
    fleet_matrix: dict


class SentinelUpdateRequest(BaseModel):
    sentinel_enabled: bool | None = None
    sentinel_poll_interval_seconds: float | None = None
    sentinel_probe_timeout_seconds: int | None = None
    sentinel_heal_cooldown_seconds: float | None = None
    sentinel_probe_retry_cooldown_seconds: float | None = None
    sentinel_suspicious_lookback_minutes: int | None = None
    sentinel_zero_uplink_window_minutes: int | None = None
    sentinel_probe_mode: str | None = None
    sentinel_probe_confirm_cycles: int | None = None
    sentinel_probe_min_cn_probe_count: int | None = None
    sentinel_probe_required_success_ratio: float | None = None
    sentinel_probe_allow_auto_heal_hy2: bool | None = None


class FleetSchedulerUpdateRequest(BaseModel):
    enabled: bool | None = None
    poll_interval_seconds: float | None = None
    cooldown_seconds: float | None = None
    max_tasks_per_cycle: int | None = None
    enabled_regions: list[str] | None = None
    enabled_protocols: list[str] | None = None


class AppUpdateRequest(BaseModel):
    environment: str | None = None
    request_timeout_seconds: int | None = None
    max_retries: int | None = None
    retry_backoff_seconds: float | None = None
    daemon_idle_poll_interval_seconds: float | None = None
    daemon_failure_backoff_seconds: float | None = None
    daemon_stale_task_recovery_interval_seconds: float | None = None
    daemon_running_task_timeout_seconds: float | None = None
    daemon_recovered_task_retry_delay_seconds: float | None = None
    phone_home_base_url: str | None = None
    phone_home_listen_host: str | None = None
    phone_home_listen_port: int | None = None
    phone_home_ready_timeout_seconds: float | None = None
    phone_home_poll_interval_seconds: float | None = None
    artifact_cache_listen_port: int | None = None
    artifact_cache_base_url_override: str | None = None
    probe_server_enabled: bool | None = None
    probe_poll_interval_seconds: float | None = None
    probe_heartbeat_timeout_seconds: float | None = None
    key_pair_local_dir: str | None = None
    skip_rollback_on_failure: bool | None = None


class LoggingUpdateRequest(BaseModel):
    level: str | None = None
    log_retention_days: int | None = None


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
        fleet_scheduler=raw.get("fleet_scheduler", {}),
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
    sentinel_fields = {
        "sentinel_enabled": request.sentinel_enabled,
        "sentinel_poll_interval_seconds": request.sentinel_poll_interval_seconds,
        "sentinel_probe_timeout_seconds": request.sentinel_probe_timeout_seconds,
        "sentinel_heal_cooldown_seconds": request.sentinel_heal_cooldown_seconds,
        "sentinel_probe_retry_cooldown_seconds": request.sentinel_probe_retry_cooldown_seconds,
        "sentinel_suspicious_lookback_minutes": request.sentinel_suspicious_lookback_minutes,
        "sentinel_zero_uplink_window_minutes": request.sentinel_zero_uplink_window_minutes,
        "sentinel_probe_mode": request.sentinel_probe_mode,
        "sentinel_probe_confirm_cycles": request.sentinel_probe_confirm_cycles,
        "sentinel_probe_min_cn_probe_count": request.sentinel_probe_min_cn_probe_count,
        "sentinel_probe_required_success_ratio": request.sentinel_probe_required_success_ratio,
        "sentinel_probe_allow_auto_heal_hy2": request.sentinel_probe_allow_auto_heal_hy2,
    }
    for key, value in sentinel_fields.items():
        if value is not None:
            app[key] = value
    save_raw_config(None, raw)
    return {"status": "ok", "message": "Sentinel settings updated. Restart the daemon to apply."}


@router.put("/fleet-scheduler")
async def update_fleet_scheduler(
    request: FleetSchedulerUpdateRequest,
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(require_admin),
) -> dict:
    raw = load_raw_config()
    scheduler = raw.setdefault("fleet_scheduler", {})
    fields = {
        "enabled": request.enabled,
        "poll_interval_seconds": request.poll_interval_seconds,
        "cooldown_seconds": request.cooldown_seconds,
        "max_tasks_per_cycle": request.max_tasks_per_cycle,
        "enabled_regions": request.enabled_regions,
        "enabled_protocols": request.enabled_protocols,
    }
    for key, value in fields.items():
        if value is not None:
            scheduler[key] = value
    save_raw_config(None, raw)
    return {"status": "ok", "message": "Fleet scheduler settings updated. Restart the daemon to apply."}


@router.put("/app")
async def update_app(
    request: AppUpdateRequest,
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(require_admin),
) -> dict:
    raw = load_raw_config()
    app = raw.setdefault("app", {})
    fields = {
        "environment": request.environment,
        "request_timeout_seconds": request.request_timeout_seconds,
        "max_retries": request.max_retries,
        "retry_backoff_seconds": request.retry_backoff_seconds,
        "daemon_idle_poll_interval_seconds": request.daemon_idle_poll_interval_seconds,
        "daemon_failure_backoff_seconds": request.daemon_failure_backoff_seconds,
        "daemon_stale_task_recovery_interval_seconds": request.daemon_stale_task_recovery_interval_seconds,
        "daemon_running_task_timeout_seconds": request.daemon_running_task_timeout_seconds,
        "daemon_recovered_task_retry_delay_seconds": request.daemon_recovered_task_retry_delay_seconds,
        "phone_home_base_url": request.phone_home_base_url,
        "phone_home_listen_host": request.phone_home_listen_host,
        "phone_home_listen_port": request.phone_home_listen_port,
        "phone_home_ready_timeout_seconds": request.phone_home_ready_timeout_seconds,
        "phone_home_poll_interval_seconds": request.phone_home_poll_interval_seconds,
        "artifact_cache_listen_port": request.artifact_cache_listen_port,
        "artifact_cache_base_url_override": request.artifact_cache_base_url_override,
        "probe_server_enabled": request.probe_server_enabled,
        "probe_poll_interval_seconds": request.probe_poll_interval_seconds,
        "probe_heartbeat_timeout_seconds": request.probe_heartbeat_timeout_seconds,
        "key_pair_local_dir": request.key_pair_local_dir,
        "skip_rollback_on_failure": request.skip_rollback_on_failure,
    }
    for key, value in fields.items():
        if value is not None:
            app[key] = value
    save_raw_config(None, raw)
    return {"status": "ok", "message": "Application settings updated. Restart the daemon to apply."}


@router.put("/logging")
async def update_logging(
    request: LoggingUpdateRequest,
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(require_admin),
) -> dict:
    raw = load_raw_config()
    logging_cfg = raw.setdefault("logging", {})
    if request.level is not None:
        logging_cfg["level"] = request.level
    if request.log_retention_days is not None:
        logging_cfg["log_retention_days"] = request.log_retention_days
    save_raw_config(None, raw)
    return {"status": "ok", "message": "Logging settings updated."}


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
