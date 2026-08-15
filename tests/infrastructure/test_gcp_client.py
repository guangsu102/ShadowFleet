from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from infrastructure.gcp import (
    GCPClient,
    GCPClientError,
    GCPCredentials,
    GCPInstanceLaunchRequest,
)


PRIVATE_KEY = "-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----\n"


def _runtime() -> MagicMock:
    runtime = MagicMock()
    runtime.logger.getChild.return_value = MagicMock()
    runtime.config.app.request_timeout_seconds = 30
    runtime.config.app.max_retries = 0
    runtime.config.app.retry_backoff_seconds = 0.01
    return runtime


def _credentials() -> GCPCredentials:
    return GCPCredentials(
        project_id="shadowfleet-test",
        client_email="shadowfleet@example.iam.gserviceaccount.com",
        private_key=PRIVATE_KEY,
    )


class _Response:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self.content = b"{}"
        self._payload = payload

    def json(self) -> object:
        return self._payload


def test_list_collection_follows_google_page_tokens() -> None:
    session = MagicMock()
    session.request.side_effect = [
        _Response(200, {"items": [{"name": "asia-east1-a"}], "nextPageToken": "next"}),
        _Response(200, {"items": [{"name": "asia-east1-b"}]}),
    ]
    client = GCPClient(_runtime(), _credentials(), session=session)

    assert [zone["name"] for zone in client.list_zones()] == [
        "asia-east1-a",
        "asia-east1-b",
    ]
    assert session.request.call_args_list[0].kwargs["params"] == {}
    assert session.request.call_args_list[1].kwargs["params"] == {
        "pageToken": "next"
    }


def test_request_surfaces_google_error_message_and_status() -> None:
    session = MagicMock()
    session.request.return_value = _Response(
        403,
        {"error": {"message": "Compute Engine API has not been used"}},
    )
    client = GCPClient(_runtime(), _credentials(), session=session)

    with pytest.raises(GCPClientError, match="Compute Engine API") as exc_info:
        client.validate_project()

    assert exc_info.value.status_code == 403


def test_launch_instance_builds_compute_engine_payload_and_returns_addresses() -> None:
    client = GCPClient(_runtime(), _credentials(), session=MagicMock())
    instance = {
        "id": "123456789",
        "name": "sf-node-21",
        "machineType": "projects/shadowfleet-test/zones/asia-east1-a/machineTypes/e2-small",
        "networkInterfaces": [
            {
                "name": "nic0",
                "accessConfigs": [{"natIP": "192.0.2.10"}],
                "ipv6AccessConfigs": [{"externalIpv6": "2001:db8::10"}],
            }
        ],
    }
    with patch.object(client, "_request", return_value={"name": "operation-1"}) as request, patch.object(
        client,
        "wait_for_zone_operation",
    ) as wait_operation, patch.object(
        client,
        "wait_for_instance_running",
        return_value=instance,
    ):
        result = client.launch_instance(
            GCPInstanceLaunchRequest(
                name="sf-node-21",
                zone="asia-east1-a",
                machine_type="e2-small",
                source_image="projects/ubuntu-os-cloud/global/images/ubuntu-2404",
                network="projects/shadowfleet-test/global/networks/default",
                subnetwork=None,
                ssh_username="ubuntu",
                ssh_public_key="ssh-ed25519 AAAA test",
                startup_script="#!/bin/bash\necho ready",
                labels={"environment": "test"},
            ),
            poll_interval_seconds=0,
        )

    payload = request.call_args.kwargs["payload"]
    assert payload["machineType"].endswith("/machineTypes/e2-small")
    assert payload["networkInterfaces"][0]["accessConfigs"][0]["type"] == "ONE_TO_ONE_NAT"
    assert payload["labels"]["managed-by"] == "shadowfleet"
    assert payload["metadata"]["items"][0]["key"] == "ssh-keys"
    wait_operation.assert_called_once_with(
        "asia-east1-a",
        "operation-1",
        timeout_seconds=600,
        poll_interval_seconds=0,
    )
    assert result.name == "sf-node-21"
    assert result.ipv4_address == "192.0.2.10"
    assert result.ipv6_address == "2001:db8::10"


def test_ensure_firewall_ports_expands_existing_managed_rule() -> None:
    client = GCPClient(_runtime(), _credentials(), session=MagicMock())
    with patch.object(
        client,
        "_request",
        side_effect=[
            {"allowed": [{"IPProtocol": "tcp", "ports": ["22"]}]},
            {"name": "operation-2"},
        ],
    ) as request, patch.object(client, "wait_for_global_operation") as wait:
        result = client.ensure_firewall_ports(
            network="projects/shadowfleet-test/global/networks/default",
            inbound_ports=(22, 443),
        )

    assert result == "shadowfleet-ingress"
    update_call = request.call_args_list[1]
    assert update_call.args[0] == "PUT"
    assert update_call.kwargs["payload"]["allowed"] == [
        {"IPProtocol": "tcp", "ports": ["22", "443"]}
    ]
    wait.assert_called_once_with("operation-2")


def test_ensure_firewall_ports_rejects_rule_from_another_network() -> None:
    client = GCPClient(_runtime(), _credentials(), session=MagicMock())
    with patch.object(
        client,
        "_request",
        return_value={
            "network": "projects/shadowfleet-test/global/networks/other",
            "allowed": [{"IPProtocol": "tcp", "ports": ["22"]}],
        },
    ):
        with pytest.raises(GCPClientError, match="belongs to network other"):
            client.ensure_firewall_ports(
                network="projects/shadowfleet-test/global/networks/default",
                inbound_ports=(22, 443),
            )


def test_rotate_external_ipv4_replaces_access_config_and_reads_new_address() -> None:
    client = GCPClient(_runtime(), _credentials(), session=MagicMock())
    with patch.object(
        client,
        "_request",
        side_effect=[{"name": "delete-op"}, {"name": "add-op"}],
    ) as request, patch.object(client, "wait_for_zone_operation") as wait, patch.object(
        client,
        "get_instance",
        return_value={
            "networkInterfaces": [
                {"accessConfigs": [{"natIP": "192.0.2.99"}]}
            ]
        },
    ):
        address = client.rotate_external_ipv4("asia-east1-a", "sf-node-21")

    assert address == "192.0.2.99"
    assert request.call_args_list[0].args[1].endswith("/deleteAccessConfig")
    assert request.call_args_list[1].args[1].endswith("/addAccessConfig")
    assert wait.call_count == 2
