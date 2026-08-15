from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.router import assets as assets_router
from services.asset_application_models import (
    AssetRegistrationResult,
    AzureAssetRegistrationRequest,
    DigitalOceanAssetRegistrationRequest,
    KamateraAssetRegistrationRequest,
    VultrAssetRegistrationRequest,
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


def test_register_vultr_asset_route_maps_request(assets_client: TestClient) -> None:
    with patch("api.router.assets.AssetApplicationService") as service_cls:
        service = service_cls.return_value
        service.register_vultr_asset.return_value = AssetRegistrationResult(
            asset_id=13,
            asset_name="vultr-sgp",
            protocol_config_id=35,
        )

        response = assets_client.post(
            "/api/v1/assets/vultr",
            json={
                "asset_name": "vultr-sgp",
                "region": "sgp",
                "vultr_token": "vultr-test-token",
                "default_plan": "vc2-1c-1gb",
                "default_os_id": 2284,
                "ssh_key_ids": ["ssh-key-1"],
                "vpc_ids": ["vpc-id"],
                "firewall_group_id": "firewall-id",
                "tags": ["prod"],
                "protocol_type": "Trojan",
                "additional_protocol_types": ["AnyTLS"],
                "target_count": 1,
                "max_count": 2,
                "priority": 80,
                "allow_cdn_proxy": True,
                "default_vcpu": 1,
            },
        )

    assert response.status_code == 201
    assert response.json()["asset_type"] == "vultr"
    assert response.json()["aws_access_key"] is None
    request = service.register_vultr_asset.call_args.args[0]
    assert isinstance(request, VultrAssetRegistrationRequest)
    assert request.vultr_token == "vultr-test-token"
    assert request.ssh_key_ids == ("ssh-key-1",)
    assert request.vpc_ids == ("vpc-id",)
    assert request.firewall_group_id == "firewall-id"


def test_register_kamatera_asset_route_maps_request(assets_client: TestClient) -> None:
    with patch("api.router.assets.AssetApplicationService") as service_cls:
        service = service_cls.return_value
        service.register_kamatera_asset.return_value = AssetRegistrationResult(
            asset_id=15,
            asset_name="kamatera-asia",
            protocol_config_id=37,
        )

        response = assets_client.post(
            "/api/v1/assets/kamatera",
            json={
                "asset_name": "kamatera-asia",
                "datacenter": "AS",
                "client_id": "kamatera-client",
                "secret": "kamatera-secret",
                "image": "ubuntu_server_24.04_64-bit",
                "ssh_public_key": "ssh-ed25519 AAAA test",
                "cpu_type": "B",
                "cpu_cores": 2,
                "ram_mb": 4096,
                "disk_sizes_gb": [30, 40],
                "billing_cycle": "hourly",
                "tags": ["prod"],
                "protocol_type": "Trojan",
                "additional_protocol_types": ["AnyTLS"],
                "target_count": 1,
                "max_count": 2,
                "priority": 80,
                "allow_cdn_proxy": True,
            },
        )

    assert response.status_code == 201
    assert response.json()["asset_type"] == "kamatera"
    assert response.json()["aws_access_key"] is None
    assert response.json()["aws_secret_key"] is None
    request = service.register_kamatera_asset.call_args.args[0]
    assert isinstance(request, KamateraAssetRegistrationRequest)
    assert request.client_id == "kamatera-client"
    assert request.secret == "kamatera-secret"
    assert request.disk_sizes_gb == (30, 40)
    assert request.additional_protocol_types == ("AnyTLS",)


def test_kamatera_catalog_route_maps_credentials_and_datacenter(
    assets_client: TestClient,
) -> None:
    with patch("api.router.assets.AssetApplicationService") as service_cls:
        service = service_cls.return_value
        service.query_kamatera_catalog.return_value = {
            "datacenters": [{"id": "AS"}],
            "images": [{"id": "ubuntu"}],
            "capabilities": {"cpu": ["1B", "2B"]},
        }

        response = assets_client.post(
            "/api/v1/assets/kamatera/query-catalog",
            json={
                "client_id": "kamatera-client",
                "secret": "kamatera-secret",
                "datacenter": "AS",
            },
        )

    assert response.status_code == 200
    assert response.json()["capabilities"]["cpu"] == ["1B", "2B"]
    service.query_kamatera_catalog.assert_called_once_with(
        client_id="kamatera-client",
        secret="kamatera-secret",
        datacenter="AS",
    )


def test_register_azure_asset_route_maps_request(assets_client: TestClient) -> None:
    with patch("api.router.assets.AssetApplicationService") as service_cls:
        service = service_cls.return_value
        service.register_azure_asset.return_value = AssetRegistrationResult(
            asset_id=14,
            asset_name="azure-japan",
            protocol_config_id=36,
        )

        response = assets_client.post(
            "/api/v1/assets/azure",
            json={
                "asset_name": "azure-japan",
                "region": "japaneast",
                "tenant_id": "tenant-id",
                "client_id": "client-id",
                "client_secret": "client-secret",
                "subscription_id": "SUB-ID",
                "resource_group": "shadowfleet",
                "ssh_public_key": "ssh-ed25519 AAAA test",
                "default_vm_size": "Standard_B1s",
                "tags": ["prod"],
                "protocol_type": "Trojan",
                "additional_protocol_types": ["AnyTLS"],
                "target_count": 1,
                "max_count": 2,
                "priority": 80,
                "allow_cdn_proxy": True,
                "default_vcpu": 1,
            },
        )

    assert response.status_code == 201
    assert response.json()["asset_type"] == "azure"
    assert response.json()["aws_account_id"] == "azure:sub-id"
    assert response.json()["aws_access_key"] is None
    request = service.register_azure_asset.call_args.args[0]
    assert isinstance(request, AzureAssetRegistrationRequest)
    assert request.tenant_id == "tenant-id"
    assert request.subscription_id == "SUB-ID"
    assert request.resource_group == "shadowfleet"
    assert request.additional_protocol_types == ("AnyTLS",)


def test_azure_catalog_route_maps_credentials_and_location(
    assets_client: TestClient,
) -> None:
    with patch("api.router.assets.AssetApplicationService") as service_cls:
        service = service_cls.return_value
        service.query_azure_catalog.return_value = {
            "locations": [{"name": "japaneast"}],
            "vm_sizes": [{"name": "Standard_B1s"}],
        }

        response = assets_client.post(
            "/api/v1/assets/azure/query-catalog",
            json={
                "tenant_id": "tenant-id",
                "client_id": "client-id",
                "client_secret": "client-secret",
                "subscription_id": "subscription-id",
                "location": "japaneast",
            },
        )

    assert response.status_code == 200
    assert response.json()["vm_sizes"][0]["name"] == "Standard_B1s"
    service.query_azure_catalog.assert_called_once_with(
        tenant_id="tenant-id",
        client_id="client-id",
        client_secret="client-secret",
        subscription_id="subscription-id",
        location="japaneast",
    )
