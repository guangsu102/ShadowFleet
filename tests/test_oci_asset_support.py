from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.router import assets as assets_router
from infrastructure.oci import OCIProvisioningTarget
from services.asset_application_models import (
    AssetRegistrationResult,
    OCIAssetRegistrationRequest,
)
from services.asset_application_service import AssetApplicationService


def _runtime() -> MagicMock:
    runtime = MagicMock()
    runtime.correlation_id = "oci-test-correlation"
    runtime.logger.getChild.return_value = MagicMock()
    runtime.config.app.request_timeout_seconds = 30
    runtime.config.app.max_retries = 0
    runtime.config.app.retry_backoff_seconds = 0.01
    return runtime


def _registration_request() -> OCIAssetRegistrationRequest:
    return OCIAssetRegistrationRequest(
        asset_name="oci-japan",
        region="ap-tokyo-1",
        tenancy_ocid="tenancy-ocid",
        user_ocid="user-ocid",
        fingerprint="aa:bb",
        private_key="private-key",
        compartment_ocid="compartment-ocid",
        subnet_ocid="subnet-ocid",
        network_security_group_ocid="nsg-ocid",
        image_ocid="image-ocid",
        ssh_public_key="ssh-ed25519 AAAA test",
        shape="VM.Standard.E4.Flex",
        tags=("prod", "owner=platform"),
        protocol_type="Trojan",
        additional_protocol_types=("AnyTLS",),
        target_count=1,
        max_count=2,
        default_vcpu=1,
        ocpus=1,
        memory_in_gbs=6,
    )


def test_register_oci_asset_validates_target_and_persists_provider_config() -> None:
    runtime = _runtime()
    with patch("services.asset_application_service.AssetRepo") as repo_type:
        service = AssetApplicationService(runtime)
    repo = repo_type.return_value
    repo.create_asset.return_value = 77
    repo.upsert_asset_protocol_config.return_value = 88
    client = MagicMock()
    client.validate_provisioning_target.return_value = OCIProvisioningTarget(
        availability_domain="AD-1",
        shape="VM.Standard.E4.Flex",
        is_flexible_shape=True,
    )

    with patch.object(service, "_build_oci_client", return_value=client):
        result = service.register_oci_asset(_registration_request())

    client.validate_identity.assert_called_once()
    client.validate_provisioning_target.assert_called_once_with(
        compartment_ocid="compartment-ocid",
        subnet_ocid="subnet-ocid",
        network_security_group_ocid="nsg-ocid",
        image_ocid="image-ocid",
        shape="VM.Standard.E4.Flex",
        availability_domain=None,
    )
    create_request = repo.create_asset.call_args.args[0]
    assert create_request.asset_type == "oci"
    assert create_request.aws_account_id == "oci:tenancy-ocid"
    assert create_request.aws_access_key == "user-ocid"
    assert create_request.aws_secret_key == "private-key"
    assert create_request.provider_config["availability_domain"] == "AD-1"
    assert create_request.provider_config["shape_is_flexible"] is True
    assert create_request.provider_config["freeform_tags"] == {
        "prod": "true",
        "owner": "platform",
    }
    assert [
        call.args[0].protocol_type
        for call in repo.upsert_asset_protocol_config.call_args_list
    ] == ["Trojan", "AnyTLS"]
    assert result == AssetRegistrationResult(77, "oci-japan", 88)


def test_query_oci_catalog_returns_all_required_resource_classes() -> None:
    runtime = _runtime()
    with patch("services.asset_application_service.AssetRepo"):
        service = AssetApplicationService(runtime)
    client = MagicMock()
    client.list_availability_domains.return_value = [{"name": "AD-1"}]
    client.list_images.return_value = [{"id": "image"}]
    client.list_shapes.return_value = [{"shape": "shape"}]
    client.list_subnets.return_value = [{"id": "subnet"}]
    client.list_network_security_groups.return_value = [{"id": "nsg"}]

    with patch.object(service, "_build_oci_client", return_value=client):
        result = service.query_oci_catalog(
            region="ap-tokyo-1",
            tenancy_ocid="tenancy",
            user_ocid="user",
            fingerprint="aa:bb",
            private_key="private-key",
            compartment_ocid="compartment",
            availability_domain="AD-1",
        )

    assert set(result) == {
        "availability_domains",
        "images",
        "shapes",
        "subnets",
        "network_security_groups",
    }
    client.validate_identity.assert_called_once()
    client.list_shapes.assert_called_once_with(
        "compartment", availability_domain="AD-1"
    )


def test_register_oci_asset_route_maps_credentials_without_exposing_them() -> None:
    app = FastAPI()
    app.include_router(assets_router.router)
    runtime = _runtime()
    app.dependency_overrides[assets_router.get_runtime_context] = lambda: runtime
    app.dependency_overrides[assets_router.get_current_user] = lambda: None
    app.dependency_overrides[assets_router.require_operator] = lambda: None

    with patch("api.router.assets.AssetApplicationService") as service_type:
        service_type.return_value.register_oci_asset.return_value = AssetRegistrationResult(
            77, "oci-japan", 88
        )
        response = TestClient(app).post(
            "/api/v1/assets/oci",
            json={
                "asset_name": "oci-japan",
                "region": "ap-tokyo-1",
                "tenancy_ocid": "tenancy-ocid",
                "user_ocid": "user-ocid",
                "fingerprint": "aa:bb",
                "private_key": "private-key",
                "compartment_ocid": "compartment-ocid",
                "subnet_ocid": "subnet-ocid",
                "network_security_group_ocid": "nsg-ocid",
                "image_ocid": "image-ocid",
                "ssh_public_key": "ssh-ed25519 AAAA test",
                "protocol_type": "Trojan",
                "additional_protocol_types": ["AnyTLS"],
            },
        )

    assert response.status_code == 201
    assert response.json()["asset_type"] == "oci"
    assert response.json()["aws_account_id"] == "oci:tenancy-ocid"
    assert response.json()["aws_access_key"] is None
    mapped = service_type.return_value.register_oci_asset.call_args.args[0]
    assert isinstance(mapped, OCIAssetRegistrationRequest)
    assert mapped.user_ocid == "user-ocid"
    assert mapped.additional_protocol_types == ("AnyTLS",)
