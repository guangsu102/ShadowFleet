from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from infrastructure.oci import OCIProvisioningTarget
from services.asset_application_models import OCIAssetRegistrationRequest
from services.asset_application_service import AssetApplicationService


def test_registration_rejects_shape_config_for_fixed_oci_shape() -> None:
    runtime = MagicMock()
    runtime.logger.getChild.return_value = MagicMock()
    runtime.correlation_id = "shape-test"
    with patch("services.asset_application_service.AssetRepo") as repo_type:
        service = AssetApplicationService(runtime)
    client = MagicMock()
    client.validate_provisioning_target.return_value = OCIProvisioningTarget(
        availability_domain="AD-1",
        shape="VM.Standard.E2.1.Micro",
        is_flexible_shape=False,
    )
    request = OCIAssetRegistrationRequest(
        asset_name="oci-fixed",
        region="ap-tokyo-1",
        tenancy_ocid="tenancy",
        user_ocid="user",
        fingerprint="aa:bb",
        private_key="private-key",
        compartment_ocid="compartment",
        subnet_ocid="subnet",
        network_security_group_ocid="nsg",
        image_ocid="image",
        ssh_public_key="ssh-ed25519 AAAA test",
        shape="VM.Standard.E2.1.Micro",
        ocpus=1,
        memory_in_gbs=1,
    )

    with patch.object(service, "_build_oci_client", return_value=client):
        with pytest.raises(ValueError, match="only valid for flexible OCI shapes"):
            service.register_oci_asset(request)

    repo_type.return_value.create_asset.assert_not_called()
