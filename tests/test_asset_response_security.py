from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from api.router.assets import get_asset


def test_asset_detail_never_returns_cloud_credentials() -> None:
    asset = MagicMock(
        id=7,
        asset_name="aws-production",
        asset_type="aws",
        region="ap-northeast-1",
        status="active",
        aws_account_id="123456789012",
        aws_access_key="must-not-leak",
        aws_secret_key="must-not-leak",
        account_total_vcpu=16,
        cpu_cores=None,
        memory_gb=None,
        remarks=None,
        updated_at="2026-08-14T00:00:00Z",
    )

    with patch("database.asset_repo.AssetRepo") as repo_type:
        repo_type.return_value.get_asset_by_id.return_value = asset
        response = asyncio.run(get_asset(7, ctx=MagicMock(), _current_user=None))

    assert response.aws_access_key is None
    assert response.aws_secret_key is None
