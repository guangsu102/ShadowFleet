"""
Unit tests for HealthCheckService
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from services.health_check_service import (
    HealthCheckResult,
    HealthCheckService,
    HealthStatus,
)


@pytest.fixture
def mock_ctx() -> MagicMock:
    """Create a mock RuntimeContext."""
    ctx = MagicMock()
    ctx.correlation_id = "test-correlation-123"
    ctx.logger = MagicMock()
    ctx.logger.getChild.return_value = MagicMock()
    ctx.config = MagicMock()
    ctx.config.cloudflare.enabled = False
    return ctx


@pytest.fixture
def health_service(mock_ctx: MagicMock) -> HealthCheckService:
    """Create a HealthCheckService instance."""
    return HealthCheckService(mock_ctx)


class TestHealthCheckResult:
    """Test HealthCheckResult dataclass."""

    def test_result_creation(self) -> None:
        """Test creating a health check result."""
        result = HealthCheckResult(
            component="database",
            status="healthy",
            message="Connection OK",
            response_time_ms=15.5,
        )
        assert result.component == "database"
        assert result.status == "healthy"
        assert result.message == "Connection OK"
        assert result.response_time_ms == 15.5

    def test_result_without_optional_fields(self) -> None:
        """Test creating result without optional fields."""
        result = HealthCheckResult(
            component="app",
            status="healthy",
        )
        assert result.component == "app"
        assert result.status == "healthy"
        assert result.message is None
        assert result.response_time_ms is None

    def test_result_is_frozen(self) -> None:
        """Test that HealthCheckResult is immutable."""
        result = HealthCheckResult(component="test", status="healthy")
        with pytest.raises(AttributeError):
            result.status = "unhealthy"  # type: ignore


class TestHealthStatus:
    """Test HealthStatus dataclass."""

    def test_status_creation(self) -> None:
        """Test creating a health status."""
        checks = [
            HealthCheckResult(component="db", status="healthy"),
            HealthCheckResult(component="api", status="healthy"),
        ]
        status = HealthStatus(
            status="healthy",
            checks=checks,
            timestamp="2026-05-10T10:00:00Z",
        )
        assert status.status == "healthy"
        assert len(status.checks) == 2
        assert status.timestamp == "2026-05-10T10:00:00Z"

    def test_status_is_frozen(self) -> None:
        """Test that HealthStatus is immutable."""
        status = HealthStatus(
            status="healthy",
            checks=[],
            timestamp="2026-05-10T10:00:00Z",
        )
        with pytest.raises(AttributeError):
            status.status = "unhealthy"  # type: ignore


class TestHealthCheckService:
    """Test HealthCheckService implementation."""

    def test_initialization(self, health_service: HealthCheckService) -> None:
        """Test HealthCheckService initializes correctly."""
        assert health_service is not None

    def test_check_liveness_returns_healthy(
        self, health_service: HealthCheckService
    ) -> None:
        """Test liveness check returns healthy status."""
        result = health_service.check_liveness()
        assert result.status == "healthy"
        assert len(result.checks) >= 1
        assert result.checks[0].component == "application"
        assert result.checks[0].status == "healthy"

    def test_check_liveness_includes_timestamp(
        self, health_service: HealthCheckService
    ) -> None:
        """Test liveness check includes timestamp."""
        result = health_service.check_liveness()
        assert result.timestamp is not None
        datetime.fromisoformat(result.timestamp)

    def test_check_readiness_checks_sqlite(
        self, health_service: HealthCheckService
    ) -> None:
        """Test readiness check includes SQLite check."""
        with patch.object(
            health_service, "_check_sqlite"
        ) as mock_check:
            mock_check.return_value = HealthCheckResult(
                component="sqlite",
                status="healthy",
            )
            result = health_service.check_readiness()
            mock_check.assert_called_once()
            assert any(c.component == "sqlite" for c in result.checks)

    def test_check_readiness_checks_xboard_postgres(
        self, health_service: HealthCheckService
    ) -> None:
        """Test readiness check includes Xboard PostgreSQL check."""
        with patch.object(
            health_service, "_check_xboard_postgres"
        ) as mock_check:
            mock_check.return_value = HealthCheckResult(
                component="xboard_postgres",
                status="healthy",
            )
            result = health_service.check_readiness()
            mock_check.assert_called_once()
            assert any(
                c.component == "xboard_postgres" for c in result.checks
            )

    def test_check_readiness_checks_cloudflare_when_enabled(
        self, mock_ctx: MagicMock
    ) -> None:
        """Test readiness check includes Cloudflare when enabled."""
        mock_ctx.config.cloudflare.enabled = True
        service = HealthCheckService(mock_ctx)

        with patch.object(
            service, "_check_cloudflare_api"
        ) as mock_check:
            mock_check.return_value = HealthCheckResult(
                component="cloudflare",
                status="healthy",
            )
            result = service.check_readiness()
            mock_check.assert_called_once()
            assert any(c.component == "cloudflare" for c in result.checks)

    def test_check_readiness_skips_cloudflare_when_disabled(
        self, health_service: HealthCheckService
    ) -> None:
        """Test readiness check skips Cloudflare when disabled."""
        with patch.object(
            health_service, "_check_cloudflare_api"
        ) as mock_check:
            result = health_service.check_readiness()
            mock_check.assert_not_called()
            assert not any(
                c.component == "cloudflare" for c in result.checks
            )

    def test_check_readiness_overall_healthy_when_all_healthy(
        self, health_service: HealthCheckService
    ) -> None:
        """Test readiness returns healthy when all checks pass."""
        with patch.object(
            health_service, "_check_sqlite"
        ) as mock_sqlite, patch.object(
            health_service, "_check_xboard_postgres"
        ) as mock_pg, patch.object(
            health_service, "_check_disk_space"
        ) as mock_disk:
            mock_sqlite.return_value = HealthCheckResult(
                component="sqlite", status="healthy"
            )
            mock_pg.return_value = HealthCheckResult(
                component="xboard_postgres", status="healthy"
            )
            mock_disk.return_value = HealthCheckResult(
                component="disk_space", status="healthy"
            )
            result = health_service.check_readiness()
            assert result.status == "healthy"

    def test_check_readiness_degraded_when_some_unhealthy(
        self, health_service: HealthCheckService
    ) -> None:
        """Test readiness returns degraded when some checks fail."""
        with patch.object(
            health_service, "_check_sqlite"
        ) as mock_sqlite, patch.object(
            health_service, "_check_xboard_postgres"
        ) as mock_pg, patch.object(
            health_service, "_check_disk_space"
        ) as mock_disk:
            mock_sqlite.return_value = HealthCheckResult(
                component="sqlite", status="healthy"
            )
            mock_pg.return_value = HealthCheckResult(
                component="xboard_postgres",
                status="unhealthy",
                message="Connection timeout",
            )
            mock_disk.return_value = HealthCheckResult(
                component="disk_space", status="healthy"
            )
            result = health_service.check_readiness()
            assert result.status in ["degraded", "unhealthy"]

    def test_check_readiness_includes_timestamp(
        self, health_service: HealthCheckService
    ) -> None:
        """Test readiness check includes timestamp."""
        with patch.object(
            health_service, "_check_sqlite"
        ) as mock_sqlite, patch.object(
            health_service, "_check_xboard_postgres"
        ) as mock_pg:
            mock_sqlite.return_value = HealthCheckResult(
                component="sqlite", status="healthy"
            )
            mock_pg.return_value = HealthCheckResult(
                component="xboard_postgres", status="healthy"
            )
            result = health_service.check_readiness()
            assert result.timestamp is not None
            datetime.fromisoformat(result.timestamp)

    def test_check_readiness_measures_response_time(
        self, health_service: HealthCheckService
    ) -> None:
        """Test readiness check measures response time for checks."""
        with patch.object(
            health_service, "_check_sqlite"
        ) as mock_sqlite, patch.object(
            health_service, "_check_xboard_postgres"
        ) as mock_pg:
            mock_sqlite.return_value = HealthCheckResult(
                component="sqlite",
                status="healthy",
                response_time_ms=5.2,
            )
            mock_pg.return_value = HealthCheckResult(
                component="xboard_postgres",
                status="healthy",
                response_time_ms=12.8,
            )
            result = health_service.check_readiness()
            sqlite_check = next(
                c for c in result.checks if c.component == "sqlite"
            )
            assert sqlite_check.response_time_ms == 5.2

    def test_liveness_always_succeeds(
        self, health_service: HealthCheckService
    ) -> None:
        """Test liveness check always returns healthy."""
        for _ in range(5):
            result = health_service.check_liveness()
            assert result.status == "healthy"

    def test_readiness_returns_list_of_checks(
        self, health_service: HealthCheckService
    ) -> None:
        """Test readiness returns a list of individual checks."""
        with patch.object(
            health_service, "_check_sqlite"
        ) as mock_sqlite, patch.object(
            health_service, "_check_xboard_postgres"
        ) as mock_pg:
            mock_sqlite.return_value = HealthCheckResult(
                component="sqlite", status="healthy"
            )
            mock_pg.return_value = HealthCheckResult(
                component="xboard_postgres", status="healthy"
            )
            result = health_service.check_readiness()
            assert isinstance(result.checks, list)
            assert len(result.checks) >= 2
            assert all(
                isinstance(c, HealthCheckResult) for c in result.checks
            )

    def test_check_sqlite_uses_runtime_sqlite_manager(
        self, mock_ctx: MagicMock
    ) -> None:
        """Test SQLite readiness uses the runtime connection manager."""
        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_connection.cursor.return_value = mock_cursor
        mock_ctx.sqlite_manager.connection.return_value.__enter__.return_value = (
            mock_connection
        )
        service = HealthCheckService(mock_ctx)

        result = service._check_sqlite()

        assert result.status == "healthy"
        mock_ctx.sqlite_manager.connection.assert_called_once()
        mock_cursor.execute.assert_called_once_with("SELECT 1")
        mock_cursor.fetchone.assert_called_once()

    def test_check_xboard_postgres_uses_runtime_pool(
        self, mock_ctx: MagicMock
    ) -> None:
        """Test PostgreSQL readiness uses the runtime db_pool."""
        mock_cursor = MagicMock()
        mock_ctx.db_pool.cursor.return_value.__enter__.return_value = mock_cursor
        service = HealthCheckService(mock_ctx)

        result = service._check_xboard_postgres()

        assert result.status == "healthy"
        mock_ctx.db_pool.cursor.assert_called_once()
        mock_cursor.execute.assert_called_once_with("SELECT 1")
        mock_cursor.fetchone.assert_called_once()

    def test_check_cloudflare_api_uses_cf_client(
        self, mock_ctx: MagicMock
    ) -> None:
        """Test Cloudflare readiness uses the current CFClient API."""
        mock_ctx.config.cloudflare.enabled = True
        service = HealthCheckService(mock_ctx)

        with patch("infrastructure.cloudflare.cf_client.CFClient") as mock_cls:
            mock_client = mock_cls.return_value

            result = service._check_cloudflare_api()

        assert result.status == "healthy"
        mock_cls.assert_called_once_with(mock_ctx)
        mock_client._request.assert_called_once_with(
            method="GET",
            endpoint="/user/tokens/verify",
        )
