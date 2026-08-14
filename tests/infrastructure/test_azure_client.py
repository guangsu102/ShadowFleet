from __future__ import annotations

import base64
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from infrastructure.azure import (
    AzureClient,
    AzureClientError,
    AzureCredentials,
    AzureVmLaunchRequest,
    resolve_azure_vnet_name,
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


def _credentials() -> AzureCredentials:
    return AzureCredentials("tenant", "client", "secret", "subscription")


def _rotation_resources() -> tuple[str, str, str, dict, dict, dict]:
    vm_id = (
        "/subscriptions/subscription/resourceGroups/rg/providers/"
        "Microsoft.Compute/virtualMachines/sf-azure"
    )
    nic_id = (
        "/subscriptions/subscription/resourceGroups/rg/providers/"
        "Microsoft.Network/networkInterfaces/sf-azure-nic"
    )
    public_ip_id = (
        "/subscriptions/subscription/resourceGroups/rg/providers/"
        "Microsoft.Network/publicIPAddresses/sf-azure-ipv6"
    )
    vm = {
        "name": "sf-azure",
        "properties": {
            "networkProfile": {
                "networkInterfaces": [
                    {"id": nic_id, "properties": {"primary": True}}
                ]
            }
        },
    }
    nic = {
        "location": "japaneast",
        "properties": {
            "ipConfigurations": [
                {
                    "name": "ipv6",
                    "properties": {
                        "privateIPAddressVersion": "IPv6",
                        "privateIPAllocationMethod": "Dynamic",
                        "subnet": {"id": "subnet-id"},
                        "publicIPAddress": {"id": public_ip_id},
                        "provisioningState": "Succeeded",
                    },
                }
            ]
        },
    }
    public_ip = {
        "location": "japaneast",
        "sku": {"name": "Standard"},
        "tags": {"shadowfleet": "true"},
        "properties": {
            "ipAddress": "2001:db8::1",
            "publicIPAllocationMethod": "Static",
            "publicIPAddressVersion": "IPv6",
            "dnsSettings": {"domainNameLabel": "sf-azure"},
            "publicIPPrefix": {"id": "ipv6-prefix-id"},
            "provisioningState": "Succeeded",
            "resourceGuid": "read-only",
        },
    }
    return vm_id, nic_id, public_ip_id, vm, nic, public_ip


def test_validate_subscription_uses_oauth_token() -> None:
    client = AzureClient(_runtime(), _credentials())
    client._session.post = MagicMock(return_value=FakeResponse(200, {"access_token": "token"}))
    client._session.request = MagicMock(
        return_value=FakeResponse(200, {"subscriptionId": "subscription"})
    )

    assert client.validate_subscription()["subscriptionId"] == "subscription"
    token_call = client._session.post.call_args
    assert token_call.args[0].endswith("/tenant/oauth2/v2.0/token")
    assert token_call.kwargs["data"]["scope"] == "https://management.azure.com/.default"
    request_call = client._session.request.call_args
    assert request_call.kwargs["headers"]["Authorization"] == "Bearer token"


def test_vm_payload_encodes_cloud_init_and_uses_ssh_key() -> None:
    request = AzureVmLaunchRequest(
        name="sf-azure",
        location="japaneast",
        resource_group="shadowfleet-rg",
        vm_size="Standard_B1s",
        admin_username="azureuser",
        ssh_public_key="ssh-ed25519 AAAA test",
        user_data="#cloud-config\nruncmd: [echo ready]\n",
    )

    payload = AzureClient._vm_payload(request, "/subscriptions/sub/nics/nic")

    profile = payload["properties"]["osProfile"]
    assert base64.b64decode(profile["customData"]).decode() == request.user_data
    assert profile["linuxConfiguration"]["disablePasswordAuthentication"] is True
    assert profile["linuxConfiguration"]["ssh"]["publicKeys"][0]["keyData"] == request.ssh_public_key


def test_nic_payload_configures_ipv4_and_ipv6() -> None:
    payload = AzureClient._nic_payload(
        "japaneast", "subnet", "nsg", "ipv4", "ipv6", ("shadowfleet",)
    )

    configs = payload["properties"]["ipConfigurations"]
    assert [item["properties"]["privateIPAddressVersion"] for item in configs] == ["IPv4", "IPv6"]
    assert configs[0]["properties"]["publicIPAddress"]["id"] == "ipv4"
    assert configs[1]["properties"]["publicIPAddress"]["id"] == "ipv6"


def test_delete_vm_deletes_vm_before_network_dependencies() -> None:
    client = AzureClient(_runtime(), _credentials())
    vm_id = (
        "/subscriptions/subscription/resourceGroups/rg/providers/"
        "Microsoft.Compute/virtualMachines/sf-azure"
    )
    with patch.object(
        client,
        "list_public_ip_addresses",
        return_value=[],
    ), patch.object(client, "_delete_resource") as delete_resource:
        client.delete_vm(vm_id)

    deleted_ids = [call.args[0] for call in delete_resource.call_args_list]
    assert deleted_ids[0] == vm_id
    assert deleted_ids[1].endswith("/networkInterfaces/sf-azure-nic")
    assert deleted_ids[2].endswith("/publicIPAddresses/sf-azure-ipv4")
    assert deleted_ids[3].endswith("/publicIPAddresses/sf-azure-ipv6")
    assert deleted_ids[4].endswith("/networkSecurityGroups/sf-azure-nsg")


def test_delete_vm_deletes_managed_healing_public_ips() -> None:
    client = AzureClient(_runtime(), _credentials())
    vm_id = (
        "/subscriptions/subscription/resourceGroups/rg/providers/"
        "Microsoft.Compute/virtualMachines/sf-azure"
    )
    healing_id = (
        "/subscriptions/subscription/resourceGroups/rg/providers/"
        "Microsoft.Network/publicIPAddresses/sf-azure-ipv6-heal-deadbeef"
    )
    public_ips = [
        {
            "id": healing_id,
            "name": "sf-azure-ipv6-heal-deadbeef",
            "tags": {"shadowfleet": "true"},
        },
        {
            "id": f"{healing_id}-external",
            "name": "sf-azure-ipv6-heal-external",
            "tags": {},
        },
    ]
    with patch.object(
        client,
        "list_public_ip_addresses",
        return_value=public_ips,
    ), patch.object(client, "_delete_resource") as delete_resource:
        client.delete_vm(vm_id)

    deleted_ids = [call.args[0] for call in delete_resource.call_args_list]
    assert healing_id in deleted_ids
    assert f"{healing_id}-external" not in deleted_ids


def test_list_virtual_machines_follows_next_link() -> None:
    client = AzureClient(_runtime(), _credentials())
    next_link = "https://management.azure.com/next-page"
    with patch.object(
        client,
        "_request",
        side_effect=[
            {"value": [{"id": "vm-1"}], "nextLink": next_link},
            {"value": [{"id": "vm-2"}]},
        ],
    ) as request:
        result = client.list_virtual_machines("shadowfleet")

    assert [item["id"] for item in result] == ["vm-1", "vm-2"]
    assert request.call_args_list[1].args == ("GET", next_link)
    assert request.call_args_list[1].kwargs["api_version"] == "2024-03-01"


def test_list_network_resources_uses_network_api() -> None:
    client = AzureClient(_runtime(), _credentials())
    with patch.object(client, "_list_collection", return_value=[]) as list_collection:
        client.list_network_interfaces("rg")
        client.list_public_ip_addresses("rg")
        client.list_network_security_groups("rg")

    calls = list_collection.call_args_list
    assert [call.kwargs["api_version"] for call in calls] == [
        "2023-09-01",
        "2023-09-01",
        "2023-09-01",
    ]
    assert calls[0].args[0].endswith("/networkInterfaces")
    assert calls[1].args[0].endswith("/publicIPAddresses")
    assert calls[2].args[0].endswith("/networkSecurityGroups")


def test_azure_resource_tags_include_parseable_creation_time() -> None:
    tags = AzureClient._tag_map(("production",))

    assert tags["shadowfleet"] == "true"
    assert tags["production"] == "true"
    assert tags["shadowfleet_created_at"].endswith("Z")
    datetime.fromisoformat(tags["shadowfleet_created_at"].replace("Z", "+00:00"))


def test_wait_for_vm_running_tolerates_eventual_consistency() -> None:
    client = AzureClient(_runtime(), _credentials())
    with patch.object(
        client,
        "get_vm_power_state",
        side_effect=[AzureClientError("not ready", status_code=404), "running"],
    ), patch("infrastructure.azure.client.time.sleep"):
        client.wait_for_vm_running(
            "vm-id",
            timeout_seconds=10,
            poll_interval_seconds=0,
        )


def test_request_does_not_duplicate_api_version_from_next_link() -> None:
    client = AzureClient(_runtime(), _credentials())
    client._access_token = "token"
    client._session.request = MagicMock(
        return_value=FakeResponse(200, {"value": []})
    )

    client._request(
        "GET",
        "https://management.azure.com/next?api-version=2024-03-01&$skiptoken=abc",
        api_version="2024-03-01",
    )

    assert client._session.request.call_args.kwargs["params"] is None


def test_put_and_wait_tracks_resource_after_azure_accepts_creation() -> None:
    client = AzureClient(_runtime(), _credentials())
    resource_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Network/networkInterfaces/nic"
    with patch.object(client, "_request", return_value={}):
        try:
            client._put_and_wait(
                resource_id,
                "2023-09-01",
                {},
                timeout_seconds=0,
                poll_interval_seconds=0,
                track_created=True,
            )
        except AzureClientError:
            pass

    assert client.created_resource_ids == (resource_id,)


def test_default_vnet_name_is_scoped_to_azure_location() -> None:
    assert resolve_azure_vnet_name("JapanEast") == "shadowfleet-vnet-japaneast"
    assert (
        resolve_azure_vnet_name("eastus", "shadowfleet-vnet")
        == "shadowfleet-vnet-eastus"
    )
    assert resolve_azure_vnet_name("eastus", "shared-custom-vnet") == "shared-custom-vnet"


def test_ensure_resource_group_reuses_existing_group_without_put() -> None:
    client = AzureClient(_runtime(), _credentials())
    with patch.object(client, "_request", return_value={"name": "rg"}) as request:
        client.ensure_resource_group("rg", "japaneast")

    request.assert_called_once_with(
        "GET",
        "/subscriptions/subscription/resourcegroups/rg",
        api_version="2021-04-01",
    )


def test_ensure_resource_group_creates_group_only_after_not_found() -> None:
    client = AzureClient(_runtime(), _credentials())
    with patch.object(
        client,
        "_request",
        side_effect=[AzureClientError("not found", status_code=404), {}],
    ) as request:
        client.ensure_resource_group("rg", "japaneast")

    assert [call.args[0] for call in request.call_args_list] == ["GET", "PUT"]


def test_ensure_network_reuses_subnet_in_matching_location() -> None:
    client = AzureClient(_runtime(), _credentials())
    with patch.object(
        client,
        "_request",
        side_effect=[
            {"location": "JapanEast"},
            {
                "id": "subnet-id",
                "properties": {
                    "addressPrefixes": ["10.42.0.0/24", "fd42:42::/64"]
                },
            },
        ],
    ), patch.object(client, "_put_and_wait") as put_and_wait:
        subnet_id = client.ensure_network(
            "rg", "japaneast", "shadowfleet-vnet-japaneast", "default"
        )

    assert subnet_id.endswith("/virtualNetworks/shadowfleet-vnet-japaneast/subnets/default")
    put_and_wait.assert_not_called()


def test_ensure_network_rejects_vnet_from_another_location() -> None:
    client = AzureClient(_runtime(), _credentials())
    with patch.object(client, "_request", return_value={"location": "eastus"}):
        with pytest.raises(AzureClientError, match="one VNet per Azure region") as exc_info:
            client.ensure_network(
                "rg", "japaneast", "shadowfleet-vnet", "default"
            )

    assert exc_info.value.status_code == 409


def test_ensure_network_does_not_invent_subnet_in_existing_vnet() -> None:
    client = AzureClient(_runtime(), _credentials())
    with patch.object(
        client,
        "_request",
        side_effect=[
            {"location": "japaneast"},
            AzureClientError("not found", status_code=404),
        ],
    ), patch.object(client, "_put_and_wait") as put_and_wait:
        with pytest.raises(AzureClientError, match="dual-stack subnet") as exc_info:
            client.ensure_network("rg", "japaneast", "existing-vnet", "missing")

    assert exc_info.value.status_code == 409
    put_and_wait.assert_not_called()


def test_ensure_network_creates_vnet_and_subnet_when_vnet_is_missing() -> None:
    client = AzureClient(_runtime(), _credentials())
    with patch.object(
        client,
        "_request",
        side_effect=AzureClientError("not found", status_code=404),
    ), patch.object(client, "_put_and_wait", return_value={}) as put_and_wait:
        subnet_id = client.ensure_network(
            "rg", "japaneast", "shadowfleet-vnet-japaneast", "default"
        )

    assert subnet_id.endswith("/virtualNetworks/shadowfleet-vnet-japaneast/subnets/default")
    assert put_and_wait.call_count == 2
    assert put_and_wait.call_args_list[0].args[0].endswith(
        "/virtualNetworks/shadowfleet-vnet-japaneast"
    )
    assert put_and_wait.call_args_list[1].args[0].endswith("/subnets/default")


def test_ensure_network_rejects_existing_single_stack_subnet() -> None:
    client = AzureClient(_runtime(), _credentials())
    with patch.object(
        client,
        "_request",
        side_effect=[
            {"location": "japaneast"},
            {
                "id": "subnet-id",
                "properties": {"addressPrefix": "10.42.0.0/24"},
            },
        ],
    ):
        with pytest.raises(AzureClientError, match="dual-stack"):
            client.ensure_network(
                "rg",
                "japaneast",
                "shadowfleet-vnet-japaneast",
                "default",
            )


def test_validate_provisioning_target_checks_catalog_and_foundation() -> None:
    client = AzureClient(_runtime(), _credentials())
    with patch.object(
        client,
        "list_locations",
        return_value=[{"name": "japaneast"}],
    ), patch.object(
        client,
        "list_vm_sizes",
        return_value=[{"name": "Standard_B1s"}],
    ), patch.object(client, "ensure_resource_group") as ensure_group, patch.object(
        client,
        "ensure_network",
        return_value="subnet-id",
    ) as ensure_network:
        subnet_id = client.validate_provisioning_target(
            location="japaneast",
            vm_size="Standard_B1s",
            resource_group="shadowfleet-rg",
            vnet_name="shadowfleet-vnet-japaneast",
            subnet_name="default",
        )

    assert subnet_id == "subnet-id"
    ensure_group.assert_called_once_with("shadowfleet-rg", "japaneast")
    ensure_network.assert_called_once_with(
        "shadowfleet-rg",
        "japaneast",
        "shadowfleet-vnet-japaneast",
        "default",
    )


def test_rotate_vm_ipv6_public_ip_uses_temporary_attachment_before_recreate() -> None:
    client = AzureClient(_runtime(), _credentials())
    vm_id, nic_id, public_ip_id, vm, nic, public_ip = _rotation_resources()
    with patch.object(client, "get_vm", return_value=vm), patch.object(
        client, "_request", side_effect=[nic, public_ip]
    ), patch.object(client, "_put_and_wait") as put_and_wait, patch.object(
        client,
        "_get_public_ip",
        side_effect=["2001:db8::2", "2001:db8::3"],
    ), patch.object(client, "_delete_resource") as delete_resource:
        old_address, new_address = client.rotate_vm_ipv6_public_ip(vm_id)

    assert (old_address, new_address) == ("2001:db8::1", "2001:db8::3")
    assert put_and_wait.call_count == 4
    temporary_public_ip_id = put_and_wait.call_args_list[0].args[0]
    assert temporary_public_ip_id.endswith(tuple("0123456789abcdef"))
    assert "-ipv6-heal-" in temporary_public_ip_id
    temporary_payload = put_and_wait.call_args_list[0].args[2]
    assert "dnsSettings" not in temporary_payload["properties"]
    assert temporary_payload["tags"]["shadowfleet_parent_vm"] == "sf-azure"
    assert "publicIPPrefix" not in temporary_payload["properties"]
    temporary_attach = put_and_wait.call_args_list[1]
    assert temporary_attach.args[0] == f"{nic_id}/ipConfigurations/ipv6"
    assert (
        temporary_attach.args[2]["properties"]["publicIPAddress"]["id"]
        == temporary_public_ip_id
    )
    assert "provisioningState" not in temporary_attach.args[2]["properties"]
    canonical_payload = put_and_wait.call_args_list[2].args[2]
    assert canonical_payload["properties"]["dnsSettings"]["domainNameLabel"] == "sf-azure"
    assert canonical_payload["properties"]["publicIPPrefix"]["id"] == "ipv6-prefix-id"
    assert "resourceGuid" not in canonical_payload["properties"]
    canonical_attach = put_and_wait.call_args_list[3]
    assert (
        canonical_attach.args[2]["properties"]["publicIPAddress"]["id"]
        == public_ip_id
    )
    assert delete_resource.call_args_list[0].args[0] == public_ip_id
    assert delete_resource.call_args_list[1].args[0] == temporary_public_ip_id


def test_rotate_vm_ipv6_public_ip_rebinds_old_ip_when_delete_fails() -> None:
    client = AzureClient(_runtime(), _credentials())
    vm_id, _, public_ip_id, vm, nic, public_ip = _rotation_resources()
    with patch.object(client, "get_vm", return_value=vm), patch.object(
        client, "_request", side_effect=[nic, public_ip]
    ), patch.object(client, "_put_and_wait") as put_and_wait, patch.object(
        client, "_get_public_ip", return_value="2001:db8::2"
    ), patch.object(
        client,
        "_delete_resource",
        side_effect=[AzureClientError("delete failed", status_code=409), None],
    ) as delete_resource:
        with pytest.raises(AzureClientError, match="delete failed"):
            client.rotate_vm_ipv6_public_ip(vm_id)

    assert put_and_wait.call_count == 3
    rollback_attach = put_and_wait.call_args_list[2]
    assert (
        rollback_attach.args[2]["properties"]["publicIPAddress"]["id"]
        == public_ip_id
    )
    temporary_public_ip_id = put_and_wait.call_args_list[0].args[0]
    assert delete_resource.call_args_list[1].args[0] == temporary_public_ip_id


def test_rotate_vm_ipv6_public_ip_keeps_temporary_ip_when_recreate_fails() -> None:
    client = AzureClient(_runtime(), _credentials())
    vm_id, _, public_ip_id, vm, nic, public_ip = _rotation_resources()
    with patch.object(client, "get_vm", return_value=vm), patch.object(
        client, "_request", side_effect=[nic, public_ip]
    ), patch.object(
        client,
        "_put_and_wait",
        side_effect=[None, None, AzureClientError("recreate failed"), None],
    ) as put_and_wait, patch.object(
        client, "_get_public_ip", return_value="2001:db8::2"
    ), patch.object(client, "_delete_resource") as delete_resource:
        old_address, new_address = client.rotate_vm_ipv6_public_ip(vm_id)

    assert (old_address, new_address) == ("2001:db8::1", "2001:db8::2")
    temporary_public_ip_id = put_and_wait.call_args_list[0].args[0]
    fallback_attach = put_and_wait.call_args_list[3]
    assert (
        fallback_attach.args[2]["properties"]["publicIPAddress"]["id"]
        == temporary_public_ip_id
    )
    assert [call.args[0] for call in delete_resource.call_args_list] == [
        public_ip_id,
        public_ip_id,
    ]
