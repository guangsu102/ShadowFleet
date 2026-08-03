from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.router import assets as assets_router
from services.asset_application_models import (
    AssetRegistrationResult,
    DigitalOceanAssetRegistrationRequest,
)


@pytest.fixture
def assets_client() -> TestClient:
    app = FastAPI()
    app.include_router(assets_router.router)

    runtime_context = Mock()
    runtime_context.correlation_id = "test-correlation-id"
    runtime_context.logger = Mock()
    runtime_context.logger.getChild.return_value = Mock()

    app.dependency_overrides[assets_router.get_runtime_context] = lambda: runtime_context
    app.dependency_overrides[assets_router.get_current_user] = lambda: None
    app.dependency_overrides[assets_router.require_operator] = lambda: None

    return TestClient(app)


def test_register_digitalocean_asset_route_maps_request(assets_client: TestClient) -> None:
    with patch("api.router.assets.AssetApplicationService") as service_cls:
        service = service_cls.return_value
        service.register_digitalocean_asset.return_value = AssetRegistrationResult(
            asset_id=12,
            asset_name="do-sgp1",
            protocol_config_id=34,
        )

        response = assets_client.post(
            "/api/v1/assets/digitalocean",
            json={
                "asset_name": "do-sgp1",
                "region": "sgp1",
                "digitalocean_token": "dop_v1_test",
                "default_size": "s-2vcpu-2gb",
                "default_image": "ubuntu-24-04-x64",
                "ssh_keys": ["fingerprint-1"],
                "vpc_uuid": "vpc-123",
                "tags": ["prod"],
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
    assert response.json() == {
        "asset_id": 12,
        "asset_name": "do-sgp1",
        "asset_type": "digitalocean",
        "region": "sgp1",
        "status": "active",
        "aws_account_id": None,
        "aws_access_key": None,
        "aws_secret_key": None,
        "account_total_vcpu": None,
        "allocated_count": 0,
        "target_count": 0,
        "max_count": 0,
        "supported_protocols": [],
        "cpu_cores": None,
        "memory_gb": None,
        "remarks": None,
        "updated_at": "",
    }
    request = service.register_digitalocean_asset.call_args.args[0]
    assert isinstance(request, DigitalOceanAssetRegistrationRequest)
    assert request.digitalocean_token == "dop_v1_test"
    assert request.default_size == "s-2vcpu-2gb"
    assert request.default_image == "ubuntu-24-04-x64"
    assert request.ssh_keys == ("fingerprint-1",)
    assert request.vpc_uuid == "vpc-123"
    assert request.tags == ("prod",)
    assert request.additional_protocol_types == ("AnyTLS",)


def test_digitalocean_catalog_routes(assets_client: TestClient) -> None:
    with patch("api.router.assets.AssetApplicationService") as service_cls:
        service = service_cls.return_value
        service.query_digitalocean_images.return_value = [
            {
                "id": 123,
                "name": "Ubuntu 24.04",
                "slug": "ubuntu-24-04-x64",
                "distribution": "Ubuntu",
                "regions": ["sgp1"],
            }
        ]
        service.query_digitalocean_sizes.return_value = [
            {
                "slug": "s-2vcpu-2gb",
                "memory": 2048,
                "vcpus": 2,
                "disk": 60,
                "transfer": 3.0,
                "price_monthly": 18.0,
                "regions": ["sgp1"],
                "available": True,
            }
        ]

        images_response = assets_client.post(
            "/api/v1/assets/digitalocean/query-images",
            json={"digitalocean_token": "dop_v1_test", "limit": 10},
        )
        sizes_response = assets_client.post(
            "/api/v1/assets/digitalocean/query-sizes",
            json={"digitalocean_token": "dop_v1_test", "limit": 10},
        )

    assert images_response.status_code == 200
    assert images_response.json()["images"][0]["slug"] == "ubuntu-24-04-x64"
    assert sizes_response.status_code == 200
    assert sizes_response.json()["sizes"][0]["slug"] == "s-2vcpu-2gb"
    service.query_digitalocean_images.assert_called_once_with(
        digitalocean_token="dop_v1_test",
        limit=10,
    )
    service.query_digitalocean_sizes.assert_called_once_with(
        digitalocean_token="dop_v1_test",
        limit=10,
    )
