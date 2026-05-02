"""Unit tests for Pydantic configuration models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from models.config_models import (
    AppRuntimeConfig,
    AppConfig,
    AwsProxyConfig,
    CloudflareConfig,
    FleetProtocolConfig,
    LoggingConfig,
    TelegramConfig,
    XboardDatabaseConfig,
)


class TestAppRuntimeConfig:
    """Tests for AppRuntimeConfig model."""

    def test_defaults(self) -> None:
        """Default values should be set correctly."""
        config = AppRuntimeConfig()
        assert config.environment == "development"
        assert config.sqlite_path == "shadowfleet.db"
        assert config.sentinel_enabled is False
        assert config.dashboard_require_password is False

    def test_custom_values(self) -> None:
        """Custom values should be accepted."""
        config = AppRuntimeConfig(
            environment="production",
            sqlite_path="/data/fleet.db",
            sentinel_enabled=True,
            dashboard_require_password=True,
            dashboard_password="secret",
            xboard_sentinel_api_base_url="https://xboard.example.com/sentinel/api",
            xboard_sentinel_api_key="sentinel_api_key",
        )
        assert config.environment == "production"
        assert config.sqlite_path == "/data/fleet.db"
        assert config.sentinel_enabled is True

    def test_invalid_environment_raises(self) -> None:
        """Invalid environment should raise ValidationError."""
        with pytest.raises(ValidationError):
            AppRuntimeConfig(environment="invalid")

    def test_zero_timeout_raises(self) -> None:
        """request_timeout_seconds <= 0 should raise."""
        with pytest.raises(ValidationError, match="request_timeout_seconds"):
            AppRuntimeConfig(request_timeout_seconds=0)

    def test_negative_max_retries_raises(self) -> None:
        """Negative max_retries should raise."""
        with pytest.raises(ValidationError, match="max_retries"):
            AppRuntimeConfig(max_retries=-1)

    def test_zero_retry_backoff_raises(self) -> None:
        """Zero retry_backoff_seconds should raise."""
        with pytest.raises(ValidationError, match="retry_backoff_seconds"):
            AppRuntimeConfig(retry_backoff_seconds=0)

    def test_password_required_when_required(self) -> None:
        """dashboard_password is required when dashboard_require_password is True."""
        with pytest.raises(ValidationError, match="dashboard_password"):
            AppRuntimeConfig(dashboard_require_password=True)

    def test_sentinel_requires_xboard_api(self) -> None:
        """Sentinel enabled requires xboard sentinel API config."""
        with pytest.raises(ValidationError, match="xboard_sentinel_api_base_url"):
            AppRuntimeConfig(sentinel_enabled=True)

    def test_sentinel_requires_min_cn_probe_count(self) -> None:
        """sentinel_probe_min_cn_probe_count must be >= 2."""
        with pytest.raises(ValidationError, match="sentinel_probe_min_cn_probe_count"):
            AppRuntimeConfig(sentinel_probe_min_cn_probe_count=1)

    def test_probe_server_requires_tokens(self) -> None:
        """probe_server_enabled requires probe_bootstrap_tokens."""
        with pytest.raises(ValidationError, match="probe_bootstrap_tokens"):
            AppRuntimeConfig(probe_server_enabled=True)


class TestTelegramConfig:
    """Tests for TelegramConfig model."""

    def test_disabled_allows_no_credentials(self) -> None:
        """Disabled telegram config should not require credentials."""
        config = TelegramConfig(enabled=False)
        assert config.enabled is False

    def test_enabled_requires_bot_token(self) -> None:
        """Enabled telegram requires bot_token."""
        with pytest.raises(ValidationError, match="bot_token"):
            TelegramConfig(enabled=True, chat_id="123")

    def test_enabled_requires_chat_id(self) -> None:
        """Enabled telegram requires chat_id."""
        with pytest.raises(ValidationError, match="chat_id"):
            TelegramConfig(enabled=True, bot_token="token")

    def test_valid_enabled_config(self) -> None:
        """Valid enabled config should work."""
        config = TelegramConfig(
            enabled=True,
            bot_token="123456:ABC-DEF",
            chat_id="987654",
        )
        assert config.enabled is True
        assert config.bot_token == "123456:ABC-DEF"


class TestCloudflareConfig:
    """Tests for CloudflareConfig model."""

    def test_disabled_allows_no_credentials(self) -> None:
        """Disabled cloudflare should not require credentials."""
        config = CloudflareConfig(enabled=False)
        assert config.enabled is False

    def test_enabled_requires_api_token(self) -> None:
        """Enabled cloudflare requires api_token."""
        with pytest.raises(ValidationError, match="cloudflare.api_token"):
            CloudflareConfig(enabled=True, zone_id="zone123")

    def test_enabled_requires_zone_id(self) -> None:
        """Enabled cloudflare requires zone_id."""
        with pytest.raises(ValidationError, match="cloudflare.zone_id"):
            CloudflareConfig(enabled=True, api_token="token")

    def test_valid_enabled_config(self) -> None:
        """Valid enabled config should work."""
        config = CloudflareConfig(
            enabled=True,
            api_token="cf_token_123",
            zone_id="zone_abc",
            root_domain="example.com",
        )
        assert config.enabled is True
        assert config.root_domain == "example.com"

    def test_root_domain_strips_trailing_dot(self) -> None:
        """root_domain should strip trailing dot."""
        config = CloudflareConfig(root_domain="example.com.")
        assert config.root_domain == "example.com"


class TestAwsProxyConfig:
    """Tests for AwsProxyConfig model."""

    def test_disabled_defaults(self) -> None:
        """Disabled proxy should have defaults."""
        config = AwsProxyConfig(enabled=False)
        assert config.enabled is False
        assert config.provider == "decodo"
        assert config.base_url == "https://api.decodo.com/v2"

    def test_enabled_requires_authorization(self) -> None:
        """Enabled proxy requires authorization."""
        with pytest.raises(ValidationError, match="aws_proxy.authorization"):
            AwsProxyConfig(enabled=True, username="user", password="pass")

    def test_enabled_requires_username(self) -> None:
        """Enabled proxy requires username."""
        with pytest.raises(ValidationError, match="aws_proxy.username"):
            AwsProxyConfig(enabled=True, authorization="auth", password="pass")

    def test_enabled_requires_password(self) -> None:
        """Enabled proxy requires password."""
        with pytest.raises(ValidationError, match="aws_proxy.password"):
            AwsProxyConfig(enabled=True, authorization="auth", username="user")


class TestXboardDatabaseConfig:
    """Tests for XboardDatabaseConfig model."""

    def test_required_fields(self) -> None:
        """Required fields must be provided."""
        config = XboardDatabaseConfig(
            host="localhost",
            database="xboard",
            user="admin",
        )
        assert config.host == "localhost"
        assert config.port == 5432  # default
        assert config.ssl_mode == "prefer"  # default

    def test_empty_host_raises(self) -> None:
        """Empty host should raise."""
        with pytest.raises(ValidationError, match="value must not be empty"):
            XboardDatabaseConfig(host="", database="db", user="user")

    def test_zero_port_raises(self) -> None:
        """Port <= 0 should raise."""
        with pytest.raises(ValidationError, match="port must be greater than 0"):
            XboardDatabaseConfig(host="host", database="db", user="user", port=0)


class TestFleetProtocolConfig:
    """Tests for FleetProtocolConfig model."""

    def test_valid_config(self) -> None:
        """Valid config should work."""
        config = FleetProtocolConfig(desired_count=10, min_alert_threshold=5)
        assert config.desired_count == 10
        assert config.min_alert_threshold == 5

    def test_negative_desired_count_raises(self) -> None:
        """Negative desired_count should raise."""
        with pytest.raises(ValidationError, match="value must be greater than or equal to 0"):
            FleetProtocolConfig(desired_count=-1, min_alert_threshold=0)

    def test_threshold_exceeds_desired_raises(self) -> None:
        """min_alert_threshold > desired_count should raise."""
        with pytest.raises(ValidationError, match="min_alert_threshold must not exceed"):
            FleetProtocolConfig(desired_count=5, min_alert_threshold=10)


class TestAppConfig:
    """Tests for AppConfig model."""

    def test_defaults(self) -> None:
        """Default config should have all sub-configs."""
        config = AppConfig()
        assert isinstance(config.app, AppRuntimeConfig)
        assert isinstance(config.logging, LoggingConfig)
        assert isinstance(config.telegram, TelegramConfig)
        assert isinstance(config.cloudflare, CloudflareConfig)

    def test_full_config(self) -> None:
        """Full config should work."""
        config = AppConfig(
            app=AppRuntimeConfig(environment="production"),
            telegram=TelegramConfig(enabled=True, bot_token="t", chat_id="c"),
            cloudflare=CloudflareConfig(
                enabled=True,
                api_token="cf",
                zone_id="zone",
            ),
            fleet_matrix={
                "ap-northeast-1": {
                    "AnyTLS": FleetProtocolConfig(desired_count=5, min_alert_threshold=2),
                }
            },
        )
        assert config.app.environment == "production"
        assert config.telegram.enabled is True
        assert "ap-northeast-1" in config.fleet_matrix
