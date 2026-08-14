from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from infrastructure.oci import OCIInstanceLaunchResult
from services.asset_selector_service import AssetSelectionResult
from services.node_registry_models import NodeStateChangeResult, RegisterNodeResult
from services.provisioning_models import DnsSyncResult, ProvisionRequest
from services.provisioning_oci_flow import provision_oci_node
from services.provisioning_support import ProvisioningDependencies


def _selection() -> AssetSelectionResult:
    return AssetSelectionResult(
        asset_id=41,
        asset_type="oci",
        asset_name="oci-asset",
        protocol_type="Trojan",
        region="ap-tokyo-1",
        aws_account_id="oci:tenancy",
        aws_access_key="user-ocid",
        aws_secret_key="private-key",
        ssh_host=None,
        ssh_port=None,
        ssh_username=None,
        ssh_password=None,
        ssh_private_key=None,
        instance_type="VM.Standard.E4.Flex",
        vcpu=1,
        architecture="x64",
        ami_id="image-ocid",
        subnet_id="subnet-ocid",
        security_group_id="nsg-ocid",
        allow_cdn_proxy=False,
        requires_domain=True,
        requires_dns_record=True,
        current_allocated_count=0,
        current_allocated_vcpu=0,
        target_count=1,
        max_count=2,
        provider_config={
            "tenancy_ocid": "tenancy",
            "fingerprint": "aa:bb",
            "compartment_ocid": "compartment-ocid",
            "availability_domain": "AD-1",
            "ssh_public_key": "ssh-ed25519 AAAA test",
            "ocpus": 1,
            "memory_in_gbs": 6,
            "freeform_tags": {"environment": "test"},
        },
    )


def _request() -> ProvisionRequest:
    return ProvisionRequest(
        protocol_type="Trojan",
        node_name="oci-node",
        port="443",
        server_port=443,
        rate=Decimal("1"),
        provisioning_task_id=91,
        asset_type="oci",
        region="ap-tokyo-1",
        domain_name="oci.example.com",
        group_ids=[1],
    )


def _dependencies() -> tuple[ProvisioningDependencies, MagicMock]:
    runtime = MagicMock()
    runtime.correlation_id = "correlation-id"
    runtime.config.app.skip_rollback_on_failure = False
    selector = MagicMock()
    selector.select_asset.return_value = _selection()
    node_registry = MagicMock()
    node_registry.register_node.return_value = RegisterNodeResult(
        local_node_id=10,
        xboard_node_id=20,
        status="provisioning",
        node_name="oci-node",
        node_type="Trojan",
    )
    node_registry.mark_node_online.return_value = NodeStateChangeResult(
        local_node_id=10,
        xboard_node_id=20,
        status="online",
    )
    ready_callback_service = MagicMock()
    ready_callback_service.register_callback.return_value = MagicMock()
    return (
        ProvisioningDependencies(
            runtime_context=runtime,
            logger=MagicMock(),
            asset_selector=selector,
            node_registry=node_registry,
            ready_callback_service=ready_callback_service,
        ),
        MagicMock(),
    )


def _launch_result() -> OCIInstanceLaunchResult:
    return OCIInstanceLaunchResult(
        instance_id="instance-ocid",
        display_name="oci-node",
        availability_domain="AD-1",
        shape="VM.Standard.E4.Flex",
        vnic_id="vnic-ocid",
        subnet_ocid="subnet-ocid",
        ipv4_address="192.0.2.10",
        ipv6_address="2001:db8::10",
    )


def _flow_patches():
    module = "services.provisioning_oci_flow"
    return (
        patch("services.node_auto_config_service.NodeAutoConfigService"),
        patch(f"{module}.build_user_data_render_request", return_value=MagicMock()),
        patch(f"{module}.render_user_data", return_value=SimpleNamespace(user_data="#cloud-config")),
        patch(
            f"{module}.sync_dns_records",
            return_value=DnsSyncResult(
                primary_record_id="aaaa-record",
                a_record_id="a-record",
                aaaa_record_id="aaaa-record",
                snapshots=(),
            ),
        ),
        patch(f"{module}.rollback_dns_records"),
        patch(f"{module}.notify_success"),
        patch(f"{module}.notify_failure"),
        patch(f"{module}.OCIClient"),
    )


def test_provision_oci_node_completes_cloud_dns_callback_and_allocation() -> None:
    dependencies, asset_repo = _dependencies()
    patches = _flow_patches()
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5] as notify_success, patches[6], patches[7] as client_cls:
        client = client_cls.return_value
        client.launch_instance.return_value = _launch_result()

        result = provision_oci_node(dependencies, asset_repo, _request())

    credentials = client_cls.call_args.kwargs["credentials"]
    assert credentials.tenancy_ocid == "tenancy"
    assert credentials.user_ocid == "user-ocid"
    client.ensure_network_security_group_ports.assert_called_once_with(
        "nsg-ocid", (22, 443)
    )
    launch_request = client.launch_instance.call_args.args[0]
    assert launch_request.compartment_ocid == "compartment-ocid"
    assert launch_request.freeform_tags == {"environment": "test"}
    dependencies.ready_callback_service.wait_for_ready_callback.assert_called_once_with(91)
    dependencies.ready_callback_service.mark_callback_completed.assert_called_once_with(91)
    asset_repo.create_allocation.assert_called_once()
    notify_success.assert_called_once()
    assert result.instance_id == "instance-ocid"
    assert result.network_interface_id == "vnic-ocid"


def test_provision_oci_node_rolls_back_dns_instance_and_node() -> None:
    dependencies, asset_repo = _dependencies()
    dependencies.ready_callback_service.wait_for_ready_callback.side_effect = RuntimeError(
        "callback timeout"
    )
    patches = _flow_patches()
    with patches[0], patches[1], patches[2], patches[3], patches[4] as rollback_dns, patches[5], patches[6] as notify_failure, patches[7] as client_cls:
        client = client_cls.return_value
        client.launch_instance.return_value = _launch_result()

        with pytest.raises(RuntimeError, match="callback timeout"):
            provision_oci_node(dependencies, asset_repo, _request())

    rollback_dns.assert_called_once()
    client.delete_instance.assert_called_once_with("instance-ocid")
    dependencies.node_registry.delete_node.assert_called_once_with(20)
    asset_repo.create_allocation.assert_not_called()
    notify_failure.assert_called_once()
