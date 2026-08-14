from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from database.asset_models import AssetRecord
from database.state_models import FleetNodeRecord
from infrastructure.vultr import (
    VultrFirewallEnsureResult,
    VultrInstanceLaunchResult,
)
from services.healing_models import HealRequest
from services.healing_vultr_flow import heal_vultr_node


def _runtime() -> MagicMock:
    runtime = MagicMock()
    runtime.config.cloudflare.enabled = True
    runtime.correlation_id = "vultr-heal-correlation"
    return runtime


def _asset() -> AssetRecord:
    return AssetRecord(
        id=8,
        asset_type="vultr",
        asset_name="vultr-sgp",
        status="active",
        region="sgp",
        aws_account_id="vultr:account",
        aws_access_key="vultr-token",
        aws_secret_key=None,
        ssh_host=None,
        ssh_port=None,
        ssh_username=None,
        ssh_password=None,
        ssh_private_key=None,
        default_instance_type="vc2-1c-1gb",
        default_vcpu=1,
        account_total_vcpu=None,
        default_architecture="x64",
        provider_config={},
    )


def _node() -> FleetNodeRecord:
    return FleetNodeRecord(
        id=12,
        xboard_node_id=12346,
        node_name="sf-vultr",
        node_type="AnyTLS",
        status="offline",
        status_reason="blocked",
        aws_account_id="vultr:account",
        aws_region="sgp",
        aws_instance_id="old-instance",
        aws_subnet_id="vpc-id",
        aws_security_group_id="firewall-id",
        cloudflare_record_id="old-record",
        domain_name="sf-vultr.example.com",
        ipv4_address="192.0.2.10",
        ipv6_address="2001:db8::10",
        last_known_host="sf-vultr.example.com",
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
        asset_type="vultr",
    )


def _source_instance() -> dict[str, object]:
    return {
        "id": "old-instance",
        "region": "sgp",
        "plan": "vc2-1c-1gb",
        "os_id": 2284,
        "v6_main_ip": "2001:db8::10",
        "firewall_group_id": "firewall-id",
        "tags": ["shadowfleet"],
    }


def _replacement() -> VultrInstanceLaunchResult:
    return VultrInstanceLaunchResult(
        instance_id="new-instance",
        label="sf-vultr-heal-deadbeef",
        region="sgp",
        plan="vc2-1c-1gb",
        os_id=2284,
        ipv4_address="192.0.2.11",
        ipv6_address="2001:db8::11",
        subnet_id="vpc-id",
    )


def test_heal_vultr_node_replaces_instance_after_endpoint_is_ready() -> None:
    runtime = _runtime()
    asset_repo = MagicMock()
    asset_repo.get_asset_by_xboard_node_id.return_value = _asset()
    state_repo = MagicMock()
    xboard_repo = MagicMock()
    xboard_repo.get_node_runtime.return_value.server_port = 443
    client = MagicMock()
    client.get_instance.return_value = _source_instance()
    client.get_instance_user_data.return_value = "#!/bin/sh\necho ready\n"
    client.list_instance_vpcs.return_value = [{"id": "vpc-id"}]
    client.ensure_firewall_ports.return_value = VultrFirewallEnsureResult(
        firewall_group_id="firewall-id",
        created=False,
    )
    client.launch_instance.return_value = _replacement()
    cf_client = MagicMock()
    cf_client.sync_aaaa_record.return_value = "new-record"

    with patch(
        "services.healing_vultr_flow.VultrClient",
        return_value=client,
    ), patch(
        "services.healing_vultr_flow.CFClient",
        return_value=cf_client,
    ), patch(
        "services.healing_vultr_flow._wait_for_tcp_endpoint"
    ) as wait_for_endpoint, patch(
        "services.healing_vultr_flow.notify_healing_success"
    ):
        result = heal_vultr_node(
            runtime_context=runtime,
            asset_repo=asset_repo,
            state_repo=state_repo,
            xboard_repo=xboard_repo,
            node_record=_node(),
            request=HealRequest(
                xboard_node_id=12346,
                reason="confirmed_blocked",
            ),
            started_monotonic=0.0,
        )

    wait_for_endpoint.assert_called_once_with(
        "2001:db8::11",
        443,
        timeout_seconds=300,
        poll_interval_seconds=5.0,
    )
    cf_client.sync_aaaa_record.assert_called_once_with(
        record_name="sf-vultr.example.com",
        ipv6_address="2001:db8::11",
        proxied=False,
    )
    metadata = state_repo.update_node_runtime_metadata.call_args.kwargs
    assert metadata["aws_instance_id"] == "new-instance"
    assert metadata["ipv6_address"] == "2001:db8::11"
    client.delete_instance.assert_called_once_with("old-instance")
    assert result.success is True
    assert result.strategy == "vultr_instance_replace"


def test_heal_vultr_node_rolls_back_replacement_when_dns_fails() -> None:
    runtime = _runtime()
    asset_repo = MagicMock()
    asset_repo.get_asset_by_xboard_node_id.return_value = _asset()
    state_repo = MagicMock()
    xboard_repo = MagicMock()
    xboard_repo.get_node_runtime.return_value.server_port = 443
    client = MagicMock()
    client.get_instance.return_value = _source_instance()
    client.get_instance_user_data.return_value = "#!/bin/sh\necho ready\n"
    client.list_instance_vpcs.return_value = []
    client.ensure_firewall_ports.return_value = VultrFirewallEnsureResult(
        firewall_group_id="managed-firewall",
        created=True,
    )
    client.launch_instance.return_value = _replacement()
    cf_client = MagicMock()
    cf_client.sync_aaaa_record.side_effect = RuntimeError("DNS failed")

    with patch(
        "services.healing_vultr_flow.VultrClient",
        return_value=client,
    ), patch(
        "services.healing_vultr_flow.CFClient",
        return_value=cf_client,
    ), patch(
        "services.healing_vultr_flow._wait_for_tcp_endpoint"
    ):
        with pytest.raises(RuntimeError, match="DNS failed"):
            heal_vultr_node(
                runtime_context=runtime,
                asset_repo=asset_repo,
                state_repo=state_repo,
                xboard_repo=xboard_repo,
                node_record=_node(),
                request=HealRequest(
                    xboard_node_id=12346,
                    reason="confirmed_blocked",
                ),
                started_monotonic=0.0,
            )

    client.delete_instance.assert_called_once_with("new-instance")
    client.delete_firewall_group.assert_called_once_with("managed-firewall")
    state_repo.update_node_runtime_metadata.assert_not_called()
