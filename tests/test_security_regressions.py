from __future__ import annotations

import asyncio
from inspect import signature
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml
from cryptography.fernet import Fernet
from fastapi import HTTPException
from starlette.responses import Response

from api.auth.db import AuthUserRepo
from api.auth.jwt import _get_secret
from api.middleware import RequestLoggingMiddleware
from api.main import _cors_allowed_origins
from api.auth.router import _parse_user_id
from api.router.config_api import _validate_save_and_reload_config
from api.router.health import CleanupRequest, RepairRequest
from models.config_models import AppRuntimeConfig, FleetSchedulerConfig
from services.database_sync_monitor import DatabaseSyncMonitor
from services.orphan_resource_cleaner import OrphanResourceCleaner
from utils.config_parser import save_raw_config


def test_jwt_secret_fails_closed_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SHADOWFLEET_JWT_SECRET", raising=False)
    monkeypatch.setattr("api.auth.jwt._load_jwt_secret_from_config", lambda: None)

    with pytest.raises(RuntimeError, match="not configured"):
        _get_secret()


def test_jwt_secret_is_trimmed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHADOWFLEET_JWT_SECRET", "  configured-secret  ")

    assert _get_secret() == "configured-secret"


def test_bootstrap_admin_requires_explicit_password(tmp_path: Path) -> None:
    repo = AuthUserRepo(tmp_path / "auth.db")

    with pytest.raises(RuntimeError, match="at least 12 characters"):
        repo.ensure_bootstrap_admin(None)

    assert repo.list_users() == []


def test_bootstrap_admin_is_created_only_once(tmp_path: Path) -> None:
    repo = AuthUserRepo(tmp_path / "auth.db")

    assert repo.ensure_bootstrap_admin("long-bootstrap-password") is True
    assert repo.ensure_bootstrap_admin(None) is False
    assert repo.authenticate("admin", "long-bootstrap-password") is not None


def test_inactive_user_database_does_not_reopen_bootstrap(tmp_path: Path) -> None:
    repo = AuthUserRepo(tmp_path / "auth.db")
    user_id = repo.create_user("operator", "long-user-password", "operator")
    assert repo.delete_user(user_id) is True

    assert repo.ensure_bootstrap_admin("another-bootstrap-password") is False
    assert repo.get_by_username("admin") is None


@pytest.mark.parametrize("subject", [None, "", "not-a-number", "0", "-1"])
def test_invalid_jwt_subject_is_rejected(subject: object) -> None:
    with pytest.raises(HTTPException) as exc_info:
        _parse_user_id(subject)

    assert exc_info.value.status_code == 401


def test_production_requires_strong_valid_secrets() -> None:
    encryption_key = Fernet.generate_key().decode("ascii")

    with pytest.raises(ValueError, match="jwt_secret is required"):
        AppRuntimeConfig(
            environment="production",
            asset_credential_encryption_key=encryption_key,
        )
    with pytest.raises(ValueError, match="at least 32"):
        AppRuntimeConfig(
            environment="production",
            jwt_secret="too-short",
            asset_credential_encryption_key=encryption_key,
        )
    with pytest.raises(ValueError, match="valid Fernet key"):
        AppRuntimeConfig(
            environment="production",
            jwt_secret="x" * 32,
            asset_credential_encryption_key="not-a-fernet-key",
        )

    config = AppRuntimeConfig(
        environment="production",
        jwt_secret="x" * 32,
        asset_credential_encryption_key=encryption_key,
    )
    assert config.environment == "production"


def test_cleanup_and_repair_defaults_are_non_destructive() -> None:
    cleanup = CleanupRequest()
    repair = RepairRequest()

    assert cleanup.dry_run is True
    assert not any(
        value
        for name, value in cleanup.model_dump().items()
        if name.startswith("cleanup_")
    )
    assert repair.dry_run is True
    assert not any(
        value
        for name, value in repair.model_dump().items()
        if name.startswith("repair_")
    )

    cleanup_signature = signature(
        OrphanResourceCleaner.cleanup_orphan_resources
    ).parameters
    repair_signature = signature(
        DatabaseSyncMonitor.auto_repair_inconsistencies
    ).parameters

    assert cleanup_signature["dry_run"].default is True
    assert all(
        parameter.default is False
        for name, parameter in cleanup_signature.items()
        if name.startswith("cleanup_")
    )
    assert repair_signature["dry_run"].default is True
    assert all(
        parameter.default is False
        for name, parameter in repair_signature.items()
        if name.startswith("repair_")
    )


def test_duplicate_provider_region_mapping_is_rejected() -> None:
    with pytest.raises(ValueError, match="mapped to both"):
        FleetSchedulerConfig(
            provider_region_mappings={
                "region-a": {"digitalocean": "sgp1"},
                "region-b": {"digitalocean": "SGP1"},
            }
        )


def test_invalid_config_is_rejected_before_persist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save = MagicMock()
    monkeypatch.setattr("api.router.config_api.save_raw_config", save)

    with pytest.raises(HTTPException) as exc_info:
        _validate_save_and_reload_config(
            MagicMock(),
            {"app": {"request_timeout_seconds": 0}},
        )

    assert exc_info.value.status_code == 422
    save.assert_not_called()


def test_save_raw_config_replaces_file_without_temp_residue(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("old: true\n", encoding="utf-8")

    save_raw_config(config_path, {"app": {"environment": "development"}})

    assert yaml.safe_load(config_path.read_text(encoding="utf-8")) == {
        "app": {"environment": "development"}
    }
    assert list(tmp_path.glob(".config.yaml.*.tmp")) == []
def test_validation_logging_never_reads_request_body() -> None:
    request = MagicMock()
    request.headers = {}
    request.state = MagicMock()
    request.method = "POST"
    request.url.path = "/api/v1/auth/login"
    request.body = MagicMock(side_effect=AssertionError("request body was read"))

    async def call_next(_request):
        return Response(status_code=422)

    middleware = RequestLoggingMiddleware(MagicMock())
    response = asyncio.run(middleware.dispatch(request, call_next))

    assert response.status_code == 422
    request.body.assert_not_called()
def test_cors_origins_are_explicit_and_deduplicated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "SHADOWFLEET_CORS_ALLOWED_ORIGINS",
        "https://console.example, https://console.example,https://ops.example",
    )

    assert _cors_allowed_origins() == [
        "https://console.example",
        "https://ops.example",
    ]


def test_cors_wildcard_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHADOWFLEET_CORS_ALLOWED_ORIGINS", "*")

    with pytest.raises(RuntimeError, match="explicit origins"):
        _cors_allowed_origins()
