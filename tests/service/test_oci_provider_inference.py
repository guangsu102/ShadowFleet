from __future__ import annotations

from unittest.mock import MagicMock

from services.fleet_scheduler_service import FleetSchedulerService
from services.healing_models import HealRequest
from services.healing_support import determine_heal_strategy
from services.monitor_support import infer_node_asset_type


def test_legacy_oci_account_prefix_overrides_old_aws_fallback() -> None:
    node = MagicMock(asset_type="aws", aws_account_id="oci:tenancy-ocid")

    assert infer_node_asset_type(node) == "oci"


def test_oci_node_selects_native_ipv6_rotation() -> None:
    node = MagicMock(
        asset_type="oci",
        aws_account_id="oci:tenancy-ocid",
        node_type="AnyTLS",
    )

    strategy = determine_heal_strategy(
        node,
        HealRequest(xboard_node_id=12345, reason="confirmed_blocked_by_gfw"),
    )

    assert strategy == "oci_ipv6_rotate"


def test_scheduler_accepts_oci_as_the_only_cloud_provider() -> None:
    service = object.__new__(FleetSchedulerService)
    service._runtime = MagicMock()
    service._runtime.config_holder = None
    service._runtime.config.fleet_scheduler.enabled_asset_types = ["oci"]

    assert service._enabled_cloud_asset_types() == ("oci",)
