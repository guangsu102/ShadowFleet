from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from pydantic import ValidationError

from api.router.tasks import ManualTaskCreateRequest, submit_manual_task
from infrastructure.oci import OCIClient, OCIClientError
from services.healing_models import HealRequest, ManualReviewRequiredError
from services.healing_support import determine_heal_strategy
from services.manual_operation_models import ManualOperationSubmitResult
from services.node_registry_service import NodeRegistryService


def test_manual_task_request_accepts_supported_literal_values() -> None:
    request = ManualTaskCreateRequest.model_validate(
        {
            "task_type": "force_heal",
            "xboard_node_id": 42,
            "force_strategy": "digitalocean_instance_replace",
        }
    )

    assert request.task_type == "force_heal"
    assert request.force_strategy == "digitalocean_instance_replace"


@pytest.mark.parametrize(
    ("field", "value"),
    [("task_type", "unknown"), ("force_strategy", "replace_ip")],
)
def test_manual_task_request_rejects_unknown_literals(field: str, value: str) -> None:
    payload: dict[str, object] = {
        "task_type": "force_heal",
        "xboard_node_id": 42,
    }
    payload[field] = value

    with pytest.raises(ValidationError):
        ManualTaskCreateRequest.model_validate(payload)


def test_manual_task_route_passes_validated_literals_to_service() -> None:
    service = MagicMock()
    service.submit_task.return_value = ManualOperationSubmitResult(
        task_id=7,
        correlation_id="manual-correlation",
        status="queued",
    )
    request = ManualTaskCreateRequest(
        task_type="force_heal",
        xboard_node_id=42,
        force_strategy="oci_ipv6_rotate",
    )

    with patch("api.router.tasks.ManualOperationService", return_value=service):
        response = asyncio.run(
            submit_manual_task(request, ctx=MagicMock(), _current_user=None)
        )

    operation = service.submit_task.call_args.args[0]
    assert operation.task_type == "force_heal"
    assert operation.force_strategy == "oci_ipv6_rotate"
    assert response.task_id == 7


def test_cross_provider_forced_healing_strategy_is_rejected() -> None:
    node = MagicMock(
        asset_type="azure",
        aws_account_id="azure:subscription",
        node_type="AnyTLS",
    )

    with pytest.raises(ManualReviewRequiredError, match="does not support"):
        determine_heal_strategy(
            node,
            HealRequest(
                xboard_node_id=42,
                reason="manual",
                force_strategy="aws_ipv6_rotate",
            ),
        )


def _oci_validation_client(*, compatible: bool, shape: dict[str, object]) -> OCIClient:
    client = object.__new__(OCIClient)
    client.list_availability_domains = MagicMock(return_value=[{"name": "AD-1"}])
    client.get_image = MagicMock(
        return_value={"compartmentId": "compartment", "lifecycleState": "AVAILABLE"}
    )
    client.get_subnet = MagicMock(
        return_value={
            "compartmentId": "compartment",
            "lifecycleState": "AVAILABLE",
            "ipv6CidrBlock": "2001:db8::/64",
            "vcnId": "vcn",
        }
    )
    client.get_network_security_group = MagicMock(
        return_value={
            "compartmentId": "compartment",
            "lifecycleState": "AVAILABLE",
            "vcnId": "vcn",
        }
    )
    client.list_shapes = MagicMock(return_value=[shape])
    client.list_image_shape_compatibility_entries = MagicMock(
        return_value=[{"shape": shape["shape"]}] if compatible else []
    )
    return client


def test_oci_target_infers_ampere_shape_as_arm64() -> None:
    client = _oci_validation_client(
        compatible=True,
        shape={
            "shape": "VM.Standard.A1.Flex",
            "isFlexible": True,
            "processorDescription": "Ampere Altra",
        },
    )

    target = client.validate_provisioning_target(
        compartment_ocid="compartment",
        subnet_ocid="subnet",
        network_security_group_ocid="nsg",
        image_ocid="image",
        shape="VM.Standard.A1.Flex",
    )

    assert target.architecture == "arm64"
    client.list_image_shape_compatibility_entries.assert_called_once_with(
        "compartment",
        "image",
        "VM.Standard.A1.Flex",
    )


def test_oci_target_rejects_incompatible_image_and_shape() -> None:
    client = _oci_validation_client(
        compatible=False,
        shape={"shape": "VM.Standard.E4.Flex", "isFlexible": True},
    )

    with pytest.raises(OCIClientError, match="not compatible"):
        client.validate_provisioning_target(
            compartment_ocid="compartment",
            subnet_ocid="subnet",
            network_security_group_ocid="nsg",
            image_ocid="image",
            shape="VM.Standard.E4.Flex",
        )


def _node_registry() -> NodeRegistryService:
    service = object.__new__(NodeRegistryService)
    service._runtime_context = MagicMock(correlation_id="delete-correlation")
    service._asset_repo = MagicMock()
    service._state_repo = MagicMock()
    return service


def test_aws_node_deletion_terminates_instance() -> None:
    service = _node_registry()
    node = MagicMock(
        id=1,
        xboard_node_id=42,
        asset_type="aws",
        aws_account_id="123456789012",
        aws_region="ap-northeast-1",
        aws_instance_id="i-123",
    )
    asset = MagicMock(
        id=8,
        asset_type="aws",
        aws_account_id="123456789012",
        aws_access_key="access",
        aws_secret_key="secret",
        region="ap-northeast-1",
    )
    service._asset_repo.get_asset_by_xboard_node_id.return_value = asset

    with patch("services.node_registry_service.EC2Client") as client_type:
        service._delete_aws_instance(node)

    client_type.return_value.terminate_instance.assert_called_once_with("i-123")


def test_aws_missing_instance_is_idempotent() -> None:
    service = _node_registry()
    node = MagicMock(
        id=1,
        xboard_node_id=42,
        asset_type="aws",
        aws_account_id="123456789012",
        aws_region="ap-northeast-1",
        aws_instance_id="i-missing",
    )
    asset = MagicMock(
        id=8,
        asset_type="aws",
        aws_account_id="123456789012",
        aws_access_key="access",
        aws_secret_key="secret",
        region="ap-northeast-1",
    )
    service._asset_repo.get_asset_by_xboard_node_id.return_value = asset
    error = ClientError(
        {"Error": {"Code": "InvalidInstanceID.NotFound", "Message": "missing"}},
        "TerminateInstances",
    )

    with patch("services.node_registry_service.EC2Client") as client_type:
        client_type.return_value.terminate_instance.side_effect = error
        service._delete_aws_instance(node)

    service._state_repo.create_event.assert_called_once()


def test_digitalocean_node_deletion_deletes_droplet() -> None:
    service = _node_registry()
    node = MagicMock(
        id=1,
        xboard_node_id=42,
        asset_type="digitalocean",
        aws_account_id="account-do",
        aws_instance_id="1001",
    )
    asset = MagicMock(
        id=9,
        asset_type="digitalocean",
        aws_access_key="dop_v1_test",
    )
    service._asset_repo.get_asset_by_xboard_node_id.return_value = asset

    with patch("services.node_registry_service.DigitalOceanClient") as client_type:
        service._delete_digitalocean_instance(node)

    client_type.return_value.delete_droplet.assert_called_once_with("1001")
