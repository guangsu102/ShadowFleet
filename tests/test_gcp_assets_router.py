from __future__ import annotations

import json
from unittest.mock import Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.router import assets as assets_router
from services.asset_application_models import (
    AssetRegistrationResult,
    GCPAssetRegistrationRequest,
)


@pytest.fixture
def assets_client() -> TestClient:
    app = FastAPI()
    app.include_router(assets_router.router)
    runtime_context = Mock()
    runtime_context.correlation_id = "gcp-route-correlation"
    runtime_context.logger = Mock()
    runtime_context.logger.getChild.return_value = Mock()
    app.dependency_overrides[assets_router.get_runtime_context] = lambda: runtime_context
    app.dependency_overrides[assets_router.get_current_user] = lambda: None
    app.dependency_overrides[assets_router.require_operator] = lambda: None
    return TestClient(app)


def _service_account_json() -> str:
    return json.dumps(
        {
            "type": "service_account",
            "project_id": "shadowfleet-test",
            "client_email": "shadowfleet@example.iam.gserviceaccount.com",
            "private_key": "-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----\n",
        }
    )


def test_register_gcp_asset_route_maps_all_provider_fields(
    assets_client: TestClient,
) -> None:
    with patch("api.router.assets.AssetApplicationService") as service_cls:
        service_cls.return_value.register_gcp_asset.return_value = (
            AssetRegistrationResult(
                asset_id=16,
                asset_name="gcp-asia-east1",
                protocol_config_id=38,
            )
        )
        response = assets_client.post(
            "/api/v1/assets/gcp",
            json={
                "asset_name": "gcp-asia-east1",
                "project_id": "shadowfleet-test",
                "service_account_json": _service_account_json(),
                "zone": "asia-east1-a",
                "machine_type": "e2-small",
                "source_image": "projects/ubuntu-os-cloud/global/images/family/ubuntu-2404-lts-amd64",
                "network": "default",
                "subnetwork": "default",
                "ssh_username": "ubuntu",
                "ssh_public_key": "ssh-ed25519 AAAA test",
                "labels": ["environment=test"],
                "protocol_type": "Trojan",
                "additional_protocol_types": ["AnyTLS"],
                "target_count": 1,
                "max_count": 2,
                "priority": 80,
                "allow_cdn_proxy": True,
                "default_vcpu": 2,
            },
        )

    assert response.status_code == 201
    assert response.json()["asset_type"] == "gcp"
    assert response.json()["aws_account_id"] == "gcp:shadowfleet-test"
    request = service_cls.return_value.register_gcp_asset.call_args.args[0]
    assert isinstance(request, GCPAssetRegistrationRequest)
    assert request.zone == "asia-east1-a"
    assert request.labels == ("environment=test",)
    assert request.additional_protocol_types == ("AnyTLS",)


def test_gcp_catalog_route_maps_credentials_zone_and_image_project(
    assets_client: TestClient,
) -> None:
    with patch("api.router.assets.AssetApplicationService") as service_cls:
        service_cls.return_value.query_gcp_catalog.return_value = {
            "zones": [{"name": "asia-east1-a"}],
            "machine_types": [{"name": "e2-small"}],
            "images": [{"name": "ubuntu-2404"}],
            "networks": [{"name": "default"}],
            "subnetworks": [{"name": "default"}],
        }
        response = assets_client.post(
            "/api/v1/assets/gcp/query-catalog",
            json={
                "service_account_json": _service_account_json(),
                "project_id": "shadowfleet-test",
                "zone": "asia-east1-a",
                "image_project": "ubuntu-os-cloud",
            },
        )

    assert response.status_code == 200
    assert response.json()["machine_types"][0]["name"] == "e2-small"
    service_cls.return_value.query_gcp_catalog.assert_called_once_with(
        service_account_json=_service_account_json(),
        project_id="shadowfleet-test",
        zone="asia-east1-a",
        image_project="ubuntu-os-cloud",
    )
