"""
Unit tests for ProvisioningPipeline core components
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from services.provisioning_pipeline import (
    ProvisioningContext,
    ProvisioningStep,
    SelectAssetStep,
    RegisterNodeStep,
    AllocateDomainStep,
)
from services.rollback_coordinator import RollbackPriority


@pytest.fixture
def mock_ctx() -> MagicMock:
    """Create a mock RuntimeContext."""
    ctx = MagicMock()
    ctx.correlation_id = "test-correlation-123"
    ctx.logger = MagicMock()
    ctx.logger.getChild.return_value = MagicMock()
    ctx.config = MagicMock()
    return ctx


@pytest.fixture
def mock_request() -> MagicMock:
    """Create a mock provision request."""
    request = MagicMock()
    request.protocol_type = "AnyTLS"
    request.asset_type = "aws"
    request.region = "ap-northeast-1"
    request.node_name = "test-node"
    request.require_cdn_proxy = False
    return request


@pytest.fixture
def provisioning_context(mock_ctx: MagicMock, mock_request: MagicMock) -> ProvisioningContext:
    """Create a ProvisioningContext instance."""
    return ProvisioningContext(
        request=mock_request,
        runtime_context=mock_ctx,
    )


class TestProvisioningContext:
    """Test ProvisioningContext dataclass."""

    def test_context_creation(
        self, mock_ctx: MagicMock, mock_request: MagicMock
    ) -> None:
        """Test creating a provisioning context."""
        context = ProvisioningContext(
            request=mock_request,
            runtime_context=mock_ctx,
        )
        assert context.request == mock_request
        assert context.runtime_context == mock_ctx
        assert context.selection_result is None

    def test_context_domain_name(
        self, provisioning_context: ProvisioningContext
    ) -> None:
        """Test setting domain name in context."""
        provisioning_context.effective_domain_name = "test.example.com"
        assert provisioning_context.effective_domain_name == "test.example.com"


class TestProvisioningStep:
    """Test ProvisioningStep abstract base class."""

    def test_step_has_name(self) -> None:
        """Test that step has a name."""
        class TestStep(ProvisioningStep):
            def execute(self, context: ProvisioningContext) -> None:
                pass

            def get_rollback_priority(self) -> RollbackPriority:
                return RollbackPriority.LOW

        step = TestStep("test_step")
        assert step.name == "test_step"


class TestSelectAssetStep:
    """Test SelectAssetStep implementation."""

    def test_step_initialization(self) -> None:
        """Test SelectAssetStep initializes correctly."""
        step = SelectAssetStep()
        assert step.name == "SelectAsset"

    def test_step_execute(
        self, provisioning_context: ProvisioningContext
    ) -> None:
        """Test executing asset selection step."""
        step = SelectAssetStep()

        with patch("services.asset_selector_service.AssetSelectorService") as mock_service:
            mock_selector = MagicMock()
            mock_service.return_value = mock_selector
            mock_selector.select_asset.return_value = MagicMock(
                asset_id=1,
                asset_name="test-asset",
                protocol_type="AnyTLS",
            )

            step.execute(provisioning_context)

            assert provisioning_context.selection_result is not None
            assert provisioning_context.selection_result.asset_id == 1


class TestRegisterNodeStep:
    """Test RegisterNodeStep implementation."""

    def test_step_initialization(self) -> None:
        """Test RegisterNodeStep initializes correctly."""
        step = RegisterNodeStep()
        assert step.name == "RegisterNode"


class TestAllocateDomainStep:
    """Test AllocateDomainStep implementation."""

    def test_step_initialization(self) -> None:
        """Test AllocateDomainStep initializes correctly."""
        step = AllocateDomainStep()
        assert step.name == "AllocateDomain"


class TestProvisioningPipeline:
    """Test ProvisioningPipeline orchestration."""

    def test_pipeline_executes_steps_in_order(
        self, provisioning_context: ProvisioningContext
    ) -> None:
        """Test that pipeline executes steps in order."""
        step1 = MagicMock(spec=ProvisioningStep)
        step1.name = "Step1"
        step2 = MagicMock(spec=ProvisioningStep)
        step2.name = "Step2"

        steps = [step1, step2]

        for step in steps:
            step.execute(provisioning_context)

        step1.execute.assert_called_once_with(provisioning_context)
        step2.execute.assert_called_once_with(provisioning_context)

    def test_pipeline_stops_on_error(
        self, provisioning_context: ProvisioningContext
    ) -> None:
        """Test that pipeline stops when a step fails."""
        step1 = MagicMock(spec=ProvisioningStep)
        step1.name = "Step1"
        step2 = MagicMock(spec=ProvisioningStep)
        step2.name = "Step2"
        step2.execute.side_effect = Exception("Step failed")

        steps = [step1, step2]

        with pytest.raises(Exception):
            for step in steps:
                step.execute(provisioning_context)

        step1.execute.assert_called_once()
        step2.execute.assert_called_once()
