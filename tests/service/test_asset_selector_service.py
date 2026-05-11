"""
Unit tests for AssetSelectorService
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from database.asset_models import AssetType, ProtocolType
from database.asset_repo import AssetSelectionCandidate
from services.asset_selector_service import (
    AssetSelectionError,
    AssetSelectionRequest,
    AssetSelectionResult,
    AssetSelectorService,
)


@pytest.fixture
def mock_ctx() -> MagicMock:
    """Create a mock RuntimeContext."""
    ctx = MagicMock()
    ctx.correlation_id = "test-correlation-123"
    ctx.logger = MagicMock()
    ctx.logger.getChild.return_value = MagicMock()
    return ctx


@pytest.fixture
def asset_selector(mock_ctx: MagicMock) -> AssetSelectorService:
    """Create an AssetSelectorService instance."""
    return AssetSelectorService(mock_ctx)


class TestAssetSelectionRequest:
    """Test AssetSelectionRequest dataclass."""

    def test_request_creation_minimal(self) -> None:
        """Test creating a minimal selection request."""
        request = AssetSelectionRequest(protocol_type="AnyTLS")
        assert request.protocol_type == "AnyTLS"
        assert request.asset_type is None
        assert request.region is None
        assert request.require_cdn_proxy is False

    def test_request_creation_full(self) -> None:
        """Test creating a full selection request."""
        request = AssetSelectionRequest(
            protocol_type="Trojan",
            asset_type="aws",
            region="ap-northeast-1",
            require_cdn_proxy=True,
        )
        assert request.protocol_type == "Trojan"
        assert request.asset_type == "aws"
        assert request.region == "ap-northeast-1"
        assert request.require_cdn_proxy is True

    def test_request_is_frozen(self) -> None:
        """Test that AssetSelectionRequest is immutable."""
        request = AssetSelectionRequest(protocol_type="AnyTLS")
        with pytest.raises(AttributeError):
            request.protocol_type = "Trojan"  # type: ignore


class TestAssetSelectorService:
    """Test AssetSelectorService implementation."""

    def test_initialization(self, asset_selector: AssetSelectorService) -> None:
        """Test AssetSelectorService initializes correctly."""
        assert asset_selector is not None

    def test_select_asset_no_candidates_raises(
        self, asset_selector: AssetSelectorService
    ) -> None:
        """Test select_asset raises when no candidates found."""
        with patch.object(
            asset_selector._asset_repo, "list_selection_candidates"
        ) as mock_list:
            mock_list.return_value = []
            request = AssetSelectionRequest(protocol_type="AnyTLS")

            with pytest.raises(AssetSelectionError) as exc_info:
                asset_selector.select_asset(request)

            assert "No active asset matches" in str(exc_info.value)

    def test_select_asset_single_candidate(
        self, asset_selector: AssetSelectorService
    ) -> None:
        """Test select_asset with single candidate."""
        mock_asset = MagicMock()
        mock_asset.id = 1
        mock_asset.asset_name = "test-asset"
        mock_asset.asset_type = "aws"
        mock_asset.region = "ap-northeast-1"

        mock_protocol = MagicMock()
        mock_protocol.protocol_type = "AnyTLS"
        mock_protocol.instance_type = "t3.micro"
        mock_protocol.vcpu = 2
        mock_protocol.target_count = 10
        mock_protocol.max_count = 20

        candidate = AssetSelectionCandidate(
            asset=mock_asset,
            protocol_config=mock_protocol,
            current_allocated_count=5,
            current_allocated_vcpu=10,
        )

        with patch.object(
            asset_selector._asset_repo, "list_selection_candidates"
        ) as mock_list:
            mock_list.return_value = [candidate]
            request = AssetSelectionRequest(protocol_type="AnyTLS")

            result = asset_selector.select_asset(request)

            assert result.asset_id == 1
            assert result.asset_name == "test-asset"
            assert result.current_allocated_count == 5

    def test_select_asset_with_region_filter(
        self, asset_selector: AssetSelectorService
    ) -> None:
        """Test select_asset with region filter."""
        mock_asset = MagicMock()
        mock_asset.id = 1
        mock_asset.region = "us-east-1"

        mock_protocol = MagicMock()
        candidate = AssetSelectionCandidate(
            asset=mock_asset,
            protocol_config=mock_protocol,
            current_allocated_count=0,
            current_allocated_vcpu=0,
        )

        with patch.object(
            asset_selector._asset_repo, "list_selection_candidates"
        ) as mock_list:
            mock_list.return_value = [candidate]
            request = AssetSelectionRequest(
                protocol_type="AnyTLS",
                region="us-east-1",
            )

            result = asset_selector.select_asset(request)

            mock_list.assert_called_once_with(
                protocol_type="AnyTLS",
                asset_type=None,
                region="us-east-1",
                require_cdn_proxy=False,
            )

    def test_select_asset_with_cdn_proxy_requirement(
        self, asset_selector: AssetSelectorService
    ) -> None:
        """Test select_asset with CDN proxy requirement."""
        mock_asset = MagicMock()
        mock_asset.id = 1

        mock_protocol = MagicMock()
        mock_protocol.allow_cdn_proxy = True

        candidate = AssetSelectionCandidate(
            asset=mock_asset,
            protocol_config=mock_protocol,
            current_allocated_count=0,
            current_allocated_vcpu=0,
        )

        with patch.object(
            asset_selector._asset_repo, "list_selection_candidates"
        ) as mock_list:
            mock_list.return_value = [candidate]
            request = AssetSelectionRequest(
                protocol_type="Trojan",
                require_cdn_proxy=True,
            )

            result = asset_selector.select_asset(request)

            mock_list.assert_called_once_with(
                protocol_type="Trojan",
                asset_type=None,
                region=None,
                require_cdn_proxy=True,
            )
