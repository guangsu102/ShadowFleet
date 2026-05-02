"""Infrastructure tests for AWS EC2 client with mocked Boto3."""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch


from models.aws_credentials import AwsCredentials
from infrastructure.aws.ec2_client_helpers import (
    MAX_IPV6_GENERATION_ATTEMPTS,
    generate_random_ipv6_address,
)


def create_mock_runtime_context() -> MagicMock:
    """Create a mock RuntimeContext for EC2 client tests."""
    mock_context = MagicMock()
    mock_context.logger = MagicMock(spec=logging.Logger)
    mock_context.logger.getChild.return_value = mock_context.logger
    mock_context.correlation_id = "test-correlation-id"

    mock_config = MagicMock()
    mock_config.app.request_timeout_seconds = 10
    mock_config.app.max_retries = 3
    mock_config.app.retry_backoff_seconds = 1.0
    mock_config.aws_proxy.enabled = False
    mock_context.config = mock_config

    return mock_context


def create_mock_aws_credential() -> AwsCredentials:
    """Create an AwsCredentials instance for testing."""
    return AwsCredentials(
        account_id="test-aws-account",
        access_key="AKIATEST123",
        secret_key="testsecretkey",
        region="ap-northeast-1",
    )


class TestIPv6AddressGeneration:
    """Tests for IPv6 address generation logic."""

    def test_generate_random_ipv6_address(self) -> None:
        """generate_random_ipv6_address should return a valid IPv6 address."""
        ipv6 = generate_random_ipv6_address()
        assert ":" in ipv6
        assert len(ipv6) >= 4

    def test_generate_random_ipv6_address_randomness(self) -> None:
        """Multiple calls should produce different addresses."""
        results = {generate_random_ipv6_address() for _ in range(10)}
        assert len(results) > 1

    def test_generate_random_ipv6_address_retries_on_collision(self) -> None:
        """Should retry when collision is detected."""
        call_count = 0
        generated = set()

        def _track() -> str:
            nonlocal call_count
            call_count += 1
            result = f"fd00::{len(generated):x}:{call_count}"
            generated.add(result)
            return result

        with patch(
            "infrastructure.aws.ec2_client_helpers._generate_ipv6_random_part",
            side_effect=[ValueError("collision")] * (MAX_IPV6_GENERATION_ATTEMPTS - 1)
            + [_track()],
        ):
            result = generate_random_ipv6_address()
            assert result.startswith("fd00::")


class TestEC2ClientHelpers:
    """Tests for EC2 client helper functions."""

    def test_create_mock_aws_credential(self) -> None:
        """create_mock_aws_credential should return a valid AwsCredentials."""
        cred = create_mock_aws_credential()
        assert cred.account_id == "test-aws-account"
        assert cred.region == "ap-northeast-1"

    def test_create_mock_runtime_context(self) -> None:
        """create_mock_runtime_context should return a valid mock context."""
        ctx = create_mock_runtime_context()
        assert ctx.correlation_id == "test-correlation-id"
        assert ctx.config.app.request_timeout_seconds == 10
