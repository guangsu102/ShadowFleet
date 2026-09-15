from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from api.router.tasks import ProvisionTaskCreateRequest
from services.provisioner_service import ProvisionerService
from services.provisioning_models import ProvisionRequest
from services.provisioning_support import ProvisionerServiceError


def _api_request(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "protocol_type": "Trojan",
        "node_name": "node-1",
        "port": "443",
        "server_port": 443,
        "asset_type": "gcp",
        "region": "asia-northeast1-a",
    }
    payload.update(overrides)
    return payload


def test_task_request_rejects_unknown_asset_type() -> None:
    with pytest.raises(ValidationError):
        ProvisionTaskCreateRequest.model_validate(
            _api_request(asset_type="unknown-cloud")
        )


def test_task_request_rejects_unknown_protocol_type() -> None:
    with pytest.raises(ValidationError):
        ProvisionTaskCreateRequest.model_validate(
            _api_request(protocol_type="wireguard")
        )


def test_task_request_accepts_all_supported_cloud_types() -> None:
    for asset_type in (
        "aws",
        "azure",
        "digitalocean",
        "gcp",
        "kamatera",
        "oci",
        "vultr",
        "self_hosted",
    ):
        request = ProvisionTaskCreateRequest.model_validate(
            _api_request(asset_type=asset_type)
        )
        assert request.asset_type == asset_type


def test_internal_provisioner_does_not_fall_back_unknown_type_to_aws() -> None:
    service = ProvisionerService.__new__(ProvisionerService)
    service._runtime_context = MagicMock()
    service._logger = MagicMock()
    service._asset_selector = MagicMock()
    service._asset_repo = MagicMock()
    service._node_registry = MagicMock()
    service._ready_callback_service = MagicMock()
    request = ProvisionRequest(
        protocol_type="Trojan",
        node_name="unknown-provider",
        port="443",
        server_port=443,
        rate=Decimal("1"),
        asset_type="unknown-cloud",
        region="unknown",
    )

    with patch("services.provisioner_service.validate_request"):
        with pytest.raises(ProvisionerServiceError, match="Unsupported asset_type"):
            service.provision_node(request)
