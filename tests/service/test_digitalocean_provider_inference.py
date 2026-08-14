from __future__ import annotations

from unittest.mock import MagicMock

from database.state_repo import NODE_SELECT_COLUMNS
from services.monitor_support import infer_node_asset_type


def test_prefixed_digitalocean_account_overrides_legacy_aws_asset_type() -> None:
    node = MagicMock(
        asset_type="aws",
        aws_account_id="digitalocean:account-uuid",
    )

    assert infer_node_asset_type(node) == "digitalocean"


def test_state_query_recovers_digitalocean_type_without_allocation() -> None:
    assert "LIKE 'digitalocean:%' THEN 'digitalocean'" in NODE_SELECT_COLUMNS
