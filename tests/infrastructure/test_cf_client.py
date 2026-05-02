"""Infrastructure tests for Cloudflare client with mocked API responses."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from tests.fixtures.mock_responses import MockCloudflareAPIResponses


def create_mock_runtime_context() -> MagicMock:
    """Create a mock RuntimeContext for Cloudflare client tests."""
    mock_context = MagicMock()
    mock_context.logger = MagicMock(spec=logging.Logger)
    mock_context.logger.getChild.return_value = mock_context.logger
    mock_context.correlation_id = "test-correlation-id"

    mock_config = MagicMock()
    mock_config.app.request_timeout_seconds = 10
    mock_config.app.max_retries = 3
    mock_config.app.retry_backoff_seconds = 1.0

    mock_cloudflare = MagicMock()
    mock_cloudflare.enabled = True
    mock_cloudflare.api_token = "test_cf_token"
    mock_cloudflare.zone_id = "test_zone_123"
    mock_cloudflare.base_url = "https://api.cloudflare.com/client/v4"
    mock_config.cloudflare = mock_cloudflare

    mock_context.config = mock_config
    return mock_context


class TestCFClientMockBehavior:
    """Tests for CFClient behavior with mocked API."""

    def test_client_initialization_requires_enabled(self) -> None:
        """CFClient should raise when cloudflare is not enabled."""
        from infrastructure.cloudflare.cf_client import CFClient

        mock_context = create_mock_runtime_context()
        mock_context.config.cloudflare.enabled = False

        with pytest.raises(ValueError, match="cloudflare.enabled=true"):
            CFClient(mock_context)

    def test_client_initialization_requires_api_token(self) -> None:
        """CFClient should raise when api_token is missing."""
        from infrastructure.cloudflare.cf_client import CFClient

        mock_context = create_mock_runtime_context()
        mock_context.config.cloudflare.api_token = None

        with pytest.raises(ValueError, match="api_token"):
            CFClient(mock_context)

    def test_client_initialization_requires_zone_id(self) -> None:
        """CFClient should raise when zone_id is missing."""
        from infrastructure.cloudflare.cf_client import CFClient

        mock_context = create_mock_runtime_context()
        mock_context.config.cloudflare.zone_id = None

        with pytest.raises(ValueError, match="zone_id"):
            CFClient(mock_context)

    def test_client_uses_rate_limiter(self) -> None:
        """CFClient should use TokenBucketRateLimiter for writes."""
        from infrastructure.cloudflare.cf_client import CFClient

        mock_context = create_mock_runtime_context()
        client = CFClient(mock_context)
        assert client._write_rate_limiter is not None

    def test_client_sets_correct_headers(self) -> None:
        """CFClient should set Authorization header."""
        from infrastructure.cloudflare.cf_client import CFClient

        mock_context = create_mock_runtime_context()
        client = CFClient(mock_context)
        assert "Authorization" in client._session.headers
        assert client._session.headers["Authorization"] == "Bearer test_cf_token"
        assert client._session.headers["Content-Type"] == "application/json"


class TestCloudflareMockResponses:
    """Tests for Cloudflare mock response structure validity."""

    def test_empty_dns_records_response(self) -> None:
        """Empty DNS records response should have correct structure."""
        response = MockCloudflareAPIResponses.ZONE_DNS_RECORDS_EMPTY
        assert "result" in response
        assert response["success"] is True
        assert response["result"] == []

    def test_dns_records_with_aaaa_response(self) -> None:
        """DNS records with AAAA response should have required fields."""
        response = MockCloudflareAPIResponses.ZONE_DNS_RECORDS_WITH_AAAA
        assert "result" in response
        assert response["success"] is True
        record = response["result"][0]
        assert record["type"] == "AAAA"
        assert "id" in record
        assert "name" in record
        assert "content" in record
        assert "proxied" in record

    def test_create_dns_record_response(self) -> None:
        """Create DNS record response should have correct structure."""
        response = MockCloudflareAPIResponses.CREATE_DNS_RECORD_SUCCESS
        assert "result" in response
        assert response["success"] is True
        assert "id" in response["result"]
        assert "type" in response["result"]
        assert response["result"]["type"] == "AAAA"

    def test_update_dns_record_response(self) -> None:
        """Update DNS record response should have correct structure."""
        response = MockCloudflareAPIResponses.UPDATE_DNS_RECORD_SUCCESS
        assert "result" in response
        assert response["success"] is True
        assert response["result"]["proxied"] is True

    def test_delete_dns_record_response(self) -> None:
        """Delete DNS record response should have correct structure."""
        response = MockCloudflareAPIResponses.DELETE_DNS_RECORD_SUCCESS
        assert "result" in response
        assert response["success"] is True


class TestCloudflareErrorHandling:
    """Tests for Cloudflare error response handling."""

    def test_cloudflare_api_error_attributes(self) -> None:
        """CloudflareApiError should have correct attributes."""
        from infrastructure.cloudflare.cf_client import CloudflareApiError

        error = CloudflareApiError(
            status_code=429,
            message="Rate limit exceeded",
            errors=[{"code": 10000, "message": "rate limit"}],
        )
        assert error.status_code == 429
        assert str(error) == "Rate limit exceeded"
        assert error.errors[0]["code"] == 10000

    def test_cloudflare_api_error_without_errors(self) -> None:
        """CloudflareApiError should handle missing errors gracefully."""
        from infrastructure.cloudflare.cf_client import CloudflareApiError

        error = CloudflareApiError(status_code=500, message="Server error")
        assert error.errors == []
