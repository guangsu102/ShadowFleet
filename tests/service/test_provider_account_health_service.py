from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from database.asset_models import AssetRecord
from infrastructure.gcp import GCPClientError
from infrastructure.kamatera import KamateraClientError
from services.provider_account_health_service import (
    is_terminal_provider_account_error,
    quarantine_terminal_provider_error,
)


def _asset(
    asset_id: int,
    *,
    asset_type: str = "gcp",
    status: str = "active",
) -> AssetRecord:
    return AssetRecord(
        id=asset_id,
        asset_type=asset_type,
        asset_name=f"asset-{asset_id}",
        status=status,
        region="asia-east1-a",
        aws_account_id="gcp:project-1",
        aws_access_key="client",
        aws_secret_key="secret",
        ssh_host=None,
        ssh_port=None,
        ssh_username=None,
        ssh_password=None,
        ssh_private_key=None,
        default_instance_type=None,
        default_vcpu=None,
        account_total_vcpu=None,
        default_architecture=None,
    )


@pytest.mark.parametrize(
    ("provider", "error", "expected"),
    [
        ("gcp", GCPClientError("permission denied", 403), False),
        ("gcp", GCPClientError("quota exceeded", 400), False),
        ("gcp", GCPClientError("rate limited", 429), False),
        ("gcp", GCPClientError("connection reset", retryable=True), False),
        ("kamatera", KamateraClientError("invalid credentials", 200), True),
        ("kamatera", KamateraClientError("quota exceeded"), False),
        ("gcp", GCPClientError("invalid credentials", 401), True),
        ("kamatera", KamateraClientError("temporary outage", 503), False),
    ],
)
def test_terminal_provider_account_error_classification(
    provider: str,
    error: BaseException,
    expected: bool,
) -> None:
    assert is_terminal_provider_account_error(provider, error) is expected


def test_quarantine_bans_only_matching_provider_assets() -> None:
    runtime = MagicMock(correlation_id="health-correlation")
    repo = MagicMock()
    repo.list_assets_by_aws_account_id.return_value = [
        _asset(1),
        _asset(2, status="banned"),
        _asset(3, asset_type="aws"),
    ]

    result = quarantine_terminal_provider_error(
        runtime_context=runtime,
        asset_repo=repo,
        provider="gcp",
        account_id="gcp:project-1",
        source_asset_id=1,
        error=GCPClientError("invalid credentials", 401),
    )

    assert result is not None
    assert result.asset_count == 1
    repo.update_asset_status.assert_called_once_with(1, "banned")
    event = repo.create_asset_event.call_args.args[0]
    assert event.asset_id == 1
    assert event.event_type == "provider_account_quarantined"
    assert event.payload["provider"] == "gcp"
    assert event.payload["error_code"] == "401"


def test_transient_provider_error_does_not_change_assets() -> None:
    runtime = MagicMock(correlation_id="health-correlation")
    repo = MagicMock()

    result = quarantine_terminal_provider_error(
        runtime_context=runtime,
        asset_repo=repo,
        provider="kamatera",
        account_id="kamatera:account",
        source_asset_id=4,
        error=KamateraClientError("service unavailable", 503),
    )

    assert result is None
    repo.list_assets_by_aws_account_id.assert_not_called()
    repo.update_asset_status.assert_not_called()
