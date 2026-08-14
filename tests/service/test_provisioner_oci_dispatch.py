from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

from services.provisioner_service import ProvisionerService
from services.provisioning_models import ProvisionRequest


def test_provisioner_service_dispatches_oci_request_to_oci_flow() -> None:
    runtime = MagicMock()
    runtime.logger.getChild.return_value = MagicMock()
    with patch("services.provisioner_service.AssetSelectorService"), patch(
        "services.provisioner_service.AssetRepo"
    ), patch("services.provisioner_service.NodeRegistryService"), patch(
        "services.provisioner_service.ReadyCallbackService"
    ):
        service = ProvisionerService(runtime)
    request = ProvisionRequest(
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
    expected = MagicMock()

    with patch(
        "services.provisioner_service.provision_oci_node", return_value=expected
    ) as flow:
        result = service.provision_node(request)

    assert result is expected
    assert flow.call_args.args[2] is request
