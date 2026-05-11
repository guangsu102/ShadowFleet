"""
Unit tests for DomainHealthChecker service
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from services.domain_health_checker import (
    DomainHealthChecker,
    DomainHealthResult,
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
def domain_checker(mock_ctx: MagicMock) -> DomainHealthChecker:
    """Create a DomainHealthChecker instance."""
    return DomainHealthChecker(mock_ctx)


class TestDomainHealthResult:
    """Test DomainHealthResult dataclass."""

    def test_result_creation(self) -> None:
        """Test creating a domain health result."""
        result = DomainHealthResult(
            domain="example.com",
            is_healthy=True,
            dns_resolves=True,
            dns_ip="1.2.3.4",
            ssl_valid=True,
            ssl_expires_at="2027-01-01T00:00:00Z",
            ssl_days_remaining=365,
            error_message=None,
            checked_at="2026-05-10T10:00:00Z",
        )
        assert result.domain == "example.com"
        assert result.is_healthy is True
        assert result.dns_resolves is True
        assert result.dns_ip == "1.2.3.4"
        assert result.ssl_valid is True
        assert result.ssl_days_remaining == 365

    def test_result_with_dns_failure(self) -> None:
        """Test result when DNS resolution fails."""
        result = DomainHealthResult(
            domain="invalid.example.com",
            is_healthy=False,
            dns_resolves=False,
            dns_ip=None,
            ssl_valid=False,
            ssl_expires_at=None,
            ssl_days_remaining=None,
            error_message="DNS resolution failed: Name or service not known",
            checked_at="2026-05-10T10:00:00Z",
        )
        assert result.is_healthy is False
        assert result.dns_resolves is False
        assert result.dns_ip is None
        assert "DNS resolution failed" in result.error_message

    def test_result_with_ssl_failure(self) -> None:
        """Test result when SSL certificate is invalid."""
        result = DomainHealthResult(
            domain="expired-cert.example.com",
            is_healthy=False,
            dns_resolves=True,
            dns_ip="1.2.3.4",
            ssl_valid=False,
            ssl_expires_at="2025-01-01T00:00:00Z",
            ssl_days_remaining=-100,
            error_message="SSL certificate invalid: Certificate expired",
            checked_at="2026-05-10T10:00:00Z",
        )
        assert result.is_healthy is False
        assert result.dns_resolves is True
        assert result.ssl_valid is False
        assert "SSL certificate invalid" in result.error_message

    def test_result_is_frozen(self) -> None:
        """Test that DomainHealthResult is immutable."""
        result = DomainHealthResult(
            domain="test.com",
            is_healthy=True,
            dns_resolves=True,
            dns_ip="1.2.3.4",
            ssl_valid=True,
            ssl_expires_at=None,
            ssl_days_remaining=None,
            error_message=None,
            checked_at="2026-05-10T10:00:00Z",
        )
        with pytest.raises(AttributeError):
            result.is_healthy = False  # type: ignore


class TestDomainHealthChecker:
    """Test DomainHealthChecker implementation."""

    def test_initialization(
        self, domain_checker: DomainHealthChecker
    ) -> None:
        """Test DomainHealthChecker initializes correctly."""
        assert domain_checker is not None

    @patch.object(DomainHealthChecker, "_check_dns_resolution")
    def test_check_domain_health_dns_success(
        self, mock_dns: MagicMock, domain_checker: DomainHealthChecker
    ) -> None:
        """Test domain health check with successful DNS resolution."""
        mock_dns.return_value = (True, "1.2.3.4", None)

        with patch.object(
            domain_checker, "_check_ssl_certificate"
        ) as mock_ssl:
            mock_ssl.return_value = (True, "2027-01-01T00:00:00Z", 365, None)
            result = domain_checker.check_domain_health("example.com")

        assert result.dns_resolves is True
        assert result.dns_ip == "1.2.3.4"

    @patch.object(DomainHealthChecker, "_check_dns_resolution")
    def test_check_domain_health_dns_failure(
        self, mock_dns: MagicMock, domain_checker: DomainHealthChecker
    ) -> None:
        """Test domain health check with DNS resolution failure."""
        mock_dns.return_value = (False, None, "Name or service not known")

        result = domain_checker.check_domain_health("invalid.example.com")

        assert result.dns_resolves is False
        assert result.dns_ip is None
        assert result.is_healthy is False
        assert "DNS resolution failed" in result.error_message

    @patch.object(DomainHealthChecker, "_check_dns_resolution")
    def test_check_domain_health_ssl_not_checked_when_dns_fails(
        self, mock_dns: MagicMock, domain_checker: DomainHealthChecker
    ) -> None:
        """Test SSL check is skipped when DNS fails."""
        mock_dns.return_value = (False, None, "DNS error")

        with patch.object(
            domain_checker, "_check_ssl_certificate"
        ) as mock_ssl:
            result = domain_checker.check_domain_health("invalid.example.com")
            mock_ssl.assert_not_called()

        assert result.ssl_valid is False
        assert result.ssl_expires_at is None

    @patch("socket.getaddrinfo")
    def test_check_domain_health_ssl_success(
        self, mock_getaddrinfo: MagicMock, domain_checker: DomainHealthChecker
    ) -> None:
        """Test domain health check with valid SSL certificate."""
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("1.2.3.4", 443))
        ]

        with patch.object(
            domain_checker, "_check_ssl_certificate"
        ) as mock_ssl:
            mock_ssl.return_value = (True, "2027-01-01T00:00:00Z", 365, None)
            result = domain_checker.check_domain_health("example.com")

        assert result.ssl_valid is True
        assert result.ssl_expires_at == "2027-01-01T00:00:00Z"
        assert result.ssl_days_remaining == 365
        assert result.is_healthy is True

    @patch.object(DomainHealthChecker, "_check_dns_resolution")
    def test_check_domain_health_ssl_failure(
        self, mock_dns: MagicMock, domain_checker: DomainHealthChecker
    ) -> None:
        """Test domain health check with invalid SSL certificate."""
        mock_dns.return_value = (True, "1.2.3.4", None)

        with patch.object(
            domain_checker, "_check_ssl_certificate"
        ) as mock_ssl:
            mock_ssl.return_value = (
                False,
                None,
                None,
                "Certificate expired",
            )
            result = domain_checker.check_domain_health("expired.example.com")

        assert result.dns_resolves is True
        assert result.ssl_valid is False
        assert result.is_healthy is False
        assert "SSL certificate invalid" in result.error_message

    @patch("socket.getaddrinfo")
    def test_check_domain_health_includes_timestamp(
        self, mock_getaddrinfo: MagicMock, domain_checker: DomainHealthChecker
    ) -> None:
        """Test domain health check includes timestamp."""
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("1.2.3.4", 443))
        ]

        with patch.object(
            domain_checker, "_check_ssl_certificate"
        ) as mock_ssl:
            mock_ssl.return_value = (True, "2027-01-01T00:00:00Z", 365, None)
            result = domain_checker.check_domain_health("example.com")

        assert result.checked_at is not None
        from datetime import datetime
        datetime.fromisoformat(result.checked_at)

    @patch.object(DomainHealthChecker, "_check_dns_resolution")
    def test_check_domain_health_ipv6_address(
        self, mock_dns: MagicMock, domain_checker: DomainHealthChecker
    ) -> None:
        """Test domain health check with IPv6 address."""
        mock_dns.return_value = (True, "2600:1f14:804:as03:1234::", None)

        with patch.object(
            domain_checker, "_check_ssl_certificate"
        ) as mock_ssl:
            mock_ssl.return_value = (True, "2027-01-01T00:00:00Z", 365, None)
            result = domain_checker.check_domain_health("ipv6.example.com")

        assert result.dns_resolves is True
        assert result.dns_ip == "2600:1f14:804:as03:1234::"

    @patch("socket.getaddrinfo")
    def test_check_domain_health_ssl_expiring_soon(
        self, mock_getaddrinfo: MagicMock, domain_checker: DomainHealthChecker
    ) -> None:
        """Test domain health check with SSL certificate expiring soon."""
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("1.2.3.4", 443))
        ]

        with patch.object(
            domain_checker, "_check_ssl_certificate"
        ) as mock_ssl:
            mock_ssl.return_value = (True, "2026-05-15T00:00:00Z", 5, None)
            result = domain_checker.check_domain_health("example.com")

        assert result.ssl_valid is True
        assert result.ssl_days_remaining == 5
        assert result.is_healthy is True

    @patch.object(DomainHealthChecker, "_check_dns_resolution")
    def test_check_domain_health_multiple_domains(
        self, mock_dns: MagicMock, domain_checker: DomainHealthChecker
    ) -> None:
        """Test checking multiple domains."""
        mock_dns.return_value = (True, "1.2.3.4", None)

        with patch.object(
            domain_checker, "_check_ssl_certificate"
        ) as mock_ssl:
            mock_ssl.return_value = (True, "2027-01-01T00:00:00Z", 365, None)

            result1 = domain_checker.check_domain_health("domain1.example.com")
            result2 = domain_checker.check_domain_health("domain2.example.com")

        assert result1.domain == "domain1.example.com"
        assert result2.domain == "domain2.example.com"
        assert result1.is_healthy is True
        assert result2.is_healthy is True

    @patch.object(DomainHealthChecker, "_check_dns_resolution")
    def test_check_domain_health_error_message_format(
        self, mock_dns: MagicMock, domain_checker: DomainHealthChecker
    ) -> None:
        """Test error message format for different failure types."""
        # DNS failure
        mock_dns.return_value = (False, None, "DNS timeout")
        result = domain_checker.check_domain_health("timeout.example.com")
        assert result.error_message.startswith("DNS resolution failed:")

        # SSL failure
        mock_dns.return_value = (True, "1.2.3.4", None)
        with patch.object(
            domain_checker, "_check_ssl_certificate"
        ) as mock_ssl:
            mock_ssl.return_value = (False, None, None, "Handshake failed")
            result = domain_checker.check_domain_health("ssl-fail.example.com")
            assert result.error_message.startswith("SSL certificate invalid:")
