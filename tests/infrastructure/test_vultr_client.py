from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

import pytest

from infrastructure.vultr.client import (
    VultrClient,
    VultrClientError,
    VultrInstanceLaunchRequest,
)


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.content = b"{}" if payload is not None else b""
        self.text = ""

    def json(self) -> dict:
        return self._payload


def _runtime() -> MagicMock:
    runtime = MagicMock()
    runtime.logger.getChild.return_value = MagicMock()
    runtime.config.app.request_timeout_seconds = 30
    runtime.config.app.max_retries = 0
    runtime.config.app.retry_backoff_seconds = 0.01
    return runtime


def test_launch_instance_encodes_userdata_and_maps_public_ips() -> None:
    client = VultrClient(runtime_context=_runtime(), api_token="vultr-test-token")
    client._session.request = MagicMock(side_effect=[
        FakeResponse(201, {"instance": {"id": "instance-123"}}),
        FakeResponse(200, {"instance": {
            "id": "instance-123",
            "label": "sf-vultr",
            "status": "active",
            "power_status": "running",
            "server_status": "ok",
            "plan": "vc2-1c-1gb",
            "os_id": 2284,
            "main_ip": "203.0.113.10",
            "v6_main_ip": "2001:db8::10",
        }}),
    ])

    result = client.launch_instance(
        VultrInstanceLaunchRequest(
            label="sf-vultr",
            region="sgp",
            plan="vc2-1c-1gb",
            os_id=2284,
            user_data="#!/bin/sh\necho ready\n",
            ssh_key_ids=("ssh-key-1",),
            vpc_ids=("vpc-id",),
            firewall_group_id="firewall-id",
            tags=("shadowfleet",),
        ),
        wait_timeout_seconds=1,
        poll_interval_seconds=0,
    )

    assert result.instance_id == "instance-123"
    assert client.created_instance_id == "instance-123"
    assert result.ipv4_address == "203.0.113.10"
    assert result.ipv6_address == "2001:db8::10"
    create_call = client._session.request.call_args_list[0]
    payload = create_call.kwargs["json"]
    assert payload["enable_ipv6"] is True
    assert base64.b64decode(payload["user_data"]).decode("utf-8") == "#!/bin/sh\necho ready\n"
    assert payload["sshkey_id"] == ["ssh-key-1"]
    assert payload["attach_vpc"] == ["vpc-id"]
    assert payload["firewall_group_id"] == "firewall-id"


def test_list_instances_follows_cursor_pagination() -> None:
    client = VultrClient(runtime_context=_runtime(), api_token="vultr-test-token")
    client._session.request = MagicMock(side_effect=[
        FakeResponse(200, {
            "instances": [{"id": "instance-1"}],
            "meta": {"links": {"next": "https://api.vultr.com/v2/instances?cursor=next-page"}},
        }),
        FakeResponse(200, {
            "instances": [{"id": "instance-2"}],
            "meta": {"links": {"next": ""}},
        }),
    ])

    instances = client.list_instances()

    assert [instance["id"] for instance in instances] == ["instance-1", "instance-2"]
    assert client._session.request.call_args_list[1].kwargs["params"]["cursor"] == "next-page"


def test_wait_for_instance_requires_active_running_and_ok() -> None:
    client = VultrClient(runtime_context=_runtime(), api_token="vultr-test-token")
    client._session.request = MagicMock(side_effect=[
        FakeResponse(200, {"instance": {
            "id": "instance-123",
            "status": "pending",
            "power_status": "running",
            "server_status": "installing",
        }}),
        FakeResponse(200, {"instance": {
            "id": "instance-123",
            "status": "active",
            "power_status": "running",
            "server_status": "ok",
        }}),
    ])

    result = client.wait_for_instance_running(
        instance_id="instance-123",
        timeout_seconds=1,
        poll_interval_seconds=0,
    )

    assert result["status"] == "active"
    assert client._session.request.call_count == 2


def test_delete_instance_treats_not_found_as_success() -> None:
    client = VultrClient(runtime_context=_runtime(), api_token="vultr-test-token")
    client._session.request = MagicMock(return_value=FakeResponse(404, {"error": "not found"}))

    client.delete_instance("already-deleted")


def test_catalog_uses_vultr_v2_collection_endpoints() -> None:
    client = VultrClient(runtime_context=_runtime(), api_token="vultr-test-token")
    client._session.request = MagicMock(side_effect=[
        FakeResponse(200, {"vpcs": [{"id": "vpc-id"}]}),
        FakeResponse(200, {"firewall_groups": [{"id": "firewall-id"}]}),
    ])

    assert client.list_vpcs() == [{"id": "vpc-id"}]
    assert client.list_firewall_groups() == [{"id": "firewall-id"}]
    calls = client._session.request.call_args_list
    assert calls[0].kwargs["url"].endswith("/vpcs")
    assert calls[1].kwargs["url"].endswith("/firewalls")


def test_get_instance_user_data_decodes_payload_and_lists_vpcs() -> None:
    client = VultrClient(runtime_context=_runtime(), api_token="vultr-test-token")
    encoded = base64.b64encode(b"#!/bin/sh\necho ready\n").decode("ascii")
    client._session.request = MagicMock(
        side_effect=[
            FakeResponse(200, {"user_data": {"data": encoded}}),
            FakeResponse(200, {"vpcs": [{"id": "vpc-id"}]}),
        ]
    )

    assert client.get_instance_user_data("instance-1").startswith("#!/bin/sh")
    assert client.list_instance_vpcs("instance-1") == [{"id": "vpc-id"}]


def test_ensure_firewall_ports_creates_dual_stack_rules() -> None:
    client = VultrClient(runtime_context=_runtime(), api_token="vultr-test-token")
    client._session.request = MagicMock(
        side_effect=[
            FakeResponse(201, {"firewall_group": {"id": "fw-managed"}}),
            FakeResponse(200, {"firewall_rules": []}),
            FakeResponse(201, {"firewall_rule": {"id": 1}}),
            FakeResponse(201, {"firewall_rule": {"id": 2}}),
            FakeResponse(201, {"firewall_rule": {"id": 3}}),
            FakeResponse(201, {"firewall_rule": {"id": 4}}),
        ]
    )

    result = client.ensure_firewall_ports(
        firewall_group_id=None,
        label="sf-node",
        inbound_ports=(22, 443),
    )

    assert result.firewall_group_id == "fw-managed"
    assert result.created is True
    rule_calls = client._session.request.call_args_list[2:]
    assert {
        (call.kwargs["json"]["ip_type"], call.kwargs["json"]["port"])
        for call in rule_calls
    } == {("v4", "22"), ("v4", "443"), ("v6", "22"), ("v6", "443")}


def test_validate_provisioning_target_checks_selected_resources() -> None:
    client = VultrClient(runtime_context=_runtime(), api_token="vultr-test-token")
    with patch.object(client, "list_regions", return_value=[{"id": "sgp"}]), patch.object(
        client,
        "list_plans",
        return_value=[{"id": "vc2-1c-1gb", "locations": ["sgp"]}],
    ), patch.object(
        client, "list_operating_systems", return_value=[{"id": 2284}]
    ), patch.object(
        client, "list_ssh_keys", return_value=[{"id": "ssh-key"}]
    ), patch.object(
        client, "list_vpcs", return_value=[{"id": "vpc-id", "region": "sgp"}]
    ), patch.object(
        client, "get_firewall_group", return_value={"id": "firewall-id"}
    ):
        client.validate_provisioning_target(
            region="sgp",
            plan="vc2-1c-1gb",
            os_id=2284,
            ssh_key_ids=("ssh-key",),
            vpc_ids=("vpc-id",),
            firewall_group_id="firewall-id",
        )


def test_validate_provisioning_target_rejects_plan_region_mismatch() -> None:
    client = VultrClient(runtime_context=_runtime(), api_token="vultr-test-token")
    with patch.object(client, "list_regions", return_value=[{"id": "sgp"}]), patch.object(
        client,
        "list_plans",
        return_value=[{"id": "vc2-1c-1gb", "locations": ["nrt"]}],
    ):
        with pytest.raises(VultrClientError, match="not available"):
            client.validate_provisioning_target(
                region="sgp",
                plan="vc2-1c-1gb",
                os_id=2284,
            )
