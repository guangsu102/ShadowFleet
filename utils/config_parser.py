from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from models.config_models import AppConfig


ENVIRONMENT_OVERRIDE_MAP: dict[str, tuple[str, ...]] = {
    "SHADOWFLEET_TELEGRAM_BOT_TOKEN": ("telegram", "bot_token"),
    "SHADOWFLEET_TELEGRAM_CHAT_ID": ("telegram", "chat_id"),
    "SHADOWFLEET_CLOUDFLARE_API_TOKEN": ("cloudflare", "api_token"),
    "SHADOWFLEET_CLOUDFLARE_ZONE_ID": ("cloudflare", "zone_id"),
    "SHADOWFLEET_AWS_PROXY_AUTHORIZATION": ("aws_proxy", "authorization"),
    "SHADOWFLEET_AWS_PROXY_USERNAME": ("aws_proxy", "username"),
    "SHADOWFLEET_AWS_PROXY_PASSWORD": ("aws_proxy", "password"),
    "SHADOWFLEET_XBOARD_PASSWORD": ("xboard", "password"),
    "SHADOWFLEET_SENTINEL_PROBE_API_BASE_URL": ("app", "sentinel_probe_api_base_url"),
    "SHADOWFLEET_SENTINEL_PROBE_API_TOKEN": ("app", "sentinel_probe_api_token"),
    "SHADOWFLEET_XBOARD_SENTINEL_API_BASE_URL": ("app", "xboard_sentinel_api_base_url"),
    "SHADOWFLEET_XBOARD_SENTINEL_API_KEY": ("app", "xboard_sentinel_api_key"),
    "SHADOWFLEET_PROBE_BOOTSTRAP_TOKENS": ("app", "probe_bootstrap_tokens"),
    "SHADOWFLEET_DASHBOARD_PASSWORD": ("app", "dashboard_password"),
}


class ConfigLoadError(RuntimeError):
    """Raised when application configuration cannot be loaded safely."""


def load_config(config_path: str | Path | None = None) -> AppConfig:
    resolved_path = _resolve_config_path(config_path)
    raw_config = _read_yaml_config(resolved_path)
    hydrated_config = _apply_environment_overrides(raw_config)

    try:
        return AppConfig.model_validate(hydrated_config)
    except ValidationError as exc:
        raise ConfigLoadError(f"Invalid configuration in {resolved_path}") from exc


def _resolve_config_path(config_path: str | Path | None) -> Path:
    """Resolve config path with priority: explicit arg > /data/config/config.yaml > /app/config.yaml."""
    if config_path is not None:
        explicit = Path(config_path).expanduser().resolve()
        if explicit.exists():
            return explicit
        raise ConfigLoadError(f"Explicit config_path does not exist: {explicit}")

    for candidate in ("/data/config/config.yaml", "/app/config.yaml"):
        p = Path(candidate)
        if p.exists():
            return p

    raise ConfigLoadError(
        "Configuration file not found. "
        "Mount your config at /data/config/config.yaml, or put config.yaml in the app directory."
    )


def load_raw_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load raw YAML config as dict without Pydantic validation (for UI editors)."""
    resolved_path = _resolve_config_path(config_path)
    return _read_yaml_config(resolved_path)


def save_raw_config(config_path: str | Path | None, config_dict: dict[str, Any]) -> None:
    """Save raw dict as YAML (for UI editors)."""
    resolved_path = _resolve_config_path(config_path)
    with resolved_path.open("w", encoding="utf-8") as f:
        yaml.dump(config_dict, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def sanitize_config_for_logging(config: AppConfig) -> dict[str, Any]:
    sanitized_config = deepcopy(config.model_dump(by_alias=True))

    telegram_config = sanitized_config.get("telegram", {})
    telegram_config["bot_token"] = _mask_secret(telegram_config.get("bot_token"))
    telegram_config["chat_id"] = _mask_secret(telegram_config.get("chat_id"))

    cloudflare_config = sanitized_config.get("cloudflare", {})
    cloudflare_config["api_token"] = _mask_secret(cloudflare_config.get("api_token"))
    cloudflare_config["zone_id"] = _mask_secret(cloudflare_config.get("zone_id"))

    aws_proxy_config = sanitized_config.get("aws_proxy", {})
    aws_proxy_config["authorization"] = _mask_secret(aws_proxy_config.get("authorization"))
    aws_proxy_config["username"] = _mask_secret(aws_proxy_config.get("username"))
    aws_proxy_config["password"] = _mask_secret(aws_proxy_config.get("password"))

    xboard_config = sanitized_config.get("xboard")
    if isinstance(xboard_config, dict):
        xboard_config["password"] = _mask_secret(xboard_config.get("password"))

    app_config = sanitized_config.get("app")
    if isinstance(app_config, dict):
        app_config["sentinel_probe_api_token"] = _mask_secret(
            app_config.get("sentinel_probe_api_token")
        )
        app_config["xboard_sentinel_api_key"] = _mask_secret(
            app_config.get("xboard_sentinel_api_key")
        )
        bootstrap_tokens = app_config.get("probe_bootstrap_tokens")
        if isinstance(bootstrap_tokens, list):
            app_config["probe_bootstrap_tokens"] = [
                _mask_secret(str(token)) for token in bootstrap_tokens
            ]
        app_config["dashboard_password"] = _mask_secret(app_config.get("dashboard_password"))

    return sanitized_config


def _read_yaml_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        raise ConfigLoadError(f"Configuration file does not exist: {config_path}")

    with config_path.open("r", encoding="utf-8") as config_file:
        loaded_config = yaml.safe_load(config_file) or {}

    if not isinstance(loaded_config, dict):
        raise ConfigLoadError("Configuration root must be a mapping")

    return loaded_config


def _apply_environment_overrides(raw_config: dict[str, Any]) -> dict[str, Any]:
    merged_config = deepcopy(raw_config)

    for env_key, path_parts in ENVIRONMENT_OVERRIDE_MAP.items():
        env_value = os.getenv(env_key)
        if env_value is None:
            continue
        if env_key == "SHADOWFLEET_PROBE_BOOTSTRAP_TOKENS":
            parsed_value = [item.strip() for item in env_value.split(",") if item.strip()]
            _set_nested_value(merged_config, path_parts, parsed_value)
            continue
        _set_nested_value(merged_config, path_parts, env_value)

    return merged_config


def _set_nested_value(target: dict[str, Any], path_parts: tuple[str, ...], value: Any) -> None:
    current: dict[str, Any] = target
    for path_part in path_parts[:-1]:
        if isinstance(path_part, str) and path_part.isdigit():
            idx = int(path_part)
            nested_value = current[idx]
        else:
            nested_value = current.get(path_part)
            if not isinstance(nested_value, (dict, list)):
                nested_value = {}
                current[path_part] = nested_value
            elif isinstance(nested_value, list) and path_part.isdigit():
                nested_value = nested_value[idx]
        current = nested_value

    last_part = path_parts[-1]
    if isinstance(last_part, str) and last_part.isdigit():
        current[int(last_part)] = value
    else:
        current[last_part] = value


def _mask_secret(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:2]}***{value[-2:]}"
