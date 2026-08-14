from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from database.asset_models import AssetRecord
from database.state_models import FleetNodeRecord
from infrastructure.kamatera import KamateraServerLaunchResult
from services.healing_kamatera_flow import heal_kamatera_node
from services.healing_models import HealRequest


def _runtime() -> MagicMock:
    runtime = MagicMock()
    runtime.config.cloudflare.enabled = True
    runtime.correlation_id = "kamatera-heal-correlation"
    return runtime


def _asset() -> AssetRecord:
    return AssetRecord(
        id=18,
        asset_type="kamatera",
        asset_name="kamatera-as",
        status="active",
        region="AS",
        aws_account_id="kamatera:account",
        aws_access_key="client-id",
        aws_secret_key="client-secret",
        ssh_host=None,
        ssh_port=None,
        ssh_username=None,
        ssh_password=None,
        ssh_private_key=None,
        default_instance_type="2B",
        default_vcpu=2,
        account_total_vcpu=None,
        default_architecture="x64",
        provider_config={"ssh_public_key": "ssh-ed25519 test"},
    )


def _node() -> FleetNodeRecord:
    return FleetNodeRecord(
        id=22,
        xboard_node_id=12348,
        node_name="sf-kamatera",
        node_type="AnyTLS",
        status="offline",
        status_reason="blocked",
        aws_account_id="kamatera:account",
        aws_region="AS",
        aws_instance_id="old-server",
        aws_subnet_id=None,
        aws_security_group_id=None,
        cloudflare_record_id="old-record",
        domain_name="sf-kamatera.example.com",
        ipv4_address="192.0.2.60",
        ipv6_address="2001:db8::60",
        last_known_host="sf-kamatera.example.com",
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
        asset_type="kamatera",
    )


def _source() -> dict[str, object]:
    return {
        "id": "old-server",
        "name": "sf-kamatera",
        "datacenter": "AS",
        "tags": ["shadowfleet", "prod"],
        "networks": [
            {
                "network": "wan",
                "ips": ["192.0.2.60", "2001:db8::60"],
            }
        ],
    }


def _replacement(*, ipv6: str | None, cpu: str | None = None) -> KamateraServerLaunchResult:
    return KamateraServerLaunchResult(
        instance_id="new-server",
        name="sf-kamatera-heal-deadbeef",
        datacenter="AS",
        cpu=cpu,
        ram_mb=2048,
        ipv4_address="192.0.2.61",
        ipv6_address=ipv6,
        networks=(),
    )


def _repos() -> tuple[MagicMock, MagicMock, MagicMock]:
    asset_repo = MagicMock()
    asset_repo.get_asset_by_xboard_node_id.return_value = _asset()
    state_repo = MagicMock()
    xboard_repo = MagicMock()
    xboard_repo.get_node_runtime.return_value.server_port = 443
    return asset_repo, state_repo, xboard_repo


def test_heal_kamatera_node_supports_ipv4_only_clone_and_cpu_fallback() -> None:
    runtime = _runtime()
    asset_repo, state_repo, xboard_repo = _repos()
    client = MagicMock()
    client.get_server.return_value = _source()
    client.clone_server.return_value = _replacement(ipv6=None, cpu=None)
    cf_client = MagicMock()
    cf_client.get_dns_record.side_effect = [
        {"id": "old-a", "content": "192.0.2.60", "proxied": False},
        {"id": "old-aaaa", "content": "2001:db8::60", "proxied": False},
        {"id": "old-aaaa", "content": "2001:db8::60", "proxied": False},
    ]
    cf_client.sync_a_record.return_value = "new-a"

    with patch(
        "services.healing_kamatera_flow.KamateraClient", return_value=client
    ), patch(
        "services.healing_kamatera_flow.CFClient", return_value=cf_client
    ), patch(
        "services.healing_kamatera_flow._wait_for_tcp_endpoint"
    ) as wait_for_endpoint, patch(
        "services.healing_kamatera_flow.notify_healing_success"
    ):
        result = heal_kamatera_node(
            runtime_context=runtime,
            asset_repo=asset_repo,
            state_repo=state_repo,
            xboard_repo=xboard_repo,
            node_record=_node(),
            request=HealRequest(xboard_node_id=12348, reason="confirmed_blocked"),
            started_monotonic=0.0,
        )

    wait_for_endpoint.assert_called_once_with(
        "192.0.2.61",
        443,
        timeout_seconds=300,
        poll_interval_seconds=5.0,
    )
    cf_client.sync_a_record.assert_called_once_with(
        "sf-kamatera.example.com", "192.0.2.61", proxied=False
    )
    cf_client.delete_dns_record.assert_called_once_with("old-aaaa")
    metadata = state_repo.update_node_runtime_metadata.call_args.kwargs
    assert metadata["instance_type"] == "2B"
    assert metadata["ipv4_address"] == "192.0.2.61"
    assert metadata["ipv6_address"] is None
    client.delete_server.assert_called_once_with("old-server")
    assert result.success is True
    assert result.strategy == "kamatera_instance_replace"


def test_heal_kamatera_node_restores_a_and_aaaa_after_partial_dns_failure() -> None:
    runtime = _runtime()
    asset_repo, state_repo, xboard_repo = _repos()
    client = MagicMock()
    client.get_server.return_value = _source()
    client.clone_server.return_value = _replacement(ipv6="2001:db8::61", cpu="2B")
    cf_client = MagicMock()
    cf_client.get_dns_record.side_effect = [
        {"id": "old-a", "content": "192.0.2.60", "proxied": False},
        {"id": "old-aaaa", "content": "2001:db8::60", "proxied": False},
    ]
    cf_client.sync_a_record.side_effect = ["new-a", "old-a"]
    cf_client.sync_aaaa_record.side_effect = [RuntimeError("DNS failed"), "old-aaaa"]

    with patch(
        "services.healing_kamatera_flow.KamateraClient", return_value=client
    ), patch(
        "services.healing_kamatera_flow.CFClient", return_value=cf_client
    ), patch("services.healing_kamatera_flow._wait_for_tcp_endpoint"):
        with pytest.raises(RuntimeError, match="DNS failed"):
            heal_kamatera_node(
                runtime_context=runtime,
                asset_repo=asset_repo,
                state_repo=state_repo,
                xboard_repo=xboard_repo,
                node_record=_node(),
                request=HealRequest(xboard_node_id=12348, reason="confirmed_blocked"),
                started_monotonic=0.0,
            )

    assert cf_client.sync_a_record.call_args_list == [
        call("sf-kamatera.example.com", "192.0.2.61", proxied=False),
        call("sf-kamatera.example.com", "192.0.2.60", proxied=False),
    ]
    assert cf_client.sync_aaaa_record.call_args_list == [
        call("sf-kamatera.example.com", "2001:db8::61", proxied=False),
        call("sf-kamatera.example.com", "2001:db8::60", proxied=False),
    ]
    client.delete_server.assert_called_once_with("new-server", name=client.created_server_name)
    state_repo.update_node_runtime_metadata.assert_not_called()
