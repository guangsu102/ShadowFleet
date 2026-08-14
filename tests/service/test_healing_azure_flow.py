from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock, patch

import pytest

from database.asset_models import AssetRecord
from database.state_models import FleetNodeRecord
from services.healing_azure_flow import (
    _azure_credentials,
    _resolve_azure_asset,
    heal_azure_node,
)
from services.healing_models import HealRequest, HealerServiceError


def _runtime() -> MagicMock:
    runtime = MagicMock()
    runtime.config.cloudflare.enabled = True
    runtime.correlation_id = "azure-heal-correlation"
    return runtime


def _asset() -> AssetRecord:
    return AssetRecord(
        id=7,
        asset_type="azure",
        asset_name="azure-japan",
        status="active",
        region="japaneast",
        aws_account_id="azure:subscription",
        aws_access_key="client-id",
        aws_secret_key="client-secret",
        ssh_host=None,
        ssh_port=None,
        ssh_username=None,
        ssh_password=None,
        ssh_private_key=None,
        default_instance_type="Standard_B1s",
        default_vcpu=1,
        account_total_vcpu=10,
        default_architecture="x64",
        provider_config={
            "tenant_id": "tenant-id",
            "subscription_id": "subscription",
            "resource_group": "shadowfleet-rg",
        },
    )


def _node() -> FleetNodeRecord:
    return FleetNodeRecord(
        id=11,
        xboard_node_id=12345,
        node_name="sf-azure",
        node_type="AnyTLS",
        status="offline",
        status_reason="blocked",
        aws_account_id="azure:subscription",
        aws_region="japaneast",
        aws_instance_id=(
            "/subscriptions/subscription/resourceGroups/shadowfleet-rg/providers/"
            "Microsoft.Compute/virtualMachines/sf-azure"
        ),
        aws_subnet_id="subnet-id",
        aws_security_group_id="nsg-id",
        cloudflare_record_id="old-record-id",
        domain_name="sf-azure.example.com",
        ipv4_address="192.0.2.1",
        ipv6_address="2001:db8::1",
        last_known_host="sf-azure.example.com",
        last_error=None,
        is_deleted=False,
        created_at="2026-08-14T00:00:00Z",
        updated_at="2026-08-14T00:00:00Z",
        online_at=None,
        offline_at="2026-08-14T00:00:00Z",
        deleted_at=None,
        last_healed_at=None,
        xboard_status=None,
        xboard_show=None,
        xboard_updated_at=None,
        asset_type="azure",
    )


def test_heal_azure_node_rotates_dns_and_commits_state() -> None:
    runtime = _runtime()
    node = _node()
    asset_repo = MagicMock()
    asset_repo.get_asset_by_xboard_node_id.return_value = _asset()
    state_repo = MagicMock()
    xboard_repo = MagicMock()
    azure_client = MagicMock()
    azure_client.rotate_vm_ipv6_public_ip.return_value = (
        "2001:db8::1",
        "2001:db8::2",
    )
    cf_client = MagicMock()
    cf_client.sync_aaaa_record.return_value = "new-record-id"

    with patch(
        "services.healing_azure_flow.AzureClient",
        return_value=azure_client,
    ) as azure_client_type, patch(
        "services.healing_azure_flow.CFClient",
        return_value=cf_client,
    ):
        result = heal_azure_node(
            runtime_context=runtime,
            asset_repo=asset_repo,
            state_repo=state_repo,
            xboard_repo=xboard_repo,
            node_record=node,
            request=HealRequest(
                xboard_node_id=node.xboard_node_id,
                reason="confirmed_blocked_by_gfw",
            ),
            started_monotonic=0.0,
        )

    credentials = azure_client_type.call_args.kwargs["credentials"]
    assert credentials.tenant_id == "tenant-id"
    assert credentials.client_id == "client-id"
    assert credentials.subscription_id == "subscription"
    azure_client.rotate_vm_ipv6_public_ip.assert_called_once_with(
        node.aws_instance_id
    )
    cf_client.sync_aaaa_record.assert_called_once_with(
        record_name=node.domain_name,
        ipv6_address="2001:db8::2",
        proxied=False,
    )
    first_metadata_update = state_repo.update_node_runtime_metadata.call_args_list[0]
    assert first_metadata_update.kwargs == {
        "xboard_node_id": node.xboard_node_id,
        "ipv6_address": "2001:db8::2",
    }
    final_metadata_update = state_repo.update_node_runtime_metadata.call_args_list[1]
    assert final_metadata_update.kwargs["cloudflare_record_id"] == "new-record-id"
    assert final_metadata_update.kwargs["ipv6_address"] == "2001:db8::2"
    xboard_repo.update_node_host.assert_called_once_with(
        node.xboard_node_id, node.domain_name
    )
    xboard_repo.mark_node_online.assert_called_once_with(node.xboard_node_id)
    state_repo.update_node_status.assert_called_once_with(
        xboard_node_id=node.xboard_node_id,
        status="online",
        status_reason=None,
        last_error=None,
    )
    event = state_repo.create_event.call_args.args[0]
    assert event.event_type == "healing_completed"
    assert event.payload["strategy"] == "azure_ipv6_rotate"
    assert event.payload["new_ipv6_address"] == "2001:db8::2"
    assert result.success is True
    assert result.asset_type == "azure"
    assert result.strategy == "azure_ipv6_rotate"
    assert result.cloudflare_record_id == "new-record-id"
    asset_repo.list_assets_by_aws_account_id.assert_not_called()


def test_resolve_azure_asset_rejects_mismatched_allocation() -> None:
    asset_repo = MagicMock()
    asset_repo.get_asset_by_xboard_node_id.return_value = replace(
        _asset(), asset_type="vultr"
    )

    with pytest.raises(HealerServiceError, match="non-Azure asset"):
        _resolve_azure_asset(asset_repo=asset_repo, node_record=_node())

    asset_repo.list_assets_by_aws_account_id.assert_not_called()


def test_azure_credentials_reject_vm_subscription_mismatch() -> None:
    node = replace(
        _node(),
        aws_instance_id=(
            "/subscriptions/other-subscription/resourceGroups/rg/providers/"
            "Microsoft.Compute/virtualMachines/sf-azure"
        ),
    )

    with pytest.raises(HealerServiceError, match="subscription"):
        _azure_credentials(_asset(), node)
