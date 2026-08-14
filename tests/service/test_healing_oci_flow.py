from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from database.asset_models import AssetRecord
from database.state_models import FleetNodeRecord
from services.healing_models import HealRequest
from services.healing_oci_flow import heal_oci_node


def _runtime() -> MagicMock:
    runtime = MagicMock()
    runtime.config.cloudflare.enabled = True
    runtime.correlation_id = "oci-heal-correlation"
    return runtime


def _asset() -> AssetRecord:
    return AssetRecord(
        id=7,
        asset_type="oci",
        asset_name="oci-japan",
        status="active",
        region="ap-tokyo-1",
        aws_account_id="oci:tenancy",
        aws_access_key="user-ocid",
        aws_secret_key="private-key",
        ssh_host=None,
        ssh_port=None,
        ssh_username=None,
        ssh_password=None,
        ssh_private_key=None,
        default_instance_type="VM.Standard.E4.Flex",
        default_vcpu=1,
        account_total_vcpu=10,
        default_architecture="x64",
        provider_config={
            "tenancy_ocid": "tenancy",
            "fingerprint": "aa:bb",
            "compartment_ocid": "compartment",
        },
    )


def _node() -> FleetNodeRecord:
    return FleetNodeRecord(
        id=11,
        xboard_node_id=12345,
        node_name="sf-oci",
        node_type="AnyTLS",
        status="offline",
        status_reason="blocked",
        aws_account_id="oci:tenancy",
        aws_region="ap-tokyo-1",
        aws_instance_id="instance-ocid",
        aws_subnet_id="subnet-ocid",
        aws_security_group_id="nsg-ocid",
        cloudflare_record_id="old-record-id",
        domain_name="sf-oci.example.com",
        ipv4_address="192.0.2.1",
        ipv6_address="2001:db8::1",
        last_known_host="sf-oci.example.com",
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
        asset_type="oci",
    )


def _request(node: FleetNodeRecord) -> HealRequest:
    return HealRequest(
        xboard_node_id=node.xboard_node_id,
        reason="confirmed_blocked_by_gfw",
    )


def _oci_client() -> MagicMock:
    client = MagicMock()
    client.get_primary_vnic.return_value = {"id": "vnic-ocid"}
    client.list_ipv6_addresses.return_value = [
        {
            "id": "old-ipv6-ocid",
            "ipAddress": "2001:db8::1",
            "lifecycleState": "AVAILABLE",
        }
    ]
    client.create_ipv6_address.return_value = {
        "id": "new-ipv6-ocid",
        "ipAddress": "2001:db8::2",
        "lifecycleState": "AVAILABLE",
    }
    return client


def test_heal_oci_node_rotates_dns_commits_state_and_deletes_old_address() -> None:
    runtime = _runtime()
    node = _node()
    asset_repo = MagicMock()
    asset_repo.get_asset_by_xboard_node_id.return_value = _asset()
    state_repo = MagicMock()
    xboard_repo = MagicMock()
    xboard_repo.get_node_runtime.return_value.server_port = 443
    client = _oci_client()
    cf_client = MagicMock()
    cf_client.sync_aaaa_record.return_value = "new-record-id"

    with patch(
        "services.healing_oci_flow.OCIClient", return_value=client
    ) as client_type, patch(
        "services.healing_oci_flow.CFClient", return_value=cf_client
    ), patch("services.healing_oci_flow._wait_for_tcp_endpoint") as wait_for_tcp:
        result = heal_oci_node(
            runtime_context=runtime,
            asset_repo=asset_repo,
            state_repo=state_repo,
            xboard_repo=xboard_repo,
            node_record=node,
            request=_request(node),
            started_monotonic=0.0,
        )

    credentials = client_type.call_args.kwargs["credentials"]
    assert credentials.tenancy_ocid == "tenancy"
    assert credentials.user_ocid == "user-ocid"
    wait_for_tcp.assert_called_once_with(
        "2001:db8::2", 443, timeout_seconds=300, poll_interval_seconds=5.0
    )
    cf_client.sync_aaaa_record.assert_called_once_with(
        record_name=node.domain_name,
        ipv6_address="2001:db8::2",
        proxied=False,
    )
    client.delete_ipv6_address.assert_called_once_with("old-ipv6-ocid")
    metadata = state_repo.update_node_runtime_metadata.call_args.kwargs
    assert metadata["ipv6_address"] == "2001:db8::2"
    assert metadata["cloudflare_record_id"] == "new-record-id"
    event = state_repo.create_event.call_args.args[0]
    assert event.payload["strategy"] == "oci_ipv6_rotate"
    assert result.success is True
    assert result.strategy == "oci_ipv6_rotate"


def test_heal_oci_node_restores_dns_and_deletes_replacement_on_state_failure() -> None:
    runtime = _runtime()
    node = _node()
    asset_repo = MagicMock()
    asset_repo.get_asset_by_xboard_node_id.return_value = _asset()
    state_repo = MagicMock()
    state_repo.update_node_runtime_metadata.side_effect = RuntimeError("database down")
    xboard_repo = MagicMock()
    xboard_repo.get_node_runtime.return_value.server_port = 443
    client = _oci_client()
    cf_client = MagicMock()
    cf_client.sync_aaaa_record.return_value = "new-record-id"

    with patch("services.healing_oci_flow.OCIClient", return_value=client), patch(
        "services.healing_oci_flow.CFClient", return_value=cf_client
    ), patch("services.healing_oci_flow._wait_for_tcp_endpoint"):
        with pytest.raises(RuntimeError, match="database down"):
            heal_oci_node(
                runtime_context=runtime,
                asset_repo=asset_repo,
                state_repo=state_repo,
                xboard_repo=xboard_repo,
                node_record=node,
                request=_request(node),
                started_monotonic=0.0,
            )

    assert cf_client.sync_aaaa_record.call_args_list == [
        call(
            record_name=node.domain_name,
            ipv6_address="2001:db8::2",
            proxied=False,
        ),
        call(
            record_name=node.domain_name,
            ipv6_address="2001:db8::1",
            proxied=False,
        ),
    ]
    client.delete_ipv6_address.assert_called_once_with("new-ipv6-ocid")
