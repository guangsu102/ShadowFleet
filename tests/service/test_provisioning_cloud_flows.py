from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from infrastructure.azure import AzureVmLaunchResult
from infrastructure.vultr import VultrFirewallEnsureResult, VultrInstanceLaunchResult
from services.asset_selector_service import AssetSelectionResult
from services.node_registry_models import NodeStateChangeResult, RegisterNodeResult
from services.provisioning_azure_flow import provision_azure_node
from services.provisioning_models import DnsSyncResult, ProvisionRequest
from services.provisioning_support import ProvisioningDependencies
from services.provisioning_vultr_flow import provision_vultr_node


def _selection(asset_type: str) -> AssetSelectionResult:
    provider_config: dict[str, object]
    if asset_type == "vultr":
        provider_config = {
            "ssh_key_ids": ["ssh-key"],
            "vpc_ids": ["vpc-id"],
            "tags": ["prod"],
        }
        account_id = "vultr:account"
        access_key = "vultr-token"
        secret_key = None
        instance_type = "vc2-1c-1gb"
        ami_id = "2284"
    else:
        provider_config = {
            "tenant_id": "tenant-id",
            "subscription_id": "subscription-id",
            "resource_group": "shadowfleet-rg",
            "admin_username": "azureuser",
            "ssh_public_key": "ssh-ed25519 test",
            "tags": ["prod"],
        }
        account_id = "azure:subscription-id"
        access_key = "client-id"
        secret_key = "client-secret"
        instance_type = "Standard_B1s"
        ami_id = None
    return AssetSelectionResult(
        asset_id=41,
        asset_type=asset_type,
        asset_name=f"{asset_type}-asset",
        protocol_type="Trojan",
        region="ewr" if asset_type == "vultr" else "japaneast",
        aws_account_id=account_id,
        aws_access_key=access_key,
        aws_secret_key=secret_key,
        ssh_host=None,
        ssh_port=None,
        ssh_username=None,
        ssh_password=None,
        ssh_private_key=None,
        instance_type=instance_type,
        vcpu=1,
        architecture=None,
        ami_id=ami_id,
        subnet_id=None,
        security_group_id=None,
        allow_cdn_proxy=False,
        requires_domain=True,
        requires_dns_record=True,
        current_allocated_count=0,
        current_allocated_vcpu=0,
        target_count=1,
        max_count=2,
        provider_config=provider_config,
    )


def _request(asset_type: str) -> ProvisionRequest:
    return ProvisionRequest(
        protocol_type="Trojan",
        node_name=f"{asset_type}-node",
        port="443",
        server_port=443,
        rate=Decimal("1"),
        provisioning_task_id=91,
        asset_type=asset_type,
        region="ewr" if asset_type == "vultr" else "japaneast",
        domain_name=f"{asset_type}.example.com",
        group_ids=[1],
    )


def _dependencies(selection: AssetSelectionResult) -> tuple[ProvisioningDependencies, MagicMock]:
    runtime = MagicMock()
    runtime.correlation_id = "correlation-id"
    runtime.config.app.skip_rollback_on_failure = False
    logger = MagicMock()
    selector = MagicMock()
    selector.select_asset.return_value = selection
    node_registry = MagicMock()
    node_registry.register_node.return_value = RegisterNodeResult(
        local_node_id=10,
        xboard_node_id=20,
        status="provisioning",
        node_name="cloud-node",
        node_type="Trojan",
    )
    node_registry.mark_node_online.return_value = NodeStateChangeResult(
        local_node_id=10,
        xboard_node_id=20,
        status="online",
    )
    ready_callback_service = MagicMock()
    ready_callback_service.register_callback.return_value = MagicMock()
    dependencies = ProvisioningDependencies(
        runtime_context=runtime,
        logger=logger,
        asset_selector=selector,
        node_registry=node_registry,
        ready_callback_service=ready_callback_service,
    )
    return dependencies, MagicMock()


def _dns_result() -> DnsSyncResult:
    return DnsSyncResult(
        primary_record_id="aaaa-record",
        a_record_id="a-record",
        aaaa_record_id="aaaa-record",
        snapshots=(),
    )


def _common_patches(module_name: str):
    return (
        patch("services.node_auto_config_service.NodeAutoConfigService"),
        patch(
            f"{module_name}.build_user_data_render_request",
            return_value=MagicMock(),
        ),
        patch(
            f"{module_name}.render_user_data",
            return_value=SimpleNamespace(user_data="#cloud-config"),
        ),
        patch(f"{module_name}.sync_dns_records", return_value=_dns_result()),
        patch(f"{module_name}.rollback_dns_records"),
        patch(f"{module_name}.notify_success"),
        patch(f"{module_name}.notify_failure"),
    )


def test_provision_vultr_node_completes_cloud_dns_callback_and_allocation() -> None:
    selection = _selection("vultr")
    dependencies, asset_repo = _dependencies(selection)
    request = _request("vultr")
    launch_result = VultrInstanceLaunchResult(
        instance_id="vultr-instance",
        label=request.node_name,
        region="ewr",
        plan="vc2-1c-1gb",
        os_id=2284,
        ipv4_address="192.0.2.10",
        ipv6_address="2001:db8::10",
        subnet_id="vpc-id",
    )
    patches = _common_patches("services.provisioning_vultr_flow")
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5] as notify_success, patches[6], patch(
        "services.provisioning_vultr_flow.VultrClient"
    ) as client_cls:
        client = client_cls.return_value
        client.ensure_firewall_ports.return_value = VultrFirewallEnsureResult(
            firewall_group_id="firewall-id",
            created=True,
        )
        client.launch_instance.return_value = launch_result

        result = provision_vultr_node(dependencies, asset_repo, request)

    assert result.instance_id == "vultr-instance"
    assert result.ipv6_address == "2001:db8::10"
    firewall_call = client.ensure_firewall_ports.call_args.kwargs
    assert firewall_call["inbound_ports"] == (22, 443)
    launch_request = client.launch_instance.call_args.args[0]
    assert launch_request.vpc_ids == ("vpc-id",)
    assert launch_request.firewall_group_id == "firewall-id"
    assert launch_request.tags == ("shadowfleet", "prod")
    dependencies.ready_callback_service.wait_for_ready_callback.assert_called_once_with(91)
    dependencies.ready_callback_service.mark_callback_completed.assert_called_once_with(91)
    asset_repo.create_allocation.assert_called_once()
    notify_success.assert_called_once()


def test_provision_vultr_node_rolls_back_dns_instance_firewall_and_node() -> None:
    selection = _selection("vultr")
    dependencies, asset_repo = _dependencies(selection)
    request = _request("vultr")
    dependencies.ready_callback_service.wait_for_ready_callback.side_effect = RuntimeError(
        "callback timeout"
    )
    patches = _common_patches("services.provisioning_vultr_flow")
    with patches[0], patches[1], patches[2], patches[3], patches[4] as rollback_dns, patches[5], patches[6] as notify_failure, patch(
        "services.provisioning_vultr_flow.VultrClient"
    ) as client_cls:
        client = client_cls.return_value
        client.ensure_firewall_ports.return_value = VultrFirewallEnsureResult(
            firewall_group_id="firewall-id",
            created=True,
        )
        client.launch_instance.return_value = VultrInstanceLaunchResult(
            instance_id="vultr-instance",
            label=request.node_name,
            region="ewr",
            plan="vc2-1c-1gb",
            os_id=2284,
            ipv4_address="192.0.2.10",
            ipv6_address="2001:db8::10",
        )

        with pytest.raises(RuntimeError, match="callback timeout"):
            provision_vultr_node(dependencies, asset_repo, request)

    rollback_dns.assert_called_once()
    client.delete_instance.assert_called_once_with("vultr-instance")
    client.delete_firewall_group.assert_called_once_with("firewall-id")
    dependencies.node_registry.delete_node.assert_called_once_with(20)
    asset_repo.create_allocation.assert_not_called()
    notify_failure.assert_called_once()


def test_provision_azure_node_completes_cloud_dns_callback_and_allocation() -> None:
    selection = _selection("azure")
    dependencies, asset_repo = _dependencies(selection)
    request = _request("azure")
    patches = _common_patches("services.provisioning_azure_flow")
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5] as notify_success, patches[6], patch(
        "services.provisioning_azure_flow.AzureClient"
    ) as client_cls:
        client = client_cls.return_value
        client.launch_vm.return_value = AzureVmLaunchResult(
            instance_id="/subscriptions/subscription-id/resourceGroups/shadowfleet-rg/providers/Microsoft.Compute/virtualMachines/azure-node",
            vm_name=request.node_name,
            location="japaneast",
            vm_size="Standard_B1s",
            network_interface_id="nic-id",
            subnet_id="subnet-id",
            network_security_group_id="nsg-id",
            ipv4_address="192.0.2.20",
            ipv6_address="2001:db8::20",
        )

        result = provision_azure_node(dependencies, asset_repo, request)

    assert result.network_interface_id == "nic-id"
    launch_request = client.launch_vm.call_args.args[0]
    assert launch_request.resource_group == "shadowfleet-rg"
    assert launch_request.inbound_ports == (22, 443)
    assert launch_request.vnet_name == "shadowfleet-vnet-japaneast"
    dependencies.ready_callback_service.mark_callback_completed.assert_called_once_with(91)
    asset_repo.create_allocation.assert_called_once()
    notify_success.assert_called_once()


def test_provision_azure_node_rolls_back_dns_resources_and_node() -> None:
    selection = _selection("azure")
    dependencies, asset_repo = _dependencies(selection)
    request = _request("azure")
    dependencies.ready_callback_service.wait_for_ready_callback.side_effect = RuntimeError(
        "callback timeout"
    )
    patches = _common_patches("services.provisioning_azure_flow")
    with patches[0], patches[1], patches[2], patches[3], patches[4] as rollback_dns, patches[5], patches[6] as notify_failure, patch(
        "services.provisioning_azure_flow.AzureClient"
    ) as client_cls:
        client = client_cls.return_value
        client.launch_vm.return_value = AzureVmLaunchResult(
            instance_id="vm-id",
            vm_name=request.node_name,
            location="japaneast",
            vm_size="Standard_B1s",
            network_interface_id="nic-id",
            subnet_id="subnet-id",
            network_security_group_id="nsg-id",
            ipv4_address="192.0.2.20",
            ipv6_address="2001:db8::20",
        )

        with pytest.raises(RuntimeError, match="callback timeout"):
            provision_azure_node(dependencies, asset_repo, request)

    rollback_dns.assert_called_once()
    client.rollback_created_resources.assert_called_once_with()
    dependencies.node_registry.delete_node.assert_called_once_with(20)
    asset_repo.create_allocation.assert_not_called()
    notify_failure.assert_called_once()
