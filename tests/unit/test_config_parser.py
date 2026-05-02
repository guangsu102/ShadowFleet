"""Unit tests for utils.config_parser module."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import pytest
import yaml

from utils.config_parser import (
    ConfigLoadError,
    _apply_environment_overrides,
    _mask_secret,
    _read_yaml_config,
    _set_nested_value,
    load_config,
    sanitize_config_for_logging,
)


class TestMaskSecret:
    """Tests for _mask_secret function."""

    def test_mask_none_returns_none(self) -> None:
        """None values should return None."""
        result = _mask_secret(None)
        assert result is None

    def test_mask_short_string_masks_completely(self) -> None:
        """Strings with length <= 4 should be fully masked."""
        result = _mask_secret("abc")
        assert result == "***"

    def test_mask_long_string_shows_partial(self) -> None:
        """Long strings should show first 2 and last 2 characters."""
        result = _mask_secret("abcdefgh")
        assert result == "ab***gh"

    def test_mask_exactly_four_chars(self) -> None:
        """Strings with exactly 4 chars should be fully masked."""
        result = _mask_secret("abcd")
        assert result == "****"


class TestSetNestedValue:
    """Tests for _set_nested_value function."""

    def test_set_single_level(self) -> None:
        """Set a value at single level."""
        target: dict[str, Any] = {}
        _set_nested_value(target, ("key",), "value")
        assert target == {"key": "value"}

    def test_set_nested_path_creates_intermediate(self) -> None:
        """Nested paths should create intermediate dicts."""
        target: dict[str, Any] = {}
        _set_nested_value(target, ("a", "b", "c"), "value")
        assert target == {"a": {"b": {"c": "value"}}}

    def test_set_nested_path_overwrites_existing(self) -> None:
        """Existing values should be overwritten."""
        target = {"a": {"b": "old"}}
        _set_nested_value(target, ("a", "b"), "new")
        assert target == {"a": {"b": "new"}}


class TestReadYamlConfig:
    """Tests for _read_yaml_config function."""

    def test_missing_file_raises_error(self) -> None:
        """Non-existent file should raise ConfigLoadError."""
        with pytest.raises(ConfigLoadError, match="does not exist"):
            _read_yaml_config(Path("/nonexistent/config.yaml"))

    def test_valid_yaml_loads_dict(self) -> None:
        """Valid YAML should return dictionary."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump({"key": "value"}, f)
            f.flush()
            result = _read_yaml_config(Path(f.name))
        assert result == {"key": "value"}
        Path(f.name).unlink()

    def test_empty_yaml_returns_empty_dict(self) -> None:
        """Empty YAML should return empty dict."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            f.flush()
            result = _read_yaml_config(Path(f.name))
        assert result == {}
        Path(f.name).unlink()

    def test_non_mapping_yaml_raises_error(self) -> None:
        """Root must be a mapping, not a list."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(["item1", "item2"], f)
            f.flush()
            with pytest.raises(ConfigLoadError, match="must be a mapping"):
                _read_yaml_config(Path(f.name))
        Path(f.name).unlink()


class TestApplyEnvironmentOverrides:
    """Tests for _apply_environment_overrides function."""

    def test_no_env_vars_unchanged(self) -> None:
        """Without env vars, config should remain unchanged."""
        raw = {"app": {"key": "value"}}
        result = _apply_environment_overrides(raw)
        assert result == raw

    def test_single_env_override(self) -> None:
        """Single env var should override corresponding config path."""
        os.environ["SHADOWFLEET_TELEGRAM_BOT_TOKEN"] = "test_token"
        raw: dict[str, Any] = {"telegram": {"bot_token": "original"}}
        result = _apply_environment_overrides(raw)
        assert result["telegram"]["bot_token"] == "test_token"
        del os.environ["SHADOWFLEET_TELEGRAM_BOT_TOKEN"]

    def test_multiple_env_overrides(self) -> None:
        """Multiple env vars should all apply."""
        os.environ["SHADOWFLEET_TELEGRAM_BOT_TOKEN"] = "token"
        os.environ["SHADOWFLEET_CLOUDFLARE_API_TOKEN"] = "cf_token"
        raw: dict[str, Any] = {"telegram": {}, "cloudflare": {}}
        result = _apply_environment_overrides(raw)
        assert result["telegram"]["bot_token"] == "token"
        assert result["cloudflare"]["api_token"] == "cf_token"
        del os.environ["SHADOWFLEET_TELEGRAM_BOT_TOKEN"]
        del os.environ["SHADOWFLEET_CLOUDFLARE_API_TOKEN"]

    def test_probe_bootstrap_tokens_split(self) -> None:
        """Probe bootstrap tokens should be split by comma."""
        os.environ["SHADOWFLEET_PROBE_BOOTSTRAP_TOKENS"] = "token1, token2 , token3"
        raw: dict[str, Any] = {"app": {"probe_bootstrap_tokens": []}}
        result = _apply_environment_overrides(raw)
        assert result["app"]["probe_bootstrap_tokens"] == ["token1", "token2", "token3"]
        del os.environ["SHADOWFLEET_PROBE_BOOTSTRAP_TOKENS"]


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_valid_config(self) -> None:
        """Valid config should load successfully."""
        config_dict = {
            "app": {"environment": "development", "sqlite_path": ":memory:"},
            "logging": {"level": "DEBUG"},
            "telegram": {"enabled": False},
            "cloudflare": {"enabled": False},
            "aws_proxy": {"enabled": False},
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(config_dict, f)
            f.flush()
            result = load_config(Path(f.name))
        assert result.app.environment == "development"
        assert result.app.sqlite_path == ":memory:"
        Path(f.name).unlink()

    def test_missing_required_field_raises(self) -> None:
        """Missing xboard host should fail validation (it's required)."""
        config_dict = {
            "app": {"environment": "test"},
            "logging": {"level": "DEBUG"},
            "telegram": {"enabled": False},
            "cloudflare": {"enabled": False},
            "aws_proxy": {"enabled": False},
            "xboard": {"host": "", "database": "db"},  # host is required and empty
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(config_dict, f)
            f.flush()
            with pytest.raises(ConfigLoadError):
                load_config(Path(f.name))
        Path(f.name).unlink()


class TestSanitizeConfigForLogging:
    """Tests for sanitize_config_for_logging function."""

    def test_sensitive_fields_masked(self) -> None:
        """Sensitive credentials should be masked in output."""
        from models.config_models import AppConfig

        config = AppConfig(
            app={"environment": "development"},
            logging={"level": "DEBUG"},
            telegram={"enabled": True, "bot_token": "secret_bot_token", "chat_id": "123456"},
            cloudflare={"enabled": True, "api_token": "cf_secret", "zone_id": "zone123"},
            aws_proxy={"enabled": False},
        )
        sanitized = sanitize_config_for_logging(config)

        assert sanitized["telegram"]["bot_token"] != "secret_bot_token"
        assert "***" in sanitized["telegram"]["bot_token"]
        assert sanitized["cloudflare"]["api_token"] != "cf_secret"
