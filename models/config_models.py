from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AppRuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment: Literal["development", "staging", "production"] = "development"
    sqlite_path: str = "shadowfleet.db"
    request_timeout_seconds: int = 10
    max_retries: int = 3
    retry_backoff_seconds: float = 1.0
    daemon_idle_poll_interval_seconds: float = 5.0
    daemon_failure_backoff_seconds: float = 5.0
    daemon_stale_task_recovery_interval_seconds: float = 30.0
    daemon_running_task_timeout_seconds: float = 900.0
    daemon_recovered_task_retry_delay_seconds: float = 10.0
    phone_home_base_url: str | None = None
    phone_home_listen_host: str = "::"  # "::" binds all interfaces (IPv6+IPv4 on Linux); "0.0.0.0" for IPv4-only
    phone_home_listen_port: int = 8787
    phone_home_ready_timeout_seconds: float = 300.0
    phone_home_poll_interval_seconds: float = 5.0
    sentinel_enabled: bool = False
    sentinel_poll_interval_seconds: float = 180.0
    sentinel_probe_timeout_seconds: int = 10
    sentinel_heal_cooldown_seconds: float = 900.0
    sentinel_probe_retry_cooldown_seconds: float = 300.0
    sentinel_suspicious_lookback_minutes: int = 60
    sentinel_zero_uplink_window_minutes: int = 3
    sentinel_probe_zero_traffic_nodes: bool = False  # 是否探测历史无流量的节点
    sentinel_probe_provider: str = "local_active_probe"
    sentinel_probe_api_base_url: str | None = None
    sentinel_probe_api_token: str | None = None
    sentinel_probe_mode: Literal["local_active_probe", "cn_probe_mesh"] = "cn_probe_mesh"
    sentinel_probe_confirm_cycles: int = 2
    sentinel_probe_result_wait_timeout_seconds: float = 30.0
    sentinel_probe_min_cn_probe_count: int = 2
    sentinel_probe_required_success_ratio: float = 0.5
    sentinel_probe_allow_auto_heal_hy2: bool = False
    artifact_cache_dir: str = "/var/www/shadowfleet-artifacts"
    artifact_cache_listen_port: int = 8080
    artifact_cache_base_url_override: str | None = None  # manual override, e.g. "http://[::1]:8080"
    probe_server_enabled: bool = False
    probe_bootstrap_tokens: list[str] = Field(default_factory=list)
    probe_poll_interval_seconds: float = 5.0
    probe_heartbeat_timeout_seconds: float = 60.0
    xboard_sentinel_api_base_url: str | None = None
    xboard_sentinel_api_key: str | None = None
    key_pair_local_dir: str = "key_pairs"
    skip_rollback_on_failure: bool = False
    jwt_secret: str | None = None

    @field_validator("request_timeout_seconds")
    @classmethod
    def validate_request_timeout_seconds(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("request_timeout_seconds must be greater than 0")
        return value

    @field_validator("max_retries")
    @classmethod
    def validate_max_retries(cls, value: int) -> int:
        if value < 0:
            raise ValueError("max_retries must be greater than or equal to 0")
        return value

    @field_validator("retry_backoff_seconds")
    @classmethod
    def validate_retry_backoff_seconds(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("retry_backoff_seconds must be greater than 0")
        return value

    @field_validator(
        "daemon_idle_poll_interval_seconds",
        "daemon_failure_backoff_seconds",
        "daemon_stale_task_recovery_interval_seconds",
        "daemon_running_task_timeout_seconds",
        "daemon_recovered_task_retry_delay_seconds",
        "phone_home_ready_timeout_seconds",
        "phone_home_poll_interval_seconds",
        "sentinel_poll_interval_seconds",
        "sentinel_heal_cooldown_seconds",
        "sentinel_probe_retry_cooldown_seconds",
        "sentinel_probe_result_wait_timeout_seconds",
        "probe_poll_interval_seconds",
        "probe_heartbeat_timeout_seconds",
    )
    @classmethod
    def validate_positive_float_settings(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("daemon timing settings must be greater than 0")
        return value

    @field_validator("phone_home_base_url")
    @classmethod
    def validate_phone_home_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("phone_home_base_url must not be empty when configured")
        return value.strip()

    @field_validator("phone_home_listen_host")
    @classmethod
    def validate_phone_home_listen_host(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("phone_home_listen_host must not be empty")
        return value.strip()

    @field_validator("phone_home_listen_port")
    @classmethod
    def validate_phone_home_listen_port(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("phone_home_listen_port must be greater than 0")
        return value

    @field_validator(
        "sentinel_probe_timeout_seconds",
        "sentinel_suspicious_lookback_minutes",
        "sentinel_zero_uplink_window_minutes",
        "sentinel_probe_confirm_cycles",
        "sentinel_probe_min_cn_probe_count",
    )
    @classmethod
    def validate_positive_monitoring_numbers(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("sentinel monitoring numeric settings must be greater than 0")
        return value

    @field_validator("sentinel_probe_provider")
    @classmethod
    def validate_sentinel_probe_provider(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("sentinel_probe_provider must not be empty")
        return value.strip()

    @field_validator(
        "sentinel_probe_api_base_url",
        "sentinel_probe_api_token",
        "xboard_sentinel_api_base_url",
        "xboard_sentinel_api_key",
    )
    @classmethod
    def validate_optional_monitoring_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("monitoring optional string settings must not be empty")
        return value.strip()

    @field_validator("probe_bootstrap_tokens")
    @classmethod
    def validate_probe_bootstrap_tokens(cls, value: list[str]) -> list[str]:
        normalized_tokens: list[str] = []
        for token in value:
            normalized_token = token.strip()
            if not normalized_token:
                raise ValueError("probe bootstrap tokens must not be empty")
            normalized_tokens.append(normalized_token)
        return normalized_tokens

    @field_validator("sentinel_probe_required_success_ratio")
    @classmethod
    def validate_success_ratio(cls, value: float) -> float:
        if value <= 0 or value > 1:
            raise ValueError("sentinel_probe_required_success_ratio must be within (0, 1]")
        return value

    @field_validator("artifact_cache_dir")
    @classmethod
    def validate_artifact_cache_dir(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("artifact_cache_dir must not be empty")
        return value.strip()

    @model_validator(mode="after")
    def validate_sentinel_and_probe_server(self) -> "AppRuntimeConfig":
        if self.sentinel_probe_min_cn_probe_count < 2:
            raise ValueError("sentinel_probe_min_cn_probe_count must be at least 2")
        if self.probe_server_enabled and not self.probe_bootstrap_tokens:
            raise ValueError("probe_bootstrap_tokens is required when probe_server_enabled is true")
        if self.sentinel_enabled and self.xboard_sentinel_api_base_url is None:
            raise ValueError(
                "xboard_sentinel_api_base_url is required when sentinel_enabled is true"
            )
        if self.sentinel_enabled and self.xboard_sentinel_api_key is None:
            raise ValueError(
                "xboard_sentinel_api_key is required when sentinel_enabled is true"
            )
        return self


class LoggingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    format: str = (
        "%(asctime)s | %(levelname)s | %(name)s | correlation_id=%(correlation_id)s "
        "| event_type=%(event_type)s | %(message)s"
    )
    logs_dir: str = "logs"
    log_retention_days: int = 30


class TelegramConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    bot_token: str | None = None
    chat_id: str | None = None
    message_prefix: str = "[ShadowFleet]"

    @model_validator(mode="after")
    def validate_enabled_credentials(self) -> "TelegramConfig":
        if self.enabled:
            if not self.bot_token or not self.bot_token.strip():
                raise ValueError("telegram.bot_token is required when telegram.enabled is true")
            if not self.chat_id or not self.chat_id.strip():
                raise ValueError("telegram.chat_id is required when telegram.enabled is true")
        return self


class CloudflareConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    api_token: str | None = None
    zone_id: str | None = None
    root_domain: str | None = None
    auto_subdomain_prefix: str = "sf"
    acme_email: str | None = None
    base_url: str = "https://api.cloudflare.com/client/v4"

    @model_validator(mode="after")
    def validate_enabled_credentials(self) -> "CloudflareConfig":
        if self.enabled:
            if not self.api_token or not self.api_token.strip():
                raise ValueError("cloudflare.api_token is required when cloudflare.enabled is true")
            if not self.zone_id or not self.zone_id.strip():
                raise ValueError("cloudflare.zone_id is required when cloudflare.enabled is true")
        return self

    @field_validator("acme_email")
    @classmethod
    def validate_acme_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("cloudflare.acme_email must not be empty when configured")
        return value.strip()

    @field_validator("root_domain")
    @classmethod
    def validate_root_domain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("cloudflare.root_domain must not be empty when configured")
        return value.strip().rstrip(".")

    @field_validator("auto_subdomain_prefix")
    @classmethod
    def validate_auto_subdomain_prefix(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("cloudflare.auto_subdomain_prefix must not be empty")
        return value.strip()


class AwsProxyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    provider: Literal["decodo", "evomi"] = "evomi"
    base_url: str = "https://api.evomi.com"
    authorization: str | None = None
    username: str | None = None
    password: str | None = None
    api_key: str | None = None
    proxy_type: str = "residential_proxies"
    auth_type: Literal["basic", "whitelist"] = "basic"
    session_type: Literal["sticky", "random", "hard"] = "sticky"
    session_duration_minutes: int = Field(default=10, alias="session_duration")
    location: str = "random"
    output_format: str = "protocol:auth@endpoint"
    response_type: Literal["json"] = "json"
    domain: str = "decodo.com"
    count: int = 1
    page: int = 1
    product: Literal["rp", "rpc"] = "rp"
    protocol: Literal["http", "https", "socks5"] = "http"
    country: str | None = None
    region: str | None = None
    city: str | None = None
    session_id: str | None = None
    adblock_enabled: bool = False

    @field_validator(
        "base_url",
        "authorization",
        "username",
        "password",
        "api_key",
        "proxy_type",
        "location",
        "output_format",
        "domain",
        "country",
        "region",
        "city",
        "session_id",
    )
    @classmethod
    def validate_optional_non_empty_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("aws_proxy string settings must not be empty")
        return value.strip()

    @field_validator("session_duration_minutes", "count", "page")
    @classmethod
    def validate_positive_numbers(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("aws_proxy numeric settings must be greater than 0")
        return value

    @field_validator("country")
    @classmethod
    def normalize_country(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip().upper()

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized.isalnum() or not 6 <= len(normalized) <= 10:
            raise ValueError("aws_proxy.session_id must be 6-10 alphanumeric characters")
        return normalized

    @model_validator(mode="after")
    def validate_enabled_credentials(self) -> "AwsProxyConfig":
        if not self.enabled:
            return self

        if self.provider == "decodo":
            if self.authorization is None:
                raise ValueError("aws_proxy.authorization is required when aws_proxy.enabled is true")
            if self.username is None:
                raise ValueError("aws_proxy.username is required when aws_proxy.enabled is true")
            if self.password is None:
                raise ValueError("aws_proxy.password is required when aws_proxy.enabled is true")
            if self.session_type == "hard":
                raise ValueError("aws_proxy.session_type=hard is only supported for provider=evomi")
            return self

        if self.api_key is None:
            raise ValueError("aws_proxy.api_key is required when aws_proxy.provider is evomi")
        if self.adblock_enabled and self.product != "rp":
            raise ValueError("aws_proxy.adblock_enabled is only supported for aws_proxy.product=rp")
        if self.protocol == "socks5":
            raise ValueError("aws_proxy.protocol=socks5 is not supported for AWS SDK proxying")
        if self.region is not None and self.country is None:
            raise ValueError("aws_proxy.country is required when aws_proxy.region is configured")
        if self.city is not None and self.country is None:
            raise ValueError("aws_proxy.country is required when aws_proxy.city is configured")
        if self.session_type == "hard" and self.session_duration_minutes != 10:
            raise ValueError("aws_proxy.session_duration must not be customized when session_type=hard")
        if self.session_duration_minutes > 120:
            raise ValueError("aws_proxy.session_duration must be less than or equal to 120")
        return self


class XboardDatabaseConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str
    port: int = 5432
    database: str
    user: str
    password: str | None = None
    ssl_mode: str = Field(default="prefer", alias="sslmode")
    v2bx_api_host: str | None = None
    v2bx_api_key: str | None = None

    @field_validator("host", "database", "user")
    @classmethod
    def validate_required_fields(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("value must not be empty")
        return value.strip()

    @field_validator("port")
    @classmethod
    def validate_port(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("port must be greater than 0")
        return value

    @field_validator("v2bx_api_host")
    @classmethod
    def validate_v2bx_api_host(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("v2bx_api_host must not be empty when configured")
        return value.strip().rstrip("/")

    @field_validator("v2bx_api_key")
    @classmethod
    def validate_v2bx_api_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("v2bx_api_key must not be empty when configured")
        return value.strip()

    @model_validator(mode="after")
    def validate_v2bx_required(self) -> "XboardDatabaseConfig":
        if self.v2bx_api_host is None and self.v2bx_api_key is None:
            return self
        if self.v2bx_api_host is None:
            raise ValueError("v2bx_api_host is required when v2bx_api_key is configured")
        if self.v2bx_api_key is None:
            raise ValueError("v2bx_api_key is required when v2bx_api_host is configured")
        return self


class FleetProtocolConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    desired_count: int
    min_alert_threshold: int

    @field_validator("desired_count", "min_alert_threshold")
    @classmethod
    def validate_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("value must be greater than or equal to 0")
        return value

    @model_validator(mode="after")
    def validate_threshold(self) -> "FleetProtocolConfig":
        if self.min_alert_threshold > self.desired_count:
            raise ValueError("min_alert_threshold must not exceed desired_count")
        return self


class FleetSchedulerConfig(BaseModel):
    """Fleet Auto-Scheduler configuration for automatic node replenishment."""
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    poll_interval_seconds: float = 30.0
    cooldown_seconds: float = 60.0
    max_tasks_per_cycle: int = 5
    enabled_regions: list[str] = Field(default_factory=lambda: ["*"])
    enabled_protocols: list[str] = Field(default_factory=lambda: ["*"])
    enabled_asset_types: list[Literal["digitalocean", "vultr", "azure", "oci", "kamatera", "aws"]] = Field(
        default_factory=lambda: ["digitalocean", "vultr", "azure", "oci", "kamatera", "aws"]
    )
    default_group_ids: list[int] = Field(default_factory=list)

    @field_validator("poll_interval_seconds", "cooldown_seconds")
    @classmethod
    def validate_positive_interval(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("must be greater than 0")
        return v

    @field_validator("max_tasks_per_cycle")
    @classmethod
    def validate_max_tasks(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("max_tasks_per_cycle must be at least 1")
        return v

    @field_validator("enabled_asset_types")
    @classmethod
    def validate_enabled_asset_types(cls, v: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(item.strip() for item in v if item and item.strip()))
        if not normalized:
            raise ValueError("enabled_asset_types must not be empty")
        return normalized


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app: AppRuntimeConfig = Field(default_factory=AppRuntimeConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    cloudflare: CloudflareConfig = Field(default_factory=CloudflareConfig)
    aws_proxy: AwsProxyConfig = Field(default_factory=AwsProxyConfig)
    xboard: XboardDatabaseConfig | None = None
    fleet_matrix: dict[str, dict[str, FleetProtocolConfig]] = Field(default_factory=dict)
    fleet_scheduler: FleetSchedulerConfig = Field(default_factory=FleetSchedulerConfig)
