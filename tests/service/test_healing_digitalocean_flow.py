from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from database.asset_models import AssetRecord
from database.state_models import FleetNodeRecord
from infrastructure.digitalocean import DigitalOceanDropletLaunchResult
from services.healing_digitalocean_flow import heal_digitalocean_node
from services.healing_models import HealRequest


def _runtime() -> MagicMock:
    runtime = MagicMock()
    runtime.config.cloudflare.enabled = True
    runtime.correlation_id = "do-heal-correlation"
    return runtime


def _asset() -> AssetRecord:
    return AssetRecord(
        id=18,
        asset_type="digitalocean",
        asset_name="do-sgp1",
        status="active",
        region="sgp1",
        aws_account_id="account-do",
        aws_access_key="dop_v1_test",
        aws_secret_key=None,
        ssh_host=None,
        ssh_port=None,
        ssh_username=None,
        ssh_password=None,
        ssh_private_key=None,
        default_instance_type="s-2vcpu-2gb",
        default_vcpu=2,
        account_total_vcpu=None,
        default_architecture="x64",
        provider_config={},
    )


def _node() -> FleetNodeRecord:
    return FleetNodeRecord(
        id=22,
        xboard_node_id=12348,
        node_name="sf-do",
        node_type="AnyTLS",
        status="offline",
        status_reason="blocked",
        aws_account_id="account-do",
        aws_region="sgp1",
        aws_instance_id="1001",
        aws_subnet_id="vpc-1",
        aws_security_group_id=None,
        cloudflare_record_id="old-record",
        domain_name="sf-do.example.com",
        ipv4_address="192.0.2.20",
        ipv6_address="2001:db8::20",
        last_known_host="sf-do.example.com",
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
        asset_type="digitalocean",
    )


def _source() -> dict[str, object]:
    return {
        "id": 1001,
        "name": "sf-do",
        "region": {"slug": "sgp1"},
        "size_slug": "s-2vcpu-2gb",
        "vpc_uuid": "vpc-1",
        "tags": ["shadowfleet", "prod"],
        "networks": {
            "v4": [{"type": "public", "ip_address": "192.0.2.20"}],
            "v6": [{"type": "public", "ip_address": "2001:db8::20"}],
        },
    }


def _replacement() -> DigitalOceanDropletLaunchResult:
    return DigitalOceanDropletLaunchResult(
        instance_id="1002",
        droplet_id=1002,
        name="sf-do-heal",
        region="sgp1",
        size="s-2vcpu-2gb",
        image="snapshot-1",
        ipv4_address="192.0.2.21",
        ipv6_addresses=("2001:db8::21",),
        subnet_id="vpc-1",
    )


def test_heal_digitalocean_node_replaces_droplet_from_temporary_snapshot() -> None:
    runtime = _runtime()
    asset_repo = MagicMock()
    asset_repo.get_asset_by_xboard_node_id.return_value = _asset()
    state_repo = MagicMock()
    xboard_repo = MagicMock()
    xboard_repo.get_node_runtime.return_value.server_port = 443
    client = MagicMock()
    client.get_droplet.return_value = _source()
    client.create_droplet_snapshot.return_value = {"id": "snapshot-1"}
    client.launch_droplet.return_value = _replacement()
    cf_client = MagicMock()
    cf_client.sync_a_record.return_value = "a-record"
    cf_client.sync_aaaa_record.return_value = "aaaa-record"

    with patch(
        "services.healing_digitalocean_flow.DigitalOceanClient",
        return_value=client,
    ), patch(
        "services.healing_digitalocean_flow.CFClient",
        return_value=cf_client,
    ), patch(
        "services.healing_digitalocean_flow._wait_for_tcp_endpoint"
    ) as wait_for_endpoint, patch(
        "services.healing_digitalocean_flow.notify_healing_success"
    ):
        result = heal_digitalocean_node(
            runtime_context=runtime,
            asset_repo=asset_repo,
            state_repo=state_repo,
            xboard_repo=xboard_repo,
            node_record=_node(),
            request=HealRequest(xboard_node_id=12348, reason="confirmed_blocked"),
            started_monotonic=time.monotonic(),
        )

    launch_request = client.launch_droplet.call_args.args[0]
    assert launch_request.image == "snapshot-1"
    assert launch_request.user_data == ""
    assert launch_request.vpc_uuid == "vpc-1"
    wait_for_endpoint.assert_called_once_with(
        "2001:db8::21",
        443,
        timeout_seconds=300,
        poll_interval_seconds=5.0,
    )
    metadata = state_repo.update_node_runtime_metadata.call_args.kwargs
    assert metadata["aws_instance_id"] == "1002"
    assert metadata["ipv4_address"] == "192.0.2.21"
    assert metadata["ipv6_address"] == "2001:db8::21"
    assert client.delete_droplet.call_args_list[-1].args == ("1001",)
    client.delete_snapshot.assert_called_once_with("snapshot-1")
    assert result.success is True
    assert result.strategy == "digitalocean_instance_replace"


def test_heal_digitalocean_node_rolls_back_replacement_when_dns_fails() -> None:
    runtime = _runtime()
    asset_repo = MagicMock()
    asset_repo.get_asset_by_xboard_node_id.return_value = _asset()
    state_repo = MagicMock()
    xboard_repo = MagicMock()
    xboard_repo.get_node_runtime.return_value.server_port = 443
    client = MagicMock()
    client.get_droplet.return_value = _source()
    client.create_droplet_snapshot.return_value = {"id": "snapshot-1"}
    client.launch_droplet.return_value = _replacement()
    cf_client = MagicMock()
    cf_client.sync_a_record.return_value = "a-record"
    cf_client.sync_aaaa_record.side_effect = RuntimeError("DNS failed")

    with patch(
        "services.healing_digitalocean_flow.DigitalOceanClient",
        return_value=client,
    ), patch(
        "services.healing_digitalocean_flow.CFClient",
        return_value=cf_client,
    ), patch(
        "services.healing_digitalocean_flow._wait_for_tcp_endpoint"
    ):
        with pytest.raises(RuntimeError, match="DNS failed"):
            heal_digitalocean_node(
                runtime_context=runtime,
                asset_repo=asset_repo,
                state_repo=state_repo,
                xboard_repo=xboard_repo,
                node_record=_node(),
                request=HealRequest(
                    xboard_node_id=12348,
                    reason="confirmed_blocked",
                ),
                started_monotonic=time.monotonic(),
            )

    client.delete_droplet.assert_called_once_with("1002")
    client.delete_snapshot.assert_called_once_with("snapshot-1")
    cf_client.sync_a_record.assert_called_with(
        record_name="sf-do.example.com",
        ipv4_address="192.0.2.20",
        proxied=False,
    )
    state_repo.update_node_runtime_metadata.assert_not_called()
