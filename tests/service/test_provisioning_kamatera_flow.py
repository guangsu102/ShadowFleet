from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from infrastructure.kamatera import KamateraServerLaunchResult
from services.asset_selector_service import AssetSelectionResult
from services.node_registry_models import NodeStateChangeResult, RegisterNodeResult
from services.provisioning_kamatera_flow import provision_kamatera_node
from services.provisioning_models import DnsSyncResult, ProvisionRequest
from services.provisioning_support import ProvisioningDependencies


def _selection() -> AssetSelectionResult:
    return AssetSelectionResult(
        asset_id=51,
        asset_type="kamatera",
        asset_name="kamatera-as",
        protocol_type="Trojan",
        region="AS",
        aws_account_id="kamatera:account",
        aws_access_key="client-id",
        aws_secret_key="client-secret",
        ssh_host=None,
        ssh_port=None,
        ssh_username=None,
        ssh_password=None,
        ssh_private_key=None,
        instance_type="2B",
        vcpu=2,
        architecture="x64",
        ami_id="ubuntu_server_24.04_64-bit",
        subnet_id=None,
        security_group_id=None,
        allow_cdn_proxy=False,
        requires_domain=True,
        requires_dns_record=True,
        current_allocated_count=0,
        current_allocated_vcpu=0,
        target_count=1,
        max_count=2,
        provider_config={
            "ssh_public_key": "ssh-ed25519 test",
            "ram_mb": 4096,
            "disk_sizes_gb": [30, 40],
            "billing_cycle": "hourly",
            "daily_backup": True,
            "managed": False,
            "tags": ["prod"],
        },
    )


def _request() -> ProvisionRequest:
    return ProvisionRequest(
        protocol_type="Trojan",
        node_name="kamatera-node",
        port="443",
        server_port=443,
        rate=Decimal("1"),
        provisioning_task_id=92,
        asset_type="kamatera",
        region="AS",
        domain_name="kamatera.example.com",
        group_ids=[1],
    )


def _dependencies() -> tuple[ProvisioningDependencies, MagicMock]:
    runtime = MagicMock()
    runtime.correlation_id = "kamatera-provision-correlation"
    runtime.config.app.skip_rollback_on_failure = False
    selector = MagicMock()
    selector.select_asset.return_value = _selection()
    node_registry = MagicMock()
    node_registry.register_node.return_value = RegisterNodeResult(
        local_node_id=11,
        xboard_node_id=21,
        status="provisioning",
        node_name="kamatera-node",
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
        primary_record_id="aaaa-record",
        a_record_id="a-record",
        aaaa_record_id="aaaa-record",
        snapshots=(),
    )


def _launch_result() -> KamateraServerLaunchResult:
    return KamateraServerLaunchResult(
        instance_id="server-1",
        name="sf-kamatera-node-deadbeef",
        datacenter="AS",
        cpu="2B",
        ram_mb=4096,
        ipv4_address="192.0.2.50",
        ipv6_address="2001:db8::50",
        networks=(),
    )


def test_provision_kamatera_node_completes_dns_callback_and_allocation() -> None:
    dependencies, asset_repo = _dependencies()
    with patch("services.node_auto_config_service.NodeAutoConfigService"), patch(
        "services.provisioning_kamatera_flow.build_user_data_render_request",
        return_value=MagicMock(),
    ), patch(
        "services.provisioning_kamatera_flow.render_user_data",
        return_value=SimpleNamespace(user_data="#cloud-config"),
    ), patch(
        "services.provisioning_kamatera_flow.sync_dns_records",
        return_value=_dns_result(),
    ) as sync_dns, patch(
        "services.provisioning_kamatera_flow.notify_success"
    ) as notify_success, patch(
        "services.provisioning_kamatera_flow.notify_failure"
    ), patch(
        "services.provisioning_kamatera_flow.KamateraClient"
    ) as client_cls:
        client_cls.return_value.launch_server.return_value = _launch_result()

        result = provision_kamatera_node(dependencies, asset_repo, _request())

    assert result.instance_id == "server-1"
    assert result.ipv4_address == "192.0.2.50"
    assert result.ipv6_address == "2001:db8::50"
    launch_request = client_cls.return_value.launch_server.call_args.args[0]
    assert launch_request.datacenter == "AS"
    assert launch_request.image == "ubuntu_server_24.04_64-bit"
    assert launch_request.cpu == "2B"
    assert launch_request.ram_mb == 4096
    assert launch_request.disk_sizes_gb == (30, 40)
    assert launch_request.tags == ("prod", "shadowfleet-xboard-21")
    assert sync_dns.call_args.kwargs["ipv4_address"] == "192.0.2.50"
    assert sync_dns.call_args.kwargs["ipv6_address"] == "2001:db8::50"
    dependencies.ready_callback_service.wait_for_ready_callback.assert_called_once_with(92)
    dependencies.ready_callback_service.mark_callback_completed.assert_called_once_with(92)
    asset_repo.create_allocation.assert_called_once()
    notify_success.assert_called_once()


def test_provision_kamatera_node_rolls_back_dns_server_and_node() -> None:
    dependencies, asset_repo = _dependencies()
    dependencies.ready_callback_service.wait_for_ready_callback.side_effect = RuntimeError(
        "callback timeout"
    )
    with patch("services.node_auto_config_service.NodeAutoConfigService"), patch(
        "services.provisioning_kamatera_flow.build_user_data_render_request",
        return_value=MagicMock(),
    ), patch(
        "services.provisioning_kamatera_flow.render_user_data",
        return_value=SimpleNamespace(user_data="#cloud-config"),
    ), patch(
        "services.provisioning_kamatera_flow.sync_dns_records",
        return_value=_dns_result(),
    ), patch(
        "services.provisioning_kamatera_flow.rollback_dns_records"
    ) as rollback_dns, patch(
        "services.provisioning_kamatera_flow.notify_success"
    ), patch(
        "services.provisioning_kamatera_flow.notify_failure"
    ) as notify_failure, patch(
        "services.provisioning_kamatera_flow.KamateraClient"
    ) as client_cls:
        client_cls.return_value.launch_server.return_value = _launch_result()

        with pytest.raises(RuntimeError, match="callback timeout"):
            provision_kamatera_node(dependencies, asset_repo, _request())

    rollback_dns.assert_called_once()
    delete_call = client_cls.return_value.delete_server.call_args
    assert delete_call.args == ("server-1",)
    assert str(delete_call.kwargs["name"]).startswith("sf-kamatera-node-")
    dependencies.node_registry.delete_node.assert_called_once_with(21)
    asset_repo.create_allocation.assert_not_called()
    notify_failure.assert_called_once()
