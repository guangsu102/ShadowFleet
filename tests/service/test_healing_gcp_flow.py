from __future__ import annotations

from unittest.mock import MagicMock, patch

from database.asset_models import AssetRecord
from database.state_models import FleetNodeRecord
from services.healing_gcp_flow import heal_gcp_node
from services.healing_models import HealRequest


PRIVATE_KEY = "-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----\n"


def _runtime() -> MagicMock:
    runtime = MagicMock()
    runtime.config.cloudflare.enabled = True
    runtime.correlation_id = "gcp-heal-correlation"
    return runtime


def _asset() -> AssetRecord:
    return AssetRecord(
        id=19,
        asset_type="gcp",
        asset_name="gcp-asia-east1",
        status="active",
        region="asia-east1-a",
        aws_account_id="gcp:shadowfleet-test",
        aws_access_key="shadowfleet@example.iam.gserviceaccount.com",
        aws_secret_key=PRIVATE_KEY,
        ssh_host=None,
        ssh_port=None,
        ssh_username=None,
        ssh_password=None,
        ssh_private_key=None,
        default_instance_type="e2-small",
        default_vcpu=2,
        account_total_vcpu=None,
        default_architecture="x64",
        provider_config={"project_id": "shadowfleet-test"},
    )


def _node() -> FleetNodeRecord:
    return FleetNodeRecord(
        id=23,
        xboard_node_id=12350,
        node_name="sf-gcp",
        node_type="AnyTLS",
        status="offline",
        status_reason="blocked",
        aws_account_id="gcp:shadowfleet-test",
        aws_region="asia-east1-a",
        aws_instance_id="sf-gcp-12350",
        aws_subnet_id="default",
        aws_security_group_id="shadowfleet-ingress",
        cloudflare_record_id="old-a-record",
        domain_name="sf-gcp.example.com",
        ipv4_address="192.0.2.80",
        ipv6_address=None,
        last_known_host="sf-gcp.example.com",
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
        asset_type="gcp",
    )


def test_heal_gcp_node_rotates_ipv4_updates_dns_and_runtime_metadata() -> None:
    runtime = _runtime()
    asset_repo = MagicMock()
    asset_repo.get_asset_by_xboard_node_id.return_value = _asset()
    state_repo = MagicMock()
    xboard_repo = MagicMock()
    xboard_repo.get_node_runtime.return_value.server_port = 443
    client = MagicMock()
    client.rotate_external_ipv4.return_value = "192.0.2.81"
    cf_client = MagicMock()
    cf_client.sync_a_record.return_value = "new-a-record"

    with patch(
        "services.healing_gcp_flow.GCPClient",
        return_value=client,
    ) as client_cls, patch(
        "services.healing_gcp_flow.CFClient",
        return_value=cf_client,
    ), patch(
        "services.healing_gcp_flow._wait_for_tcp_endpoint"
    ) as wait_for_endpoint, patch(
        "services.healing_gcp_flow.notify_healing_success"
    ) as notify:
        result = heal_gcp_node(
            runtime_context=runtime,
            asset_repo=asset_repo,
            state_repo=state_repo,
            xboard_repo=xboard_repo,
            node_record=_node(),
            request=HealRequest(xboard_node_id=12350, reason="confirmed_blocked"),
            started_monotonic=0.0,
        )

    credentials = client_cls.call_args.kwargs["credentials"]
    assert credentials.project_id == "shadowfleet-test"
    client.rotate_external_ipv4.assert_called_once_with(
        "asia-east1-a",
        "sf-gcp-12350",
    )
    wait_for_endpoint.assert_called_once_with(
        "192.0.2.81",
        443,
        timeout_seconds=300,
        poll_interval_seconds=5.0,
    )
    cf_client.sync_a_record.assert_called_once_with(
        record_name="sf-gcp.example.com",
        ipv4_address="192.0.2.81",
        proxied=False,
    )
    metadata = state_repo.update_node_runtime_metadata.call_args.kwargs
    assert metadata["ipv4_address"] == "192.0.2.81"
    assert metadata["aws_instance_id"] == "sf-gcp-12350"
    event = state_repo.create_event.call_args.args[0]
    assert event.payload["strategy"] == "gcp_ipv4_rotate"
    assert event.payload["old_ipv4_address"] == "192.0.2.80"
    assert event.payload["new_ipv4_address"] == "192.0.2.81"
    assert result.success is True
    assert result.strategy == "gcp_ipv4_rotate"
    assert result.old_ipv4_address == "192.0.2.80"
    assert result.new_ipv4_address == "192.0.2.81"
    notify.assert_called_once_with(runtime, result)
