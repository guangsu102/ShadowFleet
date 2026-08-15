from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from infrastructure.gcp import GCPInstanceLaunchResult
from services.asset_selector_service import AssetSelectionResult
from services.node_registry_models import NodeStateChangeResult, RegisterNodeResult
from services.provisioning_gcp_flow import provision_gcp_node
from services.provisioning_models import DnsSyncResult, ProvisionRequest
from services.provisioning_support import ProvisioningDependencies


PRIVATE_KEY = "-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----\n"


def _selection() -> AssetSelectionResult:
    return AssetSelectionResult(
        asset_id=61,
        asset_type="gcp",
        asset_name="gcp-asia-east1",
        protocol_type="Trojan",
        region="asia-east1-a",
        aws_account_id="gcp:shadowfleet-test",
        aws_access_key="shadowfleet@example.iam.gserviceaccount.com",
        aws_secret_key=PRIVATE_KEY,
        ssh_host=None,
        ssh_port=None,
        ssh_username=None,
        ssh_password=None,
        ssh_private_key=None,
        instance_type="e2-small",
        vcpu=2,
        architecture="x64",
        ami_id="projects/ubuntu-os-cloud/global/images/ubuntu-2404",
        subnet_id="projects/shadowfleet-test/regions/asia-east1/subnetworks/default",
        security_group_id="shadowfleet-ingress",
        allow_cdn_proxy=False,
        requires_domain=True,
        requires_dns_record=True,
        current_allocated_count=0,
        current_allocated_vcpu=0,
        target_count=1,
        max_count=2,
        provider_config={
            "project_id": "shadowfleet-test",
            "network": "projects/shadowfleet-test/global/networks/default",
            "subnetwork": "projects/shadowfleet-test/regions/asia-east1/subnetworks/default",
            "source_image": "projects/ubuntu-os-cloud/global/images/ubuntu-2404",
            "ssh_username": "ubuntu",
            "ssh_public_key": "ssh-ed25519 AAAA test",
            "labels": {"environment": "test"},
            "firewall_rule_name": "shadowfleet-ingress",
        },
    )


def _request() -> ProvisionRequest:
    return ProvisionRequest(
        protocol_type="Trojan",
        node_name="gcp-node",
        port="443",
        server_port=443,
        rate=Decimal("1"),
        provisioning_task_id=102,
        asset_type="gcp",
        region="asia-east1-a",
        domain_name="gcp.example.com",
        group_ids=[1],
    )


def _dependencies() -> tuple[ProvisioningDependencies, MagicMock]:
    runtime = MagicMock()
    runtime.correlation_id = "gcp-provision-correlation"
    runtime.config.app.skip_rollback_on_failure = False
    selector = MagicMock()
    selector.select_asset.return_value = _selection()
    node_registry = MagicMock()
    node_registry.register_node.return_value = RegisterNodeResult(
        local_node_id=11,
        xboard_node_id=21,
        status="provisioning",
        node_name="gcp-node",
        node_type="Trojan",
    )
    node_registry.mark_node_online.return_value = NodeStateChangeResult(
        local_node_id=11,
        xboard_node_id=21,
        status="online",
    )
    callbacks = MagicMock()
    callbacks.register_callback.return_value = MagicMock()
    return (
        ProvisioningDependencies(
            runtime_context=runtime,
            logger=MagicMock(),
            asset_selector=selector,
            node_registry=node_registry,
            ready_callback_service=callbacks,
        ),
        MagicMock(),
    )


def _dns_result() -> DnsSyncResult:
    return DnsSyncResult(
        primary_record_id="a-record",
        a_record_id="a-record",
        aaaa_record_id=None,
        snapshots=(),
    )


def _launch_result() -> GCPInstanceLaunchResult:
    return GCPInstanceLaunchResult(
        instance_id="123456789",
        name="gcp-node-21",
        zone="asia-east1-a",
        machine_type="e2-small",
        network_interface="nic0",
        ipv4_address="192.0.2.70",
        ipv6_address=None,
    )


def test_provision_gcp_node_completes_firewall_dns_callback_and_allocation() -> None:
    dependencies, asset_repo = _dependencies()
    with patch("services.node_auto_config_service.NodeAutoConfigService"), patch(
        "services.provisioning_gcp_flow.build_user_data_render_request",
        return_value=MagicMock(),
    ), patch(
        "services.provisioning_gcp_flow.render_user_data",
        return_value=SimpleNamespace(user_data="#cloud-config"),
    ), patch(
        "services.provisioning_gcp_flow.sync_dns_records",
        return_value=_dns_result(),
    ) as sync_dns, patch(
        "services.provisioning_gcp_flow.notify_success"
    ) as notify_success, patch(
        "services.provisioning_gcp_flow.notify_failure"
    ), patch(
        "services.provisioning_gcp_flow.GCPClient"
    ) as client_cls:
        client_cls.return_value.launch_instance.return_value = _launch_result()

        result = provision_gcp_node(dependencies, asset_repo, _request())

    client_cls.return_value.ensure_firewall_ports.assert_called_once_with(
        network="projects/shadowfleet-test/global/networks/default",
        inbound_ports=(22, 443),
        rule_name="shadowfleet-ingress",
    )
    launch_request = client_cls.return_value.launch_instance.call_args.args[0]
    assert launch_request.name == "gcp-node-21"
    assert launch_request.zone == "asia-east1-a"
    assert launch_request.machine_type == "e2-small"
    assert launch_request.labels == {"environment": "test"}
    assert sync_dns.call_args.kwargs["ipv4_address"] == "192.0.2.70"
    dependencies.ready_callback_service.wait_for_ready_callback.assert_called_once_with(102)
    dependencies.ready_callback_service.mark_callback_completed.assert_called_once_with(102)
    asset_repo.create_allocation.assert_called_once()
    notify_success.assert_called_once()
    assert result.instance_id == "gcp-node-21"
    assert result.network_interface_id == "nic0"
    assert result.ipv4_address == "192.0.2.70"


def test_provision_gcp_node_rolls_back_dns_instance_and_node() -> None:
    dependencies, asset_repo = _dependencies()
    dependencies.ready_callback_service.wait_for_ready_callback.side_effect = RuntimeError(
        "callback timeout"
    )
    with patch("services.node_auto_config_service.NodeAutoConfigService"), patch(
        "services.provisioning_gcp_flow.build_user_data_render_request",
        return_value=MagicMock(),
    ), patch(
        "services.provisioning_gcp_flow.render_user_data",
        return_value=SimpleNamespace(user_data="#cloud-config"),
    ), patch(
        "services.provisioning_gcp_flow.sync_dns_records",
        return_value=_dns_result(),
    ), patch(
        "services.provisioning_gcp_flow.rollback_dns_records"
    ) as rollback_dns, patch(
        "services.provisioning_gcp_flow.notify_success"
    ), patch(
        "services.provisioning_gcp_flow.notify_failure"
    ) as notify_failure, patch(
        "services.provisioning_gcp_flow.GCPClient"
    ) as client_cls:
        client_cls.return_value.launch_instance.return_value = _launch_result()

        with pytest.raises(RuntimeError, match="callback timeout"):
            provision_gcp_node(dependencies, asset_repo, _request())

    rollback_dns.assert_called_once()
    client_cls.return_value.delete_instance.assert_called_once_with(
        "asia-east1-a",
        "gcp-node-21",
    )
    dependencies.node_registry.delete_node.assert_called_once_with(21)
    asset_repo.create_allocation.assert_not_called()
    notify_failure.assert_called_once()
