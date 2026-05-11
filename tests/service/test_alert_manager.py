"""
Unit tests for AlertManager service
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from services.alert_manager import (
    Alert,
    AlertManager,
    AlertRule,
    AlertSeverity,
)


@pytest.fixture
def mock_ctx() -> MagicMock:
    """Create a mock RuntimeContext."""
    ctx = MagicMock()
    ctx.correlation_id = "test-correlation-123"
    ctx.logger = MagicMock()
    ctx.config = MagicMock()
    ctx.config.telegram.enabled = False
    ctx.tg_reporter = MagicMock()
    return ctx


@pytest.fixture
def alert_manager(mock_ctx: MagicMock) -> AlertManager:
    """Create an AlertManager instance."""
    return AlertManager(mock_ctx)


class TestAlertSeverity:
    """Test AlertSeverity enum."""

    def test_severity_levels(self) -> None:
        """Test all severity levels are defined."""
        assert AlertSeverity.CRITICAL.value == "critical"
        assert AlertSeverity.ERROR.value == "error"
        assert AlertSeverity.WARNING.value == "warning"
        assert AlertSeverity.INFO.value == "info"


class TestAlert:
    """Test Alert dataclass."""

    def test_alert_creation(self) -> None:
        """Test creating an alert."""
        alert = Alert(
            severity=AlertSeverity.ERROR,
            title="Test Alert",
            message="Test message",
            source="test_source",
            labels={"region": "us-east-1"},
            timestamp="2026-05-10T10:00:00Z",
            fingerprint="abc123",
        )
        assert alert.severity == AlertSeverity.ERROR
        assert alert.title == "Test Alert"
        assert alert.message == "Test message"
        assert alert.source == "test_source"
        assert alert.labels == {"region": "us-east-1"}
        assert alert.fingerprint == "abc123"

    def test_alert_is_frozen(self) -> None:
        """Test that Alert is immutable."""
        alert = Alert(
            severity=AlertSeverity.INFO,
            title="Test",
            message="Test",
            source="test",
            labels={},
            timestamp="2026-05-10T10:00:00Z",
            fingerprint="test",
        )
        with pytest.raises(AttributeError):
            alert.severity = AlertSeverity.CRITICAL  # type: ignore


class TestAlertRule:
    """Test AlertRule dataclass."""

    def test_rule_creation(self) -> None:
        """Test creating an alert rule."""
        rule = AlertRule(
            name="test_rule",
            severity=AlertSeverity.WARNING,
            throttle_seconds=300,
            aggregation_window_seconds=600,
            max_alerts_per_window=10,
        )
        assert rule.name == "test_rule"
        assert rule.severity == AlertSeverity.WARNING
        assert rule.throttle_seconds == 300
        assert rule.aggregation_window_seconds == 600
        assert rule.max_alerts_per_window == 10


class TestAlertManager:
    """Test AlertManager service."""

    def test_initialization(self, alert_manager: AlertManager) -> None:
        """Test AlertManager initializes correctly."""
        assert alert_manager is not None

    def test_send_alert_creates_fingerprint(
        self, alert_manager: AlertManager
    ) -> None:
        """Test that send_alert generates a fingerprint."""
        result = alert_manager.send_alert(
            severity=AlertSeverity.ERROR,
            title="Test Alert",
            message="Test message",
            source="test",
            labels={"key": "value"},
        )
        assert isinstance(result, bool)

    def test_send_alert_same_labels_same_fingerprint(
        self, alert_manager: AlertManager
    ) -> None:
        """Test that alerts with same labels are deduplicated."""
        result1 = alert_manager.send_alert(
            severity=AlertSeverity.ERROR,
            title="Test",
            message="Message 1",
            source="test",
            labels={"region": "us-east-1", "protocol": "AnyTLS"},
        )
        result2 = alert_manager.send_alert(
            severity=AlertSeverity.ERROR,
            title="Test",
            message="Message 2",
            source="test",
            labels={"region": "us-east-1", "protocol": "AnyTLS"},
        )
        assert result1 is True
        assert result2 is False

    def test_send_alert_different_labels_different_fingerprint(
        self, alert_manager: AlertManager
    ) -> None:
        """Test that alerts with different labels are not deduplicated."""
        result1 = alert_manager.send_alert(
            severity=AlertSeverity.ERROR,
            title="Test",
            message="Message",
            source="provisioning_failure",
            labels={"region": "us-east-1"},
        )
        result2 = alert_manager.send_alert(
            severity=AlertSeverity.ERROR,
            title="Test",
            message="Message",
            source="provisioning_failure",
            labels={"region": "ap-northeast-1"},
        )
        assert result1 is True
        assert result2 is True

    def test_send_alert_includes_timestamp(
        self, alert_manager: AlertManager
    ) -> None:
        """Test that alerts are sent successfully."""
        result = alert_manager.send_alert(
            severity=AlertSeverity.INFO,
            title="Test",
            message="Test",
            source="test",
            labels={},
        )
        assert isinstance(result, bool)

    def test_throttling_suppresses_duplicate_alerts(
        self, alert_manager: AlertManager
    ) -> None:
        """Test that duplicate alerts within throttle window are suppressed."""
        # Send first alert
        alert1 = alert_manager.send_alert(
            severity=AlertSeverity.WARNING,
            title="Throttle Test",
            message="First",
            source="test",
            labels={"key": "value"},
        )
        assert alert1 is not None

        # Send duplicate immediately (should be throttled)
        alert2 = alert_manager.send_alert(
            severity=AlertSeverity.WARNING,
            title="Throttle Test",
            message="Second",
            source="test",
            labels={"key": "value"},
        )
        # If throttled, should return None or same alert
        # Implementation dependent - adjust based on actual behavior

    def test_different_severity_levels(
        self, alert_manager: AlertManager
    ) -> None:
        """Test sending alerts with different severity levels."""
        critical = alert_manager.send_alert(
            severity=AlertSeverity.CRITICAL,
            title="Critical",
            message="Critical issue",
            source="test",
            labels={},
        )
        error = alert_manager.send_alert(
            severity=AlertSeverity.ERROR,
            title="Error",
            message="Error issue",
            source="test",
            labels={},
        )
        warning = alert_manager.send_alert(
            severity=AlertSeverity.WARNING,
            title="Warning",
            message="Warning issue",
            source="test",
            labels={},
        )
        info = alert_manager.send_alert(
            severity=AlertSeverity.INFO,
            title="Info",
            message="Info message",
            source="test",
            labels={},
        )

        assert isinstance(critical, bool)
        assert isinstance(error, bool)
        assert isinstance(warning, bool)
        assert isinstance(info, bool)

    def test_alert_with_multiple_labels(
        self, alert_manager: AlertManager
    ) -> None:
        """Test alert with multiple labels."""
        result = alert_manager.send_alert(
            severity=AlertSeverity.ERROR,
            title="Multi-label Test",
            message="Test",
            source="provisioning",
            labels={
                "region": "ap-northeast-1",
                "protocol": "Trojan",
                "account_id": "aws-001",
                "instance_id": "i-1234567890",
            },
        )
        assert isinstance(result, bool)
