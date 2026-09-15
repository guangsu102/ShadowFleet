from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from unittest.mock import MagicMock, patch

import pytest

from api.router.assets import (
    AssetCredentialRotationRequest,
    rotate_asset_credentials,
)
from database.asset_models import AssetRecord
from services.asset_application_service import AssetApplicationService


PRIVATE_KEY = """-----BEGIN PRIVATE KEY-----
test
-----END PRIVATE KEY-----
"""


def _asset(
    asset_type: str,
    *,
    account_id: str | None,
    provider_config: dict[str, object] | None = None,
) -> AssetRecord:
    return AssetRecord(
        id=17,
        asset_type=asset_type,
        asset_name=f"{asset_type}-asset",
        status="banned",
        region="asia-east1-a",
        aws_account_id=account_id,
        aws_access_key="old-access",
        aws_secret_key="old-secret",
        ssh_host="192.0.2.10" if asset_type == "self_hosted" else None,
        ssh_port=22 if asset_type == "self_hosted" else None,
        ssh_username="root" if asset_type == "self_hosted" else None,
        ssh_password=None,
        ssh_private_key=None,
        default_instance_type=None,
        default_vcpu=None,
        account_total_vcpu=None,
        default_architecture=None,
        provider_config=provider_config,
    )


def _service(asset: AssetRecord) -> AssetApplicationService:
    service = object.__new__(AssetApplicationService)
    service._runtime_context = MagicMock(correlation_id="rotate-correlation")
    service._logger = MagicMock()
    service._asset_repo = MagicMock()
    service._asset_repo.get_asset_by_id.return_value = asset
    service._asset_repo.update_asset_credentials.return_value = replace(
        asset,
        status="active",
    )
    return service


def test_rotate_gcp_service_account_validates_and_updates_decomposed_credentials() -> None:
    asset = _asset(
        "gcp",
        account_id="gcp:project-1",
        provider_config={"project_id": "project-1", "network": "default"},
    )
    service = _service(asset)
    client = MagicMock()
    service._build_gcp_client = MagicMock(return_value=client)
    service_account_json = json.dumps(
        {
            "type": "service_account",
            "project_id": "project-1",
            "client_email": "new@example.iam.gserviceaccount.com",
            "private_key": PRIVATE_KEY,
            "private_key_id": "new-key-id",
        }
    )

    updated = service.rotate_asset_credentials(
        asset_id=17,
        credentials={"service_account_json": service_account_json},
    )

    client.validate_project.assert_called_once_with()
    kwargs = service._asset_repo.update_asset_credentials.call_args.kwargs
    assert kwargs["aws_access_key"] == "new@example.iam.gserviceaccount.com"
    assert kwargs["aws_secret_key"] == PRIVATE_KEY.strip()
    assert kwargs["provider_config"]["private_key_id"] == "new-key-id"
    assert kwargs["provider_config"]["network"] == "default"
    assert kwargs["reactivate"] is True
    assert updated.status == "active"


def test_rotate_gcp_rejects_credentials_for_another_project() -> None:
    asset = _asset(
        "gcp",
        account_id="gcp:project-1",
        provider_config={"project_id": "project-1"},
    )
    service = _service(asset)
    service._build_gcp_client = MagicMock(return_value=MagicMock())
    service_account_json = json.dumps(
        {
            "type": "service_account",
            "project_id": "project-2",
            "client_email": "new@example.iam.gserviceaccount.com",
            "private_key": PRIVATE_KEY,
        }
    )

    with pytest.raises(ValueError, match="different project"):
        service.rotate_asset_credentials(
            asset_id=17,
            credentials={
                "service_account_json": service_account_json,
                "project_id": "project-2",
            },
        )

    service._asset_repo.update_asset_credentials.assert_not_called()


def test_rotate_kamatera_credentials_validates_same_account() -> None:
    asset = _asset(
        "kamatera",
        account_id=AssetApplicationService._kamatera_provider_account_id("same-client"),
        provider_config={"image": "ubuntu"},
    )
    service = _service(asset)
    client = MagicMock()
    service._build_kamatera_client = MagicMock(return_value=client)

    service.rotate_asset_credentials(
        asset_id=17,
        credentials={"client_id": "same-client", "secret": "new-secret"},
    )

    client.validate_account.assert_called_once_with()
    kwargs = service._asset_repo.update_asset_credentials.call_args.kwargs
    assert kwargs["aws_access_key"] == "same-client"
    assert kwargs["aws_secret_key"] == "new-secret"
    assert kwargs["aws_account_id"] == asset.aws_account_id


def test_rotate_kamatera_rejects_different_client_id() -> None:
    asset = _asset(
        "kamatera",
        account_id=AssetApplicationService._kamatera_provider_account_id("old-client"),
        provider_config={"image": "ubuntu"},
    )
    service = _service(asset)
    service._build_kamatera_client = MagicMock(return_value=MagicMock())

    with pytest.raises(ValueError, match="different account"):
        service.rotate_asset_credentials(
            asset_id=17,
            credentials={"client_id": "new-client", "secret": "new-secret"},
        )

    service._asset_repo.update_asset_credentials.assert_not_called()


def test_rotate_digitalocean_rejects_token_for_another_account() -> None:
    asset = _asset(
        "digitalocean",
        account_id="digitalocean:account-1",
        provider_config={},
    )
    service = _service(asset)
    client = MagicMock()
    client.validate_account.return_value = {"uuid": "account-2"}
    service._build_digitalocean_client = MagicMock(return_value=client)

    with pytest.raises(ValueError, match="different account"):
        service.rotate_asset_credentials(
            asset_id=17,
            credentials={"api_token": "new-token"},
        )


def test_rotate_self_hosted_ssh_key_does_not_require_provider_config() -> None:
    asset = _asset("self_hosted", account_id=None)
    service = _service(asset)

    with patch("services.asset_application_service.SelfHostedSshClient") as client_type:
        service.rotate_asset_credentials(
            asset_id=17,
            credentials={"ssh_private_key": "private-key"},
            reactivate=False,
        )
    client_type.return_value.validate_connection.assert_called_once_with()

    kwargs = service._asset_repo.update_asset_credentials.call_args.kwargs
    assert kwargs["ssh_private_key"] == "private-key"
    assert kwargs["provider_config"] is None
    assert kwargs["aws_account_id"] is None
    assert kwargs["reactivate"] is False


def test_rotation_api_never_returns_credentials() -> None:
    asset = replace(
        _asset("kamatera", account_id="kamatera:account"),
        status="active",
        aws_access_key="client-id",
        aws_secret_key="secret",
    )
    with patch("api.router.assets.AssetApplicationService") as service_type:
        service_type.return_value.rotate_asset_credentials.return_value = asset
        response = asyncio.run(
            rotate_asset_credentials(
                17,
                AssetCredentialRotationRequest(
                    credentials={"client_id": "new", "secret": "new-secret"}
                ),
                ctx=MagicMock(),
                _current_user=None,
            )
        )

    assert response.aws_access_key is None
    assert response.aws_secret_key is None
    service_type.return_value.rotate_asset_credentials.assert_called_once_with(
        asset_id=17,
        credentials={"client_id": "new", "secret": "new-secret"},
        reactivate=True,
    )

def test_rotate_aws_credentials_validates_account_before_update() -> None:
    asset = replace(
        _asset("aws", account_id="123456789012"),
        region="us-east-1",
    )
    service = _service(asset)
    service.resolve_account_id = MagicMock(return_value="123456789012")

    service.rotate_asset_credentials(
        asset_id=17,
        credentials={
            "aws_access_key": "new-access",
            "aws_secret_key": "new-secret",
        },
    )

    service.resolve_account_id.assert_called_once_with(
        "new-access",
        "new-secret",
        "us-east-1",
    )
    kwargs = service._asset_repo.update_asset_credentials.call_args.kwargs
    assert kwargs["aws_access_key"] == "new-access"
    assert kwargs["aws_secret_key"] == "new-secret"
    assert kwargs["aws_account_id"] == "123456789012"


def test_rotate_azure_credentials_validates_subscription_and_merges_config() -> None:
    asset = _asset(
        "azure",
        account_id="azure:subscription-1",
        provider_config={
            "tenant_id": "tenant-1",
            "subscription_id": "subscription-1",
            "resource_group": "shadowfleet",
        },
    )
    service = _service(asset)
    client = MagicMock()
    service._build_azure_client = MagicMock(return_value=client)

    service.rotate_asset_credentials(
        asset_id=17,
        credentials={
            "client_id": "new-client",
            "client_secret": "new-secret",
        },
    )

    client.validate_subscription.assert_called_once_with()
    azure_credentials = service._build_azure_client.call_args.args[0]
    assert azure_credentials.tenant_id == "tenant-1"
    assert azure_credentials.client_id == "new-client"
    assert azure_credentials.client_secret == "new-secret"
    assert azure_credentials.subscription_id == "subscription-1"
    kwargs = service._asset_repo.update_asset_credentials.call_args.kwargs
    assert kwargs["provider_config"]["resource_group"] == "shadowfleet"


def test_rotate_vultr_token_validates_before_update() -> None:
    identity = AssetApplicationService._vultr_provider_account_id({"id": "account-1"})
    asset = _asset(
        "vultr",
        account_id=identity,
        provider_config={"plan": "vc2-1c-1gb", "account_identity": identity},
    )
    service = _service(asset)
    client = MagicMock()
    client.validate_account.return_value = {"id": "account-1"}
    service._build_vultr_client = MagicMock(return_value=client)

    service.rotate_asset_credentials(
        asset_id=17,
        credentials={"api_token": "new-token"},
    )

    client.validate_account.assert_called_once_with()
    kwargs = service._asset_repo.update_asset_credentials.call_args.kwargs
    assert kwargs["aws_access_key"] == "new-token"
    assert kwargs["aws_account_id"] == identity
    assert kwargs["provider_config"]["plan"] == "vc2-1c-1gb"
    assert kwargs["provider_config"]["account_identity"] == identity


def test_rotate_vultr_rejects_token_for_different_account() -> None:
    old_identity = AssetApplicationService._vultr_provider_account_id({"id": "account-1"})
    asset = _asset(
        "vultr",
        account_id=old_identity,
        provider_config={"account_identity": old_identity},
    )
    service = _service(asset)
    client = MagicMock()
    client.validate_account.return_value = {"id": "account-2"}
    service._build_vultr_client = MagicMock(return_value=client)

    with pytest.raises(ValueError, match="different account"):
        service.rotate_asset_credentials(
            asset_id=17,
            credentials={"api_token": "new-token"},
        )
    service._asset_repo.update_asset_credentials.assert_not_called()

def test_rotate_oci_credentials_validates_tenancy_and_merges_config() -> None:
    asset = replace(
        _asset(
            "oci",
            account_id="oci:ocid1.tenancy.oc1..test",
            provider_config={
                "tenancy_ocid": "ocid1.tenancy.oc1..test",
                "fingerprint": "old-fingerprint",
                "compartment_ocid": "ocid1.compartment.oc1..test",
            },
        ),
        region="us-ashburn-1",
    )
    service = _service(asset)
    client = MagicMock()
    service._build_oci_client = MagicMock(return_value=client)

    service.rotate_asset_credentials(
        asset_id=17,
        credentials={
            "private_key": PRIVATE_KEY,
            "fingerprint": "new-fingerprint",
        },
    )

    client.validate_identity.assert_called_once_with()
    oci_credentials = service._build_oci_client.call_args.args[0]
    assert oci_credentials.tenancy_ocid == "ocid1.tenancy.oc1..test"
    assert oci_credentials.user_ocid == "old-access"
    assert oci_credentials.fingerprint == "new-fingerprint"
    assert oci_credentials.private_key == PRIVATE_KEY.strip()
    assert service._build_oci_client.call_args.args[1] == "us-ashburn-1"
    kwargs = service._asset_repo.update_asset_credentials.call_args.kwargs
    assert (
        kwargs["provider_config"]["compartment_ocid"]
        == "ocid1.compartment.oc1..test"
    )
    assert kwargs["provider_config"]["fingerprint"] == "new-fingerprint"
